"""Agent 角色定义与持久化：单 agent / 多 agent 模式的角色选择与自定义。

角色 agent 只有两类来源：代码内置（builtin）与用户自定义（持久化）。
装配时按阶段（questioner/evaluator/director）选择 agent，persona 只替换
LLM 组件的角色设定，输出契约（JSON 等）由组件固定，不可被用户覆盖。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# 角色类型：generalist 为单 agent 模式的全能角色，其余为多 agent 分工角色
AGENT_ROLES = ("generalist", "questioner", "evaluator", "director")

ROLE_NAMES = {
    "generalist": "全能面试官",
    "questioner": "出题官",
    "evaluator": "评分官",
    "director": "策略官",
}

# 多 agent 装配的阶段键
STAGES = ("questioner", "evaluator", "director")


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    name: str
    role: str
    persona: str
    profile_id: str = ""
    builtin: bool = False

    def public_payload(self) -> dict:
        return {
            "id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "persona": self.persona,
            "profile_id": self.profile_id,
            "builtin": self.builtin,
        }


BUILTIN_AGENTS = (
    AgentDefinition(
        "builtin-generalist",
        "全能面试官",
        "generalist",
        "严谨的项目领域面试官，统筹出题、评价与追问方向，始终基于项目证据提问和反馈",
        builtin=True,
    ),
    AgentDefinition(
        "builtin-questioner",
        "出题官",
        "questioner",
        "严谨的项目领域出题官，擅长把项目实现、流程与权衡转化为有挑战性的考察问题",
        builtin=True,
    ),
    AgentDefinition(
        "builtin-evaluator",
        "证据评分官",
        "evaluator",
        "基于项目证据的评价官，先逐条比对回答与证据，再给出分数、反馈与参考回答",
        builtin=True,
    ),
    AgentDefinition(
        "builtin-director",
        "追问策略官",
        "director",
        "项目面试考官的策略层，负责决定下一问的主题、方向与难度层级",
        builtin=True,
    ),
    AgentDefinition(
        "builtin-stress",
        "压力面试官",
        "questioner",
        "高要求、风格犀利的压力面试官，专挑边界条件、异常处理和关键权衡追问，要求回答给出可验证的项目证据",
        builtin=True,
    ),
)


def _validate_agent_payload(payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("agent 定义必须是 JSON 对象")
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("agent 名称不能为空")
    role = str(payload.get("role", "")).strip()
    if role not in AGENT_ROLES:
        raise ValueError(f"agent 角色必须是 {list(AGENT_ROLES)} 之一")
    persona = str(payload.get("persona", "")).strip()
    if not persona:
        raise ValueError("agent 角色设定不能为空")
    profile_id = str(payload.get("profile_id", "")).strip()
    return {"name": name, "role": role, "persona": persona, "profile_id": profile_id}


class InMemoryAgentStore:
    def __init__(self):
        self._custom: dict[str, AgentDefinition] = {}

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        return tuple(list(BUILTIN_AGENTS) + list(self._custom.values()))

    def get(self, agent_id: str) -> AgentDefinition:
        for agent in self.list_agents():
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(f"agent 不存在: {agent_id}")

    def save_agent(self, agent: AgentDefinition) -> None:
        if agent.builtin:
            raise ValueError("内置 agent 不可修改")
        self._custom[agent.agent_id] = agent

    def delete_agent(self, agent_id: str) -> None:
        if agent_id not in self._custom:
            raise KeyError(f"agent 不存在: {agent_id}")
        del self._custom[agent_id]

    def custom_agents(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._custom.values())


class SQLiteAgentStore:
    _KEY = "agent_definitions"

    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_settings "
                "(setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
            )

    def _read_custom(self) -> dict[str, AgentDefinition]:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (self._KEY,),
            ).fetchone()
        if row is None:
            return {}
        try:
            items = json.loads(row[0])
            return {
                item["id"]: AgentDefinition(
                    item["id"],
                    item["name"],
                    item["role"],
                    item["persona"],
                    item.get("profile_id", ""),
                    builtin=False,
                )
                for item in items
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("保存的 agent 定义无效") from exc

    def _persist(self, custom: dict[str, AgentDefinition]) -> None:
        payload = [
            {
                "id": agent.agent_id,
                "name": agent.name,
                "role": agent.role,
                "persona": agent.persona,
                "profile_id": agent.profile_id,
            }
            for agent in custom.values()
        ]
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                (self._KEY, json.dumps(payload, ensure_ascii=False)),
            )

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        return tuple(list(BUILTIN_AGENTS) + list(self._read_custom().values()))

    def get(self, agent_id: str) -> AgentDefinition:
        for agent in self.list_agents():
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(f"agent 不存在: {agent_id}")

    def save_agent(self, agent: AgentDefinition) -> None:
        if agent.builtin:
            raise ValueError("内置 agent 不可修改")
        custom = self._read_custom()
        custom[agent.agent_id] = agent
        self._persist(custom)

    def delete_agent(self, agent_id: str) -> None:
        custom = self._read_custom()
        if agent_id not in custom:
            raise KeyError(f"agent 不存在: {agent_id}")
        del custom[agent_id]
        self._persist(custom)

    def custom_agents(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._read_custom().values())


__all__ = [
    "AGENT_ROLES",
    "ROLE_NAMES",
    "STAGES",
    "AgentDefinition",
    "BUILTIN_AGENTS",
    "InMemoryAgentStore",
    "SQLiteAgentStore",
]
