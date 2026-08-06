import json
import unittest
from dataclasses import asdict

from interview_agent.agent import InterviewAgent
from interview_agent.models import (
    Evaluation,
    ProjectKnowledge,
    QuestionResult,
    ReviewContext,
    Topic,
)
from interview_agent.profile import ProfileUpdater
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.review import DefenseReviewPolicy, PortfolioReviewPolicy
from interview_agent.review.technical import topic_evidence
from interview_agent.tools import ProjectTools


class FixedQuestionGenerator:
    def generate(self, *, topic, project, level, history):
        return f"{topic.name} / Level {level} / {project.project_name}"


class FixedEvaluator:
    def __init__(self, evaluation):
        self.evaluation = evaluation

    def evaluate(self, *, question, answer, topic, project):
        return self.evaluation


class SequencedEvaluator:
    def __init__(self, scores):
        self.scores = iter(scores)

    def evaluate(self, *, question, answer, topic, project):
        return Evaluation(score=next(self.scores))


class DirectionAwareQuestionGenerator:
    def __init__(self):
        self.directions = []

    def generate(self, *, topic, project, level, history, review_direction=None):
        self.directions.append(review_direction)
        return f"{review_direction or 'initial'} / {topic.name}"


class ContextQuestionGenerator:
    def __init__(self):
        self.evidence = None

    def generate(self, *, topic, project, level, history, evidence):
        self.evidence = evidence
        return QuestionResult(
            question=f"{topic.name} / Level {level}",
            evidence_ids=[item["id"] for item in evidence],
            covered_points=[topic.name],
        )


class ContextEvaluator:
    def __init__(self):
        self.evidence = None

    def evaluate(self, *, question, answer, topic, project, evidence):
        self.evidence = evidence
        return Evaluation(
            score=70,
            evidence_ids=[item["id"] for item in evidence],
            covered_points=[topic.name],
            missing_points=["rollback"],
        )


class CanonicalContextGenerator:
    def __init__(self):
        self.context = None

    def generate(self, *, topic, project, level, history, evidence, evidence_ids, context):
        self.context = (evidence, evidence_ids, context)
        return {
            "question": f"{topic.name} / canonical",
            "evidence_ids": [*evidence_ids, "ghost-question"],
        }


class CanonicalContextEvaluator:
    def __init__(self):
        self.context = None

    def evaluate(self, *, question, answer, topic, project, evidence, evidence_ids, context):
        self.context = (evidence, evidence_ids, context)
        return Evaluation(score=70, evidence_ids=("ghost-evaluation",))


class CallableQuestionGenerator:
    class Generate:
        def __call__(self, *, topic, project, level, history):
            return f"{topic.name} / callable"

    generate = Generate()


class UninspectableQuestionGenerator:
    class Generate:
        __signature__ = object()

        def __call__(self, *, topic, project, level, history):
            return f"{topic.name} / opaque"

    generate = Generate()


class TopicSwitchingPolicy:
    def __init__(self):
        self.calls = []

    def select_topic(self, project, profile, history):
        self.calls.append((profile, history))
        return project.topics[0 if not history else 1]

    def next_direction(self, score, current_level):
        return "deep", 2


def sample_project():
    return ProjectKnowledge(
        project_id=1,
        project_name="订单系统",
        topics=[
            Topic(name="Redis", score=85, evidence=["CacheService.java"]),
            Topic(name="Transaction", score=90, evidence=["OrderService.java"]),
        ],
        components={"OrderService": "service/OrderService.java"},
        evidence={
            "Redis": {"file": "CacheService.java", "code": "RedisTemplate"},
            "OrderService.java": {"file": "OrderService.java", "code": "@Transactional"},
        },
        dependencies={"OrderController": ["OrderService", "OrderRepository"]},
    )


class InterviewAgentTests(unittest.TestCase):
    def test_submit_answer_updates_profile_once_through_profile_updater_and_reselects_topic(self):
        repository = InMemoryProjectRepository(
            {
                1: ProjectKnowledge(
                    project_id=1,
                    project_name="Order",
                    topics=[
                        Topic(name="Transaction", score=80),
                        Topic(name="Cache", score=80),
                    ],
                )
            }
        )
        policy = TopicSwitchingPolicy()

        class CountingUpdater(ProfileUpdater):
            def __init__(self):
                self.calls = 0

            def update(self, profile, topic, evaluation):
                self.calls += 1
                return super().update(profile, topic, evaluation)

        updater = CountingUpdater()
        agent = InterviewAgent(
            repository=repository,
            evaluator=FixedEvaluator(Evaluation(score=70, weaknesses=["缺少缓存说明"])),
            policy=policy,
            profile_updater=updater,
        )

        updated = agent.submit_answer(agent.start(project_id=1), "answer")

        self.assertEqual(updater.calls, 1)
        self.assertEqual(updated.current_topic.name, "Cache")
        self.assertEqual(updated.history[0].topic, "Transaction")
        self.assertEqual(agent.profile.skills["Transaction"].sample_count, 1)

    def test_submit_answer_clears_pending_answer_and_preserves_last_submitted_fields(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(Evaluation(score=70)),
        )
        state = agent.start(project_id=1)

        updated = agent.submit_answer(state, "submitted answer")

        self.assertEqual(updated.answer, "")
        self.assertEqual(updated.last_submitted_question, state.question)
        self.assertEqual(updated.last_submitted_answer, "submitted answer")
        self.assertEqual(updated.evaluation.score, 70)

    def test_non_perfect_answer_gets_a_reference_answer(self):
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: sample_project()}),
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(Evaluation(score=90)),
        )

        updated = agent.submit_answer(agent.start(project_id=1), "partial answer")

        self.assertTrue(updated.evaluation.reference_answer)

    def test_perfect_answer_does_not_get_a_reference_answer(self):
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: sample_project()}),
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(
                Evaluation(score=100, reference_answer="不应展示")
            ),
        )

        updated = agent.submit_answer(agent.start(project_id=1), "perfect answer")

        self.assertEqual(updated.evaluation.reference_answer, "")

    def test_portfolio_direction_changes_default_follow_up_question_content(self):
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: sample_project()}),
            evaluator=SequencedEvaluator([20, 70, 90]),
            policy=PortfolioReviewPolicy(),
        )

        state = agent.start(project_id=1)
        story = agent.submit_answer(state, "answer")
        tradeoff = agent.submit_answer(story, "answer")
        impact = agent.submit_answer(tradeoff, "answer")

        self.assertIn("背景", story.question)
        self.assertIn("权衡", tradeoff.question)
        self.assertIn("影响", impact.question)

    def test_portfolio_direction_is_optional_question_generator_context(self):
        generator = DirectionAwareQuestionGenerator()
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: sample_project()}),
            question_generator=generator,
            evaluator=SequencedEvaluator([20, 70, 90]),
            policy=PortfolioReviewPolicy(),
        )

        state = agent.start(project_id=1)
        state = agent.submit_answer(state, "answer")
        state = agent.submit_answer(state, "answer")
        agent.submit_answer(state, "answer")

        self.assertEqual(
            generator.directions,
            ["", "story", "tradeoff", "impact"],
        )

    def test_defense_direction_is_passed_to_follow_up_question_generation(self):
        generator = DirectionAwareQuestionGenerator()
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: sample_project()}),
            question_generator=generator,
            evaluator=SequencedEvaluator([20, 70, 90]),
            policy=DefenseReviewPolicy(),
        )

        state = agent.start(project_id=1)
        state = agent.submit_answer(state, "answer")
        state = agent.submit_answer(state, "answer")
        agent.submit_answer(state, "answer")

        self.assertEqual(
            generator.directions,
            ["", "clarify", "justify", "defend"],
        )

    def test_failed_next_question_generation_does_not_commit_profile(self):
        repository = InMemoryProjectRepository({1: sample_project()})

        class FailingGenerator:
            def __init__(self):
                self.calls = 0

            def generate(self, *, topic, project, level, history):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("planner failed")
                return "initial question"

        agent = InterviewAgent(
            repository=repository,
            question_generator=FailingGenerator(),
            evaluator=FixedEvaluator(Evaluation(score=70)),
        )
        state = agent.start(project_id=1)

        with self.assertRaisesRegex(RuntimeError, "planner failed"):
            agent.submit_answer(state, "answer")

        self.assertEqual(agent.profile.skills, {})
    def test_start_selects_highest_priority_topic_and_generates_question(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
        )

        state = agent.start(project_id=1)

        self.assertEqual(state.current_topic.name, "Transaction")
        self.assertEqual(state.level, 1)
        self.assertEqual(state.question, "Transaction / Level 1 / 订单系统")
        self.assertEqual(state.status, "waiting_answer")

    def test_low_score_keeps_topic_and_asks_basic_follow_up(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(
                Evaluation(score=45, strengths=[], weaknesses=["缺少回滚说明"])
            ),
        )
        state = agent.start(project_id=1)

        next_state = agent.submit_answer(state, "保证数据库操作成功")

        self.assertEqual(next_state.current_topic.name, "Transaction")
        self.assertEqual(next_state.level, 1)
        self.assertEqual(next_state.next_direction, "basic")
        self.assertEqual(next_state.status, "waiting_answer")
        self.assertEqual(len(next_state.history), 1)
        self.assertEqual(next_state.history[0].evaluation.score, 45)

    def test_high_score_updates_profile_and_moves_to_architecture_question(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(
                Evaluation(score=90, strengths=["能说明一致性方案"], weaknesses=[])
            ),
        )
        state = agent.start(project_id=1)

        next_state = agent.submit_answer(state, "使用事务并处理回滚和隔离级别")

        self.assertEqual(next_state.level, 4)
        self.assertEqual(next_state.next_direction, "architecture")
        self.assertEqual(next_state.question, "Transaction / Level 4 / 订单系统")
        self.assertEqual(agent.profile.skills["Transaction"].score, 90)

    def test_project_tools_return_project_evidence(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        tools = ProjectTools(repository)

        self.assertEqual(
            tools.search_component(1, "OrderService"),
            {"name": "OrderService", "file": "service/OrderService.java"},
        )
        self.assertEqual(
            tools.get_evidence(1, "Redis"),
            {"file": "CacheService.java", "code": "RedisTemplate"},
        )
        self.assertEqual(
            tools.get_dependency_graph(1, "OrderController"),
            ["OrderService", "OrderRepository"],
        )
        self.assertEqual(tools.get_candidate_weakness(1), [])

    def test_medium_score_moves_to_deep_follow_up(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
            evaluator=FixedEvaluator(Evaluation(score=70)),
        )

        next_state = agent.submit_answer(agent.start(project_id=1), "说明缓存策略")

        self.assertEqual(next_state.next_direction, "deep")
        self.assertEqual(next_state.level, 2)

    def test_empty_answer_and_project_without_topics_are_rejected(self):
        repository = InMemoryProjectRepository(
            {
                1: sample_project(),
                2: ProjectKnowledge(project_id=2, project_name="空项目", topics=[]),
            }
        )
        agent = InterviewAgent(repository=repository)

        with self.assertRaises(ValueError):
            agent.submit_answer(agent.start(project_id=1), "   ")
        with self.assertRaises(ValueError):
            agent.start(project_id=2)

    def test_new_context_implementations_receive_topic_evidence_and_preserve_references(self):
        project = sample_project()
        project = ProjectKnowledge(
            project_id=project.project_id,
            project_name=project.project_name,
            topics=[Topic(name="Redis", score=85, evidence=["Redis"])],
            evidence=project.evidence,
        )
        repository = InMemoryProjectRepository({1: project})
        question_generator = ContextQuestionGenerator()
        evaluator = ContextEvaluator()
        agent = InterviewAgent(
            repository=repository,
            question_generator=question_generator,
            evaluator=evaluator,
        )

        state = agent.start(project_id=1)
        next_state = agent.submit_answer(state, "使用缓存")

        self.assertEqual(question_generator.evidence[0]["id"], "Redis")
        self.assertEqual(evaluator.evidence[0]["id"], "Redis")
        self.assertEqual(next_state.evaluation.evidence_ids, ("Redis",))
        self.assertEqual(next_state.evaluation.missing_points, ("rollback",))
        self.assertEqual(next_state.question, "Redis / Level 2")

    def test_legacy_string_question_result_keeps_current_topic_evidence_ids(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        agent = InterviewAgent(
            repository=repository,
            question_generator=FixedQuestionGenerator(),
        )

        state = agent.start(project_id=1)

        self.assertEqual(state.current_topic.name, "Transaction")
        self.assertEqual(state.question_evidence_ids, ("OrderService.java",))

    def test_topic_evidence_and_tools_skip_unresolved_legacy_evidence_ids(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Legacy",
            topics=[Topic(name="Cache", score=80, evidence=["e-cache", "missing"])],
            evidence={"e-cache": {"source_path": "CacheService.java"}},
        )
        tools = ProjectTools(InMemoryProjectRepository({1: project}))

        self.assertEqual(topic_evidence(project, project.topics[0]), [{"id": "e-cache", "source_path": "CacheService.java"}])
        self.assertEqual(
            tools.get_evidence_by_topic(1, "Cache"),
            {"source_path": "CacheService.java"},
        )
        self.assertIsNone(
            ProjectTools(
                InMemoryProjectRepository(
                    {
                        2: ProjectKnowledge(
                            project_id=2,
                            project_name="Missing",
                            topics=[Topic(name="Ghost", score=90, evidence=["missing"])],
                        )
                    }
                )
            ).get_evidence_by_topic(2, "Ghost")
        )

    def test_canonical_context_is_passed_and_ghost_result_ids_are_filtered(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Canonical",
            topics=[Topic(name="API", score=80, evidence=["e-api"])],
            evidence={"e-api": {"source_path": "Api.java"}},
        )
        generator = CanonicalContextGenerator()
        evaluator = CanonicalContextEvaluator()
        agent = InterviewAgent(
            repository=InMemoryProjectRepository({1: project}),
            question_generator=generator,
            evaluator=evaluator,
        )

        state = agent.start(project_id=1)
        next_state = agent.submit_answer(state, "answer")

        evidence, evidence_ids, context = generator.context
        self.assertEqual(evidence_ids, ("e-api",))
        self.assertEqual(context.evidence_ids, ("e-api",))
        self.assertIsInstance(context, ReviewContext)
        self.assertEqual(state.question_evidence_ids, ("e-api",))
        self.assertEqual(next_state.evaluation.evidence_ids, ())

    def test_old_signature_and_callable_generator_remain_supported(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        state = InterviewAgent(
            repository=repository,
            question_generator=CallableQuestionGenerator(),
        ).start(project_id=1)

        self.assertEqual(state.question, "Transaction / callable")

    def test_uninspectable_callable_fails_explicitly_instead_of_dropping_context(self):
        with self.assertRaisesRegex(TypeError, "inspectable"):
            InterviewAgent(
                repository=InMemoryProjectRepository({1: sample_project()}),
                question_generator=UninspectableQuestionGenerator(),
            ).start(project_id=1)

    def test_multi_evidence_topic_has_explicit_single_and_list_query_apis(self):
        project = ProjectKnowledge(
            project_id=1,
            project_name="Multi Evidence",
            topics=[Topic(name="API", score=80, evidence=["e-1", "e-2"])],
            evidence={
                "e-1": {"source_path": "Api.java"},
                "e-2": {"source_path": "ApiTest.java"},
            },
        )
        tools = ProjectTools(InMemoryProjectRepository({1: project}))

        self.assertEqual(
            tools.get_evidence_list_by_topic(1, "API"),
            [
                {"id": "e-1", "source_path": "Api.java"},
                {"id": "e-2", "source_path": "ApiTest.java"},
            ],
        )
        self.assertEqual(
            tools.get_evidence_by_topic(1, "API"),
            {"source_path": "Api.java"},
        )

    def test_new_result_fields_are_immutable_and_json_restorable(self):
        question = QuestionResult(
            question="q",
            evidence_ids=["e-api"],
            covered_points=["flow"],
            missing_points=["risk"],
        )
        evaluation = Evaluation(
            score=70,
            evidence_ids=["e-api"],
            covered_points=["flow"],
            missing_points=["risk"],
        )

        with self.assertRaises(AttributeError):
            question.evidence_ids.append("e-2")
        with self.assertRaises(AttributeError):
            evaluation.missing_points.append("other")
        restored_question = QuestionResult(**json.loads(json.dumps(asdict(question))))
        restored_evaluation = Evaluation(**json.loads(json.dumps(asdict(evaluation))))
        self.assertEqual(restored_question.evidence_ids, ("e-api",))
        self.assertEqual(restored_evaluation.covered_points, ("flow",))

    def test_project_tools_support_deterministic_evidence_component_and_relation_queries(self):
        repository = InMemoryProjectRepository({1: sample_project()})
        tools = ProjectTools(repository)

        self.assertEqual(
            tools.get_evidence_by_id(1, "Redis")["code"], "RedisTemplate"
        )
        self.assertEqual(
            tools.get_evidence(1, evidence_id="Redis")["file"], "CacheService.java"
        )
        self.assertEqual(tools.get_component(1, "OrderService")["file"], "service/OrderService.java")
        self.assertEqual(
            tools.get_relations(1, "OrderController"),
            [
                {"source": "OrderController", "target": "OrderService"},
                {"source": "OrderController", "target": "OrderRepository"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
