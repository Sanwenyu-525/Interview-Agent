import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from interview_agent.http_api import create_server
from interview_agent.positions import SQLitePositionStore
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.service import InterviewService
from interview_agent.sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


PROJECTS = (
    {
        "project_id": 11,
        "project_name": "支付系统",
        "dependencies": {"pom.xml": ["java", "mysql"]},
        "topics": [{"name": "Transaction", "score": 95, "evidence": ["e-tx"]}],
        "evidence": {"e-tx": {"source_path": "OrderService.java", "excerpt": "java mysql"}},
    },
    {
        "project_id": 12,
        "project_name": "运营平台",
        "dependencies": {"package.json": ["react"]},
        "topics": [{"name": "Frontend", "score": 88, "evidence": ["e-ui"]}],
        "evidence": {"e-ui": {"source_path": "App.jsx", "excerpt": "react"}},
    },
)


def create_service(**kwargs):
    service = InterviewService(repository=kwargs.pop("repository", InMemoryProjectRepository()), **kwargs)
    for project in PROJECTS:
        service.register_project(project)
    return service


class PositionTests(unittest.TestCase):
    def test_positions_are_candidate_scoped_and_generate_project_questions(self):
        service = create_service()
        alice = service.create_position(
            {
                "candidate_id": "alice",
                "title": "全栈工程师",
                "company": "示例科技",
                "jd_text": "任职要求\n熟悉 Java 与 MySQL 数据库设计\n能够完成 React 前端开发",
                "project_ids": [11, 12],
            }
        )
        service.create_position(
            {
                "candidate_id": "bob",
                "title": "后端工程师",
                "jd_text": "具备接口设计经验",
                "project_ids": [11],
            }
        )

        self.assertEqual(alice.project_ids, (11, 12))
        self.assertEqual(len(alice.requirements), 2)
        self.assertEqual(len(alice.questions), 2)
        self.assertEqual({question.project_id for question in alice.questions}, {11, 12})
        self.assertTrue(all(question.category == "project_evidence" for question in alice.questions))
        self.assertEqual(service.list_positions("alice")["count"], 1)
        self.assertEqual(service.list_positions("bob")["count"], 1)

    def test_position_question_can_start_a_linked_session(self):
        service = create_service()
        position = service.create_position(
            {
                "candidate_id": "alice",
                "title": "Java 工程师",
                "jd_text": "熟悉事务与数据库设计",
                "project_ids": [11],
            }
        )
        question = position.questions[0]

        session_id, state = service.start_session(
            11,
            candidate_id="alice",
            position_id=position.position_id,
            position_question_id=question.question_id,
        )

        self.assertEqual(state.question, question.text)
        self.assertEqual(state.position_id, position.position_id)
        self.assertEqual(state.position_question_id, question.question_id)
        self.assertEqual(state.question_evidence_ids, question.evidence_ids)
        sessions = service.list_sessions(candidate_id="alice", position_id=position.position_id)
        self.assertEqual(sessions["sessions"][0]["session_id"], session_id)

    def test_position_and_session_link_survive_sqlite_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "positions.db")
            repository = SQLiteProjectRepository(database)
            first = create_service(
                repository=repository,
                position_store=SQLitePositionStore(database),
                session_store=SQLiteSessionStore(database),
            )
            position = first.create_position(
                {
                    "candidate_id": "alice",
                    "title": "平台工程师",
                    "jd_text": "能够设计稳定的数据流程",
                    "project_ids": [11],
                }
            )
            session_id, _ = first.start_session(
                11,
                candidate_id="alice",
                position_id=position.position_id,
                position_question_id=position.questions[0].question_id,
            )

            second = InterviewService(
                repository=SQLiteProjectRepository(database),
                position_store=SQLitePositionStore(database),
                session_store=SQLiteSessionStore(database),
            )

            self.assertEqual(second.get_position(position.position_id).title, "平台工程师")
            self.assertEqual(second.get_session(session_id).position_id, position.position_id)

    def test_position_http_crud(self):
        service = create_service()
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            request = Request(
                f"{base_url}/positions",
                data=json.dumps(
                    {
                        "candidate_id": "alice",
                        "title": "后端工程师",
                        "jd_text": "熟悉数据库事务",
                        "project_ids": [11],
                    }
                ).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                created = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 201)

            with urlopen(f"{base_url}/positions?candidate_id=alice") as response:
                listed = json.loads(response.read().decode("utf-8"))
                self.assertEqual(listed["count"], 1)

            patch = Request(
                f"{base_url}/positions/{created['position_id']}",
                data=json.dumps({"status": "interviewing"}).encode("utf-8"),
                method="PATCH",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(patch) as response:
                updated = json.loads(response.read().decode("utf-8"))
                self.assertEqual(updated["status"], "interviewing")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
