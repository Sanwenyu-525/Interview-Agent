import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from pydantic import Field

from interview_agent.llm import (
    LLMConfig,
    LLMResponseError,
    LlmEvaluator,
    LlmQuestionGenerator,
    OpenAICompatibleClient,
    agent_from_environment,
)
from interview_agent.models import Evaluation, ProjectKnowledge, QuestionResult, Topic
from interview_agent.repository import InMemoryProjectRepository


class RecordingChatModel(GenericFakeChatModel):
    """记录 LangChain 调用消息与绑定参数的测试替身。"""

    calls: list = Field(default_factory=list)

    def __init__(self, responses, **kwargs):
        super().__init__(messages=iter(responses), **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append((messages, kwargs))
        return super()._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


def sample_project():
    return ProjectKnowledge(
        project_id=7,
        project_name="订单服务",
        topics=[Topic(name="事务", score=80, evidence=["e1"])],
        components={"OrderService": "订单业务服务"},
        evidence={"e1": {"source_path": "src/OrderService.java", "excerpt": "@Transactional"}},
        dependencies={"OrderController": ["OrderService"]},
    )


def client_with(responses):
    return OpenAICompatibleClient(
        LLMConfig("https://example.test/v1", "secret", "demo-model"),
        llm=RecordingChatModel(responses),
    )


class LLMTests(unittest.TestCase):
    def test_config_reads_openai_compatible_settings(self):
        config = LLMConfig.from_env(
            {
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "https://apihub.agnes-ai.com/v1/",
                "LLM_API_KEY": "secret",
                "LLM_MODEL": "agnes-2.0-flash",
                "LLM_API_MODE": "chat_completions",
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, "https://apihub.agnes-ai.com/v1")
        self.assertEqual(config.model, "agnes-2.0-flash")
        self.assertEqual(config.api_mode, "chat_completions")

    def test_client_chats_through_langchain_model(self):
        client = client_with(["收到"])

        result = client.chat([{"role": "user", "content": "你好"}])

        self.assertEqual(result, "收到")
        self.assertEqual(len(client._llm.calls), 1)
        messages = client._llm.calls[0][0]
        self.assertEqual(messages[0].type, "human")
        self.assertEqual(messages[0].content, "你好")

    def test_client_lists_models_from_underlying_openai_client(self):
        class FakeModels:
            def list(self):
                return [
                    SimpleNamespace(id="agnes-2.0-flash"),
                    SimpleNamespace(id="agnes-2.0-pro"),
                ]

        fake_llm = SimpleNamespace(client=SimpleNamespace(models=FakeModels()))
        client = OpenAICompatibleClient(
            LLMConfig("https://example.test/v1", "secret", "unused-model"),
            llm=fake_llm,
        )

        result = client.list_models()

        self.assertEqual(result, ("agnes-2.0-flash", "agnes-2.0-pro"))

    def test_config_can_validate_provider_credentials_without_a_model_for_listing(self):
        config = LLMConfig.from_payload(
            {
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
            },
            require_model=False,
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.model, "")

    def test_question_generator_maps_json_and_keeps_evidence_references(self):
        client = client_with(
            [
                json.dumps(
                    {
                        "question": "事务失败时如何保证订单状态一致？",
                        "evidence_ids": ["e1"],
                        "covered_points": ["事务边界"],
                        "missing_points": ["重试策略"],
                    },
                    ensure_ascii=False,
                )
            ]
        )
        generator = LlmQuestionGenerator(client)

        result = generator.generate(
            topic=sample_project().topics[0],
            project=sample_project(),
            level=2,
            history=[],
            evidence=({"id": "e1", "source_path": "src/OrderService.java"},),
            evidence_ids=("e1",),
        )

        self.assertIsInstance(result, QuestionResult)
        self.assertEqual(result.question, "事务失败时如何保证订单状态一致？")
        self.assertEqual(result.evidence_ids, ("e1",))
        sent_messages = client._llm.calls[0][0]
        user_content = sent_messages[1].content
        self.assertIn("项目知识", user_content)
        self.assertIn("提问建议", user_content)
        self.assertIn("不得把证据的文件路径", user_content)

    def test_project_payload_omits_full_evidence_dump(self):
        client = client_with(
            [
                json.dumps(
                    {
                        "question": "事务失败时如何保证订单状态一致？",
                        "evidence_ids": ["e1"],
                        "covered_points": [],
                        "missing_points": [],
                    },
                    ensure_ascii=False,
                )
            ]
        )
        project = ProjectKnowledge(
            project_id=7,
            project_name="订单服务",
            topics=[Topic(name="事务", score=80, evidence=["e1"])],
            components={"OrderService": "订单业务服务"},
            evidence={
                "e1": {"source_path": "src/OrderService.java", "excerpt": "当前证据"},
                "e2": {"source_path": "src/BigBlob.java", "excerpt": "不应进入 prompt 的全量证据"},
            },
            dependencies={"OrderController": ["OrderService"]},
        )
        generator = LlmQuestionGenerator(client)

        generator.generate(
            topic=project.topics[0],
            project=project,
            level=2,
            history=[],
            evidence=({"id": "e1", "source_path": "src/OrderService.java", "excerpt": "当前证据"},),
            evidence_ids=("e1",),
        )

        user_content = client._llm.calls[0][0][1].content
        self.assertIn("当前证据", user_content)
        self.assertNotIn("BigBlob", user_content)
        self.assertNotIn("不应进入 prompt 的全量证据", user_content)

    def test_question_generator_replaces_code_detail_question_with_system_question(self):
        client = client_with(
            [
                json.dumps(
                    {
                        "question": "OrderService.java 里的 createOrder 方法如何实现事务？",
                        "evidence_ids": ["e1"],
                    },
                    ensure_ascii=False,
                )
            ]
        )
        generator = LlmQuestionGenerator(client)

        result = generator.generate(
            topic=Topic("数据一致性与状态管理", 85, ["e1"]),
            project=sample_project(),
            level=1,
            history=[],
            evidence=({"id": "e1", "source_path": "src/OrderService.java"},),
            evidence_ids=("e1",),
        )

        self.assertNotIn("OrderService", result.question)
        self.assertNotIn(".java", result.question)
        self.assertIn("关键状态和数据", result.question)

    def test_question_generator_keeps_class_and_method_names(self):
        client = client_with(
            [
                json.dumps(
                    {
                        "question": "OrderService 的 createOrder 方法在事务失败时如何保证订单一致？",
                        "evidence_ids": ["e1"],
                        "covered_points": [],
                        "missing_points": [],
                    },
                    ensure_ascii=False,
                )
            ]
        )
        generator = LlmQuestionGenerator(client)

        result = generator.generate(
            topic=sample_project().topics[0],
            project=sample_project(),
            level=2,
            history=[],
            evidence=({"id": "e1", "source_path": "src/OrderService.java"},),
            evidence_ids=("e1",),
        )

        self.assertEqual(
            result.question,
            "OrderService 的 createOrder 方法在事务失败时如何保证订单一致？",
        )

    def test_question_generator_falls_back_when_response_omits_question(self):
        client = client_with([json.dumps({"evidence_ids": ["e1"]}, ensure_ascii=False)])
        generator = LlmQuestionGenerator(client)

        result = generator.generate(
            topic=sample_project().topics[0],
            project=sample_project(),
            level=1,
            history=[],
            evidence_ids=("e1",),
        )

        self.assertIn("订单服务", result.question)
        self.assertEqual(result.evidence_ids, ("e1",))

    def test_evaluator_maps_json_to_evaluation(self):
        client = client_with(
            [
                '{"score": 85, "strengths": ["说明了事务边界"], "weaknesses": [], "feedback": "回答清晰", "evidence_ids": ["e1"], "covered_points": ["事务边界"], "missing_points": []}'
            ]
        )
        evaluator = LlmEvaluator(client)

        result = evaluator.evaluate(
            question="如何保证一致性？",
            answer="通过事务边界保证。",
            topic=sample_project().topics[0],
            project=sample_project(),
            evidence=({"id": "e1"},),
            evidence_ids=("e1",),
        )

        self.assertIsInstance(result, Evaluation)
        self.assertEqual(result.score, 85)
        self.assertEqual(result.evidence_ids, ("e1",))

    def test_invalid_json_raises_explicit_response_error(self):
        generator = LlmQuestionGenerator(client_with(["不是 JSON"]))

        with self.assertRaises(LLMResponseError):
            generator.generate(
                topic=sample_project().topics[0],
                project=sample_project(),
                level=1,
                history=[],
            )

    def test_agent_from_environment_keeps_rule_based_default(self):
        repository = InMemoryProjectRepository()
        with patch.dict(os.environ, {}, clear=True):
            agent = agent_from_environment(repository)

        self.assertEqual(agent.__class__.__name__, "InterviewAgent")
        self.assertEqual(
            agent.question_generator.__class__.__name__,
            "RuleBasedQuestionGenerator",
        )

    def test_agent_from_environment_requires_complete_llm_config(self):
        with self.assertRaises(ValueError):
            LLMConfig.from_env(
                {
                    "LLM_PROVIDER": "openai_compatible",
                    "LLM_BASE_URL": "https://example.test/v1",
                    "LLM_MODEL": "demo-model",
                }
            )

    def test_agent_from_environment_injects_llm_adapters_when_enabled(self):
        repository = InMemoryProjectRepository()
        agent = agent_from_environment(
            repository,
            {
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "https://example.test/v1",
                "LLM_API_KEY": "secret",
                "LLM_MODEL": "demo-model",
            },
        )

        self.assertIsInstance(agent.question_generator, LlmQuestionGenerator)
        self.assertIsInstance(agent.evaluator, LlmEvaluator)


if __name__ == "__main__":
    unittest.main()
