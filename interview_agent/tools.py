from .models import ProjectKnowledge, Topic
from .repository import InMemoryProjectRepository
from .review.evidence import resolve_topic_evidence


class ProjectTools:
    """Agent 可调用的项目证据查询工具。"""

    def __init__(self, repository: InMemoryProjectRepository):
        self.repository = repository

    def _project(self, project_id: int) -> ProjectKnowledge:
        return self.repository.get(project_id)

    def search_component(self, project_id: int, name: str) -> dict[str, str] | None:
        project = self._project(project_id)
        file_path = project.components.get(name)
        return {"name": name, "file": file_path} if file_path else None

    def get_component(self, project_id: int, name: str) -> dict[str, str] | None:
        return self.search_component(project_id, name)

    def get_evidence(
        self,
        project_id: int,
        topic: str | None = None,
        *,
        evidence_id: str | None = None,
    ) -> dict | None:
        if evidence_id is not None:
            return self.get_evidence_by_id(project_id, evidence_id)
        if topic is None:
            return None
        return self.get_evidence_by_topic(project_id, topic)

    def get_evidence_by_id(self, project_id: int, evidence_id: str) -> dict | None:
        return self._project(project_id).evidence.get(evidence_id)

    def get_evidence_by_topic(self, project_id: int, topic: str) -> dict | None:
        """单条兼容查询：返回统一优先级下的第一条事实。"""

        project = self._project(project_id)
        facts = self.get_evidence_list_by_topic(project_id, topic)
        if not facts:
            return None
        raw_fact = None
        for alias in (f"topic:{topic}", topic):
            if alias in project.evidence:
                raw_fact = project.evidence[alias]
                break
        if raw_fact is None:
            project_topic = next(
                (item for item in project.topics if item.name == topic),
                None,
            )
            for evidence_id in project_topic.evidence if project_topic else ():
                if evidence_id in project.evidence:
                    raw_fact = project.evidence[evidence_id]
                    break
        if raw_fact is not None and "id" not in raw_fact:
            return {key: value for key, value in facts[0].items() if key != "id"}
        return facts[0]

    def get_evidence_list_by_topic(self, project_id: int, topic: str) -> list[dict]:
        project = self._project(project_id)
        project_topic = next(
            (item for item in project.topics if item.name == topic),
            Topic(name=topic, score=0),
        )
        return [dict(fact) for fact in resolve_topic_evidence(project, project_topic)]

    def query_evidence(
        self,
        project_id: int,
        *,
        evidence_id: str | None = None,
        topic: str | None = None,
    ) -> dict | None:
        return self.get_evidence(project_id, topic, evidence_id=evidence_id)

    def get_dependency_graph(self, project_id: int, component: str) -> list[str]:
        return self._project(project_id).dependencies.get(component, [])

    def get_relation(
        self, project_id: int, source: str, target: str | None = None
    ) -> list[dict[str, str]] | dict[str, str] | None:
        targets = self._project(project_id).dependencies.get(source, [])
        if target is not None:
            return {"source": source, "target": target} if target in targets else None
        return [{"source": source, "target": item} for item in targets]

    def get_relations(self, project_id: int, source: str) -> list[dict[str, str]]:
        return self.get_relation(project_id, source) or []

    def get_candidate_weakness(self, project_id: int) -> list[str]:
        return list(self._project(project_id).weaknesses)
