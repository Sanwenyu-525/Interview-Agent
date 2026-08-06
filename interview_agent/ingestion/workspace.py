"""项目输入与分析结果使用的隔离工作区。"""

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .security import (
    is_link_like,
    normalize_project_id,
    path_exists,
    prepare_target,
    validate_target_path,
)


@dataclass(frozen=True)
class Workspace:
    project_id: int
    root: Path
    source: Path
    analysis: Path

    @property
    def project_root(self) -> Path:
        return self.source

    @property
    def source_dir(self) -> Path:
        return self.source

    @property
    def analysis_dir(self) -> Path:
        return self.analysis


class WorkspaceManager:
    """创建 workspace/projects/{project_id}/source 和 analysis。"""

    def __init__(self, workspace_root: Path = Path("workspace")) -> None:
        root_path, safe_root = validate_target_path(workspace_root)
        if not root_path.resolve().is_relative_to(safe_root):
            raise ValueError("workspace root escapes its allowed directory")
        if path_exists(root_path) and (is_link_like(root_path) or not root_path.is_dir()):
            raise ValueError("workspace root must be a real directory")
        self.workspace_root = root_path

    def create_workspace(self, project_id: int | str) -> Workspace:
        normalized_project_id = normalize_project_id(project_id)
        project_name = str(normalized_project_id)
        windows_name = PureWindowsPath(project_name)
        if windows_name.is_absolute() or windows_name.drive or len(windows_name.parts) != 1:
            raise ValueError("project_id must be a single path component")

        projects = prepare_target(self.workspace_root / "projects")
        projects.mkdir(parents=True, exist_ok=True)
        project_root = prepare_target(projects / project_name)
        project_root.mkdir(parents=True, exist_ok=True)
        source = prepare_target(project_root / "source")
        source.mkdir(parents=True, exist_ok=True)
        analysis = prepare_target(project_root / "analysis")
        analysis.mkdir(parents=True, exist_ok=True)
        return Workspace(
            project_id=normalized_project_id,
            root=project_root,
            source=source,
            analysis=analysis,
        )


__all__ = ["Workspace", "WorkspaceManager"]
