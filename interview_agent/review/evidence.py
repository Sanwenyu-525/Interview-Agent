from ..models import ProjectKnowledge, Topic


def contains_topic(text: str, topic_name: str) -> bool:
    normalized_text = str(text).casefold()
    normalized_topic = str(topic_name).casefold()
    return bool(normalized_topic) and (
        normalized_topic in normalized_text or normalized_text in normalized_topic
    )


def _fact(project: ProjectKnowledge, key: str) -> dict:
    fact = dict(project.evidence[key])
    fact_id = fact.get("id")
    fact["id"] = fact_id if fact_id in project.evidence else key
    return fact


def resolve_topic_evidence(
    project: ProjectKnowledge, topic: Topic
) -> tuple[dict, ...]:
    """按统一优先级解析主题事实，只返回 evidence 字典中真实存在的记录。"""

    for alias in (f"topic:{topic.name}", topic.name):
        if alias in project.evidence:
            return (_fact(project, alias),)

    facts = []
    seen_ids = set()
    for evidence_id in topic.evidence:
        if evidence_id not in project.evidence:
            continue
        fact = _fact(project, evidence_id)
        if fact["id"] in seen_ids:
            continue
        seen_ids.add(fact["id"])
        facts.append(fact)
    return tuple(facts)


def real_evidence_ids(
    project: ProjectKnowledge, evidence_ids: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """过滤返回结果中的 Ghost id，并保持原顺序和唯一性。"""

    result = []
    seen = set()
    for evidence_id in evidence_ids:
        if evidence_id in project.evidence and evidence_id not in seen:
            seen.add(evidence_id)
            result.append(evidence_id)
    return tuple(result)


def topic_component_match(project: ProjectKnowledge, topic: Topic) -> int:
    return int(
        any(
            contains_topic(name, topic.name) or contains_topic(description, topic.name)
            for name, description in project.components.items()
        )
    )


def topic_flow_match(project: ProjectKnowledge, topic: Topic) -> int:
    related_names = [
        name
        for source, targets in project.dependencies.items()
        for name in (source, *targets)
    ]
    return int(any(contains_topic(name, topic.name) for name in related_names))


def topic_signal(
    project: ProjectKnowledge, topic: Topic, keywords: tuple[str, ...]
) -> int:
    """Find a defense signal only in facts related to the selected topic."""

    context = [topic.name]
    context.extend(str(evidence_id) for evidence_id in topic.evidence)
    for fact in resolve_topic_evidence(project, topic):
        for key, value in fact.items():
            context.append(str(key))
            context.append(str(value))
    for name, description in project.components.items():
        if contains_topic(name, topic.name) or contains_topic(description, topic.name):
            context.extend((str(name), str(description)))
    for source, targets in project.dependencies.items():
        names = (source, *targets)
        if any(contains_topic(name, topic.name) for name in names):
            context.extend(str(name) for name in names)
    for weakness in project.weaknesses:
        if contains_topic(weakness, topic.name):
            context.append(str(weakness))

    normalized_context = " ".join(context).casefold()
    return int(any(keyword.casefold() in normalized_context for keyword in keywords))


__all__ = [
    "contains_topic",
    "real_evidence_ids",
    "resolve_topic_evidence",
    "topic_component_match",
    "topic_flow_match",
    "topic_signal",
]
