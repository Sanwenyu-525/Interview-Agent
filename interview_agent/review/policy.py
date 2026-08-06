from enum import Enum
from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from ..models import AnswerRecord, ProjectKnowledge, Topic
    from ..profile import CandidateProfile


class ReviewMode(str, Enum):
    TECHNICAL_INTERVIEW = "technical_interview"
    PORTFOLIO_REVIEW = "portfolio_review"
    DEFENSE_REVIEW = "defense_review"


@runtime_checkable
class ReviewPolicy(Protocol):
    mode: ReviewMode

    def select_topic(
        self,
        project: "ProjectKnowledge",
        profile: "CandidateProfile",
        history: list["AnswerRecord"],
    ) -> "Topic": ...

    def next_direction(self, score: int, current_level: int) -> tuple[str, int]: ...


def policy_for_mode(mode: ReviewMode | str) -> ReviewPolicy:
    resolved_mode = mode if isinstance(mode, ReviewMode) else ReviewMode(mode)
    if resolved_mode is ReviewMode.TECHNICAL_INTERVIEW:
        from .technical import TechnicalInterviewPolicy

        return TechnicalInterviewPolicy()
    if resolved_mode is ReviewMode.PORTFOLIO_REVIEW:
        from .portfolio import PortfolioReviewPolicy

        return PortfolioReviewPolicy()
    if resolved_mode is ReviewMode.DEFENSE_REVIEW:
        from .defense import DefenseReviewPolicy

        return DefenseReviewPolicy()
    raise NotImplementedError(f"review mode is not implemented: {resolved_mode.value}")
