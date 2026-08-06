"""应用级大模型配置与配置档案持久化。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from .llm import LLMConfig


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _local_config() -> LLMConfig:
    return LLMConfig("", "", "", provider="rule_based", provider_name="local")


def _default_profile_name(config: LLMConfig) -> str:
    if config.provider_name not in {"", "custom", "local"}:
        return config.provider_name
    return config.model or "本地规则引擎"


@dataclass(frozen=True)
class LLMProfile:
    profile_id: str
    name: str
    config: LLMConfig

    def public_payload(self, active: bool = False) -> dict:
        return {
            "id": self.profile_id,
            "name": self.name,
            "active": active,
            **self.config.public_payload(),
        }


class InMemoryLLMSettingsStore:
    def __init__(self, initial: LLMConfig | None = None):
        self._config = initial or _local_config()
        self._profiles: dict[str, LLMProfile] = {}
        self._active_id: str | None = None
        if self._config.enabled:
            profile = LLMProfile("default", _default_profile_name(self._config), self._config)
            self._profiles[profile.profile_id] = profile
            self._active_id = profile.profile_id

    def get(self) -> LLMConfig:
        if self._active_id and self._active_id in self._profiles:
            return self._profiles[self._active_id].config
        return self._config

    def save(self, config: LLMConfig) -> None:
        self._config = config
        if not config.enabled:
            self._active_id = None
            return
        profile_id = self._active_id or "default"
        current = self._profiles.get(profile_id)
        self._profiles[profile_id] = LLMProfile(
            profile_id,
            current.name if current else _default_profile_name(config),
            config,
        )
        self._active_id = profile_id

    def list_profiles(self) -> tuple[LLMProfile, ...]:
        return tuple(self._profiles.values())

    def get_profile(self, profile_id: str) -> LLMProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"大模型配置不存在: {profile_id}") from exc

    def save_profile(self, profile: LLMProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def delete_profile(self, profile_id: str) -> None:
        self.get_profile(profile_id)
        del self._profiles[profile_id]
        if self._active_id == profile_id:
            self._active_id = None
            self._config = _local_config()

    def active_profile_id(self) -> str | None:
        return self._active_id

    def set_active(self, profile_id: str) -> None:
        profile = self.get_profile(profile_id)
        self._active_id = profile_id
        self._config = profile.config

    @staticmethod
    def config_from_payload(payload, existing_api_key: str = "", require_model: bool = True) -> LLMConfig:
        return LLMConfig.from_payload(
            payload,
            existing_api_key=existing_api_key,
            require_model=require_model,
        )


class SQLiteLLMSettingsStore:
    _KEY = "llm_config"
    _PROFILES_KEY = "llm_profiles"

    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_settings "
                "(setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
            )

    def _read_state(self):
        with _connection(self.database) as connection:
            rows = dict(connection.execute("SELECT setting_key, setting_value FROM app_settings"))
        profiles_payload = rows.get(self._PROFILES_KEY)
        if profiles_payload is not None:
            try:
                payload = json.loads(profiles_payload)
                profiles = {
                    item["id"]: LLMProfile(
                        item["id"],
                        item["name"],
                        LLMConfig.from_payload(item["config"]),
                    )
                    for item in payload.get("profiles", [])
                }
                return profiles, payload.get("active_id"), True
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("保存的大模型配置档案无效") from exc

        legacy_payload = rows.get(self._KEY)
        if legacy_payload is None:
            return {}, None, False
        try:
            config = LLMConfig.from_payload(json.loads(legacy_payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("保存的大模型配置无效") from exc
        if config.enabled:
            profile = LLMProfile("legacy", _default_profile_name(config), config)
            return {profile.profile_id: profile}, profile.profile_id, False
        return {}, None, True

    def _persist_state(self, profiles: dict[str, LLMProfile], active_id: str | None) -> None:
        payload = {
            "active_id": active_id,
            "profiles": [
                {"id": profile.profile_id, "name": profile.name, "config": asdict(profile.config)}
                for profile in profiles.values()
            ],
        }
        active_config = profiles[active_id].config if active_id in profiles else _local_config()
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (self._PROFILES_KEY, json.dumps(payload, ensure_ascii=False)),
            )
            connection.execute(
                "INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (self._KEY, json.dumps(asdict(active_config), ensure_ascii=False)),
            )

    def get(self) -> LLMConfig | None:
        profiles, active_id, has_state = self._read_state()
        if active_id and active_id in profiles:
            return profiles[active_id].config
        if has_state:
            return _local_config()
        return None

    def save(self, config: LLMConfig) -> None:
        profiles, active_id, _ = self._read_state()
        if config.enabled:
            profile_id = active_id or "default"
            current = profiles.get(profile_id)
            profiles[profile_id] = LLMProfile(
                profile_id,
                current.name if current else _default_profile_name(config),
                config,
            )
            active_id = profile_id
        else:
            active_id = None
        self._persist_state(profiles, active_id)

    def list_profiles(self) -> tuple[LLMProfile, ...]:
        profiles, _, _ = self._read_state()
        return tuple(profiles.values())

    def get_profile(self, profile_id: str) -> LLMProfile:
        profiles, _, _ = self._read_state()
        try:
            return profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"大模型配置不存在: {profile_id}") from exc

    def save_profile(self, profile: LLMProfile) -> None:
        profiles, active_id, _ = self._read_state()
        profiles[profile.profile_id] = profile
        self._persist_state(profiles, active_id)

    def delete_profile(self, profile_id: str) -> None:
        profiles, active_id, _ = self._read_state()
        if profile_id not in profiles:
            raise KeyError(f"大模型配置不存在: {profile_id}")
        del profiles[profile_id]
        self._persist_state(profiles, None if active_id == profile_id else active_id)

    def active_profile_id(self) -> str | None:
        _, active_id, _ = self._read_state()
        return active_id

    def set_active(self, profile_id: str) -> None:
        profiles, _, _ = self._read_state()
        if profile_id not in profiles:
            raise KeyError(f"大模型配置不存在: {profile_id}")
        self._persist_state(profiles, profile_id)

    @staticmethod
    def config_from_payload(payload, existing_api_key: str = "", require_model: bool = True) -> LLMConfig:
        return LLMConfig.from_payload(
            payload,
            existing_api_key=existing_api_key,
            require_model=require_model,
        )


__all__ = ["LLMProfile", "InMemoryLLMSettingsStore", "SQLiteLLMSettingsStore"]
