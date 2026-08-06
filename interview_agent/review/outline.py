from dataclasses import dataclass
from typing import Any, Mapping

from ..models import ProjectKnowledge, Topic


@dataclass(frozen=True)
class _DirectionRule:
    name: str
    score: int
    keywords: tuple[str, ...]
    kinds: tuple[str, ...] = ()


_RULES = (
    _DirectionRule(
        "系统架构与模块协作",
        100,
        ("architecture", "module", "component", "dependency", "架构", "模块", "依赖"),
        ("component", "source", "module", "relation", "structure"),
    ),
    _DirectionRule(
        "接口设计与前后端联调",
        95,
        (
            "api",
            "http",
            "endpoint",
            "route",
            "request",
            "response",
            "controller",
            "fetch",
            "axios",
            "get ",
            "post ",
            "put ",
            "delete ",
            "patch ",
            "接口",
            "联调",
            "前端",
            "后端",
        ),
    ),
    _DirectionRule(
        "核心业务流程与数据流",
        90,
        ("flow", "entrypoint", "pipeline", "process", "service", "业务", "流程", "数据流"),
        ("flow", "entrypoint", "component", "function", "symbol", "service"),
    ),
    _DirectionRule(
        "数据一致性与状态管理",
        85,
        (
            "transaction",
            "database",
            "repository",
            "storage",
            "persist",
            "cache",
            "redis",
            "state",
            "事务",
            "数据库",
            "缓存",
            "状态",
            "一致性",
        ),
    ),
    _DirectionRule(
        "工程质量、稳定性与扩展",
        80,
        (
            "manifest",
            "dependency",
            "technology",
            "build",
            "package",
            "test",
            "deploy",
            "config",
            "error",
            "retry",
            "monitor",
            "performance",
            "工程",
            "测试",
            "部署",
            "稳定性",
            "性能",
            "扩展",
        ),
        ("manifest", "dependency", "technology", "build", "config", "test"),
    ),
)


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_text(item) for item in value)
    return str(value)


def _evidence_records(project: ProjectKnowledge) -> list[tuple[str, str, str]]:
    records = []
    seen = set()
    for key, value in project.evidence.items():
        if not isinstance(value, Mapping):
            continue
        candidate_id = str(value.get("id") or key)
        evidence_id = candidate_id if candidate_id in project.evidence else str(key)
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        records.append(
            (
                evidence_id,
                str(value.get("kind", "")).casefold(),
                f"{key} {_text(value)}".casefold(),
            )
        )
    return records


class InterviewOutlineBuilder:
    """把分析器事实聚合为少量面试方向，不把代码标识符当作面试主题。"""

    max_directions = 5
    max_evidence_per_direction = 4

    @staticmethod
    def supports(project: ProjectKnowledge) -> bool:
        return any(
            isinstance(value, Mapping) and bool(str(value.get("kind", "")).strip())
            for value in project.evidence.values()
        )

    def build(self, project: ProjectKnowledge) -> list[Topic]:
        records = _evidence_records(project)
        project_text = _text(
            {
                "topics": [topic.name for topic in project.topics],
                "components": project.components,
                "dependencies": project.dependencies,
                "weaknesses": project.weaknesses,
                "evidence": project.evidence,
            }
        ).casefold()
        if not project_text.strip():
            return []

        directions = []
        for index, rule in enumerate(_RULES):
            matched = [
                evidence_id
                for evidence_id, kind, text in records
                if any(keyword in text for keyword in rule.keywords)
                or any(expected in kind for expected in rule.kinds)
            ]
            if index == 0:
                matched = [evidence_id for evidence_id, _, _ in records]
            supported = bool(matched) or any(
                keyword in project_text for keyword in rule.keywords
            )
            if index == 0:
                supported = bool(
                    project.topics
                    or project.components
                    or project.dependencies
                    or records
                )
            elif rule.name == "核心业务流程与数据流":
                supported = supported or bool(project.components or project.dependencies)
            if not supported:
                continue
            if not matched:
                matched = [evidence_id for evidence_id, _, _ in records]
            directions.append(
                Topic(
                    name=rule.name,
                    score=rule.score,
                    evidence=matched[: self.max_evidence_per_direction],
                )
            )
            if len(directions) == self.max_directions:
                break
        return directions


__all__ = ["InterviewOutlineBuilder"]
