"""确定性的项目文件结构扫描。"""

import json
from pathlib import Path
from collections.abc import Iterator


_LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".kt": "kotlin",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".xml": "xml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".properties": "properties",
    ".gradle": "gradle",
    ".md": "markdown",
}

_CONFIG_NAMES = {
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "application.yml",
    "application.yaml",
    "application.properties",
    "bootstrap.yml",
    "bootstrap.yaml",
    "bootstrap.properties",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}
IGNORED_DIRS = frozenset({"target", "build", ".gradle", "out", "node_modules"})


def is_ignored_path(relative_path: str | Path) -> bool:
    """Return whether a relative project file is under a shared ignored directory."""
    path = Path(relative_path)
    return any(part.casefold() in IGNORED_DIRS for part in path.parts[:-1])


def _root_package_json_type(root: Path, files: list[str]) -> str | None:
    root_package = next(
        (
            relative_path
            for relative_path in files
            if len(Path(relative_path).parts) == 1
            and Path(relative_path).name.casefold() == "package.json"
        ),
        None,
    )
    if root_package is None:
        return None
    package_path = root / root_package
    try:
        value = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_json"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


class ProjectScanner:
    """收集文件结构事实，不读取源码语义，也不生成评审策略。"""

    @staticmethod
    def scan(root: Path) -> dict[str, object]:
        project_root = Path(root)
        if not project_root.is_dir():
            raise ValueError("scan root must be a directory")

        project_files = list(iter_project_files(project_root))
        files = sorted(
            (path.relative_to(project_root).as_posix() for path in project_files),
            key=str.casefold,
        )
        language_counts: dict[str, int] = {}
        for relative_path in files:
            suffix = Path(relative_path).suffix.lower()
            language = _LANGUAGE_BY_SUFFIX.get(suffix)
            if language:
                language_counts[language] = language_counts.get(language, 0) + 1

        root_file_names = {
            Path(relative_path).name.lower()
            for relative_path in files
            if len(Path(relative_path).parts) == 1
        }
        if "pom.xml" in root_file_names:
            build_tool = "maven"
            build_file = next(
                relative_path
                for relative_path in files
                if len(Path(relative_path).parts) == 1
                and Path(relative_path).name.lower() == "pom.xml"
            )
        elif {"build.gradle", "build.gradle.kts"} & root_file_names:
            build_tool = "gradle"
            build_file = next(
                relative_path
                for relative_path in files
                if len(Path(relative_path).parts) == 1
                and Path(relative_path).name.lower() in {"build.gradle", "build.gradle.kts"}
            )
        else:
            build_tool = None
            build_file = None

        java_source_roots = ProjectScanner._find_java_source_roots(project_root, files)
        config_files = [
            relative_path
            for relative_path in files
            if ProjectScanner._is_config_file(relative_path)
        ]
        root_package_json_type = _root_package_json_type(project_root, files)
        return {
            "build_tool": build_tool,
            "build_file": build_file,
            "language_counts": language_counts,
            "java_source_roots": java_source_roots,
            "config_files": config_files,
            "file_count": len(files),
            "files": files,
            "root_package_json_type": root_package_json_type,
            "manifest_status": (
                None
                if root_package_json_type is None
                else "valid"
                if root_package_json_type == "object"
                else "invalid_json"
                if root_package_json_type == "invalid_json"
                else "invalid_shape"
            ),
        }

    @staticmethod
    def _find_java_source_roots(root: Path, files: list[str]) -> list[str]:
        java_files = [Path(relative_path) for relative_path in files if relative_path.lower().endswith(".java")]
        candidates = set()
        for path in java_files:
            lower_parts = [part.casefold() for part in path.parts]
            if "java" not in lower_parts:
                continue
            java_index = lower_parts.index("java")
            candidates.add(Path(*path.parts[: java_index + 1]).as_posix())
        return sorted(
            {
                candidate
                for candidate in candidates
                if candidate.casefold().endswith("/java")
                or candidate.casefold() == "java"
            }
        )

    @staticmethod
    def _is_config_file(relative_path: str) -> bool:
        path = Path(relative_path)
        name = path.name.lower()
        return (
            name in _CONFIG_NAMES
            or name.startswith("application.")
            or name.startswith("bootstrap.")
            or name.startswith("docker-compose.")
        )


def iter_project_files(root: Path) -> Iterator[Path]:
    """Yield source files once using the scanner's canonical ignore policy."""
    project_root = Path(root)
    if not project_root.is_dir():
        raise ValueError("scan root must be a directory")
    paths = sorted(
        (
            path
            for path in project_root.rglob("*")
            if path.is_file()
            and not is_ignored_path(path.relative_to(project_root))
        ),
        key=lambda path: path.relative_to(project_root).as_posix().casefold(),
    )
    return iter(paths)

__all__ = ["IGNORED_DIRS", "ProjectScanner", "is_ignored_path", "iter_project_files"]
