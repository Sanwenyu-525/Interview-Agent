import unittest

from interview_agent.agent import InterviewAgent, RuleBasedQuestionGenerator
from interview_agent.models import ProjectKnowledge, Topic
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.review.outline import InterviewOutlineBuilder


def analyzed_project(*, topics=None):
    return ProjectKnowledge(
        project_id=1,
        project_name="订单系统",
        topics=topics
        if topics is not None
        else [
            Topic("HTTP API", 75, ["e-api"]),
            Topic("Transaction", 70, ["e-transaction"]),
        ],
        components={
            "OrderController": "src/OrderController.java",
            "OrderService": "src/OrderService.java",
        },
        evidence={
            "e-component": {
                "id": "e-component",
                "kind": "component",
                "source_path": "src/OrderController.java",
                "excerpt": "controller",
            },
            "e-api": {
                "id": "e-api",
                "kind": "flow",
                "source_path": "src/OrderController.java",
                "excerpt": "POST /orders",
            },
            "e-transaction": {
                "id": "e-transaction",
                "kind": "topic",
                "source_path": "src/OrderService.java",
                "excerpt": "transaction boundary",
            },
            "e-build": {
                "id": "e-build",
                "kind": "technology",
                "source_path": "pom.xml",
                "excerpt": "build dependency",
            },
        },
        dependencies={"OrderController": ["OrderService", "OrderRepository"]},
    )


class InterviewOutlineTests(unittest.TestCase):
    def test_analyzed_facts_are_synthesized_into_a_few_system_directions(self):
        project = analyzed_project()

        directions = InterviewOutlineBuilder().build(project)

        names = [direction.name for direction in directions]
        self.assertGreaterEqual(len(directions), 3)
        self.assertLessEqual(len(directions), 5)
        self.assertIn("系统架构与模块协作", names)
        self.assertIn("接口设计与前后端联调", names)
        self.assertIn("数据一致性与状态管理", names)
        self.assertNotIn("HTTP API", names)
        self.assertNotIn("Transaction", names)
        self.assertTrue(
            all(
                evidence_id in project.evidence
                for direction in directions
                for evidence_id in direction.evidence
            )
        )

    def test_agent_starts_with_outline_and_a_system_level_question(self):
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: analyzed_project()}),
        )

        state = agent.start(project_id=1)

        self.assertEqual(state.current_topic.name, "系统架构与模块协作")
        self.assertEqual(
            state.question,
            "请从整体上介绍订单系统：系统由哪些主要部分组成，它们如何协作完成核心目标？",
        )
        self.assertIn(
            "接口设计与前后端联调",
            [topic.name for topic in state.project.topics],
        )
        for code_detail in ("OrderController", "OrderService", ".java", "具体代码"):
            self.assertNotIn(code_detail, state.question)

    def test_analyzed_frontend_without_raw_topics_can_still_start(self):
        project = analyzed_project(topics=[])
        project.evidence["e-api"]["kind"] = "frontend_api"

        state = InterviewAgent(
            repository=InMemoryProjectRepository({1: project}),
        ).start(project_id=1)

        self.assertTrue(state.project.topics)
        self.assertIn(
            "接口设计与前后端联调",
            [topic.name for topic in state.project.topics],
        )

    def test_deep_follow_up_asks_about_flow_instead_of_code(self):
        question = RuleBasedQuestionGenerator().generate(
            topic=Topic("接口设计与前后端联调", 95, ["e-api"]),
            project=analyzed_project(),
            level=2,
            history=[],
            review_direction="deep",
        )

        self.assertIn("关键流程", question)
        self.assertNotIn("具体实现", question)
        self.assertNotIn("OrderController", question)


if __name__ == "__main__":
    unittest.main()
