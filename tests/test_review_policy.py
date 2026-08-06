import unittest

from interview_agent.models import ProjectKnowledge, Topic
from interview_agent.profile import CandidateProfile, SkillSnapshot
from interview_agent.review import (
    DefenseReviewPolicy,
    PortfolioReviewPolicy,
    ReviewMode,
    ReviewPolicy,
    TechnicalInterviewPolicy,
)
from interview_agent.review.policy import policy_for_mode
from interview_agent.review.technical import topic_evidence


class ReviewPolicyTests(unittest.TestCase):
    def test_review_modes_are_recognized_and_review_policies_are_registered(self):
        self.assertEqual(ReviewMode.TECHNICAL_INTERVIEW.value, "technical_interview")
        self.assertIsInstance(TechnicalInterviewPolicy(), ReviewPolicy)
        self.assertIsInstance(
            policy_for_mode(ReviewMode.PORTFOLIO_REVIEW), PortfolioReviewPolicy
        )
        self.assertIsInstance(
            policy_for_mode(ReviewMode.DEFENSE_REVIEW), DefenseReviewPolicy
        )

    def test_defense_prioritizes_goal_decision_risk_and_real_evidence(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Generic", score=100),
                Topic(name="Project Goal", score=50, evidence=["e-goal"]),
                Topic(name="Transaction Decision", score=60, evidence=["e-decision"]),
                Topic(name="Failure Risk", score=70, evidence=["e-risk"]),
            ],
            components={"Transaction Decision": "OrderService"},
            dependencies={"OrderController": ["Transaction Decision"]},
            evidence={
                "e-goal": {"kind": "goal", "summary": "protect order consistency"},
                "e-decision": {"kind": "decision", "summary": "transaction boundary"},
                "e-risk": {"kind": "risk", "summary": "failure rollback"},
            },
            weaknesses=["Failure Risk can lose consistency"],
        )

        policy = DefenseReviewPolicy()

        self.assertEqual(
            policy.select_topic(project, CandidateProfile(), []).name,
            "Project Goal",
        )
        self.assertEqual(policy.next_direction(59, 3), ("clarify", 1))
        self.assertEqual(policy.next_direction(60, 1), ("justify", 2))
        self.assertEqual(policy.next_direction(79, 3), ("justify", 3))
        self.assertEqual(policy.next_direction(80, 2), ("defend", 4))

    def test_defense_real_evidence_beats_ghost_topic(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Ghost Risk", score=100, evidence=["missing"]),
                Topic(name="Order Decision", score=70, evidence=["e-decision"]),
            ],
            evidence={"e-decision": {"kind": "decision", "source_path": "OrderService.java"}},
        )

        self.assertEqual(
            DefenseReviewPolicy().select_topic(project, CandidateProfile(), []).name,
            "Order Decision",
        )

    def test_portfolio_prioritizes_real_evidence_and_component_flow_facts(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Generic", score=100),
                Topic(name="OrderService", score=70, evidence=["e-service"]),
            ],
            components={"OrderService": "service/OrderService.java"},
            evidence={
                "e-service": {
                    "source_path": "OrderService.java",
                    "kind": "component",
                },
            },
            dependencies={"OrderController": ["OrderService"]},
        )
        policy = PortfolioReviewPolicy()

        self.assertEqual(
            policy.select_topic(project, CandidateProfile(), []).name,
            "OrderService",
        )
        self.assertEqual(policy.next_direction(59, 3), ("story", 1))
        self.assertEqual(policy.next_direction(60, 1), ("tradeoff", 2))
        self.assertEqual(policy.next_direction(79, 3), ("tradeoff", 3))
        self.assertEqual(policy.next_direction(80, 2), ("impact", 4))

    def test_topic_with_evidence_beats_higher_priority_topic_without_evidence(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Generic", score=100),
                Topic(name="Transaction", score=70, evidence=["e-transaction"]),
            ],
            evidence={
                "e-transaction": {"source_path": "OrderService.java"},
            },
        )

        topic = TechnicalInterviewPolicy().select_topic(
            project, CandidateProfile(), []
        )

        self.assertEqual(topic.name, "Transaction")

    def test_candidate_weakness_is_used_as_deterministic_tiebreaker(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Cache", score=80, evidence=["e-cache"]),
                Topic(name="Transaction", score=80, evidence=["e-tx"]),
            ],
            evidence={
                "e-cache": {"source_path": "CacheService.java"},
                "e-tx": {"source_path": "OrderService.java"},
            },
        )
        profile = CandidateProfile(
            skills={"Transaction": SkillSnapshot(score=40, trend="declining")}
        )

        topic = TechnicalInterviewPolicy().select_topic(project, profile, [])

        self.assertEqual(topic.name, "Transaction")

    def test_direction_boundaries_preserve_existing_interview_levels(self):
        policy = TechnicalInterviewPolicy()

        self.assertEqual(policy.next_direction(59, 3), ("basic", 1))
        self.assertEqual(policy.next_direction(60, 1), ("deep", 2))
        self.assertEqual(policy.next_direction(79, 3), ("deep", 3))
        self.assertEqual(policy.next_direction(80, 2), ("architecture", 4))
        self.assertEqual(policy.next_direction(100, 4), ("architecture", 4))

    def test_missing_evidence_is_not_counted_and_ghost_topic_cannot_beat_real_topic(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Ghost", score=100, evidence=["missing"]),
                Topic(name="Transaction", score=70, evidence=["e-transaction"]),
            ],
            evidence={
                "e-transaction": {"source_path": "OrderService.java"},
            },
        )

        self.assertEqual(topic_evidence(project, project.topics[0]), [])
        self.assertEqual(
            TechnicalInterviewPolicy().select_topic(project, CandidateProfile(), []).name,
            "Transaction",
        )

    def test_policy_mode_and_dependency_relation_bonus_are_deterministic(self):
        policy = TechnicalInterviewPolicy()
        self.assertEqual(policy.mode, ReviewMode.TECHNICAL_INTERVIEW)
        project = ProjectKnowledge(
            project_id=1,
            project_name="Order System",
            topics=[
                Topic(name="Cache", score=70, evidence=["e-cache"]),
                Topic(name="OrderService", score=70, evidence=["e-service"]),
            ],
            evidence={
                "e-service": {"source_path": "OrderService.java"},
                "e-cache": {"source_path": "CacheService.java"},
            },
            dependencies={"OrderService": ["OrderRepository"]},
        )

        self.assertEqual(
            policy.select_topic(project, CandidateProfile(), []).name,
            "OrderService",
        )


if __name__ == "__main__":
    unittest.main()
