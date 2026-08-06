"""Project Intelligence Engine 的领域模型。

这些模型描述分析器输出的项目事实，不依赖具体评审领域或输入类型。
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..models import ProjectKnowledge, Topic


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def _json_safe(value: Any) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    try:
        return str(value)
    except Exception:
        return f"<{type(value).__name__}>"


@dataclass(frozen=True)
class ProjectIdentity:
    name: str
    artifact_type: str = ""
    goal: str = ""
    description: str = ""


@dataclass(frozen=True)
class StructureNode:
    id: str
    name: str
    kind: str = ""
    path: str = ""
    parent_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Technology:
    name: str
    category: str = ""
    version: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Evidence:
    id: str
    source_path: str
    locator: str
    excerpt: str
    kind: str
    confidence: float
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "metadata", _json_safe(self.metadata))


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    kind: str = ""
    description: str = ""
    path: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Relation:
    source_id: str
    target_id: str
    kind: str
    description: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Flow:
    id: str
    name: str
    description: str = ""
    component_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Insight:
    id: str
    kind: str
    summary: str
    topic: str = ""
    score: int = 0
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectTopic:
    name: str
    score: int
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UniversalProjectModel:
    """分析器输出的、与语言和评审领域无关的项目模型。"""

    project_id: int
    identity: ProjectIdentity
    structure: list[StructureNode] = field(default_factory=list)
    technologies: list[Technology] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    topics: list[ProjectTopic] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.evidence, list):
            raise TypeError("UniversalProjectModel.evidence must be list[Evidence]")
        if any(not isinstance(item, Evidence) for item in self.evidence):
            raise TypeError("UniversalProjectModel.evidence must be list[Evidence]")
        evidence_ids = [item.id for item in self.evidence]
        duplicate_evidence_ids = {
            evidence_id for evidence_id in evidence_ids if evidence_ids.count(evidence_id) > 1
        }
        if duplicate_evidence_ids:
            raise ValueError(
                f"duplicate Evidence.id: {sorted(duplicate_evidence_ids)[0]}"
            )

        component_names = [component.name or component.id for component in self.components]
        duplicate_component_names = {
            name for name in component_names if component_names.count(name) > 1
        }
        if duplicate_component_names:
            raise ValueError(
                f"duplicate component name: {sorted(duplicate_component_names)[0]}"
            )
        object.__setattr__(self, "metadata", _json_safe(self.metadata))


# Short names keep the model convenient for analyzer adapters while retaining
# explicit names in the public API.
Identity = ProjectIdentity
Structure = StructureNode


def _evidence_to_dicts(evidence: list[Evidence]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in evidence:
        if not isinstance(item, Evidence):
            raise TypeError("UniversalProjectModel.evidence must be list[Evidence]")
        normalized_id = item.id
        if normalized_id in result:
            raise ValueError(f"duplicate Evidence.id: {normalized_id}")
        result[normalized_id] = _json_safe(asdict(item))
    return result


def _topics_from_model(model: UniversalProjectModel) -> list[Topic]:
    topics = model.topics
    if not topics:
        topics = [
            ProjectTopic(
                name=insight.topic,
                score=insight.score,
                evidence_ids=insight.evidence_ids,
            )
            for insight in model.insights
            if insight.topic
        ]
    return [
        Topic(name=topic.name, score=topic.score, evidence=list(topic.evidence_ids))
        for topic in topics
    ]


def _dependencies_from_model(model: UniversalProjectModel) -> dict[str, list[str]]:
    dependencies = {source: list(targets) for source, targets in model.dependencies.items()}
    dependency_kinds = {"dependency", "depends_on", "depends", "uses"}
    for relation in model.relations:
        kind = relation.kind.lower().replace("-", "_").replace(" ", "_")
        if kind not in dependency_kinds:
            continue
        targets = dependencies.setdefault(relation.source_id, [])
        if relation.target_id not in targets:
            targets.append(relation.target_id)
    return dependencies


def project_model_to_knowledge(model: UniversalProjectModel) -> ProjectKnowledge:
    """将 Universal Project Model 转换为当前面试流程使用的旧模型。"""

    topics = _topics_from_model(model)
    evidence = _evidence_to_dicts(model.evidence)
    topic_aliases = {}
    for topic in topics:
        if not topic.evidence:
            if topic.name in evidence:
                raise ValueError(
                    f"topic {topic.name!r} must map to exactly one evidence id"
                )
            continue
        if len(topic.evidence) != 1 or topic.evidence[0] not in evidence:
            raise ValueError(
                f"topic {topic.name!r} must map to exactly one evidence id"
            )

        evidence_id = topic.evidence[0]
        if topic.name in topic_aliases:
            if topic_aliases[topic.name] != evidence_id:
                raise ValueError(f"topic {topic.name!r} has conflicting evidence ids")
            continue

        alias = topic.name if topic.name not in evidence else f"topic:{topic.name}"
        if alias in evidence:
            raise ValueError(f"cannot create topic evidence alias: {alias}")
        evidence[alias] = evidence[evidence_id]
        topic_aliases[topic.name] = evidence_id

    components = {}
    for component in model.components:
        component_name = component.name or component.id
        if component_name in components:
            raise ValueError(f"duplicate component name: {component_name}")
        components[component_name] = component.path or component.description
    weaknesses = [
        insight.summary
        for insight in model.insights
        if insight.kind.lower() in {"weakness", "risk", "gap"}
    ]
    return ProjectKnowledge(
        project_id=model.project_id,
        project_name=model.identity.name,
        topics=topics,
        components=components,
        evidence=evidence,
        dependencies=_dependencies_from_model(model),
        weaknesses=weaknesses,
    )


__all__ = [
    "Component",
    "Evidence",
    "Flow",
    "Identity",
    "Insight",
    "ProjectIdentity",
    "ProjectTopic",
    "Relation",
    "Structure",
    "StructureNode",
    "Technology",
    "UniversalProjectModel",
    "project_model_to_knowledge",
]
