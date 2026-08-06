import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from interview_agent.http_api import create_server
from interview_agent.memory.profile_store import SQLiteCandidateProfileStore
from interview_agent.service import InterviewService
from interview_agent.sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


PROJECT = {
    "project_id": 7,
    "project_name": "订单系统",
    "topics": [{"name": "Transaction", "score": 90}],
}


class SessionHistoryTests(unittest.TestCase):
    def test_session_completion_requires_an_answer_and_is_idempotent(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, "alice")

        with self.assertRaisesRegex(ValueError, "至少完成一次回答"):
            service.complete_session(session_id)

        service.submit_answer(session_id, "事务由服务层控制，失败时回滚。")
        completed = service.complete_session(session_id)
        completed_again = service.complete_session(session_id)

        self.assertEqual(completed.status, "completed")
        self.assertTrue(completed.completed_at)
        self.assertEqual(completed_again.completed_at, completed.completed_at)
        with self.assertRaisesRegex(ValueError, "等待回答状态"):
            service.submit_answer(session_id, "不能继续回答")

    def test_service_lists_filtered_session_summaries(self):
        service = InterviewService()
        service.register_project(PROJECT)
        first, _ = service.start_session(7, "alice")
        second, _ = service.start_session(7, "alice")
        service.start_session(7, "bob")

        result = service.list_sessions(candidate_id="alice", project_id="7")

        self.assertEqual(result["count"], 2)
        self.assertEqual({item["session_id"] for item in result["sessions"]}, {first, second})
        self.assertTrue(all(item["project_name"] == "订单系统" for item in result["sessions"]))
        self.assertTrue(all(item["question_count"] == 0 for item in result["sessions"]))
        self.assertEqual(service.list_sessions(candidate_id="alice")["count"], 2)
        self.assertEqual(service.list_sessions(candidate_id="alice", limit=1)["count"], 1)

    def test_service_renames_and_deletes_sessions(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, created = service.start_session(7, "alice", title="第一次练习")

        self.assertEqual(created.title, "第一次练习")
        renamed = service.rename_session(session_id, "前后端联调复盘")

        self.assertEqual(renamed.title, "前后端联调复盘")
        self.assertEqual(
            service.list_sessions(candidate_id="alice")["sessions"][0]["title"],
            "前后端联调复盘",
        )

        service.delete_session(session_id)

        self.assertEqual(service.list_sessions(candidate_id="alice")["count"], 0)
        with self.assertRaisesRegex(KeyError, "session"):
            service.get_session(session_id)

    def test_session_title_validation_is_shared_by_create_and_rename(self):
        service = InterviewService()
        service.register_project(PROJECT)

        with self.assertRaisesRegex(ValueError, "会话标题"):
            service.start_session(7, "alice", title="   ")

        session_id, _ = service.start_session(7, "alice")
        with self.assertRaisesRegex(ValueError, "会话标题"):
            service.rename_session(session_id, "x" * 81)

    def test_sqlite_session_history_survives_service_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "history.db")
            service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            service.register_project(PROJECT)
            session_id, _ = service.start_session(7, "alice")

            reopened = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )

            result = reopened.list_sessions(candidate_id="alice", project_id=7)

            self.assertEqual(result["count"], 1)
            self.assertEqual(result["sessions"][0]["session_id"], session_id)
            self.assertEqual(result["sessions"][0]["review_mode"], "technical_interview")

    def test_sqlite_session_rename_and_delete_survive_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "session-crud.db")
            service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            service.register_project(PROJECT)
            session_id, _ = service.start_session(7, "alice")
            service.rename_session(session_id, "持久化联调练习")

            reopened = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            self.assertEqual(reopened.get_session(session_id).title, "持久化联调练习")

            reopened.delete_session(session_id)
            final = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            self.assertEqual(final.list_sessions(candidate_id="alice")["count"], 0)

    def test_completed_session_survives_sqlite_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "completed.db")
            service = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            service.register_project(PROJECT)
            session_id, _ = service.start_session(7, "alice")
            service.submit_answer(session_id, "事务边界位于服务层。")
            completed = service.complete_session(session_id)

            reopened = InterviewService(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                profile_store=SQLiteCandidateProfileStore(database),
            )
            restored = reopened.get_session(session_id)

            self.assertEqual(restored.status, "completed")
            self.assertEqual(restored.completed_at, completed.completed_at)

    def test_http_lists_sessions_with_query_filters(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, "alice")
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_address[1]}/sessions"
                "?candidate_id=alice&project_id=7&limit=1"
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["sessions"][0]["session_id"], session_id)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_completes_session_without_request_body(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, "alice")
        service.submit_answer(session_id, "事务边界位于服务层。")
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_address[1]}/sessions/{session_id}/complete",
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(payload["session_id"], session_id)
            self.assertEqual(payload["state"]["status"], "completed")
            self.assertTrue(payload["state"]["completed_at"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_renames_and_deletes_session(self):
        service = InterviewService()
        service.register_project(PROJECT)
        session_id, _ = service.start_session(7, "alice")
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            rename = Request(
                f"http://127.0.0.1:{server.server_address[1]}/sessions/{session_id}",
                data=json.dumps({"title": "接口联调练习"}).encode("utf-8"),
                method="PATCH",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(rename) as response:
                renamed = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(renamed["state"]["title"], "接口联调练习")

            delete = Request(
                f"http://127.0.0.1:{server.server_address[1]}/sessions/{session_id}",
                method="DELETE",
            )
            with urlopen(delete) as response:
                deleted = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 200)
            self.assertEqual(deleted, {"session_id": session_id, "deleted": True})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
