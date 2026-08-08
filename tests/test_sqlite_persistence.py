import tempfile
import threading
import unittest
import json
import sqlite3
from pathlib import Path

from interview_agent.agent import InterviewAgent
from interview_agent.service import InterviewService
from interview_agent.sqlite_store import (
    SQLiteProjectRepository,
    SQLiteSessionStore,
)
from interview_agent.memory.profile_store import SQLiteCandidateProfileStore
from interview_agent.ingestion import FolderSource, IngestionService, WorkspaceManager
from interview_agent.models import Evaluation, ProjectKnowledge, QuestionResult, Topic
from interview_agent.models import SessionConflictError
from interview_agent.review import ReviewMode
from interview_agent.service import ProjectAnalysisError
from interview_agent.http_api import create_server
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PROJECT = {
    "project_id": 11,
    "project_name": "支付系统",
    "topics": [{"name": "Transaction", "score": 95, "evidence": ["e-tx"]}],
    "evidence": {"e-tx": {"source_path": "OrderService.java"}},
}


class SQLitePersistenceTests(unittest.TestCase):
    def test_sqlite_session_store_rejects_malformed_payloads_with_value_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "malformed-session.db")
            store = SQLiteSessionStore(database)
            valid = {
                "project_id": 11,
                "project": {
                    "project_id": 11,
                    "project_name": "Legacy",
                    "topics": [{"name": "API", "score": 80, "evidence": []}],
                },
                "current_topic": {"name": "API", "score": 80, "evidence": []},
                "level": 1,
                "question": "question",
            }
            malformed = (
                [],
                None,
                {key: value for key, value in valid.items() if key != "project"},
                {**valid, "history": {}},
                {**valid, "evaluation": []},
            )
            connection = sqlite3.connect(database)
            for index, payload in enumerate(malformed):
                connection.execute(
                    "INSERT OR REPLACE INTO sessions(session_id, payload) VALUES (?, ?)",
                    (f"bad-{index}", json.dumps(payload)),
                )
            connection.commit()
            connection.close()

            for index in range(len(malformed)):
                with self.assertRaisesRegex(ValueError, "session payload"):
                    store.get(f"bad-{index}")

    def test_http_returns_json_error_for_malformed_session_payload_on_get_and_post(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "http-malformed-session.db")
            store = SQLiteSessionStore(database)
            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT INTO sessions(session_id, payload) VALUES (?, ?)",
                ("bad", json.dumps([])),
            )
            connection.commit()
            connection.close()
            service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=store,
                profile_store=SQLiteCandidateProfileStore(database),
            )
            server = create_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for method, path, body in (
                    ("GET", "/sessions/bad", None),
                    ("POST", "/sessions/bad/answers", {"answer": "answer"}),
                ):
                    request = Request(
                        f"http://127.0.0.1:{server.server_port}{path}",
                        data=json.dumps(body).encode("utf-8") if body else None,
                        method=method,
                        headers={"Content-Type": "application/json"},
                    )
                    with self.assertRaises(HTTPError) as context:
                        urlopen(request)
                    self.assertEqual(context.exception.code, 400)
                    response = json.loads(context.exception.read().decode("utf-8"))
                    self.assertIn("error", response)
            finally:
                server.shutdown()
                server.server_close()

    def test_project_and_session_survive_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "interview-agent.db")
            first_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )
            first_service.register_project(PROJECT)
            session_id, _ = first_service.start_session(11)
            first_service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )

            restored = second_service.get_session(session_id)

            self.assertEqual(restored.project.project_name, "支付系统")
            self.assertEqual(restored.history[0].evaluation.score, 70)
            self.assertEqual(restored.next_direction, "deep")
            self.assertEqual(restored.question_evidence_ids, ("e-tx",))
            self.assertEqual(restored.history[0].evaluation.evidence_ids, ("e-tx",))

    def test_question_and_evaluation_analysis_survive_sqlite_recreation(self):
        class AnalysisQuestionGenerator:
            def generate(self, *, topic, project, level, history, **kwargs):
                return QuestionResult(
                    question=f"{topic.name} / Level {level} / 订单系统",
                    analysis=f"出题分析 L{level}",
                )

        class AnalysisEvaluator:
            def evaluate(self, *, question, answer, topic, project, **kwargs):
                return Evaluation(score=70, analysis="评分分析")

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "analysis-session.db")
            repository = SQLiteProjectRepository(database)
            first_service = InterviewService(
                repository=repository,
                session_store=SQLiteSessionStore(database),
                agent=InterviewAgent(
                    repository=repository,
                    question_generator=AnalysisQuestionGenerator(),
                    evaluator=AnalysisEvaluator(),
                ),
            )
            first_service.register_project(PROJECT)
            session_id, state = first_service.start_session(11)
            self.assertEqual(state.question_analysis, "出题分析 L1")
            first_service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )

            restored = second_service.get_session(session_id)

            self.assertEqual(restored.history[0].analysis, "出题分析 L1")
            self.assertEqual(restored.history[0].evaluation.analysis, "评分分析")
            self.assertNotEqual(restored.question_analysis, "出题分析 L1")

    def test_portfolio_review_mode_survives_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "portfolio-session.db")
            first_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )
            first_service.register_project(PROJECT)
            session_id, state = first_service.start_session(
                11, review_mode=ReviewMode.PORTFOLIO_REVIEW
            )
            first_service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )

            restored = second_service.get_session(session_id)

            self.assertEqual(state.review_mode, "portfolio_review")
            self.assertEqual(restored.review_mode, "portfolio_review")
            self.assertEqual(restored.next_direction, "tradeoff")

    def test_defense_review_mode_survives_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "defense-session.db")
            repository = SQLiteProjectRepository(database)

            class MediumEvaluator:
                def evaluate(self, **kwargs):
                    return Evaluation(score=70)

            first_service = InterviewService(
                repository=repository,
                session_store=SQLiteSessionStore(database),
                agent=InterviewAgent(
                    repository=repository,
                    evaluator=MediumEvaluator(),
                ),
            )
            first_service.register_project(PROJECT)
            session_id, state = first_service.start_session(
                11, review_mode=ReviewMode.DEFENSE_REVIEW
            )
            first_service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )

            restored = second_service.get_session(session_id)

            self.assertEqual(state.review_mode, "defense_review")
            self.assertEqual(restored.review_mode, "defense_review")
            self.assertEqual(restored.next_direction, "justify")

    def test_candidate_profile_and_session_survive_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.db")
            first_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            first_service.register_project(PROJECT)
            session_id, _ = first_service.start_session(11, candidate_id="alice")
            first_service.submit_answer(session_id, "使用事务保证一致性并支持回滚")

            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )

            restored = second_service.get_session(session_id)
            profile = second_service.get_candidate_profile("alice")

            self.assertEqual(restored.candidate_id, "alice")
            self.assertEqual(profile.skills["Transaction"].score, 70)
            self.assertEqual(profile.skills["Transaction"].sample_count, 1)
            self.assertEqual(second_service.get_candidate_profile("bob").skills, {})

    def test_independent_services_merge_concurrent_same_candidate_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "concurrent-services.db")
            barrier = threading.Barrier(2)

            class BarrierEvaluator:
                def __init__(self, weakness):
                    self.weakness = weakness

                def evaluate(self, **kwargs):
                    barrier.wait()
                    return Evaluation(score=70, weaknesses=[self.weakness])

            first_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
                agent=InterviewAgent(
                    repository=SQLiteProjectRepository(database),
                    evaluator=BarrierEvaluator("weak-a"),
                ),
            )
            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
                agent=InterviewAgent(
                    repository=SQLiteProjectRepository(database),
                    evaluator=BarrierEvaluator("weak-b"),
                ),
            )
            first_service.register_project(PROJECT)
            first_session, _ = first_service.start_session(11, candidate_id="alice")
            second_session, _ = second_service.start_session(11, candidate_id="alice")
            errors = []

            def submit(service, session_id):
                try:
                    service.submit_answer(session_id, "answer")
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=submit, args=(first_service, first_session)),
                threading.Thread(target=submit, args=(second_service, second_session)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            snapshot = SQLiteCandidateProfileStore(database).get("alice").skills[
                "Transaction"
            ]
            self.assertEqual(snapshot.sample_count, 2)
            self.assertEqual(set(snapshot.weaknesses), {"weak-a", "weak-b"})

    def test_independent_services_same_session_use_version_cas(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "session-cas.db")
            barrier = threading.Barrier(2)

            class BarrierEvaluator:
                def __init__(self, weakness):
                    self.weakness = weakness

                def evaluate(self, **kwargs):
                    barrier.wait()
                    return Evaluation(score=70, weaknesses=[self.weakness])

            first_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
                agent=InterviewAgent(
                    repository=SQLiteProjectRepository(database),
                    evaluator=BarrierEvaluator("weak-a"),
                ),
            )
            second_service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
                agent=InterviewAgent(
                    repository=SQLiteProjectRepository(database),
                    evaluator=BarrierEvaluator("weak-b"),
                ),
            )
            first_service.register_project(PROJECT)
            session_id, _ = first_service.start_session(11, candidate_id="alice")
            errors = []

            def submit(service):
                try:
                    service.submit_answer(session_id, "answer")
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=submit, args=(first_service,)),
                threading.Thread(target=submit, args=(second_service,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], SessionConflictError)
            restored = SQLiteSessionStore(database).get(session_id)
            profile = SQLiteCandidateProfileStore(database).get("alice")
            self.assertEqual(len(restored.history), 1)
            self.assertEqual(
                profile.skills["Transaction"].sample_count,
                1,
            )

    def test_legacy_session_payload_without_candidate_id_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "legacy-session.db")
            project_repository = SQLiteProjectRepository(database)
            project_repository.save(
                ProjectKnowledge(
                    project_id=18,
                    project_name="Legacy",
                    topics=[Topic(name="API", score=80)],
                )
            )
            session_store = SQLiteSessionStore(database)
            state = InterviewService(
                repository=project_repository,
                session_store=session_store,
            ).start_session(18)[1]
            payload = json.loads(json.dumps({
                "project_id": state.project_id,
                "project": {
                    "project_id": state.project.project_id,
                    "project_name": state.project.project_name,
                    "topics": [{"name": "API", "score": 80, "evidence": []}],
                },
                "current_topic": {"name": "API", "score": 80, "evidence": []},
                "level": 1,
                "question": state.question,
            }))
            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT OR REPLACE INTO sessions(session_id, payload) VALUES (?, ?)",
                ("legacy-session", json.dumps(payload)),
            )
            connection.commit()
            connection.close()

            restored = session_store.get("legacy-session")

            self.assertEqual(restored.candidate_id, "default")

    def test_legacy_session_payload_candidate_id_is_used_when_owner_column_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "legacy-session-owner.db")
            store = SQLiteSessionStore(database)
            payload = {
                "project_id": 19,
                "project": {
                    "project_id": 19,
                    "project_name": "Legacy",
                    "topics": [{"name": "API", "score": 80, "evidence": []}],
                },
                "current_topic": {"name": "API", "score": 80, "evidence": []},
                "level": 1,
                "question": "question",
                "candidate_id": "alice",
            }
            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT INTO sessions(session_id, payload, candidate_id) VALUES (?, ?, NULL)",
                ("legacy-alice", json.dumps(payload)),
            )
            connection.commit()
            connection.close()

            self.assertEqual(store.get("legacy-alice").candidate_id, "alice")
            connection = sqlite3.connect(database)
            self.assertEqual(
                connection.execute(
                    "SELECT candidate_id FROM sessions WHERE session_id = ?",
                    ("legacy-alice",),
                ).fetchone()[0],
                "alice",
            )
            connection.execute(
                "UPDATE sessions SET payload = ? WHERE session_id = ?",
                (json.dumps({**payload, "candidate_id": "bob"}), "legacy-alice"),
            )
            connection.commit()
            connection.close()

            self.assertEqual(store.get("legacy-alice").candidate_id, "alice")

    def test_sqlite_session_owner_is_not_taken_from_tampered_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "session-owner.db")
            service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            service.register_project(PROJECT)
            session_id, _ = service.start_session(11, candidate_id="alice")

            connection = sqlite3.connect(database)
            payload = json.loads(
                connection.execute(
                    "SELECT payload FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
            )
            payload["candidate_id"] = "bob"
            connection.execute(
                "UPDATE sessions SET payload = ? WHERE session_id = ?",
                (json.dumps(payload), session_id),
            )
            connection.commit()
            connection.close()

            service.submit_answer(session_id, "使用事务保证一致性并支持回滚", candidate_id="alice")

            self.assertIn("Transaction", service.get_candidate_profile("alice").skills)
            self.assertEqual(service.get_candidate_profile("bob").skills, {})

    def test_legacy_project_payload_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "legacy.db")
            payload = {
                "project_id": 12,
                "project_name": "Legacy",
                "topics": [{"name": "API", "score": 80, "evidence": []}],
            }
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE projects (project_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO projects(project_id, payload) VALUES (?, ?)",
                (12, json.dumps(payload)),
            )
            connection.commit()
            connection.close()

            restored = SQLiteProjectRepository(database).get(12)

            self.assertEqual(restored.project_name, "Legacy")
            self.assertEqual(restored.topics[0].name, "API")
            self.assertEqual(SQLiteProjectRepository(database).get_analysis(12).analyzer_id, "legacy")

    def test_source_ready_and_failed_restore_custom_project_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = str(root / "analysis.db")
            source = FolderSource((("README.md", b"not supported"),))
            first = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                ingestion_service=IngestionService(WorkspaceManager(root / "workspace")),
            )
            first.ingest_project(source, 13, "自定义待分析项目")
            connection = sqlite3.connect(database)
            connection.execute("UPDATE projects SET project_name = NULL WHERE project_id = 13")
            connection.commit()
            connection.close()
            first.ingest_project(FolderSource(()), 14, "自定义失败项目")
            with self.assertRaises(ProjectAnalysisError):
                first.analyze_project(14)

            second = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                ingestion_service=IngestionService(WorkspaceManager(root / "workspace")),
            )

            self.assertEqual(
                second.get_project_analysis(13).project_name, "自定义待分析项目"
            )
            self.assertEqual(
                second.get_project_analysis(14).project_name, "自定义失败项目"
            )

    def test_sqlite_rejects_unsupported_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "version.db")
            repository = SQLiteProjectRepository(database)
            repository.save(
                ProjectKnowledge(
                    project_id=15,
                    project_name="Versioned",
                    topics=[Topic(name="API", score=80)],
                )
            )
            connection = sqlite3.connect(database)
            connection.execute("UPDATE projects SET schema_version = 999 WHERE project_id = 15")
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(ValueError, "schema_version"):
                repository.get_analysis(15)

    def test_sqlite_rejects_universal_model_project_id_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "model.db")
            repository = SQLiteProjectRepository(database)
            service = InterviewService(
                repository=repository,
                session_store=SQLiteSessionStore(database),
            )
            service.register_project(
                {
                    "project_id": 16,
                    "project_name": "Model",
                    "topics": [{"name": "API", "score": 80}],
                }
            )
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE projects SET universal_model_payload = ? WHERE project_id = 16",
                (json.dumps({"project_id": 999}),),
            )
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(ValueError, "project_id"):
                repository.get_analysis(16)

    def test_sqlite_rejects_knowledge_payload_project_id_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "knowledge.db")
            repository = SQLiteProjectRepository(database)
            repository.save(
                ProjectKnowledge(
                    project_id=17,
                    project_name="Knowledge",
                    topics=[Topic(name="API", score=80)],
                )
            )
            corrupt_payload = {
                "project_id": 999,
                "project_name": "Corrupt",
                "topics": [{"name": "API", "score": 80, "evidence": []}],
            }
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE projects SET knowledge_payload = ? WHERE project_id = 17",
                (json.dumps(corrupt_payload),),
            )
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(ValueError, "ProjectKnowledge.*project_id"):
                repository.get_analysis(17)


if __name__ == "__main__":
    unittest.main()
