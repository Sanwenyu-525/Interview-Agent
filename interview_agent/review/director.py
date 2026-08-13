"""Director 的 tool-calling 决策：让策略官在决定下一问前主动查询证据、历史与画像。

输出最小动作集 ask / stop。任何失败或非法输出都返回 None，由调用方回退到
同模式的规则策略（ReviewPolicy），保证面试行为可控且可测。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from ..models import AnswerRecord, ProjectKnowledge
from ..profile import CandidateProfile
from .evidence import resolve_topic_evidence
from .policy import ReviewMode, policy_for_mode

# 与 llm_policy 保持一致的允许方向；模式决定合法追问方向集合。
_DIRECTIONS = {
    ReviewMode.TECHNICAL_INTERVIEW: ("basic", "deep", "architecture"),
    ReviewMode.PORTFOLIO_REVIEW: ("story", "tradeoff", "impact"),
    ReviewMode.DEFENSE_REVIEW: ("clarify", "justify", "defend"),
}

_MAX_TOOL_ROUNDS = 4


@dataclass(frozen=True)
class DirectorAction:
    action: str  # "ask" | "stop"
    topic: str = ""
    direction: str = ""
    level: int = 1
    reason: str = ""


def _content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(parts).strip()
    return ""


def _parse_json_object(text: str) -> dict | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


class ToolCallingDirector:
    """用 tool-calling 决定下一动作；失败回退 None，由调用方走规则策略。"""

    def __init__(self, client, mode=ReviewMode.TECHNICAL_INTERVIEW, persona=None):
        self.client = client
        self.mode = mode
        self.persona = persona
        self._fallback = policy_for_mode(mode)

    def decide_turn(
        self,
        *,
        project: ProjectKnowledge,
        profile: CandidateProfile,
        history: list[AnswerRecord],
        resume_claims=(),
        current_topic=None,
        current_level: int = 1,
        last_score=None,
        turn_count: int = 0,
        max_turns: int = 10,
    ) -> DirectorAction | None:
        try:
            tools = self._build_tools(project, profile, history)
            payload = self._run_tool_loop(
                tools,
                project,
                profile,
                history,
                resume_claims,
                current_topic,
                current_level,
                last_score,
                turn_count,
                max_turns,
            )
            return self._parse_action(payload, project)
        except Exception:
            return None

    def _build_tools(self, project, profile, history):
        def query_evidence(topic_name: str) -> str:
            """查询指定主题的项目证据内容，返回可追溯的证据条目列表。"""
            topic = next(
                (
                    item
                    for item in project.topics
                    if item.name.casefold() == str(topic_name).strip().casefold()
                ),
                None,
            )
            if topic is None:
                return json.dumps({"error": f"主题不存在: {topic_name}"}, ensure_ascii=False)
            facts = list(resolve_topic_evidence(project, topic))
            return json.dumps(facts, ensure_ascii=False, default=str)

        def read_history() -> str:
            """读取已进行的问答历史与每次评价得分。"""
            return json.dumps(
                [
                    {
                        "topic": record.topic,
                        "question": record.question,
                        "answer": record.answer,
                        "score": record.evaluation.score,
                    }
                    for record in history
                ],
                ensure_ascii=False,
            )

        def get_profile() -> str:
            """读取候选人当前的能力画像：各主题的分数、趋势与薄弱项。"""
            return json.dumps(
                {
                    name: {
                        "score": snapshot.score,
                        "trend": snapshot.trend,
                        "sample_count": snapshot.sample_count,
                        "weaknesses": list(snapshot.weaknesses),
                    }
                    for name, snapshot in profile.skills.items()
                },
                ensure_ascii=False,
            )

        return [
            StructuredTool.from_function(
                func=query_evidence,
                name="query_evidence",
                description="查询指定主题的项目证据内容，返回可追溯的证据条目。",
            ),
            StructuredTool.from_function(
                func=read_history,
                name="read_history",
                description="读取已进行的问答历史与每次评价得分。",
            ),
            StructuredTool.from_function(
                func=get_profile,
                name="get_profile",
                description="读取候选人当前的能力画像。",
            ),
        ]

    def _system_message(self) -> SystemMessage:
        role = self.persona or "项目面试考官的策略层"
        return SystemMessage(
            content=(
                f"你是{role}，负责决定面试的下一步。"
                "你可以调用 query_evidence / read_history / get_profile 工具了解项目证据、"
                "历史回答和候选人画像后再决策。"
                "最终只输出 JSON："
                '继续追问输出 {"action":"ask","topic":"主题名","direction":"方向","level":1,"reason":"一句话"}；'
                '结束面试输出 {"action":"stop","reason":"一句话"}。'
                "topic 必须来自当前项目主题，direction 从允许方向中选，level 是 1 到 4 的整数。"
                "不要输出 JSON 以外的任何文字。"
            )
        )

    def _user_message(
        self,
        project,
        profile,
        history,
        resume_claims,
        current_topic,
        current_level,
        last_score,
        turn_count,
        max_turns,
    ) -> HumanMessage:
        return HumanMessage(
            content=json.dumps(
                {
                    "任务": "决定面试的下一动作：继续追问还是结束",
                    "模式": self.mode.value,
                    "允许方向": list(_DIRECTIONS[self.mode]),
                    "项目主题": [item.name for item in project.topics],
                    "当前主题": current_topic.name if current_topic else "",
                    "当前层级": current_level,
                    "上一轮得分": last_score,
                    "已进行轮数": turn_count,
                    "最大轮数": max_turns,
                    "简历主张": list(resume_claims),
                    "结束建议": (
                        "已问主题覆盖充分、画像样本足够、或达到最大轮数时应输出 stop；"
                        "否则针对薄弱主题输出 ask。"
                    ),
                },
                ensure_ascii=False,
            )
        )

    def _run_tool_loop(
        self,
        tools,
        project,
        profile,
        history,
        resume_claims,
        current_topic,
        current_level,
        last_score,
        turn_count,
        max_turns,
    ) -> dict | None:
        llm = self.client.bind_tools(tools)
        messages = [
            self._system_message(),
            self._user_message(
                project,
                profile,
                history,
                resume_claims,
                current_topic,
                current_level,
                last_score,
                turn_count,
                max_turns,
            ),
        ]
        for _ in range(_MAX_TOOL_ROUNDS):
            response = llm.invoke(messages)
            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                return _parse_json_object(_content_text(getattr(response, "content", "")))
            messages.append(response)
            for call in tool_calls:
                name = call.get("name", "") if isinstance(call, dict) else getattr(call, "name", "")
                args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
                call_id = call.get("id", "") if isinstance(call, dict) else getattr(call, "id", "")
                messages.append(ToolMessage(content=self._execute_tool(tools, name, args), tool_call_id=call_id))
        return None

    @staticmethod
    def _execute_tool(tools, name, args) -> str:
        tool = next((item for item in tools if item.name == name), None)
        if tool is None:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            return str(tool.invoke(args or {}))
        except Exception as exc:  # noqa: BLE001 - 工具失败返回可读错误，避免中断决策
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _parse_action(self, payload, project) -> DirectorAction | None:
        if not isinstance(payload, dict):
            return None
        action = str(payload.get("action", "")).strip().lower()
        reason = str(payload.get("reason", "")).strip()
        if action == "stop":
            return DirectorAction(action="stop", reason=reason)
        if action != "ask":
            return None
        topic_name = str(payload.get("topic", "")).strip()
        topic = next(
            (
                item
                for item in project.topics
                if item.name.casefold() == topic_name.casefold()
            ),
            None,
        )
        if topic is None:
            return None
        direction = str(payload.get("direction", "")).strip()
        if direction not in _DIRECTIONS[self.mode]:
            return None
        try:
            level = int(payload.get("level", 1))
        except (TypeError, ValueError):
            return None
        if not 1 <= level <= 4:
            return None
        return DirectorAction(
            action="ask",
            topic=topic.name,
            direction=direction,
            level=level,
            reason=reason,
        )


__all__ = ["DirectorAction", "ToolCallingDirector"]
