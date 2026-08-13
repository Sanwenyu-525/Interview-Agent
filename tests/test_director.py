import unittest

from langchain_core.messages import AIMessage

from interview_agent.models import AnswerRecord, Evaluation, ProjectKnowledge, Topic
from interview_agent.profile import CandidateProfile, SkillSnapshot
from interview_agent.review.director import DirectorAction, ToolCallingDirector
from interview_agent.review.policy import ReviewMode


def make_project():
    return ProjectKnowledge(
        project_id=1,
        project_name="支付系统",
        topics=[Topic(name="支付", score=80, evidence=["e1"])],
        evidence={
            "e1": {
                "id": "e1",
                "source_path": "src/pay.py",
                "excerpt": "def settle()",
            }
        },
    )


def make_profile():
    return CandidateProfile(
        skills={
            "支付": SkillSnapshot(score=60, trend="stable", sample_count=2, weaknesses=("缺乏权衡说明",)),
        }
    )


def make_history():
    return [
        AnswerRecord(
            question="介绍一下支付流程",
            answer="用了事务保证一致性",
            topic="支付",
            level=1,
            evaluation=Evaluation(score=70),
        )
    ]


class FakeClient:
    """模拟 OpenAICompatibleClient：bind_tools 返回自身，invoke 依序返回给定响应。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.tools = []
        self.invocations = []

    def bind_tools(self, tools):
        self.tools = list(tools)
        return self

    def invoke(self, messages):
        self.invocations.append(messages)
        if not self._responses:
            raise AssertionError("fake client 没有更多响应")
        return self._responses.pop(0)


def decide(client, **overrides):
    kwargs = dict(
        project=make_project(),
        profile=make_profile(),
        history=make_history(),
        resume_claims=(),
        current_topic=Topic(name="支付", score=80, evidence=["e1"]),
        current_level=2,
        last_score=70,
        turn_count=3,
        max_turns=8,
    )
    kwargs.update(overrides)
    return ToolCallingDirector(client).decide_turn(**kwargs)


class DirectorDecisionTests(unittest.TestCase):
    def test_decides_ask_with_valid_topic_and_direction(self):
        client = FakeClient(
            [
                AIMessage(
                    content='{"action":"ask","topic":"支付","direction":"deep","level":3,"reason":"继续深挖权衡"}'
                )
            ]
        )
        action = decide(client)
        self.assertEqual(action, DirectorAction("ask", "支付", "deep", 3, "继续深挖权衡"))

    def test_decides_stop(self):
        client = FakeClient(
            [AIMessage(content='{"action":"stop","reason":"已覆盖充分"}')]
        )
        action = decide(client)
        self.assertEqual(action.action, "stop")
        self.assertEqual(action.reason, "已覆盖充分")

    def test_calls_query_evidence_tool_before_deciding(self):
        client = FakeClient(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "query_evidence", "args": {"topic_name": "支付"}, "id": "call_1"}
                    ],
                ),
                AIMessage(
                    content='{"action":"ask","topic":"支付","direction":"architecture","level":4,"reason":"基于证据追问演进"}'
                ),
            ]
        )
        action = decide(client)
        self.assertEqual(action.action, "ask")
        self.assertEqual(action.level, 4)
        # 第一轮调用工具，第二轮输出决策
        self.assertEqual(len(client.invocations), 2)
        tool_names = [tool.name for tool in client.tools]
        self.assertEqual(
            tool_names, ["query_evidence", "read_history", "get_profile"]
        )

    def test_rejects_unknown_topic(self):
        client = FakeClient(
            [
                AIMessage(
                    content='{"action":"ask","topic":"不存在","direction":"deep","level":2}'
                )
            ]
        )
        self.assertIsNone(decide(client))

    def test_rejects_invalid_direction(self):
        client = FakeClient(
            [
                AIMessage(
                    content='{"action":"ask","topic":"支付","direction":"hack","level":2}'
                )
            ]
        )
        self.assertIsNone(decide(client))

    def test_rejects_out_of_range_level(self):
        client = FakeClient(
            [
                AIMessage(
                    content='{"action":"ask","topic":"支付","direction":"deep","level":9}'
                )
            ]
        )
        self.assertIsNone(decide(client))

    def test_invalid_json_returns_none(self):
        client = FakeClient([AIMessage(content="不是 JSON")])
        self.assertIsNone(decide(client))

    def test_llm_exception_returns_none(self):
        class ExplodingClient(FakeClient):
            def invoke(self, messages):
                raise RuntimeError("上游失败")

        self.assertIsNone(decide(ExplodingClient([])))


if __name__ == "__main__":
    unittest.main()
