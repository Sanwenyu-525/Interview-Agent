from ..models import AnswerRecord, ProjectKnowledge, Topic
from ..profile import CandidateProfile
from .evidence import (
    resolve_topic_evidence,
    topic_component_match,
    topic_flow_match,
    topic_signal,
)
from .policy import ReviewMode


class DefenseReviewPolicy:
    mode = ReviewMode.DEFENSE_REVIEW

    def select_topic(
        self,
        project: ProjectKnowledge,
        profile: CandidateProfile,
        history: list[AnswerRecord],
        resume_claims=(),
    ) -> Topic:
        if not project.topics:
            raise ValueError("project has no topics")

        candidates = []
        for index, topic in enumerate(project.topics):
            evidence = resolve_topic_evidence(project, topic)
            goal = topic_signal(
                project,
                topic,
                ("goal", "objective", "purpose", "requirement", "target", "目标", "目的"),
            )
            decision = topic_signal(
                project,
                topic,
                ("decision", "design", "choice", "tradeoff", "architecture", "决策", "设计", "选择", "权衡"),
            )
            risk = topic_signal(
                project,
                topic,
                ("risk", "failure", "weakness", "gap", "rollback", "风险", "失败", "薄弱", "缺口"),
            )
            relation = max(
                topic_component_match(project, topic),
                topic_flow_match(project, topic),
            )
            candidates.append(
                (
                    bool(evidence),
                    goal,
                    decision,
                    risk,
                    relation,
                    len(evidence),
                    topic.score,
                    -index,
                    topic,
                )
            )
        return max(candidates, key=lambda item: item[:-1])[-1]

    @staticmethod
    def next_direction(score: int, current_level: int) -> tuple[str, int]:
        if score < 60:
            return "clarify", 1
        if score < 80:
            return "justify", min(3, current_level + 1)
        return "defend", 4


__all__ = ["DefenseReviewPolicy"]
