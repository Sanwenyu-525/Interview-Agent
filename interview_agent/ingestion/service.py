"""项目输入编排，不包含项目解析或面试领域逻辑。"""

from dataclasses import dataclass
from pathlib import Path

from .security import ensure_within, normalize_project_id
from .sources import ProjectSource
from .workspace import Workspace, WorkspaceManager


@dataclass(frozen=True)
class IngestionResult:
    project_id: int
    project_root: Path
    source_info: dict[str, str | int]
    workspace: Workspace


class IngestionService:
    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()

    def ingest(self, project_id: int | str, source: ProjectSource) -> IngestionResult:
        normalized_project_id = normalize_project_id(project_id)
        if not isinstance(source, ProjectSource):
            raise TypeError("source must implement ProjectSource")

        workspace = self.workspace_manager.create_workspace(normalized_project_id)
        project_root = ensure_within(
            Path(source.prepare(workspace.source)),
            workspace.source,
            label="prepared project root",
        )
        if not project_root.is_dir():
            raise ValueError("prepared project root must be inside the workspace source directory")
        return IngestionResult(
            project_id=normalized_project_id,
            project_root=project_root,
            source_info={
                "source_type": source.source_type,
                "project_id": normalized_project_id,
                "project_root": str(project_root),
            },
            workspace=workspace,
        )


__all__ = ["IngestionResult", "IngestionService"]
