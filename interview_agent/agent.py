import inspect
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol

from .models import (
    AnswerRecord,
    Evaluation,
    InterviewState,
    ProjectKnowledge,
    QuestionResult,
    ReviewContext,
    Topic,
)
from .profile import CandidateProfile, ProfileUpdate, ProfileUpdater
from .review import InterviewOutlineBuilder, ReviewMode, ReviewPolicy, policy_for_mode
from .review.evidence import real_evidence_ids
from .review.technical import topic_evidence


class QuestionGenerator(Protocol):
    def generate(
        self,
        *,
        topic: Topic,
        project: ProjectKnowledge,
        level: int,
        history: list[AnswerRecord],
        evidence: tuple[dict, ...] | None = None,
        evidence_ids: tuple[str, ...] | None = None,
        context: ReviewContext | None = None,
        review_direction: str | None = None,
    ) -> str | QuestionResult: ...


class Evaluator(Protocol):
    def evaluate(
        self,
        *,
        question: str,
        answer: str,
        topic: Topic,
        project: ProjectKnowledge,
        evidence: tuple[dict, ...] | None = None,
        evidence_ids: tuple[str, ...] | None = None,
        context: ReviewContext | None = None,
    ) -> Evaluation: ...


class RuleBasedQuestionGenerator:
    """不依赖外部模型的默认问题生成器，便于本地运行和测试。"""

    def generate(
        self,
        *,
        topic,
        project,
        level,
        history,
        review_direction="",
        context=None,
    ):
        resume_claims = tuple(getattr(context, "resume_claims", ()) or ())
        matched_claim = next(
            (
                claim
                for claim in resume_claims
                if (
                    topic.name.casefold() in claim.casefold()
                    or claim.casefold() in topic.name.casefold()
                )
            ),
            "",
        )
        if matched_claim:
            if review_direction in ("basic", "deep", "architecture", "clarify"):
                return (
                    f"简历主张提到“{matched_claim}”。请结合{project.project_name}中"
                    f"“{topic.name}”的具体实现，说明你是怎么做到的、如何验证结果，以及有哪些关键权衡。"
                )
            return (
                f"简历主张提到“{matched_claim}”。请用{project.project_name}中的真实实现"
                f"说明你的做法和最终结果，并给出可追溯的项目证据。"
            )
        direction_questions = {
            "basic": f"请先说明{project.project_name}在“{topic.name}”方向解决的问题、参与方和边界。",
            "deep": f"请沿着{project.project_name}的一条关键流程继续展开：各环节如何协作，失败时怎样处理？",
            "architecture": f"如果规模或复杂度显著增加，{project.project_name}在“{topic.name}”方向的边界、性能和稳定性方案会怎样演进？",
            "clarify": f"请澄清{project.project_name}中{topic.name}的项目目标、事实与证据。",
            "justify": f"请论证{project.project_name}中{topic.name}的关键设计决策及其权衡。",
            "defend": f"请为{project.project_name}中{topic.name}面对的风险提出防御和失败处理方案。",
            "story": f"请讲述{project.project_name}中{topic.name}的背景、目标和关键选择。",
            "tradeoff": f"请结合{project.project_name}说明{topic.name}的关键权衡，以及为什么这样取舍。",
            "impact": f"请说明{project.project_name}中{topic.name}带来的实际影响，以及如何验证结果。",
        }
        if review_direction in direction_questions:
            return direction_questions[review_direction]
        direction_openings = {
            "系统架构与模块协作": f"请从整体上介绍{project.project_name}：系统由哪些主要部分组成，它们如何协作完成核心目标？",
            "接口设计与前后端联调": f"请整体讲一下{project.project_name}的前后端如何联调：双方怎样约定接口、传递数据并处理异常？",
            "核心业务流程与数据流": f"请选取{project.project_name}的一条核心业务流程，从入口到结果讲清楚数据和职责如何流转。",
            "数据一致性与状态管理": f"{project.project_name}中的关键状态和数据如何管理？请说明正常流程、一致性边界和异常恢复。",
            "工程质量、稳定性与扩展": f"{project.project_name}如何保证可测试、可部署和稳定运行？请从工程流程和运行保障两个方面说明。",
        }
        if topic.name in direction_openings:
            return direction_openings[topic.name]
        questions = {
            1: f"请从整体上介绍{project.project_name}在“{topic.name}”方向的目标、方案和协作边界。",
            2: f"请结合{project.project_name}的一条核心流程，说明{topic.name}如何参与其中。",
            3: f"在{project.project_name}中，{topic.name}有哪些边界、异常处理和关键权衡？",
            4: f"如果{project.project_name}的规模显著增加，{topic.name}相关架构如何演进？",
        }
        return questions[level]


class RuleBasedEvaluator:
    """本地兜底评分器；接入 LLM 时只需替换 Evaluator。"""

    _quality_terms = (
        "事务",
        "回滚",
        "隔离",
        "一致性",
        "缓存",
        "过期",
        "降级",
        "集群",
        "故障",
        "重试",
        "权衡",
        "监控",
        "扩容",
    )

    def evaluate(self, *, question, answer, topic, project):
        matches = sum(term in answer for term in self._quality_terms)
        score = min(100, 40 + matches * 10) if answer.strip() else 20
        weaknesses = [] if matches >= 3 else [f"缺少{topic.name}的项目细节或权衡说明"]
        strengths = ["覆盖了关键技术点"] if matches >= 2 else []
        return Evaluation(score=score, strengths=strengths, weaknesses=weaknesses)


class InterviewAgent:
    def __init__(
        self,
        *,
        repository,
        question_generator=None,
        evaluator=None,
        profile=None,
        profile_updater=None,
        policy: ReviewPolicy | None = None,
        review_mode: ReviewMode | str = ReviewMode.TECHNICAL_INTERVIEW,
        outline_builder=None,
    ):
        self.repository = repository
        self.question_generator = question_generator or RuleBasedQuestionGenerator()
        self.evaluator = evaluator or RuleBasedEvaluator()
        self.profile = profile or CandidateProfile()
        self.profile_updater = profile_updater or ProfileUpdater()
        self.pending_profile_update: ProfileUpdate | None = None
        self.policy = policy or policy_for_mode(review_mode)
        self.outline_builder = outline_builder
        if outline_builder is None and (
            question_generator is None
            or isinstance(self.question_generator, RuleBasedQuestionGenerator)
        ):
            self.outline_builder = InterviewOutlineBuilder()

    def start(
        self,
        *,
        project_id: int,
        topic_name: str = "",
        resume_claims: tuple[str, ...] = (),
    ) -> InterviewState:
        project = self.load_project(project_id)
        topic = self.select_initial_topic(project, topic_name, resume_claims)
        question = self.generate_initial_question(project, topic, resume_claims)
        return self.assemble_initial_state(
            project_id,
            project,
            topic,
            question["question"],
            question["question_result"],
            resume_claims,
        )

    def load_project(self, project_id: int):
        self.pending_profile_update = None
        project = self.repository.get(project_id)
        if (
            self.outline_builder is not None
            and getattr(self.policy, "mode", None) == ReviewMode.TECHNICAL_INTERVIEW
            and self.outline_builder.supports(project)
        ):
            project = replace(project, topics=self.outline_builder.build(project))
        if not project.topics:
            raise ValueError("项目没有可面试主题")
        return project

    def select_initial_topic(self, project, topic_name: str = "", resume_claims=()):
        requested_name = str(topic_name).strip()
        if requested_name:
            for topic in project.topics:
                if topic.name.casefold() == requested_name.casefold():
                    return topic
            raise ValueError(f"项目中不存在主题：{requested_name}")
        return self._select_topic(project, self.profile, [], resume_claims)

    def generate_initial_question(self, project, topic, resume_claims=()) -> dict:
        question, question_result = self._generate_question(
            topic=topic,
            project=project,
            level=1,
            history=[],
            resume_claims=resume_claims,
        )
        return {
            "question": question,
            "question_result": question_result,
        }

    @staticmethod
    def assemble_initial_state(
        project_id: int,
        project,
        topic: Topic,
        question: str,
        question_result: QuestionResult,
        resume_claims: tuple[str, ...] = (),
    ) -> InterviewState:
        return InterviewState(
            project_id=project_id,
            project=project,
            current_topic=topic,
            level=1,
            question=question,
            question_evidence_ids=question_result.evidence_ids,
            question_covered_points=question_result.covered_points,
            question_missing_points=question_result.missing_points,
            resume_claims=resume_claims,
        )

    def submit_answer(self, state: InterviewState, answer: str) -> InterviewState:
        self.validate_answer(state, answer)
        turn = self.evaluate_answer(state, answer)
        profile_update = self.update_profile(state, turn["evaluation"])
        follow_up = self.decide_follow_up(
            state,
            turn["evaluation"],
            turn["history"],
            profile_update["working_profile"],
        )
        question = self.generate_follow_up_question(
            state,
            turn["history"],
            follow_up["direction"],
            follow_up["next_level"],
            follow_up["next_topic"],
            state.resume_claims,
        )
        return self.assemble_follow_up(
            state,
            answer,
            turn["evaluation"],
            turn["history"],
            profile_update["working_profile"],
            profile_update["pending_profile_update"],
            follow_up["direction"],
            follow_up["next_level"],
            follow_up["next_topic"],
            question["next_question"],
            question["question_result"],
        )

    @staticmethod
    def validate_answer(state: InterviewState, answer: str) -> None:
        if state.status != "waiting_answer":
            raise ValueError("当前面试不在等待回答状态")
        if not answer.strip():
            raise ValueError("回答不能为空")

    def evaluate_answer(self, state: InterviewState, answer: str) -> dict:
        evidence = topic_evidence(state.project, state.current_topic)
        evaluation = self._evaluate(
            question=state.question,
            answer=answer,
            topic=state.current_topic,
            project=state.project,
            evidence=evidence,
            resume_claims=state.resume_claims,
        )
        record = AnswerRecord(
            question=state.question,
            answer=answer,
            topic=state.current_topic.name,
            level=state.level,
            evaluation=evaluation,
        )
        return {
            "evaluation": evaluation,
            "history": [*state.history, record],
        }

    def update_profile(self, state: InterviewState, evaluation: Evaluation) -> dict:
        working_profile = deepcopy(self.profile)
        snapshot = self.profile_updater.update(
            working_profile, state.current_topic.name, evaluation
        )
        pending_profile_update = ProfileUpdate(
            topic=state.current_topic.name,
            score=snapshot.score,
            weaknesses=snapshot.weaknesses,
            snapshot=snapshot,
        )
        return {
            "working_profile": working_profile,
            "pending_profile_update": pending_profile_update,
        }

    def decide_follow_up(
        self,
        state: InterviewState,
        evaluation: Evaluation,
        history: list[AnswerRecord],
        working_profile: CandidateProfile,
    ) -> dict:
        direction, next_level = self.policy.next_direction(
            evaluation.score, state.level
        )
        next_topic = self._select_topic(
            state.project, working_profile, history, state.resume_claims
        )
        return {
            "direction": direction,
            "next_level": next_level,
            "next_topic": next_topic,
        }

    def generate_follow_up_question(
        self,
        state: InterviewState,
        history: list[AnswerRecord],
        direction: str,
        next_level: int,
        next_topic: Topic,
        resume_claims=(),
    ) -> dict:
        next_question, question_result = self._generate_question(
            topic=next_topic,
            project=state.project,
            level=next_level,
            history=history,
            review_direction=direction,
            resume_claims=resume_claims,
        )
        return {
            "next_question": next_question,
            "question_result": question_result,
        }

    def _select_topic(self, project, profile, history, resume_claims=()):
        try:
            parameters = inspect.signature(self.policy.select_topic).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "resume_claims" in parameters:
            return self.policy.select_topic(
                project, profile, history, resume_claims
            )
        return self.policy.select_topic(project, profile, history)

    def assemble_follow_up(
        self,
        state: InterviewState,
        answer: str,
        evaluation: Evaluation,
        history: list[AnswerRecord],
        working_profile: CandidateProfile,
        pending_profile_update: ProfileUpdate,
        direction: str,
        next_level: int,
        next_topic: Topic,
        next_question: str,
        question_result: QuestionResult,
    ) -> InterviewState:
        updated = replace(
            state,
            current_topic=next_topic,
            level=next_level,
            question=next_question,
            answer="",
            evaluation=evaluation,
            next_direction=direction,
            history=history,
            question_evidence_ids=question_result.evidence_ids,
            question_covered_points=question_result.covered_points,
            question_missing_points=question_result.missing_points,
            last_submitted_question=state.question,
            last_submitted_answer=answer,
        )
        self.profile = working_profile
        self.pending_profile_update = pending_profile_update
        return updated

    def _generate_question(
        self, *, topic, project, level, history, review_direction="", resume_claims=()
    ):
        context = self._review_context(
            project,
            topic,
            review_direction=review_direction,
            resume_claims=resume_claims,
        )
        legacy_kwargs = {
            "topic": topic,
            "project": project,
            "level": level,
            "history": history,
        }
        result = self._invoke_compatible(
            self.question_generator.generate,
            legacy_kwargs,
            context,
            "QuestionGenerator",
            review_direction=context.review_direction,
        )
        return self._normalize_question(
            result, project, evidence_ids=context.evidence_ids
        )

    def _evaluate(self, *, question, answer, topic, project, evidence, resume_claims=()):
        context = self._review_context(
            project, topic, evidence, resume_claims=resume_claims
        )
        legacy_kwargs = {
            "question": question,
            "answer": answer,
            "topic": topic,
            "project": project,
        }
        result = self._invoke_compatible(
            self.evaluator.evaluate,
            legacy_kwargs,
            context,
            "Evaluator",
        )
        if isinstance(result, Evaluation):
            evaluation = result
        elif isinstance(result, Mapping):
            evaluation = Evaluation(**result)
        else:
            return result
        returned_ids = evaluation.evidence_ids or context.evidence_ids
        reference_answer = str(evaluation.reference_answer or "").strip()
        if evaluation.score >= 100:
            reference_answer = ""
        elif not reference_answer:
            reference_answer = self._fallback_reference_answer(
                question, topic, project, context.evidence
            )
        return replace(
            evaluation,
            evidence_ids=real_evidence_ids(project, returned_ids),
            reference_answer=reference_answer,
        )

    @staticmethod
    def _fallback_reference_answer(question, topic, project, evidence) -> str:
        evidence_names = [
            str(item.get("source_path") or item.get("file") or item.get("path") or item.get("id"))
            for item in evidence[:2]
            if isinstance(item, Mapping)
        ]
        evidence_hint = (
            f"项目证据可从 {', '.join(evidence_names)} 追溯。"
            if evidence_names
            else "回答应明确指出对应的项目模块和验证方式。"
        )
        return (
            f"这道题可以这样回答：在{project.project_name}中，{topic.name}的实现要先说明目标和边界，"
            f"再结合调用链说明关键步骤，并补充异常处理、性能或一致性权衡，以及如何通过测试和监控验证结果。"
            f"{evidence_hint}本题原问题是：{question}"
        )

    @staticmethod
    def _review_context(
        project,
        topic,
        evidence=None,
        review_direction="",
        resume_claims=(),
    ) -> ReviewContext:
        facts = tuple(evidence if evidence is not None else topic_evidence(project, topic))
        return ReviewContext(
            evidence=facts,
            evidence_ids=tuple(item["id"] for item in facts),
            review_direction=review_direction,
            resume_claims=resume_claims,
        )

    @staticmethod
    def _invoke_compatible(
        method, legacy_kwargs, context, role, review_direction: str | None = None
    ):
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{role} callable signature is not inspectable; "
                "cannot safely pass review context"
            ) from exc
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        canonical = {
            "evidence": context.evidence,
            "evidence_ids": context.evidence_ids,
            "context": context,
            "review_direction": review_direction,
        }
        supports_canonical = accepts_kwargs or any(
            name in parameters for name in canonical
        )
        if not supports_canonical:
            return method(**legacy_kwargs)
        kwargs = dict(legacy_kwargs)
        for name, value in canonical.items():
            if accepts_kwargs or name in parameters:
                kwargs[name] = value
        return method(**kwargs)

    @staticmethod
    def _normalize_question(
        result, project, evidence_ids=()
    ) -> tuple[str, QuestionResult]:
        if isinstance(result, str):
            return result, QuestionResult(
                question=result,
                evidence_ids=real_evidence_ids(project, evidence_ids),
            )
        if isinstance(result, QuestionResult):
            returned_ids = result.evidence_ids or evidence_ids
            return result.question, replace(
                result,
                evidence_ids=real_evidence_ids(project, returned_ids),
            )
        if isinstance(result, Mapping):
            question = result.get("question", result.get("text", ""))
            result_evidence_ids = tuple(result.get("evidence_ids", ()))
            return question, QuestionResult(
                question=question,
                evidence_ids=real_evidence_ids(
                    project, result_evidence_ids or evidence_ids
                ),
                covered_points=tuple(result.get("covered_points", ())),
                missing_points=tuple(result.get("missing_points", ())),
            )
        question = getattr(result, "question", getattr(result, "text", ""))
        result_evidence_ids = tuple(getattr(result, "evidence_ids", ()))
        return question, QuestionResult(
            question=question,
            evidence_ids=real_evidence_ids(
                project, result_evidence_ids or evidence_ids
            ),
            covered_points=tuple(getattr(result, "covered_points", ())),
            missing_points=tuple(getattr(result, "missing_points", ())),
        )

    @staticmethod
    def _next_level(score: int, current_level: int) -> tuple[str, int]:
        """保留旧的静态调用边界；实际流程由 TechnicalInterviewPolicy 决定。"""

        from .review.technical import TechnicalInterviewPolicy

        return TechnicalInterviewPolicy.next_direction(score, current_level)
