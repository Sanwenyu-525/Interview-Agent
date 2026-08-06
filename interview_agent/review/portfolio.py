from ..models import AnswerRecord, ProjectKnowledge, Topic
from ..profile import CandidateProfile
from .evidence import resolve_topic_evidence, topic_component_match, topic_flow_match
from .policy import ReviewMode


class PortfolioReviewPolicy:
    mode = ReviewMode.PORTFOLIO_REVIEW

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
            component_match = self._component_match(project, topic)
            flow_match = self._flow_match(project, topic)
            candidates.append(
                (
                    bool(evidence),
                    component_match,
                    flow_match,
                    len(evidence),
                    topic.score,
                    -index,
                    topic,
                )
            )
        return max(candidates, key=lambda item: item[:-1])[-1]

    @staticmethod
    def _component_match(project: ProjectKnowledge, topic: Topic) -> int:
        return topic_component_match(project, topic)

    @staticmethod
    def _flow_match(project: ProjectKnowledge, topic: Topic) -> int:
        return topic_flow_match(project, topic)

    @staticmethod
    def next_direction(score: int, current_level: int) -> tuple[str, int]:
        if score < 60:
            return "story", 1
        if score < 80:
            return "tradeoff", min(3, current_level + 1)
        return "impact", 4


__all__ = ["PortfolioReviewPolicy"]
