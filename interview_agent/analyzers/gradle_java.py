"""Gradle Java 项目分析器。"""

from .java import JavaAnalyzer


class GradleJavaAnalyzer(JavaAnalyzer):
    """Analyze Gradle Java projects with the shared Java/Spring fact rules."""

    analyzer_id = "gradle-java"

    def supports(self, structure: object) -> bool:
        if not isinstance(structure, dict):
            return False
        if structure.get("build_tool") != "gradle":
            return False
        language_counts = structure.get("language_counts")
        java_count = language_counts.get("java") if isinstance(language_counts, dict) else None
        return isinstance(java_count, int) and not isinstance(java_count, bool) and java_count > 0


__all__ = ["GradleJavaAnalyzer"]
