"""Minimal, evidence-first JavaScript/TypeScript project analyzer adapter."""

import json
import hashlib
import re
from pathlib import Path

from ..intelligence.models import (
    Component,
    Evidence,
    Flow,
    ProjectIdentity,
    Relation,
    StructureNode,
    Technology,
    UniversalProjectModel,
)
from .scanner import ProjectScanner, is_ignored_path, iter_project_files


_SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_BUILD_TOOLS = ("vite", "webpack", "rollup", "parcel", "next", "esbuild", "gulp")


def _safe_id(value: str) -> str:
    raw_value = str(value)
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_value).strip("-") or "item"
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


def _excerpt(text: str, start: int = 0) -> str:
    for line in text[start:].splitlines():
        if line.strip() and not line.lstrip().startswith(("//", "/*", "*")):
            return line.strip()[:240]
    return ""


def _unique_component_name(
    name: str,
    source_path: str,
    line: int,
    offset: int,
    used_names: set[str],
) -> str:
    candidates = (
        name,
        f"{source_path}:{name}:line:{line}:offset:{offset}",
    )
    for candidate in candidates:
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
    occurrence = 2
    while True:
        candidate = f"{source_path}:{name}:line:{line}:offset:{offset}:occurrence:{occurrence}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        occurrence += 1


class FrontendAnalyzer:
    """Analyze generic JS/TS project facts without importing a UI framework."""

    analyzer_id = "frontend"

    def supports(self, structure: object) -> bool:
        if not isinstance(structure, dict):
            return False
        files = structure.get("files")
        if not isinstance(files, list):
            return False
        manifest_status = structure.get("manifest_status")
        if manifest_status is not None and manifest_status != "valid":
            return False
        manifest_type = structure.get("root_package_json_type")
        if manifest_type is not None and manifest_type != "object":
            return False
        root_files = [Path(str(item)) for item in files if len(Path(str(item)).parts) == 1]
        has_root_package = any(item.name.casefold() == "package.json" for item in root_files)
        source_files = [
            Path(str(item))
            for item in files
            if Path(str(item)).suffix.casefold() in _SOURCE_SUFFIXES
            and not is_ignored_path(str(item))
        ]
        return has_root_package and bool(source_files)

    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel:
        if isinstance(project_id, bool) or not isinstance(project_id, int):
            raise TypeError("project_id must be int")
        root = Path(artifact_root)
        structure = ProjectScanner.scan(root)
        if not self.supports(structure):
            if structure.get("manifest_status") == "invalid_json":
                raise ValueError(
                    "FrontendAnalyzer found root package.json invalid JSON: "
                    f"{root / 'package.json'}"
                )
            if structure.get("manifest_status") == "invalid_shape":
                raise ValueError(
                    "FrontendAnalyzer requires root package.json top-level object: "
                    f"{root / 'package.json'}"
                )
            raise ValueError(
                "FrontendAnalyzer supports package.json projects with JS/TS files; "
                f"scanner found: {structure!r}"
            )

        evidence: list[Evidence] = []
        evidence_ids: dict[tuple[str, str], str] = {}

        def add_evidence(kind: str, source_path: str, locator: str, excerpt: str) -> str:
            key = (kind, source_path + ":" + locator)
            if key not in evidence_ids:
                identifier = f"e-frontend-{_safe_id(kind)}-{_safe_id(source_path)}-{_safe_id(locator)}"
                evidence_ids[key] = identifier
                evidence.append(
                    Evidence(
                        id=identifier,
                        source_path=source_path,
                        locator=locator,
                        excerpt=excerpt[:240],
                        kind=kind,
                        confidence=0.86,
                    )
                )
            return evidence_ids[key]

        package_path = root / "package.json"
        package_text = package_path.read_text(encoding="utf-8", errors="replace")
        try:
            package = json.loads(package_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"FrontendAnalyzer found package.json invalid JSON: {package_path}"
            ) from exc
        if not isinstance(package, dict):
            raise ValueError(
                "FrontendAnalyzer requires package.json top-level object: "
                f"{package_path}"
            )
        package_evidence = add_evidence(
            "frontend_manifest", "package.json", "manifest", _excerpt(package_text)
        )

        dependencies = {}
        all_packages = {}
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            values = package.get(section, {})
            if isinstance(values, dict):
                dependencies[section] = sorted(str(name) for name in values)
                all_packages.update({str(name): str(version) for name, version in values.items()})

        scripts = package.get("scripts", {})
        script_text = " ".join(str(value) for value in scripts.values()) if isinstance(scripts, dict) else ""
        build_tool = next(
            (name for name in _BUILD_TOOLS if name in all_packages or re.search(rf"\b{name}\b", script_text)),
            "",
        )
        technologies = [
            Technology(name=name, category="frontend_dependency", version=version, evidence_ids=[package_evidence])
            for name, version in sorted(all_packages.items())
        ]
        if build_tool and build_tool not in all_packages:
            technologies.append(
                Technology(name=build_tool, category="build_tool", evidence_ids=[package_evidence])
            )

        structure_nodes = [
            StructureNode(
                id="manifest:package.json",
                name="package.json",
                kind="manifest",
                path="package.json",
                evidence_ids=[package_evidence],
            )
        ]
        components: list[Component] = []
        relations: list[Relation] = []
        flows: list[Flow] = []
        used_names: set[str] = set()
        source_paths = []
        api_relation_keys: set[tuple[str, str]] = set()
        for path in iter_project_files(root):
            if (
                path.suffix.casefold() not in _SOURCE_SUFFIXES
                or is_ignored_path(path.relative_to(root))
            ):
                continue
            relative = path.relative_to(root).as_posix()
            source_paths.append(relative)
            text = path.read_text(encoding="utf-8", errors="replace")
            source_evidence = add_evidence("frontend_source", relative, "file", _excerpt(text))
            structure_nodes.append(
                StructureNode(
                    id=f"source:{relative}",
                    name=relative,
                    kind="source_file",
                    path=relative,
                    evidence_ids=[source_evidence],
                )
            )

            component_matches = re.finditer(
                r"(?:export\s+)?(?:default\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|"
                r"(?:export\s+)?(?:const|let|var)\s+([A-Z][A-Za-z0-9_$]*)\s*=",
                text,
            )
            for match in component_matches:
                name = match.group(1) or match.group(2)
                line = text.count(chr(10), 0, match.start()) + 1
                display_name = _unique_component_name(
                    name, relative, line, match.start(), used_names
                )
                locator = f"offset {match.start()} ({name})"
                item_evidence = add_evidence(
                    "frontend_component", relative, locator, _excerpt(text, match.start())
                )
                components.append(
                    Component(
                        id=(
                            f"component:{relative}:{name}:line:"
                            f"{text.count(chr(10), 0, match.start()) + 1}:offset:{match.start()}"
                        ),
                        name=display_name,
                        kind="component",
                        path=relative,
                        evidence_ids=[item_evidence],
                    )
                )

            for match in re.finditer(r"(?:path|route)\s*[:=]\s*[\"']([^\"']+)", text, re.IGNORECASE):
                route = match.group(1)
                route_evidence = add_evidence(
                    "frontend_route", relative, f"offset {match.start()}", _excerpt(text, match.start())
                )
                route_id = _safe_id(
                    f"{relative}:line:{text.count(chr(10), 0, match.start()) + 1}:"
                    f"offset:{match.start()}:route:{route}"
                )
                flows.append(
                    Flow(
                        id=f"route:{route_id}",
                        name=route,
                        description="Detected frontend route.",
                        evidence_ids=[route_evidence],
                    )
                )

            for match in re.finditer(
                r"(?:fetch|axios\.(?:get|post|put|delete|patch)|\b(?:get|post|put|delete)\s*\()\s*\(?\s*[\"'`]([^\"'`]+)",
                text,
                re.IGNORECASE,
            ):
                target = match.group(1)
                relation_key = (relative, target)
                if relation_key in api_relation_keys:
                    continue
                api_relation_keys.add(relation_key)
                api_evidence = add_evidence(
                    "frontend_api", relative, f"offset {match.start()}", _excerpt(text, match.start())
                )
                relations.append(
                    Relation(
                        source_id=relative,
                        target_id=target,
                        kind="api_call",
                        evidence_ids=[api_evidence],
                    )
                )

        return UniversalProjectModel(
            project_id=project_id,
            identity=ProjectIdentity(
                name=str(package.get("name") or root.name),
                artifact_type="frontend_project",
                description="Generic JavaScript/TypeScript project structure and dependency facts.",
            ),
            structure=structure_nodes,
            technologies=technologies,
            components=components,
            relations=relations,
            flows=flows,
            evidence=evidence,
            dependencies=dependencies,
            metadata={
                "analyzer": self.analyzer_id,
                "manifest": "package.json",
                "source_files": source_paths,
                "build_tool": build_tool or None,
                "scripts": sorted(str(name) for name in scripts) if isinstance(scripts, dict) else [],
            },
        )


__all__ = ["FrontendAnalyzer"]
