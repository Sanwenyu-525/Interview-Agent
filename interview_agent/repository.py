from .models import ProjectKnowledge


class InMemoryProjectRepository:
    """开发和测试用的项目知识仓库；生产环境可替换为 PostgreSQL 实现。"""

    def __init__(self, projects: dict[int, ProjectKnowledge] | None = None):
        self._projects = projects or {}

    def get(self, project_id: int) -> ProjectKnowledge:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise KeyError(f"项目不存在: {project_id}") from exc

    def save(self, project: ProjectKnowledge) -> None:
        self._projects[project.project_id] = project

    def list(self) -> list[ProjectKnowledge]:
        return [self._projects[key] for key in sorted(self._projects)]

    def delete(self, project_id: int) -> None:
        self._projects.pop(project_id, None)
