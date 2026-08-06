"""Artifact Analyzer 插件边界。"""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..intelligence.models import UniversalProjectModel


@runtime_checkable
class ArtifactAnalyzer(Protocol):
    """把一种项目输入分析为 Universal Project Model 的适配器。"""

    analyzer_id: str

    def supports(self, structure: Any) -> bool:
        """返回该分析器是否支持给定的输入结构描述。"""

    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel:
        """分析输入根目录并返回可持久化的项目模型。"""


__all__ = ["ArtifactAnalyzer"]
