"""Artifact analyzer 注册与确定性选择。"""

from collections.abc import Iterable

from .base import ArtifactAnalyzer


class AnalyzerRegistry:
    def __init__(self, analyzers: Iterable[ArtifactAnalyzer] | None = None) -> None:
        self._analyzers: dict[str, ArtifactAnalyzer] = {}
        for analyzer in analyzers or ():
            self.register(analyzer)

    @classmethod
    def with_defaults(cls) -> "AnalyzerRegistry":
        """Return a registry with the built-in project analyzers."""
        from .frontend import FrontendAnalyzer
        from .gradle_java import GradleJavaAnalyzer
        from .java import JavaAnalyzer
        from .python import PythonAnalyzer

        return cls([JavaAnalyzer(), GradleJavaAnalyzer(), PythonAnalyzer(), FrontendAnalyzer()])

    def register(self, analyzer: ArtifactAnalyzer) -> None:
        analyzer_id = getattr(analyzer, "analyzer_id", "")
        if not isinstance(analyzer_id, str) or not analyzer_id:
            raise ValueError("analyzer must define a non-empty analyzer_id")
        if not callable(getattr(analyzer, "supports", None)) or not callable(
            getattr(analyzer, "analyze", None)
        ):
            raise TypeError("analyzer must implement supports() and analyze()")
        if analyzer_id in self._analyzers:
            raise ValueError(f"analyzer already registered: {analyzer_id}")
        self._analyzers[analyzer_id] = analyzer

    def select(self, structure: object) -> ArtifactAnalyzer:
        matches = [
            analyzer
            for analyzer in self._analyzers.values()
            if analyzer.supports(structure)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            analyzer_ids = ", ".join(analyzer.analyzer_id for analyzer in matches)
            raise ValueError(f"Multiple analyzers support scanner structure: {analyzer_ids}")
        raise LookupError(f"No analyzer supports scanner structure: {structure!r}")

    def get(self, analyzer_id: str) -> ArtifactAnalyzer:
        try:
            return self._analyzers[analyzer_id]
        except KeyError as exc:
            raise LookupError(f"Unknown analyzer: {analyzer_id}") from exc


__all__ = ["AnalyzerRegistry"]
