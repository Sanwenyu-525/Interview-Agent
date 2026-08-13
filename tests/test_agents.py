import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

from interview_agent.agents import (
    BUILTIN_AGENTS,
    InMemoryAgentStore,
    SQLiteAgentStore,
    _validate_agent_payload,
)
from interview_agent.http_api import create_server
from interview_agent.llm import LLMConfig
from interview_agent.models import ProjectKnowledge, Topic
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.review import ReviewMode
from interview_agent.service import InterviewService


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


def sample_project():
    return ProjectKnowledge(
        project_id=7,
        project_name="订单服务",
        topics=[Topic(name="事务", score=80, evidence=["e1"])],
        components={"OrderService": "订单业务服务"},
        evidence={"e1": {"source_path": "src/OrderService.java", "excerpt": "@Transactional"}},
        dependencies={"OrderController": ["OrderService"]},
    )


class FakeClient:
    """记录 system 消息并返回合法 JSON 的测试替身。"""

    def __init__(self):
        self.system_contents = []

    def chat(self, messages, **kwargs):
        self.system_contents.extend(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        user = " ".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "user"
        )
        if "候选主题" in user or "下一问" in user:
            return '{"topic_name": "事务", "reason": "x"}'
        if "评价" in user:
            return '{"score": 80, "strengths": ["a"], "weaknesses": ["b"], "feedback": "f", "reference_answer": ""}'
        return '{"question": "请解释订单系统的事务实现", "evidence_ids": [], "covered_points": [], "missing_points": []}'


class AgentPayloadValidationTests(unittest.TestCase):
    def test_valid_payload_is_normalized(self):
        fields = _validate_agent_payload(
            {"name": " 出题官 ", "role": "questioner", "persona": " 严格出题 ", "profile_id": ""}
        )
        self.assertEqual(fields["name"], "出题官")
        self.assertEqual(fields["persona"], "严格出题")

    def test_rejects_empty_name_role_and_persona(self):
        for payload in (
            {"name": "", "role": "questioner", "persona": "x"},
            {"name": "x", "role": "invalid", "persona": "x"},
            {"name": "x", "role": "questioner", "persona": "  "},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    _validate_agent_payload(payload)


class AgentStoreTests(unittest.TestCase):
    def test_inmemory_store_lists_builtins_and_manages_custom(self):
        store = InMemoryAgentStore()
        self.assertEqual(len(store.list_agents()), len(BUILTIN_AGENTS))
        with self.assertRaises(KeyError):
            store.get("unknown-agent")
        store.save_agent(BUILTIN_AGENTS[0].__class__(
            "custom-1", "自定义出题官", "questioner", "人设", ""
        ))
        self.assertEqual(store.get("custom-1").name, "自定义出题官")
        store.delete_agent("custom-1")
        with self.assertRaises(KeyError):
            store.get("custom-1")

    def test_store_rejects_modifying_builtin(self):
        store = InMemoryAgentStore()
        with self.assertRaises(ValueError):
            store.save_agent(BUILTIN_AGENTS[0])
        with self.assertRaises(KeyError):
            store.delete_agent("builtin-generalist")

    def test_sqlite_store_persists_custom_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "agents.db")
            first = SQLiteAgentStore(database)
            first.save_agent(BUILTIN_AGENTS[0].__class__(
                "custom-1", "压力出题官", "questioner", "犀利的出题人设", "profile-1"
            ))
            second = SQLiteAgentStore(database)
            custom = second.get("custom-1")
            self.assertEqual(custom.name, "压力出题官")
            self.assertEqual(custom.profile_id, "profile-1")
            self.assertFalse(custom.builtin)
            self.assertEqual(len(second.list_agents()), len(BUILTIN_AGENTS) + 1)


class AgentServiceTests(unittest.TestCase):
    def setUp(self):
        repository = InMemoryProjectRepository()
        repository.save(sample_project())
        self.service = InterviewService(repository=repository)

    def test_create_update_list_delete_agent(self):
        result = self.service.create_agent(
            {"name": "犀利出题官", "role": "questioner", "persona": "犀利追问"}
        )
        agent_id = result["id"]
        self.assertFalse(result["builtin"])

        listed = self.service.list_agents()
        self.assertEqual(len(listed["agents"]), len(BUILTIN_AGENTS) + 1)
        self.assertTrue(any(item["id"] == agent_id for item in listed["agents"]))

        updated = self.service.update_agent(
            agent_id, {"name": "温柔出题官", "persona": "温和引导"}
        )
        self.assertEqual(updated["name"], "温柔出题官")
        self.assertEqual(updated["persona"], "温和引导")
        self.assertEqual(updated["role"], "questioner")

        deleted = self.service.delete_agent(agent_id)
        self.assertTrue(deleted["deleted"])
        listed = self.service.list_agents()
        self.assertFalse(any(item["id"] == agent_id for item in listed["agents"]))

    def test_update_rejects_missing_fields_and_builtin(self):
        result = self.service.create_agent(
            {"name": "x", "role": "evaluator", "persona": "p"}
        )
        with self.assertRaises(ValueError):
            self.service.update_agent(result["id"], {"name": ""})
        with self.assertRaises(ValueError):
            self.service.update_agent("builtin-generalist", {"name": "改名"})

    def test_start_session_records_single_agent_mode(self):
        session_id, state = self.service.start_session(7, agent_mode="single")
        self.assertEqual(state.agent_mode, "single")
        self.assertEqual(
            state.agent_ids,
            {"questioner": "builtin-generalist", "evaluator": "builtin-generalist", "director": "builtin-generalist"},
        )

    def test_start_session_records_multi_agent_mode_and_falls_back(self):
        session_id, state = self.service.start_session(
            7,
            agent_mode="multi",
            agent_ids={"questioner": "builtin-stress", "director": "builtin-director"},
        )
        self.assertEqual(state.agent_mode, "multi")
        self.assertEqual(state.agent_ids["questioner"], "builtin-stress")
        self.assertEqual(state.agent_ids["director"], "builtin-director")
        self.assertEqual(state.agent_ids["evaluator"], "builtin-generalist")

    def test_start_session_rejects_unknown_agent_and_bad_mode(self):
        with self.assertRaises(KeyError):
            self.service.start_session(7, agent_mode="multi", agent_ids={"questioner": "nope"})
        with self.assertRaises(ValueError):
            self.service.start_session(7, agent_mode="panel")

    def test_agent_mode_survives_submit(self):
        session_id, state = self.service.start_session(
            7, agent_mode="multi", agent_ids={"questioner": "builtin-stress"}
        )
        updated = self.service.submit_answer(session_id, "使用事务保证一致性")
        self.assertEqual(updated.agent_mode, "multi")
        self.assertEqual(updated.agent_ids["questioner"], "builtin-stress")

    def test_llm_multi_agent_assembly_injects_stage_personas(self):
        config = LLMConfig(
            "https://example.test/v1", "secret", "demo-model"
        )
        repository = InMemoryProjectRepository()
        repository.save(sample_project())
        service = InterviewService(repository=repository, llm_config=config)
        fake = FakeClient()
        with patch("interview_agent.service.OpenAICompatibleClient", return_value=fake):
            service.start_session(
                7,
                agent_mode="multi",
                agent_ids={
                    "questioner": "builtin-stress",
                    "evaluator": "builtin-evaluator",
                    "director": "builtin-director",
                },
            )
        system = " ".join(fake.system_contents)
        self.assertIn("压力面试官", system)
        self.assertIn("策略层", system)


class AgentHttpApiTests(unittest.TestCase):
    def setUp(self):
        repository = InMemoryProjectRepository()
        repository.save(sample_project())
        self.service = InterviewService(repository=repository)
        self.server = create_server(self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_http_agent_crud(self):
        status, listed = request_json(f"{self.base}/settings/agents")
        self.assertEqual(status, 200)
        self.assertTrue(all(item["builtin"] for item in listed["agents"]))
        builtin_count = len(listed["agents"])

        status, created = request_json(
            f"{self.base}/settings/agents",
            "POST",
            {"name": "自定义压力官", "role": "questioner", "persona": "犀利"},
        )
        self.assertEqual(status, 201)
        agent_id = created["id"]

        status, listed = request_json(f"{self.base}/settings/agents")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["agents"]), builtin_count + 1)

        status, updated = request_json(
            f"{self.base}/settings/agents/{agent_id}",
            "PUT",
            {"name": "自定义温柔官", "profile_id": ""},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["name"], "自定义温柔官")

        status, deleted = request_json(f"{self.base}/settings/agents/{agent_id}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

        with self.assertRaises(Exception):
            request_json(f"{self.base}/settings/agents/{agent_id}", "DELETE")

    def test_http_agents_reject_invalid_payload_and_builtin_edit(self):
        with self.assertRaises(Exception):
            request_json(
                f"{self.base}/settings/agents",
                "POST",
                {"name": "", "role": "questioner", "persona": "x"},
            )
        with self.assertRaises(Exception):
            request_json(
                f"{self.base}/settings/agents/builtin-generalist",
                "PUT",
                {"name": "改名"},
            )

    def test_http_start_session_accepts_agent_mode(self):
        status, result = request_json(
            f"{self.base}/sessions",
            "POST",
            {
                "project_id": 7,
                "agent_mode": "multi",
                "agent_ids": {"questioner": "builtin-stress"},
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["state"]["agent_mode"], "multi")
        self.assertEqual(result["state"]["agent_ids"]["questioner"], "builtin-stress")

    def test_http_start_session_rejects_unknown_agent(self):
        with self.assertRaises(Exception):
            request_json(
                f"{self.base}/sessions",
                "POST",
                {"project_id": 7, "agent_mode": "multi", "agent_ids": {"questioner": "nope"}},
            )


if __name__ == "__main__":
    unittest.main()
