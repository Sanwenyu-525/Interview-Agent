import json
import unittest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from pydantic import Field

from interview_agent.llm import LLMConfig, LLMError, OpenAICompatibleClient, agent_from_config
from interview_agent.models import ProjectKnowledge, Topic
from interview_agent.profile import CandidateProfile
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.review import LlmReviewPolicy, ReviewMode
from interview_agent.service import InterviewService


class RecordingChatModel(GenericFakeChatModel):
    """记录调用消息的测试替身，返回预设响应。"""

    calls: list = Field(default_factory=list)

    def __init__(self, responses, **kwargs):
        super().__init__(messages=iter(responses), **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append((messages, kwargs))
        return super()._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


class FailingClient:
    def chat(self, *args, **kwargs):
        raise LLMError("boom")


def sample_project():
    return ProjectKnowledge(
        project_id=1,
        project_name="示例项目",
        topics=[
            Topic(name="事务", score=80, evidence=["e1"]),
            Topic(name="缓存", score=90, evidence=["e2"]),
            Topic(name="消息队列", score=70, evidence=["e3"]),
        ],
        components={},
        evidence={
            "e1": {"id": "e1", "kind": "source", "source_path": "src/Flow.java"},
            "e2": {"id": "e2", "kind": "source", "source_path": "src/Cache.java"},
            "e3": {"id": "e3", "kind": "source", "source_path": "src/Mq.java"},
        },
        dependencies={},
        weaknesses=[],
    )


def client_with(responses):
    return OpenAICompatibleClient(
        LLMConfig("https://example.test/v1", "secret", "demo-model"),
        llm=RecordingChatModel(responses),
    )


def _payload(topic_name, reason="测试理由"):
    return json.dumps({"topic_name": topic_name, "reason": reason}, ensure_ascii=False)


class LlmReviewPolicyTests(unittest.TestCase):
    def test_select_topic_uses_valid_llm_choice(self):
        policy = LlmReviewPolicy(client_with([_payload("缓存")]))

        result = policy.select_topic(sample_project(), CandidateProfile(), [])

        self.assertEqual(result.name, "缓存")

    def test_select_topic_falls_back_to_rule_on_unknown_topic(self):
        policy = LlmReviewPolicy(client_with([_payload("量子计算")]))

        result = policy.select_topic(sample_project(), CandidateProfile(), [])

        self.assertEqual(result.name, "缓存")

    def test_select_topic_falls_back_to_rule_on_invalid_json(self):
        policy = LlmReviewPolicy(client_with(["不是 JSON"]))

        result = policy.select_topic(sample_project(), CandidateProfile(), [])

        self.assertEqual(result.name, "缓存")

    def test_select_topic_falls_back_to_rule_when_client_fails(self):
        policy = LlmReviewPolicy(FailingClient())

        result = policy.select_topic(sample_project(), CandidateProfile(), [])

        self.assertEqual(result.name, "缓存")

    def test_next_direction_uses_valid_llm_choice(self):
        policy = LlmReviewPolicy(
            client_with([json.dumps({"direction": "deep", "level": 3})])
        )

        result = policy.next_direction(85, 1)

        self.assertEqual(result, ("deep", 3))

    def test_next_direction_rejects_unknown_direction(self):
        policy = LlmReviewPolicy(
            client_with([json.dumps({"direction": "middle", "level": 3})])
        )

        result = policy.next_direction(85, 1)

        self.assertEqual(result, ("architecture", 4))

    def test_next_direction_rejects_out_of_range_level(self):
        policy = LlmReviewPolicy(
            client_with([json.dumps({"direction": "deep", "level": 9})])
        )

        result = policy.next_direction(85, 1)

        self.assertEqual(result, ("architecture", 4))

    def test_next_direction_rejects_non_integer_level(self):
        policy = LlmReviewPolicy(
            client_with([json.dumps({"direction": "deep", "level": "x"})])
        )

        result = policy.next_direction(85, 1)

        self.assertEqual(result, ("architecture", 4))

    def test_next_direction_falls_back_when_client_fails(self):
        policy = LlmReviewPolicy(FailingClient())

        result = policy.next_direction(50, 1)

        self.assertEqual(result, ("basic", 1))

    def test_non_technical_mode_uses_its_own_direction_set(self):
        policy = LlmReviewPolicy(
            client_with([json.dumps({"direction": "justify", "level": 2})]),
            ReviewMode.DEFENSE_REVIEW,
        )

        result = policy.next_direction(70, 1)

        self.assertEqual(result, ("justify", 2))


class LlmReviewPolicyIntegrationTests(unittest.TestCase):
    def test_agent_from_config_injects_llm_review_policy(self):
        agent = agent_from_config(
            InMemoryProjectRepository(),
            LLMConfig("https://example.test/v1", "secret", "demo-model"),
        )

        self.assertIsInstance(agent.policy, LlmReviewPolicy)
        self.assertEqual(agent.policy.mode, ReviewMode.TECHNICAL_INTERVIEW)
        self.assertEqual(
            agent.policy_builder(ReviewMode.DEFENSE_REVIEW).mode,
            ReviewMode.DEFENSE_REVIEW,
        )

    def test_service_uses_llm_policy_builder_for_non_technical_mode(self):
        repository = InMemoryProjectRepository()
        service = InterviewService(
            repository=repository,
            llm_config=LLMConfig("https://example.test/v1", "secret", "demo-model"),
        )

        agent = service._agent_for_profile(CandidateProfile(), ReviewMode.DEFENSE_REVIEW)

        self.assertIsInstance(agent.policy, LlmReviewPolicy)
        self.assertEqual(agent.policy.mode, ReviewMode.DEFENSE_REVIEW)


if __name__ == "__main__":
    unittest.main()