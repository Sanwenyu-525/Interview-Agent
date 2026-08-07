import json
import zipfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from interview_agent.http_api import create_server
from interview_agent.agent import InterviewAgent
from interview_agent.llm import LLMError
from interview_agent.memory.profile_store import (
    InMemoryCandidateProfileStore,
    SQLiteCandidateProfileStore,
)
from interview_agent.server import build_server
from interview_agent.models import Evaluation, ProfileConflictError, SessionConflictError
from interview_agent.profile import ProfileUpdate, SkillSnapshot
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.review import ReviewMode
from interview_agent.service import InterviewService, InMemorySessionStore
from interview_agent.ingestion.service import IngestionService
from interview_agent.ingestion.sources import DirectorySource, ZipSource
from interview_agent.ingestion.workspace import WorkspaceManager
from interview_agent.sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


PROJECT = {
    "project_id": 7,
    "project_name": "订单系统",
    "topics": [
        {"name": "Transaction", "score": 90},
        {"name": "Redis", "score": 85},
    ],
}


def request_json(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class InterviewServiceTests(unittest.TestCase):
    def test_zip_descriptor_uses_server_default_quotas(self):
        source = InterviewService.source_from_descriptor(
            {"type": "zip", "source_path": "project.zip"}
        )

        self.assertIsInstance(source, ZipSource)
        self.assertEqual(source.max_file_size, 10 * 1024 * 1024)
        self.assertEqual(source.max_total_size, 100 * 1024 * 1024)
        self.assertEqual(source.max_files, 10_000)

    def test_zip_descriptor_accepts_non_negative_quotas_below_server_defaults(self):
        source = InterviewService.source_from_descriptor(
            {
                "type": "zip",
                "source_path": "project.zip",
                "max_total_size": 1024,
                "max_file_size": 512,
                "max_files": 3,
            }
        )

        self.assertEqual(source.max_total_size, 1024)
        self.assertEqual(source.max_file_size, 512)
        self.assertEqual(source.max_files, 3)

    def test_zip_descriptor_rejects_invalid_or_over_limit_quotas(self):
        invalid_values = (-1, 1.5, "1")
        defaults = {
            "max_total_size": 100 * 1024 * 1024,
            "max_file_size": 10 * 1024 * 1024,
            "max_files": 10_000,
        }

        for field, default in defaults.items():
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, field):
                        InterviewService.source_from_descriptor(
                            {
                                "type": "zip",
                                "source_path": "project.zip",
                                field: value,
                            }
                        )
            with self.subTest(field=field, value=default + 1):
                with self.assertRaisesRegex(ValueError, field):
                    InterviewService.source_from_descriptor(
                        {
                            "type": "zip",
                            "source_path": "project.zip",
                            field: default + 1,
                        }
                    )

    def test_folder_descriptor_ignores_zip_quota_fields(self):
        source = InterviewService.source_from_descriptor(
            {
                "type": "folder",
                "max_total_size": -1,
                "max_file_size": "invalid",
                "max_files": 1.5,
                "files": [{"path": "README.md", "content": "folder"}],
            }
        )

        self.assertEqual(source.source_type, "folder")

    def test_directory_descriptor_uses_server_default_quotas(self):
        source = InterviewService.source_from_descriptor(
            {"type": "directory", "source_path": "C:/projects/demo"}
        )

        self.assertIsInstance(source, DirectorySource)
        self.assertEqual(source.max_file_size, 10 * 1024 * 1024)
        self.assertEqual(source.max_total_size, 100 * 1024 * 1024)
        self.assertEqual(source.max_files, 10_000)

    def test_directory_descriptor_requires_source_path(self):
        with self.assertRaisesRegex(ValueError, "source_path"):
            InterviewService.source_from_descriptor({"type": "directory"})

    def test_zip_quota_failure_is_saved_as_readable_failed_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "project.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("README.md", b"too large for this descriptor")
            service = InterviewService(
                ingestion_service=IngestionService(WorkspaceManager(Path(temp_dir) / "workspace"))
            )

            with self.assertRaisesRegex(ValueError, "ZIP file count exceeds limit"):
                service.ingest_and_analyze_project(
                    {
                        "project_id": 27,
                        "source": {
                            "type": "zip",
                            "source_path": str(archive),
                            "max_files": 0,
                        },
                    }
                )

            failed = service.get_project_analysis(27)
            self.assertEqual(failed.analysis_status.value, "FAILED")
            self.assertIn("ZIP file count exceeds limit", failed.error)

    def test_same_session_submits_are_serialized_without_lost_history(self):
        class SlowEvaluator:
            def evaluate(self, **kwargs):
                time.sleep(0.05)
                return Evaluation(score=70)

        repository = InMemoryProjectRepository()
        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(
                repository=repository,
                evaluator=SlowEvaluator(),
            ),
        )
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")
        barrier = threading.Barrier(2)
        errors = []

        def submit(answer):
            barrier.wait()
            try:
                service.submit_answer(session_id, answer)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=submit, args=(answer,)) for answer in ("one", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(service.get_session(session_id).history), 2)
        self.assertEqual(
            service.get_candidate_profile("alice").skills["Transaction"].sample_count,
            2,
        )

    def test_different_sessions_for_same_candidate_serialize_profile_updates(self):
        class SlowEvaluator:
            def evaluate(self, **kwargs):
                time.sleep(0.05)
                return Evaluation(score=70)

        repository = InMemoryProjectRepository()
        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(
                repository=repository,
                evaluator=SlowEvaluator(),
            ),
        )
        service.register_project(PROJECT)
        session_ids = [
            service.start_session(7, candidate_id="alice")[0]
            for _ in range(2)
        ]
        barrier = threading.Barrier(2)
        errors = []

        def submit(session_id):
            barrier.wait()
            try:
                service.submit_answer(session_id, "answer")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=submit, args=(session_id,))
            for session_id in session_ids
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(
            service.get_candidate_profile("alice").skills["Transaction"].sample_count,
            2,
        )

    def test_different_candidates_can_submit_in_parallel(self):
        active = 0
        max_active = 0
        counter_lock = threading.Lock()

        class TrackingEvaluator:
            def evaluate(self, **kwargs):
                nonlocal active, max_active
                with counter_lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.05)
                    return Evaluation(score=70)
                finally:
                    with counter_lock:
                        active -= 1

        repository = InMemoryProjectRepository()
        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(
                repository=repository,
                evaluator=TrackingEvaluator(),
            ),
        )
        service.register_project(PROJECT)
        session_ids = [
            service.start_session(7, candidate_id=candidate_id)[0]
            for candidate_id in ("alice", "bob")
        ]
        barrier = threading.Barrier(2)

        def submit(session_id):
            barrier.wait()
            service.submit_answer(session_id, "answer")

        threads = [
            threading.Thread(target=submit, args=(session_id,))
            for session_id in session_ids
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(max_active, 2)

    def test_session_and_candidate_lock_registries_release_after_submit(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")

        service.submit_answer(session_id, "answer")

        self.assertEqual(service._session_locks, {})
        self.assertEqual(service._candidate_locks, {})

    def test_inmemory_session_store_rejects_stale_version(self):
        session_store = InMemorySessionStore()
        service = InterviewService(session_store=session_store)
        service.register_project(PROJECT)
        session_id, state = service.start_session(7, candidate_id="alice")

        current_state, version = session_store.get_with_version(session_id)
        self.assertEqual(current_state, state)
        session_store.save(session_id, state, expected_version=version)

        with self.assertRaises(SessionConflictError):
            session_store.save(session_id, state, expected_version=version)

    def test_inmemory_session_store_returns_deep_copies(self):
        session_store = InMemorySessionStore()
        service = InterviewService(session_store=session_store)
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")

        state, version = session_store.get_with_version(session_id)
        state.answer = "mutated"
        state.history.append("mutated")
        state.project.topics.append(state.current_topic)

        restored, restored_version = session_store.get_with_version(session_id)
        self.assertEqual(restored.answer, "")
        self.assertEqual(restored.history, [])
        self.assertEqual(len(restored.project.topics), 2)
        self.assertEqual(restored_version, version)

    def test_profile_rollback_does_not_overwrite_concurrent_update(self):
        class FailingAfterCommitStore(InMemoryCandidateProfileStore):
            def __init__(self):
                super().__init__()
                self.committed = threading.Event()
                self.release = threading.Event()
                self.fail = False

            def commit(self, candidate_id, update):
                version = super().commit(candidate_id, update)
                if not self.fail:
                    return version
                self.committed.set()
                self.release.wait(2)
                raise RuntimeError("profile save failed")

        profile_store = FailingAfterCommitStore()
        service = InterviewService(profile_store=profile_store)
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")
        errors = []

        def submit():
            try:
                service.submit_answer(session_id, "answer")
            except Exception as exc:
                errors.append(exc)

        profile_store.fail = True
        thread = threading.Thread(target=submit)
        thread.start()
        self.assertTrue(profile_store.committed.wait(2))
        profile_store.fail = False
        profile_store.commit(
            "alice",
            ProfileUpdate(
                topic="Transaction",
                score=75,
                weaknesses=("concurrent weakness",),
                snapshot=SkillSnapshot(
                    score=75,
                    trend="improving",
                    recent_score=75,
                    sample_count=1,
                    weaknesses=("concurrent weakness",),
                ),
            ),
        )
        profile_store.release.set()
        thread.join()

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ProfileConflictError)
        snapshot = service.get_candidate_profile("alice").skills["Transaction"]
        self.assertEqual(snapshot.sample_count, 2)
        self.assertIn("concurrent weakness", snapshot.weaknesses)

    def test_legacy_two_argument_session_store_uses_compatibility_adapter(self):
        class LegacySessionStore:
            def __init__(self):
                self.delegate = InMemorySessionStore()

            def save(self, session_id, state):
                return self.delegate.save(session_id, state)

            def get(self, session_id):
                return self.delegate.get(session_id)

            def get_candidate_id(self, session_id):
                return self.delegate.get_candidate_id(session_id)

        service = InterviewService(session_store=LegacySessionStore())
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")

        updated = service.submit_answer(session_id, "answer")

        self.assertEqual(len(updated.history), 1)

    def test_session_save_failure_does_not_persist_profile_and_keeps_original_error(self):
        class FailingSessionStore(InMemorySessionStore):
            def __init__(self):
                super().__init__()
                self.fail = False

            def save(self, session_id, state, expected_version=None):
                if self.fail:
                    raise RuntimeError("session save failed")
                return super().save(
                    session_id, state, expected_version=expected_version
                )

        session_store = FailingSessionStore()
        service = InterviewService(session_store=session_store)
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")
        session_store.fail = True

        with self.assertRaisesRegex(RuntimeError, "session save failed"):
            service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        self.assertEqual(service.get_candidate_profile("alice").skills, {})

    def test_profile_save_failure_restores_old_session_and_preserves_original_error(self):
        class FailingProfileStore(InMemoryCandidateProfileStore):
            def __init__(self):
                super().__init__()
                self.fail = False

            def commit(self, candidate_id, update):
                result = super().commit(candidate_id, update)
                if self.fail:
                    raise RuntimeError("profile save failed")
                return result

        profile_store = FailingProfileStore()
        service = InterviewService(profile_store=profile_store)
        service.register_project(PROJECT)
        session_id, before = service.start_session(7, candidate_id="alice")
        profile_store.fail = True

        with self.assertRaisesRegex(RuntimeError, "profile save failed"):
            service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        restored = service.get_session(session_id)
        self.assertEqual(restored.history, before.history)
        self.assertEqual(restored.last_submitted_answer, "")
        self.assertEqual(service.get_candidate_profile("alice").skills, {})

    def test_rollback_failure_is_wrapped_but_original_error_is_preserved(self):
        class FailingSessionStore(InMemorySessionStore):
            def __init__(self):
                super().__init__()
                self.fail = False

            def save(self, session_id, state, expected_version=None):
                if self.fail:
                    raise RuntimeError("session save failed")
                return super().save(
                    session_id, state, expected_version=expected_version
                )

        session_store = FailingSessionStore()
        service = InterviewService(session_store=session_store)
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")
        session_store.fail = True

        with self.assertRaisesRegex(RuntimeError, "rollback failed") as context:
            service.submit_answer(session_id, "answer")

        self.assertIn("session save failed", str(context.exception.__cause__))
    def test_service_registers_project_and_keeps_session_state(self):
        service = InterviewService()
        service.register_project(PROJECT)

        session_id, state = service.start_session(7)
        updated = service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        self.assertTrue(session_id)
        self.assertEqual(state.current_topic.name, "Transaction")
        self.assertEqual(updated.history[0].evaluation.score, 70)
        self.assertEqual(service.get_session(session_id), updated)

    def test_start_session_can_target_an_initial_topic(self):
        service = InterviewService()
        service.register_project(PROJECT)

        _, state = service.start_session(7, topic_name="Redis")

        self.assertEqual(state.current_topic.name, "Redis")
        self.assertIn("Redis", state.title)

    def test_start_session_rejects_an_unknown_initial_topic(self):
        service = InterviewService()
        service.register_project(PROJECT)

        with self.assertRaisesRegex(ValueError, "不存在主题"):
            service.start_session(7, topic_name="Kafka")

    def test_service_builds_report_and_public_candidate_profile_from_domain_state(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")
        service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        report = service.get_session_report(session_id)
        profile = service.get_candidate_profile_summary("alice")

        self.assertEqual(report["session_id"], session_id)
        self.assertEqual(report["candidate_id"], "alice")
        self.assertEqual(report["question_count"], 1)
        self.assertEqual(report["average_score"], 70)
        self.assertEqual(report["records"][0]["topic"], "Transaction")
        self.assertEqual(profile["candidate_id"], "alice")
        self.assertEqual(profile["skills"]["Transaction"]["recent_score"], 70)
        self.assertGreaterEqual(profile["version"], 1)

    def test_start_session_passes_portfolio_review_mode_and_uses_portfolio_direction(self):
        service = InterviewService()
        service.register_project(PROJECT)

        session_id, state = service.start_session(
            7, review_mode=ReviewMode.PORTFOLIO_REVIEW
        )
        updated = service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        self.assertEqual(state.review_mode, ReviewMode.PORTFOLIO_REVIEW.value)
        self.assertEqual(updated.review_mode, ReviewMode.PORTFOLIO_REVIEW.value)
        self.assertEqual(updated.next_direction, "tradeoff")

    def test_start_session_passes_defense_review_mode_and_uses_defense_direction(self):
        repository = InMemoryProjectRepository()

        class MediumEvaluator:
            def evaluate(self, **kwargs):
                return Evaluation(score=70)

        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(repository=repository, evaluator=MediumEvaluator()),
        )
        service.register_project(PROJECT)

        session_id, state = service.start_session(
            7, review_mode=ReviewMode.DEFENSE_REVIEW
        )
        updated = service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

        self.assertEqual(state.review_mode, ReviewMode.DEFENSE_REVIEW.value)
        self.assertEqual(updated.review_mode, ReviewMode.DEFENSE_REVIEW.value)
        self.assertEqual(updated.next_direction, "justify")

    def test_submit_answer_rejects_candidate_id_mismatch(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, candidate_id="alice")

        with self.assertRaises(ValueError):
            service.submit_answer(session_id, "answer", candidate_id="bob")

        self.assertEqual(service.get_candidate_profile("alice").skills, {})
        self.assertEqual(service.get_candidate_profile("bob").skills, {})


class HttpApiTests(unittest.TestCase):
    def test_http_api_streams_reference_answer_and_final_state(self):
        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, _ = request_json(
                f"http://127.0.0.1:{server.server_port}/projects",
                "POST",
                PROJECT,
            )
            self.assertEqual(status, 201)
            _, session = request_json(
                f"http://127.0.0.1:{server.server_port}/sessions",
                "POST",
                {"project_id": 7},
            )
            request = Request(
                f"http://127.0.0.1:{server.server_port}/sessions/{session['session_id']}/answers/stream",
                data=json.dumps({"answer": "answer"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
            self.assertIn("event: status", body)
            self.assertIn('"stage": "preparing"', body)
            self.assertIn('"stage": "reviewed"', body)
            self.assertIn("event: chunk", body)
            self.assertIn("event: done", body)
            self.assertIn("reference_answer", body)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_api_returns_502_for_llm_failures(self):
        class LLMFailureService:
            def start_session(self, *args, **kwargs):
                raise LLMError("LLM 请求超时")

        server = create_server(LLMFailureService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as context:
                request_json(
                    f"http://127.0.0.1:{server.server_port}/sessions",
                    "POST",
                    {"project_id": 7},
                )
            self.assertEqual(context.exception.code, 502)
            body = json.loads(context.exception.read().decode("utf-8"))
            self.assertEqual(body["error"], "LLM 请求超时")
        finally:
            server.shutdown()
            server.server_close()

    def test_http_zip_descriptor_rejects_invalid_or_over_limit_quotas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "project.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("README.md", b"project")
            server = create_server(InterviewService())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            defaults = {
                "max_total_size": 100 * 1024 * 1024,
                "max_file_size": 10 * 1024 * 1024,
                "max_files": 10_000,
            }
            try:
                cases = [
                    (field, value)
                    for field in defaults
                    for value in (-1, 1.5, "1", defaults[field] + 1)
                ]
                for field, value in cases:
                    with self.subTest(field=field, value=value):
                        with self.assertRaises(HTTPError) as context:
                            request_json(
                                f"http://127.0.0.1:{server.server_port}/projects/upload",
                                "POST",
                                {
                                    "project_id": 27,
                                    "source": {
                                        "type": "zip",
                                        "source_path": str(archive),
                                        field: value,
                                    },
                                },
                            )
                        self.assertEqual(context.exception.code, 400)
                        body = json.loads(context.exception.read().decode("utf-8"))
                        self.assertIn(field, body["error"])
            finally:
                server.shutdown()
                server.server_close()

    def test_http_api_reads_and_saves_llm_settings_without_returning_api_key(self):
        service = InterviewService()
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, initial = request_json(
                f"http://127.0.0.1:{server.server_port}/settings/llm"
            )
            self.assertEqual(status, 200)
            self.assertFalse(initial["configured"])

            status, saved = request_json(
                f"http://127.0.0.1:{server.server_port}/settings/llm",
                "POST",
                {
                    "provider": "openai_compatible",
                    "base_url": "https://example.test/v1",
                    "api_key": "secret",
                    "model": "demo-model",
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(saved["configured"])
            self.assertTrue(saved["api_key_set"])
            self.assertNotIn("api_key", saved)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_api_reads_available_llm_models_without_saving_settings(self):
        service = InterviewService()
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("interview_agent.service.OpenAICompatibleClient") as client_type:
                client_type.return_value.list_models.return_value = (
                    "deepseek-v4-flash",
                    "deepseek-v4-pro",
                )
                status, result = request_json(
                    f"http://127.0.0.1:{server.server_port}/settings/llm/models",
                    "POST",
                    {
                        "provider": "openai_compatible",
                        "provider_name": "DeepSeek",
                        "base_url": "https://api.deepseek.com",
                        "api_key": "secret",
                    },
                )
            self.assertEqual(status, 200)
            self.assertEqual(result["models"], ["deepseek-v4-flash", "deepseek-v4-pro"])
            self.assertFalse(service.get_llm_settings()["configured"])
            self.assertNotIn("api_key", result)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_api_manages_llm_profiles_and_tests_saved_connection(self):
        service = InterviewService()
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}/settings/llm/profiles"
        try:
            status, created = request_json(
                base,
                "POST",
                {
                    "name": "DeepSeek 工作模型",
                    "provider": "openai_compatible",
                    "provider_name": "DeepSeek",
                    "base_url": "https://example.test/v1",
                    "api_key": "secret",
                    "model": "demo-model",
                },
            )
            self.assertEqual(status, 201)
            profile_id = created["id"]
            self.assertNotIn("api_key", created)
            self.assertFalse(created["active"])

            status, listed = request_json(base)
            self.assertEqual(status, 200)
            self.assertEqual(listed["profiles"][0]["id"], profile_id)

            status, activated = request_json(f"{base}/{profile_id}/activate", "POST", {})
            self.assertEqual(status, 200)
            self.assertTrue(activated["active"])

            with patch("interview_agent.service.OpenAICompatibleClient") as client_type:
                client_type.return_value.chat.return_value = "OK"
                status, tested = request_json(f"{base}/{profile_id}/test", "POST", {})
            self.assertEqual(status, 200)
            self.assertTrue(tested["ok"])
            client_type.return_value.chat.assert_called_once()

            status, updated = request_json(
                f"{base}/{profile_id}",
                "PUT",
                {"name": "DeepSeek 生产模型", "model": "updated-model"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(updated["name"], "DeepSeek 生产模型")
            self.assertEqual(updated["model"], "updated-model")

            status, deleted = request_json(f"{base}/{profile_id}", "DELETE")
            self.assertEqual(status, 200)
            self.assertEqual(deleted["profiles"], [])
            self.assertFalse(service.get_llm_settings()["configured"])
        finally:
            server.shutdown()
            server.server_close()

    def test_http_api_returns_409_for_profile_and_session_conflicts(self):
        class ConflictService:
            def __init__(self, error):
                self.error = error

            def submit_answer(self, *args, **kwargs):
                raise self.error

        for error in (
            SessionConflictError("session version conflict"),
            ProfileConflictError("profile version conflict"),
        ):
            server = create_server(ConflictService(error))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as context:
                    request_json(
                        f"http://127.0.0.1:{server.server_port}/sessions/s1/answers",
                        "POST",
                        {"answer": "answer"},
                    )
                self.assertEqual(context.exception.code, 409)
                body = json.loads(context.exception.read().decode("utf-8"))
                self.assertEqual(body["error"], str(error))
            finally:
                server.shutdown()
                server.server_close()

    def test_http_sessions_pass_candidate_id_and_isolate_profiles(self):
        service = InterviewService()
        service.register_project(PROJECT)
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            status, alice = request_json(
                f"{base_url}/sessions", "POST", {"project_id": 7, "candidate_id": "alice"}
            )
            self.assertEqual(status, 201)
            self.assertEqual(alice["state"]["candidate_id"], "alice")

            status, bob = request_json(
                f"{base_url}/sessions", "POST", {"project_id": 7, "candidate_id": "bob"}
            )
            self.assertEqual(status, 201)
            self.assertEqual(bob["state"]["candidate_id"], "bob")

            status, _ = request_json(
                f"{base_url}/sessions/{alice['session_id']}/answers",
                "POST",
                {"answer": "使用事务保证一致性并支持回滚"},
            )
            self.assertEqual(status, 200)
            self.assertIn("Transaction", service.get_candidate_profile("alice").skills)
            self.assertEqual(service.get_candidate_profile("bob").skills, {})

            status, report = request_json(
                f"{base_url}/sessions/{alice['session_id']}/report"
            )
            self.assertEqual(status, 200)
            self.assertEqual(report["average_score"], 70)

            status, profile = request_json(f"{base_url}/candidates/alice/profile")
            self.assertEqual(status, 200)
            self.assertEqual(profile["skills"]["Transaction"]["sample_count"], 1)
            self.assertEqual(profile["schema_version"], 2)
            self.assertIsInstance(
                profile["skills"]["Transaction"]["weakness_sources"],
                list,
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_http_sessions_pass_review_mode(self):
        service = InterviewService()
        service.register_project(PROJECT)
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, session = request_json(
                f"http://127.0.0.1:{server.server_port}/sessions",
                "POST",
                {"project_id": 7, "review_mode": "portfolio_review"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(
                session["state"]["review_mode"], "portfolio_review"
            )
        finally:
            server.shutdown()
            server.server_close()

    def test_http_sessions_create_defense_review_mode(self):
        service = InterviewService()
        service.register_project(PROJECT)
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, session = request_json(
                f"http://127.0.0.1:{server.server_port}/sessions",
                "POST",
                {"project_id": 7, "review_mode": "defense_review"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(session["state"]["review_mode"], "defense_review")
        finally:
            server.shutdown()
            server.server_close()
    def test_http_api_supports_browser_preflight(self):
        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/sessions",
                method="OPTIONS",
                headers={"Origin": "http://localhost:4173"},
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(
                    response.headers["Access-Control-Allow-Origin"],
                    "http://localhost:4173",
                )
                self.assertIn(
                    "PATCH",
                    response.headers["Access-Control-Allow-Methods"],
                )
        finally:
            server.shutdown()
            server.server_close()

    def test_http_api_rejects_non_local_browser_origin_and_bind_address(self):
        with self.assertRaisesRegex(ValueError, "回环地址"):
            create_server(InterviewService(), host="0.0.0.0")

        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/sessions",
                method="OPTIONS",
                headers={"Origin": "https://example.test"},
            )
            with self.assertRaises(HTTPError) as context:
                urlopen(request)
            self.assertEqual(context.exception.code, 403)
            payload = json.loads(context.exception.read().decode("utf-8"))
            self.assertEqual(payload["code"], "origin_not_allowed")
            self.assertIsNone(context.exception.headers["Access-Control-Allow-Origin"])
        finally:
            server.shutdown()
            server.server_close()

    def test_build_server_uses_local_default(self):
        server = build_server()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()

    def test_build_server_can_persist_projects_to_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "server.db")
            server = build_server(port=0, database=database)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request_json(
                    f"http://127.0.0.1:{server.server_port}/projects",
                    "POST",
                    PROJECT,
                )
            finally:
                server.shutdown()
                server.server_close()

            self.assertEqual(
                SQLiteProjectRepository(database).get(7).project_name,
                "订单系统",
            )

    def test_build_server_http_profile_survives_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "server-memory.db")
            server = build_server(port=0, database=database)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                request_json(f"{base_url}/projects", "POST", PROJECT)
                status, session = request_json(
                    f"{base_url}/sessions",
                    "POST",
                    {"project_id": 7, "candidate_id": "alice"},
                )
                self.assertEqual(status, 201)
                status, _ = request_json(
                    f"{base_url}/sessions/{session['session_id']}/answers",
                    "POST",
                    {"answer": "使用事务保证一致性并支持回滚"},
                )
                self.assertEqual(status, 200)
            finally:
                server.shutdown()
                server.server_close()

            restored_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )

            self.assertEqual(
                restored_service.get_candidate_profile("alice").skills["Transaction"].score,
                70,
            )

    def test_http_api_creates_project_session_and_answer(self):
        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            status, project = request_json(f"{base_url}/projects", "POST", PROJECT)
            self.assertEqual(status, 201)
            self.assertEqual(project["project_id"], 7)

            status, session = request_json(
                f"{base_url}/sessions",
                "POST",
                {"project_id": 7, "topic": "Redis"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(session["state"]["current_topic"]["name"], "Redis")

            status, result = request_json(
                f"{base_url}/sessions/{session['session_id']}/answers",
                "POST",
                {"answer": "使用事务保证一致性并支持回滚"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(result["state"]["evaluation"]["score"], 70)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_projects_endpoint_normalizes_numeric_project_id(self):
        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, project = request_json(
                f"http://127.0.0.1:{server.server_port}/projects",
                "POST",
                {**PROJECT, "project_id": "007"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(project["project_id"], 7)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
