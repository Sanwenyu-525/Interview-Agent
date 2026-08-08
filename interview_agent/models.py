from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Iterator, Mapping
from typing import Any


class SessionConflictError(RuntimeError):
    """Session version changed before this write could be committed."""


class ProfileConflictError(RuntimeError):
    """Candidate profile version changed before a conditional restore."""


@dataclass(frozen=True)
class Topic:
    name: str
    score: int
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectKnowledge:
    """当前面试流程使用的稳定旧契约。

    Universal Project Model 通过 intelligence.models 中的转换函数进入该模型，
    以保持 QuestionGenerator、Evaluator、仓库和 InterviewGraph 的兼容边界。
    """

    project_id: int
    project_name: str
    topics: list[Topic]
    components: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    weaknesses: list[str] = field(default_factory=list)


class AnalysisStatus(str, Enum):
    CREATED = "CREATED"
    SOURCE_READY = "SOURCE_READY"
    SCANNING = "SCANNING"
    ANALYZING = "ANALYZING"
    READY = "READY"
    FAILED = "FAILED"


CURRENT_ANALYSIS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProjectAnalysis:
    """可持久化的项目输入与分析生命周期记录。"""

    project_id: int
    project_name: str = ""
    source_type: str = ""
    workspace_path: str = ""
    analysis_status: AnalysisStatus = AnalysisStatus.CREATED
    schema_version: int = CURRENT_ANALYSIS_SCHEMA_VERSION
    analyzer_id: str = ""
    universal_model: Any | None = None
    knowledge: ProjectKnowledge | None = None
    error: str = ""


ProjectAnalysisRecord = ProjectAnalysis


@dataclass(frozen=True)
class Evaluation:
    score: int
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    feedback: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    covered_points: tuple[str, ...] = field(default_factory=tuple)
    missing_points: tuple[str, ...] = field(default_factory=tuple)
    reference_answer: str = ""
    analysis: str = ""

    def __post_init__(self):
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "covered_points", tuple(self.covered_points))
        object.__setattr__(self, "missing_points", tuple(self.missing_points))


@dataclass(frozen=True)
class ReviewContext(Mapping[str, Any]):
    """生成器和评价器共享的、只读的项目证据上下文。"""

    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    review_direction: str = ""
    resume_claims: tuple[str, ...] = field(default_factory=tuple)
    position_requirement: str = ""
    position_title: str = ""

    def __post_init__(self):
        object.__setattr__(
            self,
            "evidence",
            tuple(dict(item) for item in self.evidence),
        )
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "resume_claims", tuple(self.resume_claims))

    def __getitem__(self, key: str):
        if key == "evidence":
            return self.evidence
        if key == "evidence_ids":
            return self.evidence_ids
        if key == "review_direction":
            return self.review_direction
        if key == "resume_claims":
            return self.resume_claims
        if key == "position_requirement":
            return self.position_requirement
        if key == "position_title":
            return self.position_title
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(
            (
                "evidence",
                "evidence_ids",
                "review_direction",
                "resume_claims",
                "position_requirement",
                "position_title",
            )
        )

    def __len__(self) -> int:
        return 6


@dataclass(frozen=True)
class QuestionResult:
    """问题生成结果；保留字符串问题的兼容边界，同时携带项目证据引用。"""

    question: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    covered_points: tuple[str, ...] = field(default_factory=tuple)
    missing_points: tuple[str, ...] = field(default_factory=tuple)
    analysis: str = ""

    def __post_init__(self):
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "covered_points", tuple(self.covered_points))
        object.__setattr__(self, "missing_points", tuple(self.missing_points))

    @property
    def text(self) -> str:
        return self.question


GeneratedQuestion = QuestionResult


@dataclass(frozen=True)
class AnswerRecord:
    question: str
    answer: str
    topic: str
    level: int
    evaluation: Evaluation
    analysis: str = ""


@dataclass
class InterviewState:
    project_id: int
    project: ProjectKnowledge
    current_topic: Topic
    level: int
    question: str
    title: str = ""
    answer: str = ""
    evaluation: Evaluation | None = None
    next_direction: str = ""
    history: list[AnswerRecord] = field(default_factory=list)
    status: str = "waiting_answer"
    question_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    question_covered_points: tuple[str, ...] = field(default_factory=tuple)
    question_missing_points: tuple[str, ...] = field(default_factory=tuple)
    question_analysis: str = ""
    candidate_id: str = "default"
    last_submitted_question: str = ""
    last_submitted_answer: str = ""
    review_mode: str = "technical_interview"
    completed_at: str = ""
    position_id: str = ""
    position_question_id: str = ""
    position_requirement: str = ""
    position_title: str = ""
    resume_claims: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        self.question_evidence_ids = tuple(self.question_evidence_ids)
        self.question_covered_points = tuple(self.question_covered_points)
        self.question_missing_points = tuple(self.question_missing_points)
        self.resume_claims = tuple(self.resume_claims)


def project_model_to_knowledge(model: Any) -> ProjectKnowledge:
    """兼容入口：将 Universal Project Model 转换为旧项目知识模型。"""

    from .intelligence.models import project_model_to_knowledge as convert

    return convert(model)
