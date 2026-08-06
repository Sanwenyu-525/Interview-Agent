import json
import sqlite3
from copy import deepcopy
from contextlib import contextmanager
from threading import RLock
from typing import Callable, Protocol, runtime_checkable

from ..models import ProfileConflictError
from ..profile import CandidateProfile, ProfileUpdate, SkillSnapshot, WeaknessSource


@runtime_checkable
class CandidateProfileStore(Protocol):
    def get(self, candidate_id: str) -> CandidateProfile: ...

    def get_with_version(self, candidate_id: str) -> tuple[CandidateProfile, int]: ...

    def save(self, candidate_id: str, profile: CandidateProfile) -> int: ...

    def update(
        self,
        candidate_id: str,
        updater: Callable[[CandidateProfile], CandidateProfile | None],
    ) -> CandidateProfile: ...

    def merge(self, candidate_id: str, update: ProfileUpdate) -> CandidateProfile: ...

    def commit(self, candidate_id: str, update: ProfileUpdate) -> int: ...

    def restore_if_version(
        self,
        candidate_id: str,
        profile: CandidateProfile,
        expected_version: int,
    ) -> int: ...


CURRENT_PROFILE_SCHEMA_VERSION = 2


def normalize_candidate_id(candidate_id) -> str:
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a non-blank string")
    return candidate_id.strip()


def _candidate_key(candidate_id: str) -> str:
    return normalize_candidate_id(candidate_id)


def _profile_to_dict(profile: CandidateProfile) -> dict:
    return {
        "schema_version": CURRENT_PROFILE_SCHEMA_VERSION,
        "skills": {
            topic: {
                "score": snapshot.score,
                "trend": snapshot.trend,
                "recent_score": snapshot.recent_score,
                "sample_count": snapshot.sample_count,
                "weaknesses": list(snapshot.weaknesses),
                "weakness_sources": [
                    {
                        "weakness": source.weakness,
                        "session_id": source.session_id,
                        "project_id": source.project_id,
                        "record_index": source.record_index,
                        "question": source.question,
                        "evidence_ids": list(source.evidence_ids),
                    }
                    for source in snapshot.weakness_sources
                ],
            }
            for topic, snapshot in profile.skills.items()
        }
    }


def _profile_from_dict(payload: dict | None) -> CandidateProfile:
    if payload is None:
        raise ValueError("candidate profile payload must be a JSON object")
    if not isinstance(payload, dict):
        raise ValueError("candidate profile payload must be a JSON object")
    schema_version = payload.get("schema_version", 0)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("candidate profile schema_version must be an integer")
    if schema_version not in (0, 1, CURRENT_PROFILE_SCHEMA_VERSION):
        raise ValueError(
            f"unsupported candidate profile schema_version: {schema_version}"
        )
    raw_skills = payload.get("skills", {})
    if not isinstance(raw_skills, dict):
        raise ValueError("candidate profile skills must be a JSON object")
    skills = {}
    for topic, raw_snapshot in raw_skills.items():
        if not isinstance(topic, str) or not isinstance(raw_snapshot, dict):
            raise ValueError("candidate profile skill snapshot must be an object")
        if "score" not in raw_snapshot:
            raise ValueError(f"candidate profile skill is missing score: {topic}")
        score = raw_snapshot["score"]
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError(f"candidate profile score must be an integer: {topic}")
        trend = raw_snapshot.get("trend", "new")
        if not isinstance(trend, str):
            raise ValueError(f"candidate profile trend must be a string: {topic}")
        recent_score = raw_snapshot.get("recent_score")
        if recent_score is not None and (
            isinstance(recent_score, bool) or not isinstance(recent_score, int)
        ):
            raise ValueError(
                f"candidate profile recent_score must be an integer or null: {topic}"
            )
        sample_count = raw_snapshot.get("sample_count", 1)
        if (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count < 1
        ):
            raise ValueError(
                f"candidate profile sample_count must be a positive integer: {topic}"
            )
        weaknesses = raw_snapshot.get("weaknesses", [])
        if not isinstance(weaknesses, list) or not all(
            isinstance(weakness, str) for weakness in weaknesses
        ):
            raise ValueError(
                f"candidate profile weaknesses must be a string array: {topic}"
            )
        raw_sources = raw_snapshot.get("weakness_sources", [])
        if not isinstance(raw_sources, list):
            raise ValueError(
                f"candidate profile weakness_sources must be an array: {topic}"
            )
        sources = tuple(
            _weakness_source_from_dict(raw_source, topic)
            for raw_source in raw_sources
        )
        skills[str(topic)] = SkillSnapshot(
            score=score,
            trend=trend,
            recent_score=recent_score,
            sample_count=sample_count,
            weaknesses=tuple(weaknesses),
            weakness_sources=sources,
        )
    return CandidateProfile(skills=skills)


def _decode_profile(raw_payload: str, candidate_id: str) -> CandidateProfile:
    try:
        payload = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError):
        raise ValueError(
            f"invalid candidate profile payload for candidate {_candidate_key(candidate_id)}: invalid JSON"
        ) from None
    try:
        return _profile_from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid candidate profile payload for candidate {_candidate_key(candidate_id)}: {exc}"
        ) from None


def _weakness_source_from_dict(payload, topic: str) -> WeaknessSource:
    if not isinstance(payload, dict):
        raise ValueError(f"candidate profile weakness source must be an object: {topic}")
    weakness = payload.get("weakness")
    session_id = payload.get("session_id")
    project_id = payload.get("project_id")
    record_index = payload.get("record_index")
    question = payload.get("question")
    evidence_ids = payload.get("evidence_ids", [])
    if not isinstance(weakness, str) or not weakness:
        raise ValueError(f"candidate profile weakness source has invalid weakness: {topic}")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError(f"candidate profile weakness source has invalid session_id: {topic}")
    if isinstance(project_id, bool) or not isinstance(project_id, int):
        raise ValueError(f"candidate profile weakness source has invalid project_id: {topic}")
    if isinstance(record_index, bool) or not isinstance(record_index, int) or record_index < 0:
        raise ValueError(f"candidate profile weakness source has invalid record_index: {topic}")
    if not isinstance(question, str):
        raise ValueError(f"candidate profile weakness source has invalid question: {topic}")
    if not isinstance(evidence_ids, list) or not all(
        isinstance(evidence_id, str) for evidence_id in evidence_ids
    ):
        raise ValueError(f"candidate profile weakness source has invalid evidence_ids: {topic}")
    return WeaknessSource(
        weakness=weakness,
        session_id=session_id,
        project_id=project_id,
        record_index=record_index,
        question=question,
        evidence_ids=tuple(evidence_ids),
    )


def _updated_profile(
    profile: CandidateProfile,
    updater: Callable[[CandidateProfile], CandidateProfile | None],
) -> CandidateProfile:
    result = updater(profile)
    if result is None:
        result = profile
    if not isinstance(result, CandidateProfile):
        raise ValueError("candidate profile updater must return CandidateProfile or None")
    return result


class InMemoryCandidateProfileStore:
    def __init__(self):
        self._profiles: dict[str, CandidateProfile] = {}
        self._versions: dict[str, int] = {}
        self._lock = RLock()

    def get(self, candidate_id: str) -> CandidateProfile:
        return self.get_with_version(candidate_id)[0]

    def get_with_version(self, candidate_id: str) -> tuple[CandidateProfile, int]:
        with self._lock:
            key = _candidate_key(candidate_id)
            return (
                deepcopy(self._profiles.get(key, CandidateProfile())),
                self._versions.get(key, 0),
            )

    def save(self, candidate_id: str, profile: CandidateProfile) -> int:
        if not isinstance(profile, CandidateProfile):
            raise ValueError("profile must be CandidateProfile")
        with self._lock:
            key = _candidate_key(candidate_id)
            version = self._versions.get(key, 0) + 1
            self._profiles[key] = deepcopy(profile)
            self._versions[key] = version
            return version

    def update(
        self,
        candidate_id: str,
        updater: Callable[[CandidateProfile], CandidateProfile | None],
    ) -> CandidateProfile:
        with self._lock:
            current = deepcopy(
                self._profiles.get(_candidate_key(candidate_id), CandidateProfile())
            )
            updated = deepcopy(_updated_profile(current, updater))
            self._profiles[_candidate_key(candidate_id)] = updated
            key = _candidate_key(candidate_id)
            self._versions[key] = self._versions.get(key, 0) + 1
            return deepcopy(updated)

    def merge(self, candidate_id: str, update: ProfileUpdate) -> CandidateProfile:
        if not isinstance(update, ProfileUpdate):
            raise ValueError("profile update must be ProfileUpdate")
        return self.update(
            candidate_id,
            lambda profile: _merge_profile(profile, update),
        )

    def commit(self, candidate_id: str, update: ProfileUpdate) -> int:
        if not isinstance(update, ProfileUpdate):
            raise ValueError("profile update must be ProfileUpdate")
        if not isinstance(update.snapshot, SkillSnapshot):
            raise ValueError("profile update snapshot must be SkillSnapshot")
        key = _candidate_key(candidate_id)
        with self._lock:
            profile = deepcopy(self._profiles.get(key, CandidateProfile()))
            _commit_snapshot(profile, update)
            self._profiles[key] = deepcopy(profile)
            version = self._versions.get(key, 0) + 1
            self._versions[key] = version
            return version

    def restore_if_version(
        self,
        candidate_id: str,
        profile: CandidateProfile,
        expected_version: int,
    ) -> int:
        if not isinstance(profile, CandidateProfile):
            raise ValueError("profile must be CandidateProfile")
        key = _candidate_key(candidate_id)
        with self._lock:
            current_version = self._versions.get(key, 0)
            if current_version != expected_version:
                raise ProfileConflictError(
                    f"candidate profile version conflict: {key} "
                    f"expected {expected_version}, current {current_version}"
                )
            version = current_version + 1
            self._profiles[key] = deepcopy(profile)
            self._versions[key] = version
            return version

    get_profile = get
    save_profile = save


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class SQLiteCandidateProfileStore:
    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS candidate_profiles "
                "(candidate_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            existing = {
                row[1]
                for row in connection.execute("PRAGMA table_info(candidate_profiles)")
            }
            if "version" not in existing:
                connection.execute(
                    "ALTER TABLE candidate_profiles "
                    "ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
                )

    def get(self, candidate_id: str) -> CandidateProfile:
        return self.get_with_version(candidate_id)[0]

    def get_with_version(self, candidate_id: str) -> tuple[CandidateProfile, int]:
        key = _candidate_key(candidate_id)
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload, version FROM candidate_profiles WHERE candidate_id = ?",
                (key,),
            ).fetchone()
        return (
            _decode_profile(row[0], key) if row else CandidateProfile(),
            int(row[1] or 0) if row else 0,
        )

    def save(self, candidate_id: str, profile: CandidateProfile) -> int:
        if not isinstance(profile, CandidateProfile):
            raise ValueError("profile must be CandidateProfile")
        key = _candidate_key(candidate_id)
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM candidate_profiles WHERE candidate_id = ?",
                (key,),
            ).fetchone()
            version = (int(row[0] or 0) if row else 0) + 1
            connection.execute(
                "INSERT INTO candidate_profiles(candidate_id, payload, version) VALUES (?, ?, ?) "
                "ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload, "
                "version=excluded.version",
                (key, json.dumps(_profile_to_dict(profile), ensure_ascii=False), version),
            )
            connection.commit()
            return version
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update(
        self,
        candidate_id: str,
        updater: Callable[[CandidateProfile], CandidateProfile | None],
    ) -> CandidateProfile:
        key = _candidate_key(candidate_id)
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, version FROM candidate_profiles WHERE candidate_id = ?",
                (key,),
            ).fetchone()
            current = _decode_profile(row[0], key) if row else CandidateProfile()
            updated = _updated_profile(current, updater)
            payload = json.dumps(_profile_to_dict(updated), ensure_ascii=False)
            version = int(row[1] or 0) + 1 if row else 1
            connection.execute(
                "INSERT INTO candidate_profiles(candidate_id, payload, version) VALUES (?, ?, ?) "
                "ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload, "
                "version=excluded.version",
                (key, payload, version),
            )
            connection.commit()
            return deepcopy(updated)

        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def merge(self, candidate_id: str, update: ProfileUpdate) -> CandidateProfile:
        if not isinstance(update, ProfileUpdate):
            raise ValueError("profile update must be ProfileUpdate")
        return self.update(
            candidate_id,
            lambda profile: _merge_profile(profile, update),
        )

    def commit(self, candidate_id: str, update: ProfileUpdate) -> int:
        if not isinstance(update, ProfileUpdate):
            raise ValueError("profile update must be ProfileUpdate")
        if not isinstance(update.snapshot, SkillSnapshot):
            raise ValueError("profile update snapshot must be SkillSnapshot")
        key = _candidate_key(candidate_id)
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, version FROM candidate_profiles WHERE candidate_id = ?",
                (key,),
            ).fetchone()
            profile = _decode_profile(row[0], key) if row else CandidateProfile()
            _commit_snapshot(profile, update)
            version = (int(row[1] or 0) if row else 0) + 1
            connection.execute(
                "INSERT INTO candidate_profiles(candidate_id, payload, version) VALUES (?, ?, ?) "
                "ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload, "
                "version=excluded.version",
                (key, json.dumps(_profile_to_dict(profile), ensure_ascii=False), version),
            )
            connection.commit()
            return version
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def restore_if_version(
        self,
        candidate_id: str,
        profile: CandidateProfile,
        expected_version: int,
    ) -> int:
        if not isinstance(profile, CandidateProfile):
            raise ValueError("profile must be CandidateProfile")
        key = _candidate_key(candidate_id)
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM candidate_profiles WHERE candidate_id = ?",
                (key,),
            ).fetchone()
            current_version = int(row[0] or 0) if row else 0
            if current_version != expected_version:
                raise ProfileConflictError(
                    f"candidate profile version conflict: {key} "
                    f"expected {expected_version}, current {current_version}"
                )
            version = current_version + 1
            connection.execute(
                "INSERT INTO candidate_profiles(candidate_id, payload, version) VALUES (?, ?, ?) "
                "ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload, "
                "version=excluded.version",
                (key, json.dumps(_profile_to_dict(profile), ensure_ascii=False), version),
            )
            connection.commit()
            return version
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    get_profile = get
    save_profile = save


def _merge_profile(profile: CandidateProfile, update: ProfileUpdate) -> CandidateProfile:
    profile.update(update.topic, update.score, update.weaknesses)
    if update.weakness_sources:
        profile.merge_weakness_sources(update.topic, update.weakness_sources)
    return profile


def _commit_snapshot(profile: CandidateProfile, update: ProfileUpdate) -> CandidateProfile:
    incoming = deepcopy(update.snapshot)
    previous = profile.skills.get(update.topic)
    weaknesses = _merge_strings(
        incoming.weaknesses,
        update.weaknesses,
    )
    weakness_sources = _merge_weakness_sources(
        incoming.weakness_sources,
        update.weakness_sources,
    )
    if previous is None:
        profile.skills[update.topic] = SkillSnapshot(
            score=incoming.score,
            trend=incoming.trend,
            recent_score=incoming.recent_score,
            sample_count=incoming.sample_count,
            weaknesses=weaknesses,
            weakness_sources=weakness_sources,
        )
        return profile

    previous_score = previous.recent_score or previous.score
    if incoming.trend not in {"new", "improving", "declining", "stable"}:
        trend = incoming.trend
    elif incoming.score > previous_score:
        trend = "improving"
    elif incoming.score < previous_score:
        trend = "declining"
    else:
        trend = "stable"
    profile.skills[update.topic] = SkillSnapshot(
        score=incoming.score,
        trend=trend,
        recent_score=incoming.recent_score,
        sample_count=previous.sample_count + 1,
        weaknesses=_merge_strings(previous.weaknesses, weaknesses),
        weakness_sources=_merge_weakness_sources(
            previous.weakness_sources,
            weakness_sources,
        ),
    )
    return profile


def _merge_strings(existing, new_values) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, *new_values)))


def _merge_weakness_sources(existing, new_values) -> tuple[WeaknessSource, ...]:
    latest = {source.weakness: source for source in existing}
    for source in new_values:
        latest[source.weakness] = source
    return tuple(latest.values())
