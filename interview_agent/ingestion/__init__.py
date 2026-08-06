"""项目输入准备与工作区管理。"""

from .service import IngestionResult, IngestionService
from .sources import (
    FolderFile,
    FolderSource,
    ProjectSource,
    ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE,
    ZIP_DESCRIPTOR_DEFAULT_MAX_FILES,
    ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE,
    ZipSource,
)
from .workspace import Workspace, WorkspaceManager

__all__ = [
    "FolderFile",
    "FolderSource",
    "IngestionResult",
    "IngestionService",
    "ProjectSource",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_FILES",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE",
    "Workspace",
    "WorkspaceManager",
    "ZipSource",
]
