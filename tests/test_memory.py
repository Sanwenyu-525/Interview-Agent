import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from interview_agent.agent import InterviewAgent
from interview_agent.models import Evaluation, ProjectKnowledge, Topic
from interview_agent.profile import CandidateProfile, SkillSnapshot, WeaknessSource
from interview_agent.profile import ProfileUpdate, ProfileUpdater
from interview_agent.service import InterviewService, InMemorySessionStore
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.service import InterviewService
from interview_agent.memory.profile_store import (
    InMemoryCandidateProfileStore,
    SQLiteCandidateProfileStore,
)


class MemoryTests(unittest.TestCase):
    def test_profile_store_atomic_updates_keep_all_concurrent_samples(self):
        for store_factory in (
            InMemoryCandidateProfileStore,
            SQLiteCandidateProfileStore,
        ):
            with self.subTest(store=store_factory.__name__):
                if store_factory is SQLiteCandidateProfileStore:
                    with tempfile.TemporaryDirectory() as directory:
                        self._assert_concurrent_updates(
                            store_factory(str(Path(directory) / "concurrent.db"))
                        )
                else:
                    self._assert_concurrent_updates(store_factory())

    def _assert_concurrent_updates(self, store):
        barrier = threading.Barrier(8)

        def update(index):
            barrier.wait()
            store.update(
                "alice",
                lambda profile: (
                    profile.update("API", 50 + index, [f"weakness-{index}"]),
                    profile,
                )[1],
            )

        threads = [threading.Thread(target=update, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = store.get("alice").skills["API"]
        self.assertEqual(snapshot.sample_count, 8)
        self.assertEqual(len(snapshot.weaknesses), 8)

    def test_service_updates_same_candidate_across_sessions_and_deduplicates_weaknesses(self):
        project = ProjectKnowledge(
            project_id=2,
            project_name="Order",
            topics=[Topic("Transaction", 80, evidence=["tx-service"])],
            evidence={"tx-service": {"file": "OrderService.java", "code": "@Transactional"}},
        )
        repository = InMemoryProjectRepository({2: project})

        class SequenceEvaluator:
            def __init__(self):
                self.scores = iter((40, 80))

            def evaluate(self, **kwargs):
                return Evaluation(
                    score=next(self.scores),
                    weaknesses=["缺少回滚说明", "缺少回滚说明"],
                    evidence_ids=("tx-service",),
                )

        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(
                repository=repository,
                evaluator=SequenceEvaluator(),
            ),
        )

        first_session, _ = service.start_session(2, candidate_id="alice")
        service.submit_answer(first_session, "answer")
        second_session, second_state = service.start_session(2, candidate_id="alice")
        service.submit_answer(second_session, "answer")

        snapshot = service.get_candidate_profile("alice").skills["Transaction"]
        self.assertEqual(snapshot.sample_count, 2)
        self.assertEqual(snapshot.trend, "improving")
        self.assertEqual(snapshot.weaknesses, ("缺少回滚说明",))
        self.assertEqual(len(snapshot.weakness_sources), 1)
        source = snapshot.weakness_sources[0]
        self.assertEqual(source.weakness, "缺少回滚说明")
        self.assertEqual(source.session_id, second_session)
        self.assertEqual(source.project_id, 2)
        self.assertEqual(source.record_index, 0)
        self.assertEqual(source.question, second_state.question)
        self.assertEqual(source.evidence_ids, ("tx-service",))
        summary_source = service.get_candidate_profile_summary("alice")["skills"]["Transaction"]["weakness_sources"][0]
        self.assertEqual(summary_source["session_id"], second_session)
        self.assertEqual(service.get_candidate_profile("bob").skills, {})

    def test_service_does_not_reuse_template_agent_profile_between_candidates(self):
        project = ProjectKnowledge(
            project_id=3,
            project_name="Order",
            topics=[Topic("Transaction", 80)],
        )
        repository = InMemoryProjectRepository({3: project})
        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(repository=repository),
        )

        alice_session, _ = service.start_session(3, candidate_id="alice")
        bob_session, _ = service.start_session(3, candidate_id="bob")
        service.submit_answer(alice_session, "使用事务保证一致性并支持回滚")

        self.assertEqual(service.agent.profile.skills, {})
        self.assertEqual(service.get_candidate_profile("bob").skills, {})
        self.assertEqual(service.get_session(bob_session).candidate_id, "bob")

    def test_skill_snapshot_keeps_legacy_fields_and_tracks_history(self):
        profile = CandidateProfile()

        first = profile.update("Transaction", 45, ["缺少回滚说明"])
        second = profile.update("Transaction", 75, ["缺少回滚说明", "缺少容量权衡"])

        self.assertEqual(first, SkillSnapshot(score=45, trend="new", recent_score=45,
                                              sample_count=1, weaknesses=("缺少回滚说明",)))
        self.assertEqual(second.score, 75)
        self.assertEqual(second.recent_score, 75)
        self.assertEqual(second.sample_count, 2)
        self.assertEqual(second.trend, "improving")
        self.assertEqual(second.weaknesses, ("缺少回滚说明", "缺少容量权衡"))

    def test_profile_store_isolates_candidates(self):
        store = InMemoryCandidateProfileStore()

        profile = store.get("alice")
        profile.update("API", 50, ["缺少鉴权"])
        store.save("alice", profile)

        self.assertEqual(store.get("alice").skills["API"].score, 50)
        self.assertEqual(store.get("bob").skills, {})

    def test_profile_store_returns_independent_profile_copies(self):
        store = InMemoryCandidateProfileStore()
        profile = CandidateProfile()
        profile.update("API", 50, ["缺少鉴权"])
        store.save("alice", profile)

        loaded = store.get("alice")
        loaded.update("API", 90)

        self.assertEqual(store.get("alice").skills["API"].score, 50)

    def test_normalize_candidate_id_accepts_only_non_blank_strings(self):
        from interview_agent.memory.profile_store import normalize_candidate_id

        self.assertEqual(normalize_candidate_id(" 123 "), "123")
        for invalid in (None, True, 123, "", "   "):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_candidate_id(invalid)

    def test_service_uses_custom_profile_updater_once_and_commits_its_snapshot(self):
        project = ProjectKnowledge(
            project_id=4,
            project_name="Order",
            topics=[Topic("API", 80)],
        )
        repository = InMemoryProjectRepository({4: project})

        class CustomUpdater(ProfileUpdater):
            def __init__(self):
                self.calls = 0

            def update(self, profile, topic, evaluation):
                self.calls += 1
                return profile.update(topic, 99, ["custom weakness"])

        updater = CustomUpdater()
        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(repository=repository, profile_updater=updater),
        )
        session_id, _ = service.start_session(4, candidate_id="alice")

        service.submit_answer(session_id, "answer")

        self.assertEqual(updater.calls, 1)
        self.assertEqual(service.get_candidate_profile("alice").skills["API"].score, 99)

    def test_service_commits_custom_snapshot_fields_without_recomputing_them(self):
        project = ProjectKnowledge(
            project_id=5,
            project_name="Order",
            topics=[Topic("API", 80)],
        )
        repository = InMemoryProjectRepository({5: project})

        class SnapshotUpdater(ProfileUpdater):
            def update(self, profile, topic, evaluation):
                snapshot = SkillSnapshot(
                    score=88,
                    trend="custom-trend",
                    recent_score=77,
                    sample_count=42,
                    weaknesses=("custom weakness", "custom weakness"),
                )
                profile.skills[topic] = snapshot
                return snapshot

        service = InterviewService(
            repository=repository,
            agent=InterviewAgent(
                repository=repository,
                profile_updater=SnapshotUpdater(),
            ),
        )
        session_id, _ = service.start_session(5, candidate_id="alice")

        service.submit_answer(session_id, "answer")

        self.assertEqual(
            service.get_candidate_profile("alice").skills["API"],
            SkillSnapshot(
                score=88,
                trend="custom-trend",
                recent_score=77,
                sample_count=42,
                weaknesses=("custom weakness",),
            ),
        )

    def test_profile_store_commit_merges_increment_against_current_snapshot(self):
        first_update = ProfileUpdate(
            topic="API",
            score=50,
            weaknesses=("weak-a",),
            snapshot=SkillSnapshot(
                score=50,
                trend="new",
                recent_score=50,
                sample_count=1,
                weaknesses=("weak-a",),
            ),
        )
        second_update = ProfileUpdate(
            topic="API",
            score=80,
            weaknesses=("weak-b", "weak-a"),
            snapshot=SkillSnapshot(
                score=80,
                trend="improving",
                recent_score=80,
                sample_count=1,
                weaknesses=("weak-b", "weak-a"),
            ),
        )

        for store_factory in (
            InMemoryCandidateProfileStore,
            SQLiteCandidateProfileStore,
        ):
            with self.subTest(store=store_factory.__name__):
                if store_factory is SQLiteCandidateProfileStore:
                    with tempfile.TemporaryDirectory() as directory:
                        store = store_factory(str(Path(directory) / "commit.db"))
                        store.commit("alice", first_update)
                        store.commit("alice", second_update)
                        snapshot = store.get("alice").skills["API"]
                else:
                    store = store_factory()
                    store.commit("alice", first_update)
                    store.commit("alice", second_update)
                    snapshot = store.get("alice").skills["API"]

                self.assertEqual(snapshot.score, 80)
                self.assertEqual(snapshot.recent_score, 80)
                self.assertEqual(snapshot.sample_count, 2)
                self.assertEqual(snapshot.trend, "improving")
                self.assertEqual(snapshot.weaknesses, ("weak-a", "weak-b"))

    def test_profile_restore_if_version_rejects_newer_profile(self):
        first_update = ProfileUpdate(
            topic="API",
            score=50,
            weaknesses=("weak-a",),
            snapshot=SkillSnapshot(score=50, weaknesses=("weak-a",)),
        )
        second_update = ProfileUpdate(
            topic="API",
            score=80,
            weaknesses=("weak-b",),
            snapshot=SkillSnapshot(score=80, weaknesses=("weak-b",)),
        )
        for store_factory in (InMemoryCandidateProfileStore, SQLiteCandidateProfileStore):
            with self.subTest(store=store_factory.__name__):
                if store_factory is SQLiteCandidateProfileStore:
                    with tempfile.TemporaryDirectory() as directory:
                        store = store_factory(str(Path(directory) / "rollback.db"))
                        old = CandidateProfile()
                        version = store.commit("alice", first_update)
                        store.commit("alice", second_update)
                        with self.assertRaisesRegex(Exception, "version conflict"):
                            store.restore_if_version("alice", old, version)
                else:
                    store = store_factory()
                    old = CandidateProfile()
                    version = store.commit("alice", first_update)
                    store.commit("alice", second_update)
                    with self.assertRaisesRegex(Exception, "version conflict"):
                        store.restore_if_version("alice", old, version)

    def test_technical_policy_can_use_persisted_weakness_even_when_score_recovered(self):
        from interview_agent.review.technical import TechnicalInterviewPolicy

        project = ProjectKnowledge(
            project_id=1,
            project_name="Order",
            topics=[
                Topic("Cache", 80, ["cache"]),
                Topic("Transaction", 80, ["tx"]),
            ],
            evidence={"cache": {}, "tx": {}},
        )
        profile = CandidateProfile(
            skills={
                "Transaction": SkillSnapshot(
                    score=80,
                    trend="improving",
                    recent_score=80,
                    sample_count=2,
                    weaknesses=("缺少容量权衡",),
                )
            }
        )

        self.assertEqual(
            TechnicalInterviewPolicy().select_topic(project, profile, []).name,
            "Transaction",
        )

    def test_sqlite_profile_store_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.db")
            first = SQLiteCandidateProfileStore(database)
            profile = CandidateProfile(
                skills={
                    "API": SkillSnapshot(
                        score=55,
                        weaknesses=("缺少鉴权",),
                        weakness_sources=(
                            WeaknessSource(
                                weakness="缺少鉴权",
                                session_id="session-1",
                                project_id=7,
                                record_index=2,
                                question="接口如何鉴权？",
                                evidence_ids=("api-controller",),
                            ),
                        ),
                    )
                }
            )
            first.save("alice", profile)

            restored = SQLiteCandidateProfileStore(database).get("alice")

            self.assertEqual(restored.skills["API"].score, 55)
            self.assertEqual(restored.skills["API"].weaknesses, ("缺少鉴权",))
            self.assertEqual(restored.skills["API"].weakness_sources[0].session_id, "session-1")
            self.assertEqual(restored.skills["API"].weakness_sources[0].evidence_ids, ("api-controller",))
            self.assertEqual(SQLiteCandidateProfileStore(database).get("bob").skills, {})

    def test_sqlite_profile_store_restores_legacy_and_deduplicates_dirty_weaknesses(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "legacy-profile.db")
            store = SQLiteCandidateProfileStore(database)
            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT INTO candidate_profiles(candidate_id, payload) VALUES (?, ?)",
                (
                    "alice",
                    json.dumps(
                        {
                            "skills": {
                                "API": {
                                    "score": 60,
                                    "trend": "stable",
                                    "weaknesses": ["缺少鉴权", "缺少鉴权", "缺少错误处理", "缺少鉴权"],
                                }
                            }
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.commit()
            connection.close()

            restored = store.get("alice")
            snapshot = restored.skills["API"]

            self.assertEqual(snapshot.recent_score, 60)
            self.assertEqual(snapshot.sample_count, 1)
            self.assertEqual(snapshot.weaknesses, ("缺少鉴权", "缺少错误处理"))
            self.assertEqual(snapshot.weakness_sources, ())

    def test_sqlite_profile_store_rejects_corrupt_payloads_with_value_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "corrupt-profile.db")
            store = SQLiteCandidateProfileStore(database)
            connection = sqlite3.connect(database)
            payloads = {
                "invalid-json": "not-json",
                "array": json.dumps([]),
                "null": json.dumps(None),
                "unknown-version": json.dumps({"schema_version": 99, "skills": {}}),
                "invalid-score": json.dumps(
                    {"schema_version": 1, "skills": {"API": {"score": "bad"}}}
                ),
            }
            for candidate_id, payload in payloads.items():
                connection.execute(
                    "INSERT INTO candidate_profiles(candidate_id, payload) VALUES (?, ?)",
                    (candidate_id, payload),
                )
            connection.commit()
            connection.close()

            for candidate_id in payloads:
                with self.subTest(candidate_id=candidate_id):
                    with self.assertRaisesRegex(ValueError, "invalid candidate profile payload"):
                        store.get(candidate_id)


if __name__ == "__main__":
    unittest.main()
