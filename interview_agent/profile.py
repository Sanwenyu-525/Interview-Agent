from dataclasses import dataclass, field

from .models import Evaluation


@dataclass(frozen=True)
class WeaknessSource:
    weakness: str
    session_id: str
    project_id: int
    record_index: int
    question: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "evidence_ids", _unique_strings(self.evidence_ids))


@dataclass(frozen=True)
class SkillSnapshot:
    score: int
    trend: str = "new"
    recent_score: int | None = None
    sample_count: int = 1
    weaknesses: tuple[str, ...] = field(default_factory=tuple)
    weakness_sources: tuple[WeaknessSource, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "weaknesses", _unique_strings(self.weaknesses))
        object.__setattr__(
            self,
            "weakness_sources",
            _latest_weakness_sources(self.weakness_sources),
        )
        if self.recent_score is None:
            object.__setattr__(self, "recent_score", self.score)


@dataclass(frozen=True)
class ProfileUpdate:
    topic: str
    score: int
    weaknesses: tuple[str, ...]
    snapshot: SkillSnapshot
    weakness_sources: tuple[WeaknessSource, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "weaknesses", _unique_strings(self.weaknesses))
        object.__setattr__(
            self,
            "weakness_sources",
            _latest_weakness_sources(self.weakness_sources),
        )


@dataclass
class CandidateProfile:
    skills: dict[str, SkillSnapshot] = field(default_factory=dict)

    def update(
        self,
        topic: str,
        score: int,
        weaknesses: list[str] | tuple[str, ...] = (),
    ) -> SkillSnapshot:
        previous = self.skills.get(topic)
        if previous is None:
            trend = "new"
            sample_count = 1
            merged_weaknesses = _unique_strings(weaknesses)
            weakness_sources = ()
        elif score > (previous.recent_score or previous.score):
            trend = "improving"
            sample_count = previous.sample_count + 1
            merged_weaknesses = _merge_strings(previous.weaknesses, weaknesses)
            weakness_sources = previous.weakness_sources
        elif score < (previous.recent_score or previous.score):
            trend = "declining"
            sample_count = previous.sample_count + 1
            merged_weaknesses = _merge_strings(previous.weaknesses, weaknesses)
            weakness_sources = previous.weakness_sources
        else:
            trend = "stable"
            sample_count = previous.sample_count + 1
            merged_weaknesses = _merge_strings(previous.weaknesses, weaknesses)
            weakness_sources = previous.weakness_sources
        snapshot = SkillSnapshot(
            score=score,
            trend=trend,
            recent_score=score,
            sample_count=sample_count,
            weaknesses=merged_weaknesses,
            weakness_sources=weakness_sources,
        )
        self.skills[topic] = snapshot
        return snapshot

    def merge_weaknesses(self, topic: str, weaknesses: list[str] | tuple[str, ...]) -> SkillSnapshot:
        previous = self.skills.get(topic)
        if previous is None:
            raise KeyError(topic)
        snapshot = SkillSnapshot(
            score=previous.score,
            trend=previous.trend,
            recent_score=previous.recent_score,
            sample_count=previous.sample_count,
            weaknesses=_merge_strings(previous.weaknesses, weaknesses),
            weakness_sources=previous.weakness_sources,
        )
        self.skills[topic] = snapshot
        return snapshot

    def merge_weakness_sources(
        self,
        topic: str,
        sources: tuple[WeaknessSource, ...] | list[WeaknessSource],
    ) -> SkillSnapshot:
        previous = self.skills.get(topic)
        if previous is None:
            raise KeyError(topic)
        snapshot = SkillSnapshot(
            score=previous.score,
            trend=previous.trend,
            recent_score=previous.recent_score,
            sample_count=previous.sample_count,
            weaknesses=previous.weaknesses,
            weakness_sources=_merge_weakness_sources(
                previous.weakness_sources,
                sources,
            ),
        )
        self.skills[topic] = snapshot
        return snapshot


class ProfileUpdater:
    """将一次评价的评分和弱项归并到候选人长期画像。"""

    def update(
        self, profile: CandidateProfile, topic: str, evaluation: Evaluation
    ) -> SkillSnapshot:
        return profile.update(topic, evaluation.score, evaluation.weaknesses)

    def apply(
        self, profile: CandidateProfile, topic: str, evaluation: Evaluation
    ) -> SkillSnapshot:
        """兼容旧调用名；实际更新仍统一委托给 update。"""

        return self.update(profile, topic, evaluation)


def _unique_strings(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _merge_strings(existing, new_values) -> tuple[str, ...]:
    return _unique_strings((*existing, *new_values))


def _latest_weakness_sources(values) -> tuple[WeaknessSource, ...]:
    latest = {}
    for source in values:
        if not isinstance(source, WeaknessSource):
            raise ValueError("weakness source must be WeaknessSource")
        latest[source.weakness] = source
    return tuple(latest.values())


def _merge_weakness_sources(existing, new_values) -> tuple[WeaknessSource, ...]:
    return _latest_weakness_sources((*existing, *new_values))
