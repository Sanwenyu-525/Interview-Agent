"""Minimal, evidence-first Python project analyzer adapter."""

import ast
import hashlib
import re
from pathlib import Path

from ..intelligence.models import (
    Component,
    Evidence,
    Flow,
    ProjectIdentity,
    StructureNode,
    Technology,
    UniversalProjectModel,
)
from .scanner import ProjectScanner, is_ignored_path, iter_project_files


_DEPENDENCY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
)
def _safe_id(value: str) -> str:
    raw_value = str(value)
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_value).strip("-") or "item"
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


def _line_excerpt(path: Path, line_number: int) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()[:240]
    return ""


def _first_content_line(path: Path) -> tuple[int, str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_number, line in enumerate(lines, 1):
        if line.strip() and not line.lstrip().startswith("#"):
            return line_number, line.strip()[:240]
    return 1, ""


def _module_name(relative_path: str) -> str:
    path = Path(relative_path)
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or path.stem


def _unique_component_name(
    name: str,
    source_path: str,
    module: str,
    line: int,
    column: int,
    used_names: set[str],
) -> str:
    candidates = (
        name,
        f"{module}.{name}",
        f"{source_path}:{name}:line:{line}:col:{column}",
    )
    for candidate in candidates:
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
    occurrence = 2
    while True:
        candidate = f"{source_path}:{name}:line:{line}:col:{column}:occurrence:{occurrence}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        occurrence += 1


def _requirements(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        value = line.split("#", 1)[0].strip()
        if not value or value.startswith(("-", "git+", "http:")):
            continue
        name = re.split(r"[<>=!~;\[\s]", value, maxsplit=1)[0].strip()
        if name and name not in result:
            result.append(name)
    return result


def _pyproject_requirements(text: str) -> list[str]:
    matches = re.findall(r"dependencies\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
    values = []
    for block in matches:
        values.extend(re.findall(r"[\"']([^\"']+)[\"']", block))
    return _requirements("\n".join(values))


def _setup_requirements(text: str) -> list[str]:
    matches = re.findall(r"install_requires\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
    values = []
    for block in matches:
        values.extend(re.findall(r"[\"']([^\"']+)[\"']", block))
    return _requirements("\n".join(values))


def _setup_cfg_requirements(text: str) -> list[str]:
    match = re.search(
        r"(?im)^\s*install_requires\s*=\s*\n((?:^[ \t]+.*\n?)+)", text
    )
    return _requirements(match.group(1) if match else "")


class PythonAnalyzer:
    """Analyze Python structure without producing domain-specific questions."""

    analyzer_id = "python"

    def supports(self, structure: object) -> bool:
        if not isinstance(structure, dict):
            return False
        files = structure.get("files")
        if not isinstance(files, list):
            return False
        root_files = [Path(str(item)) for item in files if len(Path(str(item)).parts) == 1]
        root_names = {item.name.casefold() for item in root_files}
        has_python_source = any(
            Path(str(item)).suffix.casefold() == ".py"
            and not is_ignored_path(str(item))
            for item in files
        )
        return has_python_source and "package.json" not in root_names

    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel:
        if isinstance(project_id, bool) or not isinstance(project_id, int):
            raise TypeError("project_id must be int")
        root = Path(artifact_root)
        structure = ProjectScanner.scan(root)
        if not self.supports(structure):
            raise ValueError(
                "PythonAnalyzer supports Python projects without package.json; "
                f"scanner found: {structure!r}"
            )

        evidence: list[Evidence] = []
        evidence_ids: dict[tuple[str, str], str] = {}

        def add_evidence(kind: str, source_path: str, locator: str, excerpt: str) -> str:
            key = (kind, source_path + ":" + locator)
            if key not in evidence_ids:
                identifier = f"e-python-{_safe_id(kind)}-{_safe_id(source_path)}-{_safe_id(locator)}"
                evidence_ids[key] = identifier
                evidence.append(
                    Evidence(
                        id=identifier,
                        source_path=source_path,
                        locator=locator,
                        excerpt=excerpt[:240],
                        kind=kind,
                        confidence=0.9,
                    )
                )
            return evidence_ids[key]

        source_files = [
            path
            for path in iter_project_files(root)
            if path.suffix.casefold() == ".py"
            and not is_ignored_path(path.relative_to(root))
        ]
        components: list[Component] = []
        structure_nodes: list[StructureNode] = []
        entrypoints: list[str] = []
        entrypoint_evidence: dict[str, str] = {}
        used_component_names: set[str] = set()
        for path in source_files:
            relative = path.relative_to(root).as_posix()
            module = _module_name(relative)
            source_line, source_excerpt = _first_content_line(path)
            source_evidence = add_evidence(
                "python_source", relative, f"line {source_line}", source_excerpt
            )
            structure_nodes.append(
                StructureNode(
                    id=f"module:{relative}",
                    name=module,
                    kind="module",
                    path=relative,
                    evidence_ids=[source_evidence],
                )
            )
            source_text = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source_text)
            except SyntaxError as exc:
                line_number = exc.lineno or 1
                raise ValueError(
                    f"PythonAnalyzer failed to parse {relative} at line {line_number}: {exc.msg}"
                ) from exc
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                name = node.name
                display_name = _unique_component_name(
                    name,
                    relative,
                    module,
                    node.lineno,
                    node.col_offset,
                    used_component_names,
                )
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                entrypoint_id = ""
                if name == "main":
                    kind = "entrypoint"
                    entrypoint_id = (
                        f"entrypoint:{relative}:line:{node.lineno}:col:{node.col_offset}"
                    )
                    entrypoints.append(entrypoint_id)
                locator = f"line {node.lineno} ({name})"
                item_evidence = add_evidence(
                    "python_symbol", relative, locator, _line_excerpt(path, node.lineno)
                )
                if kind == "entrypoint":
                    entrypoint_evidence[entrypoint_id] = item_evidence
                components.append(
                    Component(
                        id=f"component:{relative}:{name}:line:{node.lineno}:col:{node.col_offset}",
                        name=display_name,
                        kind=kind,
                        path=relative,
                        evidence_ids=[item_evidence],
                    )
                )
            main_guard = next((
                node for node in tree.body
                if (
                    isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and any(
                        isinstance(part, ast.Constant) and part.value == "__main__"
                        for part in ast.walk(node.test)
                    )
                )
            ), None)
            if (
                main_guard is not None
            ):
                entrypoint_id = (
                    f"entrypoint:{relative}:line:{main_guard.lineno}:col:{main_guard.col_offset}"
                )
                guard_evidence = add_evidence(
                    "python_entrypoint",
                    relative,
                    f"line {main_guard.lineno} (__main__)",
                    _line_excerpt(path, main_guard.lineno),
                )
                entrypoints.append(entrypoint_id)
                entrypoint_evidence[entrypoint_id] = guard_evidence
                components.append(
                    Component(
                        id=f"component:{relative}:__main__:line:{main_guard.lineno}:col:{main_guard.col_offset}",
                        name=_unique_component_name(
                            "__main__",
                            relative,
                            module,
                            main_guard.lineno,
                            main_guard.col_offset,
                            used_component_names,
                        ),
                        kind="entrypoint",
                        path=relative,
                        evidence_ids=[guard_evidence],
                    )
                )

        dependencies: dict[str, list[str]] = {}
        dependency_files: list[str] = []
        technologies: list[Technology] = []
        for dependency_name in _DEPENDENCY_FILES:
            path = root / dependency_name
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            dependency_files.append(relative)
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.name.casefold() == "pyproject.toml":
                packages = _pyproject_requirements(text)
            elif path.name.casefold() == "setup.py":
                packages = _setup_requirements(text)
            elif path.name.casefold() == "setup.cfg":
                packages = _setup_cfg_requirements(text)
            else:
                packages = _requirements(text)
            dependencies[relative] = packages
            dependency_line, dependency_excerpt = _first_content_line(path)
            file_evidence = add_evidence(
                "python_dependency",
                relative,
                f"line {dependency_line}",
                dependency_excerpt,
            )
            structure_nodes.append(
                StructureNode(
                    id=f"dependency-file:{relative}",
                    name=relative,
                    kind="dependency_file",
                    path=relative,
                    evidence_ids=[file_evidence],
                )
            )
            for package in packages:
                technologies.append(
                    Technology(
                        name=package,
                        category="python_dependency",
                        evidence_ids=[file_evidence],
                    )
                )

        flows = []
        if entrypoints:
            flows.append(
                Flow(
                    id="python-entrypoint",
                    name="Python entrypoint",
                    description="Detected executable entrypoint(s).",
                    component_ids=[component.id for component in components if component.kind == "entrypoint"],
                    evidence_ids=[entrypoint_evidence[entrypoint] for entrypoint in entrypoints],
                )
            )

        return UniversalProjectModel(
            project_id=project_id,
            identity=ProjectIdentity(
                name=root.name,
                artifact_type="python_project",
                description="Python project structure and dependency facts.",
            ),
            structure=structure_nodes,
            technologies=technologies,
            components=components,
            flows=flows,
            evidence=evidence,
            dependencies=dependencies,
            metadata={
                "analyzer": self.analyzer_id,
                "source_files": [path.relative_to(root).as_posix() for path in source_files],
                "dependency_files": dependency_files,
                "entrypoints": entrypoints,
            },
        )


__all__ = ["PythonAnalyzer"]
