"""ReviewPolicy 的 LLM 实现。

主题与追问方向由 LLM 在规则圈定的候选集内决策；任何失败（调用异常、
非法 JSON、越界选择）都回退到同模式的规则策略，保证可用性与可测试性。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .evidence import resolve_topic_evidence
from .policy import ReviewMode, policy_for_mode


_LEVEL_HINTS = {
    1: "大方向：目标、边界、参与方、总体方案",
    2: "一条核心流程：职责划分、数据流转、异常处理",
    3: "边界条件、方案权衡、验证方式",
    4: "容量、稳定性、架构演进",
}

_DIRECTIONS = {
    ReviewMode.TECHNICAL_INTERVIEW: ("basic", "deep", "architecture"),
    ReviewMode.PORTFOLIO_REVIEW: ("story", "tradeoff", "impact"),
    ReviewMode.DEFENSE_REVIEW: ("clarify", "justify", "defend"),
}

_MODE_INSTRUCTION = {
    ReviewMode.TECHNICAL_INTERVIEW: "技术面试视角：选最值得追问的实现、流程、权衡与架构方向",
    ReviewMode.PORTFOLIO_REVIEW: "作品集评审视角：选最能体现创意、执行与影响的方向",
    ReviewMode.DEFENSE_REVIEW: "答辩评审视角：选最需要拷问目标、决策与风险防御的方向",
}


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("LLM 决策响应必须是 JSON 对象")
    return payload


class LlmReviewPolicy:
    """LLM 参与主题与下一步方向决策；规则策略做候选与兜底。

    主题采用候选制：规则先给出推荐并圈出有证据的主题，LLM 只能从候选中选，
    防止选出无证据或与项目无关的主题。
    """

    def __init__(self, client, mode=ReviewMode.TECHNICAL_INTERVIEW, persona: str | None = None):
        self.client = client
        self.mode = mode
        self.persona = persona
        self._fallback = policy_for_mode(mode)

    def select_topic(
        self,
        project,
        profile,
        history,
        resume_claims: Iterable[str] = (),
    ):
        try:
            candidates = self._candidates(project, profile, history, resume_claims)
            result = self._decide(self._topic_payload(project, profile, history, resume_claims, candidates))
            chosen = self._match_topic(candidates, result.get("topic_name"))
            if chosen is None:
                return self._fallback_topic(project, profile, history, resume_claims)
            return chosen
        except Exception:
            return self._fallback_topic(project, profile, history, resume_claims)

    def next_direction(self, score: int, current_level: int):
        try:
            result = self._decide(self._direction_payload(score, current_level))
            direction = str(result.get("direction", "")).strip()
            level = int(result.get("level", 0))
            if direction not in _DIRECTIONS[self.mode] or not 1 <= level <= 4:
                return self._fallback.next_direction(score, current_level)
            return direction, level
        except Exception:
            return self._fallback.next_direction(score, current_level)

    def _candidates(self, project, profile, history, resume_claims) -> list:
        try:
            rule_choice = self._fallback.select_topic(project, profile, history, resume_claims)
        except Exception:
            rule_choice = None
        candidates = [
            topic for topic in project.topics if resolve_topic_evidence(project, topic)
        ]
        if not candidates:
            candidates = list(project.topics)
        if rule_choice is not None and rule_choice not in candidates:
            candidates.insert(0, rule_choice)
        return candidates[:3]

    def _topic_payload(self, project, profile, history, resume_claims, candidates) -> dict:
        asked = {record.topic for record in history}
        return {
            "任务": "从候选主题中选一个作为下一题主题，不要臆造候选中没有的主题",
            "模式": self.mode.value,
            "模式要点": _MODE_INSTRUCTION[self.mode],
            "项目": project.project_name,
            "候选主题": [
                {
                    "name": topic.name,
                    "score": topic.score,
                    "evidence_count": len(topic.evidence),
                    "已追问": topic.name in asked,
                }
                for topic in candidates
            ],
            "已问主题": [{"topic": record.topic, "score": record.evaluation.score} for record in history],
            "技能画像": [
                {
                    "name": name,
                    "score": snapshot.score,
                    "trend": snapshot.trend,
                    "weaknesses": list(snapshot.weaknesses),
                }
                for name, snapshot in profile.skills.items()
            ],
            "简历主张": list(resume_claims),
            "输出格式": {
                "topic_name": "必须等于某个候选主题的 name 原样",
                "reason": "一句话说明为什么选它",
            },
        }

    def _direction_payload(self, score: int, current_level: int) -> dict:
        return {
            "任务": "决定下一题的追问方向与难度层级",
            "模式": self.mode.value,
            "模式要点": _MODE_INSTRUCTION[self.mode],
            "本轮得分": score,
            "当前层级": current_level,
            "允许方向": list(_DIRECTIONS[self.mode]),
            "允许层级": "1 到 4 的整数，只能升深不能回落",
            "层级说明": _LEVEL_HINTS,
            "输出格式": {
                "direction": "从允许方向中选一个",
                "level": "1 到 4 的整数",
                "reason": "一句话说明为什么这么定",
            },
        }

    def _decide(self, payload: dict) -> dict[str, Any]:
        role = self.persona or "项目面试考官的策略层"
        messages = [
            {
                "role": "system",
                "content": f"你是{role}，只输出 JSON，不要输出任何多余文字。",
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ]
        content = self.client.chat(
            messages,
            response_format={"type": "json_object"},
        )
        return _parse_json_object(content)

    @staticmethod
    def _match_topic(candidates, topic_name: Any):
        if not isinstance(topic_name, str):
            return None
        normalized = topic_name.strip().casefold()
        if not normalized:
            return None
        for topic in candidates:
            if topic.name.casefold() == normalized:
                return topic
        return None

    def _fallback_topic(self, project, profile, history, resume_claims):
        return self._fallback.select_topic(project, profile, history, resume_claims)


__all__ = ["LlmReviewPolicy"]