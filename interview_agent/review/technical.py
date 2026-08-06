from collections.abc import Iterable

from ..models import AnswerRecord, ProjectKnowledge, Topic
from ..profile import CandidateProfile
from .evidence import resolve_topic_evidence
from .policy import ReviewMode


def topic_evidence(project: ProjectKnowledge, topic: Topic) -> list[dict]:
    """兼容旧调用的列表 API；解析规则由共享 helper 统一维护。"""

    return list(resolve_topic_evidence(project, topic))


def _contains_topic(text: str, topic_name: str) -> bool:
    normalized_text = text.casefold()
    normalized_topic = topic_name.casefold()
    return bool(normalized_topic) and (
        normalized_topic in normalized_text or normalized_text in normalized_topic
    )


class TechnicalInterviewPolicy:
    mode = ReviewMode.TECHNICAL_INTERVIEW

    def select_topic(
        self,
        project: ProjectKnowledge,
        profile: CandidateProfile,
        history: list[AnswerRecord],
        resume_claims: Iterable[str] = (),
    ) -> Topic:
        if not project.topics:
            raise ValueError("project has no topics")

        candidates = []
        for index, topic in enumerate(project.topics):
            weakness = self._weakness_match(topic, project, profile, history)
            evidence = topic_evidence(project, topic)
            relation_bonus = self._relation_bonus(project, topic, evidence)
            claim_bonus = self._claim_match(topic, resume_claims)
            candidates.append(
                (
                    bool(evidence),
                    weakness,
                    relation_bonus + claim_bonus,
                    len(evidence),
                    topic.score,
                    -index,
                    topic,
                )
            )
        return max(candidates, key=lambda item: item[:-1])[-1]

    @staticmethod
    def _claim_match(topic: Topic, resume_claims: Iterable[str]) -> int:
        normalized_topic = topic.name.casefold()
        if any(
            _contains_topic(claim, normalized_topic)
            for claim in resume_claims
        ):
            return 2
        return 0

    @staticmethod
    def _relation_bonus(
        project: ProjectKnowledge, topic: Topic, evidence: list[dict]
    ) -> int:
        if not evidence or not project.dependencies:
            return 0
        related_names = [
            name
            for source, targets in project.dependencies.items()
            for name in (source, *targets)
        ]
        if any(_contains_topic(str(name), topic.name) for name in related_names):
            return 2
        return 1

    @staticmethod
    def _weakness_match(
        topic: Topic,
        project: ProjectKnowledge,
        profile: CandidateProfile,
        history: Iterable[AnswerRecord],
    ) -> int:
        project_weaknesses = any(
            _contains_topic(weakness, topic.name) for weakness in project.weaknesses
        )
        profile_weakness = any(
            (
                _contains_topic(name, topic.name)
                and (
                    snapshot.score < 60
                    or bool(snapshot.weaknesses)
                )
            )
            for name, snapshot in profile.skills.items()
        )
        history_weakness = any(
            record.topic == topic.name
            and (
                record.evaluation.score < 60
                or bool(record.evaluation.weaknesses)
            )
            for record in history
        )
        return int(project_weaknesses or profile_weakness or history_weakness)

    @staticmethod
    def next_direction(score: int, current_level: int) -> tuple[str, int]:
        if score < 60:
            return "basic", 1
        if score < 80:
            return "deep", min(3, current_level + 1)
        return "architecture", 4


__all__ = ["TechnicalInterviewPolicy", "topic_evidence"]
