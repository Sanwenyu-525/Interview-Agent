import copy
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .memory.profile_store import normalize_candidate_id
from .models import ProjectKnowledge


CURRENT_POSITION_SCHEMA_VERSION = 1
POSITION_STATUSES = frozenset({"preparing", "applied", "interviewing", "archived"})
_SECTION_HEADINGS = frozenset(
    {
        "职位描述",
        "岗位描述",
        "岗位职责",
        "职位职责",
        "任职要求",
        "技能要求",
        "职位要求",
        "加分项",
        "job description",
        "responsibilities",
        "requirements",
        "qualifications",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _text(value, name: str, *, required=False, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是字符串")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{name} 不能为空")
    if len(normalized) > limit:
        raise ValueError(f"{name} 不能超过 {limit} 个字符")
    return normalized


def normalize_project_ids(value) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError("project_ids 必须是数组")
    if len(value) > 20:
        raise ValueError("project_ids 最多包含 20 个项目")
    normalized = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError("project_ids 必须只包含正整数")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def normalize_status(value) -> str:
    if not isinstance(value, str) or value not in POSITION_STATUSES:
        raise ValueError(f"status 必须是以下值之一：{', '.join(sorted(POSITION_STATUSES))}")
    return value


def extract_requirements(jd_text: str) -> tuple[str, ...]:
    text = _text(jd_text, "jd_text", required=True, limit=100_000)
    raw_lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    if len(raw_lines) < 3:
        raw_lines = [line.strip() for line in re.split(r"[。；;]+", text) if line.strip()]

    requirements = []
    for raw in raw_lines:
        line = re.sub(r"^\s*(?:[-*•·]|\(?\d+[.)、）]|[一二三四五六七八九十]+[、.])\s*", "", raw)
        line = line.strip(" ：:")
        if not line or line.casefold() in _SECTION_HEADINGS:
            continue
        if len(line) < 4:
            continue
        line = line[:240]
        if line not in requirements:
            requirements.append(line)
        if len(requirements) == 12:
            break
    return tuple(requirements or [text[:240]])


@dataclass(frozen=True)
class PositionQuestion:
    question_id: str
    text: str
    requirement: str
    category: str
    difficulty: int
    project_id: int | None = None
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True)
class TargetPosition:
    position_id: str
    candidate_id: str
    title: str
    company: str
    jd_text: str
    source_url: str
    status: str
    project_ids: tuple[int, ...] = field(default_factory=tuple)
    requirements: tuple[str, ...] = field(default_factory=tuple)
    questions: tuple[PositionQuestion, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = CURRENT_POSITION_SCHEMA_VERSION

    def __post_init__(self):
        object.__setattr__(self, "project_ids", tuple(self.project_ids))
        object.__setattr__(self, "requirements", tuple(self.requirements))
        object.__setattr__(self, "questions", tuple(self.questions))


def generate_questions(
    position_id: str,
    requirements: tuple[str, ...],
    projects: tuple[ProjectKnowledge, ...],
) -> tuple[PositionQuestion, ...]:
    def requirement_terms(value: str) -> set[str]:
        terms = {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,31}", value)
            if len(token) >= 2
        }
        chinese_stops = {"能够", "说明", "熟悉", "掌握", "要求", "具有", "具备", "相关", "以及", "项目", "系统"}
        for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", value):
            terms.update(
                phrase[index : index + 2]
                for index in range(len(phrase) - 1)
                if phrase[index : index + 2] not in chinese_stops
            )
        return terms

    def project_text(project: ProjectKnowledge) -> str:
        return " ".join(
            [
                project.project_name,
                *(topic.name for topic in project.topics),
                *project.components.keys(),
                *project.components.values(),
                *project.dependencies.keys(),
                *(item for values in project.dependencies.values() for item in values),
            ]
        ).casefold()

    questions = []
    for index, requirement in enumerate(requirements[:8]):
        terms = requirement_terms(requirement)
        ranked_projects = sorted(
            ((sum(term in project_text(project) for term in terms), project) for project in projects),
            key=lambda item: item[0],
            reverse=True,
        )
        matched_score, matched_project = ranked_projects[0] if ranked_projects else (0, None)
        project = matched_project if matched_score else (projects[index % len(projects)] if projects else None)
        topic = None
        if project and project.topics:
            topic = max(
                project.topics,
                key=lambda candidate: sum(term in candidate.name.casefold() for term in terms),
            )
        evidence_ids = ()
        if matched_score and project:
            matched_evidence = [
                evidence_id
                for evidence_id, evidence in project.evidence.items()
                if any(term in f"{evidence_id} {json.dumps(evidence, ensure_ascii=False)}".casefold() for term in terms)
            ]
            if matched_evidence:
                evidence_ids = tuple(matched_evidence[:3])
            elif topic and any(term in topic.name.casefold() for term in terms):
                evidence_ids = tuple(topic.evidence)
        if project and evidence_ids:
            text = (
                f"岗位要求提到“{requirement}”。请结合你在{project.project_name}中的真实实现，"
                "说明具体做法、可验证证据和关键权衡。"
            )
            category = "project_evidence"
        else:
            text = (
                f"岗位要求提到“{requirement}”。请用一个真实项目或工作经历说明你的做法、"
                "结果以及可以验证的证据。"
            )
            category = "experience"
        project_id = project.project_id if project else None
        question_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"interview-agent:{position_id}:{requirement}:{project_id}",
        ).hex
        questions.append(
            PositionQuestion(
                question_id=question_id,
                text=text,
                requirement=requirement,
                category=category,
                difficulty=2,
                project_id=project_id,
                evidence_ids=evidence_ids,
            )
        )
    return tuple(questions)


def position_from_dict(payload: dict) -> TargetPosition:
    if not isinstance(payload, dict):
        raise ValueError("position payload must be an object")
    schema_version = payload.get("schema_version", CURRENT_POSITION_SCHEMA_VERSION)
    if schema_version != CURRENT_POSITION_SCHEMA_VERSION:
        raise ValueError(f"unsupported position schema_version: {schema_version}")
    try:
        return TargetPosition(
            position_id=_text(payload["position_id"], "position_id", required=True, limit=128),
            candidate_id=normalize_candidate_id(payload["candidate_id"]),
            title=_text(payload["title"], "title", required=True, limit=120),
            company=_text(payload.get("company", ""), "company", limit=120),
            jd_text=_text(payload["jd_text"], "jd_text", required=True, limit=100_000),
            source_url=_text(payload.get("source_url", ""), "source_url", limit=2_000),
            status=normalize_status(payload.get("status", "preparing")),
            project_ids=normalize_project_ids(payload.get("project_ids", [])),
            requirements=tuple(str(item) for item in payload.get("requirements", [])),
            questions=tuple(PositionQuestion(**item) for item in payload.get("questions", [])),
            created_at=_text(payload.get("created_at", ""), "created_at", limit=100),
            updated_at=_text(payload.get("updated_at", ""), "updated_at", limit=100),
            schema_version=schema_version,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("position payload contains invalid fields") from exc


class InMemoryPositionStore:
    def __init__(self):
        self._positions: dict[str, TargetPosition] = {}

    def save(self, position: TargetPosition) -> None:
        self._positions[position.position_id] = copy.deepcopy(position)

    def get(self, position_id: str) -> TargetPosition:
        try:
            return copy.deepcopy(self._positions[position_id])
        except KeyError as exc:
            raise KeyError(f"position not found: {position_id}") from exc

    def list(self, candidate_id: str, limit: int = 50) -> list[TargetPosition]:
        positions = [
            copy.deepcopy(position)
            for position in self._positions.values()
            if position.candidate_id == candidate_id
        ]
        positions.sort(key=lambda item: item.updated_at, reverse=True)
        return positions[:limit]

    def delete(self, position_id: str) -> None:
        if position_id not in self._positions:
            raise KeyError(f"position not found: {position_id}")
        del self._positions[position_id]


class SQLitePositionStore:
    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS positions "
                "(position_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, "
                "payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS positions_candidate_updated "
                "ON positions(candidate_id, updated_at DESC)"
            )

    def save(self, position: TargetPosition) -> None:
        payload = json.dumps(asdict(position), ensure_ascii=False)
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO positions(position_id, candidate_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(position_id) DO UPDATE SET "
                "candidate_id=excluded.candidate_id, payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (position.position_id, position.candidate_id, payload, position.updated_at),
            )

    def get(self, position_id: str) -> TargetPosition:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload FROM positions WHERE position_id = ?", (position_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"position not found: {position_id}")
        return position_from_dict(json.loads(row[0]))

    def list(self, candidate_id: str, limit: int = 50) -> list[TargetPosition]:
        with _connection(self.database) as connection:
            rows = connection.execute(
                "SELECT payload FROM positions WHERE candidate_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (candidate_id, limit),
            ).fetchall()
        return [position_from_dict(json.loads(row[0])) for row in rows]

    def delete(self, position_id: str) -> None:
        with _connection(self.database) as connection:
            cursor = connection.execute(
                "DELETE FROM positions WHERE position_id = ?", (position_id,)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"position not found: {position_id}")


def new_position(
    *,
    candidate_id: str,
    title: str,
    company: str,
    jd_text: str,
    source_url: str,
    status: str,
    project_ids: tuple[int, ...],
    projects: tuple[ProjectKnowledge, ...],
) -> TargetPosition:
    position_id = uuid.uuid4().hex
    timestamp = _now()
    requirements = extract_requirements(jd_text)
    return TargetPosition(
        position_id=position_id,
        candidate_id=normalize_candidate_id(candidate_id),
        title=_text(title, "title", required=True, limit=120),
        company=_text(company, "company", limit=120),
        jd_text=_text(jd_text, "jd_text", required=True, limit=100_000),
        source_url=_text(source_url, "source_url", limit=2_000),
        status=normalize_status(status),
        project_ids=project_ids,
        requirements=requirements,
        questions=generate_questions(position_id, requirements, projects),
        created_at=timestamp,
        updated_at=timestamp,
    )


def updated_at() -> str:
    return _now()
