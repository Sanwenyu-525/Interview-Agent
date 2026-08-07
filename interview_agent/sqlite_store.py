import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone

from .intelligence.models import (
    Component,
    Evidence,
    Flow,
    Insight,
    ProjectIdentity,
    ProjectTopic,
    Relation,
    StructureNode,
    Technology,
    UniversalProjectModel,
)
from .models import (
    AnalysisStatus,
    AnswerRecord,
    CURRENT_ANALYSIS_SCHEMA_VERSION,
    Evaluation,
    InterviewState,
    ProjectAnalysis,
    ProjectKnowledge,
    SessionConflictError,
    Topic,
)
from .memory.profile_store import SQLiteCandidateProfileStore, normalize_candidate_id


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _project_to_dict(project: ProjectKnowledge) -> dict:
    return asdict(project)


def _project_from_dict(payload: dict) -> ProjectKnowledge:
    return ProjectKnowledge(
        project_id=int(payload["project_id"]),
        project_name=str(payload.get("project_name", payload["project_id"])),
        topics=[Topic(**topic) for topic in payload.get("topics", [])],
        components=dict(payload.get("components", {})),
        evidence=dict(payload.get("evidence", {})),
        dependencies={key: list(value) for key, value in payload.get("dependencies", {}).items()},
        weaknesses=list(payload.get("weaknesses", [])),
    )


def _universal_model_to_dict(model: UniversalProjectModel | None) -> dict | None:
    return asdict(model) if model is not None else None


def _universal_model_from_dict(
    payload: dict | None, expected_project_id: int | None = None
) -> UniversalProjectModel | None:
    if payload is None:
        return None
    stored_project_id = int(payload["project_id"])
    if expected_project_id is not None and stored_project_id != expected_project_id:
        raise ValueError(
            "UniversalProjectModel project_id does not match persisted project_id: "
            f"{stored_project_id} != {expected_project_id}"
        )
    return UniversalProjectModel(
        project_id=stored_project_id,
        identity=ProjectIdentity(**payload["identity"]),
        structure=[StructureNode(**item) for item in payload.get("structure", [])],
        technologies=[Technology(**item) for item in payload.get("technologies", [])],
        components=[Component(**item) for item in payload.get("components", [])],
        relations=[Relation(**item) for item in payload.get("relations", [])],
        flows=[Flow(**item) for item in payload.get("flows", [])],
        insights=[Insight(**item) for item in payload.get("insights", [])],
        evidence=[Evidence(**item) for item in payload.get("evidence", [])],
        topics=[ProjectTopic(**item) for item in payload.get("topics", [])],
        dependencies={key: list(value) for key, value in payload.get("dependencies", {}).items()},
        metadata=dict(payload.get("metadata", {})),
    )


def _session_candidate_id(payload: dict, stored_candidate_id) -> str:
    if isinstance(stored_candidate_id, str) and stored_candidate_id.strip():
        return normalize_candidate_id(stored_candidate_id)
    payload_candidate_id = payload.get("candidate_id") if isinstance(payload, dict) else None
    if isinstance(payload_candidate_id, str) and payload_candidate_id.strip():
        return normalize_candidate_id(payload_candidate_id)
    return "default"


def _state_to_dict(state: InterviewState) -> dict:
    return asdict(state)


def _session_payload(raw_payload) -> dict:
    try:
        payload = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("session payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("session payload must be a JSON object")
    return payload


def _require_session_type(payload: dict, name: str, expected, *, required=True):
    if name not in payload:
        if required:
            raise ValueError(f"session payload missing required field: {name}")
        return None
    value = payload[name]
    if expected is int and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"session payload field {name} must be an integer")
    if not isinstance(value, expected):
        raise ValueError(
            f"session payload field {name} must be {expected.__name__}"
        )
    return value


def _validate_topic(payload, field_name: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"session payload field {field_name} must be an object")
    _require_session_type(payload, "name", str)
    _require_session_type(payload, "score", int)
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) for item in evidence
    ):
        raise ValueError(f"session payload field {field_name}.evidence must be a string list")


def _validate_evaluation(payload, field_name: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"session payload field {field_name} must be an object")
    allowed = {
        "score",
        "strengths",
        "weaknesses",
        "feedback",
        "reference_answer",
        "evidence_ids",
        "covered_points",
        "missing_points",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"session payload field {field_name} has unknown fields: {sorted(unknown)}"
        )
    _require_session_type(payload, "score", int)
    for name in (
        "strengths",
        "weaknesses",
        "evidence_ids",
        "covered_points",
        "missing_points",
    ):
        values = payload.get(name, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError(
                f"session payload field {field_name}.{name} must be a string list"
            )
    if not isinstance(payload.get("feedback", ""), str):
        raise ValueError(f"session payload field {field_name}.feedback must be a string")
    if not isinstance(payload.get("reference_answer", ""), str):
        raise ValueError(
            f"session payload field {field_name}.reference_answer must be a string"
        )


def _validate_state_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("session payload must be a JSON object")
    _require_session_type(payload, "project_id", int)
    project = _require_session_type(payload, "project", dict)
    _require_session_type(payload, "current_topic", dict)
    _require_session_type(payload, "level", int)
    _require_session_type(payload, "question", str)
    _require_session_type(payload, "title", str, required=False)
    _require_session_type(payload, "answer", str, required=False)
    _require_session_type(payload, "next_direction", str, required=False)
    _require_session_type(payload, "status", str, required=False)
    _require_session_type(payload, "candidate_id", str, required=False)
    _require_session_type(payload, "last_submitted_question", str, required=False)
    _require_session_type(payload, "last_submitted_answer", str, required=False)
    _require_session_type(payload, "review_mode", str, required=False)
    _require_session_type(payload, "completed_at", str, required=False)
    _require_session_type(payload, "position_id", str, required=False)
    _require_session_type(payload, "resume_claims", list, required=False)
    _require_session_type(payload, "position_question_id", str, required=False)

    _require_session_type(project, "project_id", int)
    _require_session_type(project, "project_name", str, required=False)
    topics = _require_session_type(project, "topics", list)
    for index, topic in enumerate(topics):
        _validate_topic(topic, f"project.topics[{index}]")
    for name in ("components", "evidence", "dependencies"):
        value = project.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"session payload field project.{name} must be an object")
    weaknesses = project.get("weaknesses", [])
    if not isinstance(weaknesses, list) or not all(
        isinstance(item, str) for item in weaknesses
    ):
        raise ValueError("session payload field project.weaknesses must be a string list")

    _validate_topic(payload["current_topic"], "current_topic")
    for name in (
        "question_evidence_ids",
        "question_covered_points",
        "question_missing_points",
    ):
        values = payload.get(name, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError(f"session payload field {name} must be a string list")

    evaluation = payload.get("evaluation")
    if evaluation is not None:
        _validate_evaluation(evaluation, "evaluation")
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise ValueError("session payload field history must be a list")
    for index, record in enumerate(history):
        if not isinstance(record, dict):
            raise ValueError(f"session payload field history[{index}] must be an object")
        for name in ("question", "answer", "topic"):
            _require_session_type(record, name, str)
        _require_session_type(record, "level", int)
        if "evaluation" not in record:
            raise ValueError(
                f"session payload missing required field: history[{index}].evaluation"
            )
        _validate_evaluation(record["evaluation"], f"history[{index}].evaluation")


def _state_from_dict(payload: dict) -> InterviewState:
    _validate_state_payload(payload)
    try:
        evaluation = payload.get("evaluation")
        history = [
            AnswerRecord(
                question=record["question"],
                answer=record["answer"],
                topic=record["topic"],
                level=int(record["level"]),
                evaluation=Evaluation(**record["evaluation"]),
            )
            for record in payload.get("history", [])
        ]
        return InterviewState(
            project_id=int(payload["project_id"]),
            project=_project_from_dict(payload["project"]),
            current_topic=Topic(**payload["current_topic"]),
            level=int(payload["level"]),
            question=payload["question"],
            title=payload.get("title", ""),
            answer=payload.get("answer", ""),
            evaluation=Evaluation(**evaluation) if evaluation else None,
            next_direction=payload.get("next_direction", ""),
            history=history,
            status=payload.get("status", "waiting_answer"),
            question_evidence_ids=list(payload.get("question_evidence_ids", [])),
            question_covered_points=list(payload.get("question_covered_points", [])),
            question_missing_points=list(payload.get("question_missing_points", [])),
            candidate_id=str(payload.get("candidate_id", "default")),
            last_submitted_question=payload.get("last_submitted_question", ""),
            last_submitted_answer=payload.get("last_submitted_answer", ""),
            review_mode=payload.get("review_mode", "technical_interview"),
            completed_at=payload.get("completed_at", ""),
            position_id=payload.get("position_id", ""),
            position_question_id=payload.get("position_question_id", ""),
            resume_claims=list(payload.get("resume_claims", [])),
        )
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("session payload contains invalid state fields") from exc


class SQLiteProjectRepository:
    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS projects "
                "(project_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            columns = {
                "source_type": "TEXT",
                "workspace_path": "TEXT",
                "analysis_status": "TEXT",
                "schema_version": "INTEGER",
                "analyzer_id": "TEXT",
                "project_name": "TEXT",
                "universal_model_payload": "TEXT",
                "knowledge_payload": "TEXT",
                "error_message": "TEXT",
            }
            existing = {
                row[1] for row in connection.execute("PRAGMA table_info(projects)")
            }
            for name, column_type in columns.items():
                if name not in existing:
                    connection.execute(
                        f"ALTER TABLE projects ADD COLUMN {name} {column_type}"
                    )

    def save(self, project: ProjectKnowledge) -> None:
        self.save_analysis(
            ProjectAnalysis(
                project_id=project.project_id,
                project_name=project.project_name,
                source_type="manual",
                analysis_status=AnalysisStatus.READY,
                analyzer_id="manual",
                knowledge=project,
            )
        )

    def save_analysis(self, record: ProjectAnalysis) -> None:
        if record.schema_version != CURRENT_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported project analysis schema_version: {record.schema_version}"
            )
        knowledge_payload = (
            json.dumps(_project_to_dict(record.knowledge), ensure_ascii=False)
            if record.knowledge is not None
            else None
        )
        universal_payload = (
            json.dumps(_universal_model_to_dict(record.universal_model), ensure_ascii=False)
            if record.universal_model is not None
            else None
        )
        payload = knowledge_payload or json.dumps(
            {"project_id": record.project_id, "project_name": record.project_name},
            ensure_ascii=False,
        )
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO projects "
                "(project_id, payload, source_type, workspace_path, analysis_status, "
                "schema_version, analyzer_id, project_name, universal_model_payload, "
                "knowledge_payload, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET payload=excluded.payload, "
                "source_type=excluded.source_type, workspace_path=excluded.workspace_path, "
                "analysis_status=excluded.analysis_status, schema_version=excluded.schema_version, "
                "analyzer_id=excluded.analyzer_id, "
                "project_name=excluded.project_name, "
                "universal_model_payload=excluded.universal_model_payload, "
                "knowledge_payload=excluded.knowledge_payload, error_message=excluded.error_message",
                (
                    record.project_id,
                    payload,
                    record.source_type,
                    record.workspace_path,
                    record.analysis_status.value,
                    record.schema_version,
                    record.analyzer_id,
                    record.project_name,
                    universal_payload,
                    knowledge_payload,
                    record.error,
                ),
            )

    def get_analysis(self, project_id: int) -> ProjectAnalysis:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT project_id, payload, source_type, workspace_path, analysis_status, "
                "schema_version, analyzer_id, project_name, universal_model_payload, "
                "knowledge_payload, error_message "
                "FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"项目不存在: {project_id}")
        (
            stored_id,
            legacy_payload,
            source_type,
            workspace_path,
            analysis_status,
            schema_version,
            analyzer_id,
            project_name,
            universal_payload,
            knowledge_payload,
            error_message,
        ) = row
        knowledge_data = json.loads(knowledge_payload or legacy_payload)
        knowledge = _project_from_dict(knowledge_data) if "topics" in knowledge_data else None
        if knowledge is not None and knowledge.project_id != int(stored_id):
            raise ValueError(
                "ProjectKnowledge project_id does not match persisted project_id: "
                f"{knowledge.project_id} != {stored_id}"
            )
        is_legacy_record = not analysis_status and schema_version is None
        resolved_schema_version = int(
            schema_version
            if schema_version is not None
            else CURRENT_ANALYSIS_SCHEMA_VERSION
        )
        if resolved_schema_version != CURRENT_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported project analysis schema_version: {resolved_schema_version}"
            )
        if analysis_status:
            status = AnalysisStatus(analysis_status)
        else:
            status = AnalysisStatus.READY
        restored_project_name = (
            project_name
            or (knowledge.project_name if knowledge else None)
            or knowledge_data.get("project_name")
            or str(stored_id)
        )
        return ProjectAnalysis(
            project_id=int(stored_id),
            project_name=restored_project_name,
            source_type=source_type or "manual",
            workspace_path=workspace_path or "",
            analysis_status=status,
            schema_version=resolved_schema_version,
            analyzer_id=(analyzer_id if analyzer_id is not None else "legacy")
            if not is_legacy_record
            else (analyzer_id or "legacy"),
            universal_model=_universal_model_from_dict(
                json.loads(universal_payload) if universal_payload else None,
                expected_project_id=int(stored_id),
            ),
            knowledge=knowledge,
            error=error_message or "",
        )

    def delete(self, project_id: int) -> None:
        with _connection(self.database) as connection:
            connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def list(self) -> list[ProjectKnowledge]:
        with _connection(self.database) as connection:
            rows = connection.execute(
                "SELECT project_id FROM projects ORDER BY project_id"
            ).fetchall()
        projects = []
        for (project_id,) in rows:
            try:
                projects.append(self.get(int(project_id)))
            except KeyError:
                continue
        return projects

    def get(self, project_id: int) -> ProjectKnowledge:
        record = self.get_analysis(project_id)
        if record.knowledge is None:
            raise KeyError(f"项目尚未生成 knowledge: {project_id}")
        return record.knowledge


class SQLiteSessionStore:
    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(session_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            existing = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "candidate_id" not in existing:
                connection.execute("ALTER TABLE sessions ADD COLUMN candidate_id TEXT")
            if "version" not in existing:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
                )
            if "updated_at" not in existing:
                connection.execute("ALTER TABLE sessions ADD COLUMN updated_at TEXT")

    def save(
        self,
        session_id: str,
        state: InterviewState,
        expected_version: int | None = None,
    ) -> int:
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            current_version = int(row[0] or 0) if row is not None else 0
            if expected_version is not None and expected_version != current_version:
                raise SessionConflictError(
                    f"session version conflict: {session_id} "
                    f"expected {expected_version}, current {current_version}"
                )
            payload = json.dumps(_state_to_dict(state), ensure_ascii=False)
            candidate_id = normalize_candidate_id(state.candidate_id)
            updated_at = datetime.now(timezone.utc).isoformat()
            if row is None:
                connection.execute(
                    "INSERT INTO sessions(session_id, payload, candidate_id, version, updated_at) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (session_id, payload, candidate_id, updated_at),
                )
                new_version = 0
            else:
                new_version = current_version + 1
                if expected_version is None:
                    cursor = connection.execute(
                        "UPDATE sessions SET payload = ?, candidate_id = ?, "
                        "version = ?, updated_at = ? WHERE session_id = ?",
                        (payload, candidate_id, new_version, updated_at, session_id),
                    )
                else:
                    cursor = connection.execute(
                        "UPDATE sessions SET payload = ?, candidate_id = ?, "
                        "version = ?, updated_at = ? WHERE session_id = ? AND version = ?",
                        (payload, candidate_id, new_version, updated_at, session_id, expected_version),
                    )
                if cursor.rowcount != 1:
                    raise SessionConflictError(
                        f"session version conflict: {session_id} "
                        f"expected {expected_version}, current {current_version}"
                    )
            connection.commit()
            return new_version
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_if_version(self, session_id, state, expected_version):
        return self.save(session_id, state, expected_version=expected_version)

    def get_with_version(self, session_id: str) -> tuple[InterviewState, int]:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload, candidate_id, version FROM sessions "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"session not found: {session_id}")
            payload = _session_payload(row[0])
            candidate_id = _session_candidate_id(payload, row[1])
            if row[1] != candidate_id:
                connection.execute(
                    "UPDATE sessions SET candidate_id = ? WHERE session_id = ?",
                    (candidate_id, session_id),
                )
            return (
                replace(_state_from_dict(payload), candidate_id=candidate_id),
                int(row[2] or 0),
            )

    def get(self, session_id: str) -> InterviewState:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload, candidate_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"会话不存在: {session_id}")
        payload = _session_payload(row[0])
        candidate_id = _session_candidate_id(payload, row[1])
        if row[1] != candidate_id:
            with _connection(self.database) as connection:
                connection.execute(
                    "UPDATE sessions SET candidate_id = ? WHERE session_id = ?",
                    (candidate_id, session_id),
                )
        return replace(
            _state_from_dict(payload),
            candidate_id=candidate_id,
        )

    def list(
        self,
        *,
        candidate_id: str | None = None,
        project_id: int | None = None,
        position_id: str | None = None,
        limit: int = 50,
    ) -> list[tuple[str, InterviewState, str]]:
        with _connection(self.database) as connection:
            rows = connection.execute(
                "SELECT rowid, session_id, payload, candidate_id, updated_at "
                "FROM sessions ORDER BY COALESCE(updated_at, '') DESC, rowid DESC"
            ).fetchall()
        result = []
        for _, session_id, raw_payload, stored_candidate_id, updated_at in rows:
            payload = _session_payload(raw_payload)
            owner = _session_candidate_id(payload, stored_candidate_id)
            state = replace(_state_from_dict(payload), candidate_id=owner)
            if candidate_id is not None and owner != candidate_id:
                continue
            if project_id is not None and state.project_id != project_id:
                continue
            if position_id is not None and state.position_id != position_id:
                continue
            result.append((session_id, state, updated_at or ""))
            if len(result) >= limit:
                break
        return result

    def get_candidate_id(self, session_id: str) -> str:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload, candidate_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"会话不存在: {session_id}")
        payload = _session_payload(row[0])
        _validate_state_payload(payload)
        candidate_id = _session_candidate_id(payload, row[1])
        if row[1] != candidate_id:
            with _connection(self.database) as connection:
                connection.execute(
                    "UPDATE sessions SET candidate_id = ? WHERE session_id = ?",
                    (candidate_id, session_id),
                )
        return candidate_id

    def delete(self, session_id: str) -> None:
        with _connection(self.database) as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            if cursor.rowcount != 1:
                raise KeyError(f"session not found: {session_id}")
