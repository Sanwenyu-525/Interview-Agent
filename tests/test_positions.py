import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from interview_agent.http_api import create_server
from interview_agent.llm import LLMError
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


class FakeLlmClient:
    def __init__(self, response="", error=None):
        self.response = response
        self.error = error
        self.requests = []

    def chat(self, messages, response_format=None):
        self.requests.append({"messages": messages, "response_format": response_format})
        if self.error is not None:
            raise self.error
        return self.response


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

    def test_llm_generates_position_questions_and_filters_invalid_items(self):
        fake = FakeLlmClient(
            json.dumps(
                {
                    "questions": [
                        {
                            "text": "岗位要求提到熟悉 Java 与 MySQL。请结合支付系统的真实实现说明数据库设计做法与权衡。",
                            "requirement": "熟悉 Java 与 MySQL 数据库设计",
                            "category": "project_evidence",
                            "difficulty": 2,
                            "project_id": 11,
                            "evidence_ids": ["e-tx", "e-ui", "no-such-id"],
                        },
                        {
                            "text": "请用一个真实项目说明 React 前端开发的实践。",
                            "requirement": "能够完成 React 前端开发",
                            "category": "experience",
                            "difficulty": 1,
                            "project_id": None,
                            "evidence_ids": [],
                        },
                        {
                            "text": "这是一条无效题目",
                            "requirement": "不存在的需求",
                            "category": "experience",
                            "difficulty": 1,
                            "project_id": None,
                            "evidence_ids": [],
                        },
                    ]
                },
                ensure_ascii=False,
            )
        )
        service = create_service(llm_client=fake)
        position = service.create_position(
            {
                "candidate_id": "alice",
                "title": "全栈工程师",
                "jd_text": "任职要求\n熟悉 Java 与 MySQL 数据库设计\n能够完成 React 前端开发",
                "project_ids": [11, 12],
            }
        )
        self.assertEqual(len(position.questions), 2)
        first = position.questions[0]
        self.assertEqual(first.requirement, "熟悉 Java 与 MySQL 数据库设计")
        self.assertEqual(first.category, "project_evidence")
        self.assertEqual(first.project_id, 11)
        self.assertEqual(first.evidence_ids, ("e-tx",))
        second = position.questions[1]
        self.assertEqual(second.category, "experience")
        self.assertIsNone(second.project_id)

    def test_llm_failure_falls_back_to_rules(self):
        service = create_service(
            llm_client=FakeLlmClient(
                json.dumps(
                    {"questions": [{"text": "", "requirement": "x", "category": "experience"}]},
                    ensure_ascii=False,
                )
            )
        )
        position = service.create_position(
            {
                "candidate_id": "alice",
                "title": "Java 工程师",
                "jd_text": "熟悉 Java 与 MySQL 数据库设计",
                "project_ids": [11],
            }
        )
        self.assertEqual(len(position.questions), 1)
        self.assertEqual(position.questions[0].category, "project_evidence")

        failing = create_service(llm_client=FakeLlmClient(error=LLMError("上游失败")))
        fallback = failing.create_position(
            {
                "candidate_id": "alice",
                "title": "Java 工程师",
                "jd_text": "熟悉 Java 与 MySQL 数据库设计",
                "project_ids": [11],
            }
        )
        self.assertEqual(len(fallback.questions), 1)
        self.assertEqual(fallback.questions[0].category, "project_evidence")

    def test_ocr_requires_configured_llm(self):
        service = create_service()
        with self.assertRaises(ValueError):
            service.ocr_position_jd({"image_base64": "AAAA", "mime_type": "image/png"})

    def test_ocr_extracts_jd_text_and_validates_input(self):
        fake = FakeLlmClient("岗位职责：负责后端开发。任职要求：熟悉 Java。")
        service = create_service(llm_client=fake)
        result = service.ocr_position_jd({"image_base64": "QUJD", "mime_type": "image/png"})
        self.assertEqual(result["text"], "岗位职责：负责后端开发。任职要求：熟悉 Java。")
        self.assertGreater(result["chars"], 0)
        self.assertTrue(any(
            message["role"] == "user" and isinstance(message["content"], list)
            for request in fake.requests
            for message in request["messages"]
        ))

        with self.assertRaises(ValueError):
            service.ocr_position_jd({"image_base64": "!!!not-base64!!!", "mime_type": "image/png"})
        with self.assertRaises(ValueError):
            service.ocr_position_jd({"image_base64": "QUJD", "mime_type": "text/plain"})

    def test_position_follow_up_questions_target_the_requirement(self):
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
        self.assertEqual(state.position_requirement, question.requirement)
        self.assertEqual(state.position_title, "Java 工程师")

        updated = service.submit_answer(session_id, "我用 MySQL 的事务隔离级别与回滚机制保证一致性。")
        self.assertIn("岗位要求提到", updated.question)
        self.assertIn(question.requirement, updated.question)

        summary = service.list_sessions(candidate_id="alice", position_id=position.position_id)
        self.assertEqual(
            summary["sessions"][0]["position_requirement"], question.requirement
        )


if __name__ == "__main__":
    unittest.main()
