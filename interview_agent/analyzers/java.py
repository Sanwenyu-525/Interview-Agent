"""Java 项目分析器：将受限 Java/Spring 事实组装成统一项目模型。"""

from pathlib import Path
import re

from ..intelligence.models import (
    Component,
    Evidence,
    Flow,
    Insight,
    ProjectIdentity,
    ProjectTopic,
    Relation,
    StructureNode,
    Technology,
    UniversalProjectModel,
)
from .java_rules import parse_java_project
from .scanner import ProjectScanner


class JavaAnalyzer:
    """V1 Maven Java analyzer.

    Gradle projects are scanned by :class:`ProjectScanner`, but are intentionally
    unsupported here until a Gradle dependency parser is added.
    """

    analyzer_id = "java"

    def supports(self, structure: object) -> bool:
        if not isinstance(structure, dict):
            return False
        build_tool = structure.get("build_tool")
        language_counts = structure.get("language_counts")
        java_count = language_counts.get("java") if isinstance(language_counts, dict) else None
        return (
            build_tool == "maven"
            and isinstance(language_counts, dict)
            and isinstance(java_count, int)
            and not isinstance(java_count, bool)
            and java_count > 0
        )

    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel:
        if isinstance(project_id, bool) or not isinstance(project_id, int):
            raise TypeError("project_id must be int")
        root = Path(artifact_root)
        scanner_structure = ProjectScanner.scan(root)
        if not self.supports(scanner_structure):
            raise ValueError(
                "JavaAnalyzer supports Maven Java projects only; "
                f"scanner found: {scanner_structure!r}"
            )

        facts = parse_java_project(root, build_file=scanner_structure.get("build_file"))
        evidence: list[Evidence] = []
        evidence_by_key: dict[tuple[str, str, int, str], str] = {}

        def evidence_id(kind: str, source_path: str, line: int, symbol: str, excerpt: str) -> str:
            key = (kind, source_path, line, symbol)
            if key not in evidence_by_key:
                safe_symbol = re.sub(r"[^A-Za-z0-9_.-]+", "-", symbol).strip("-") or "item"
                identifier = f"e-{kind}-{source_path.replace('/', '-')}-{line}-{safe_symbol}"
                evidence_by_key[key] = identifier
                evidence.append(
                    Evidence(
                        id=identifier,
                        source_path=source_path,
                        locator=f"line {line} ({symbol})",
                        excerpt=excerpt,
                        kind=kind,
                        confidence=0.9,
                    )
                )
            return evidence_by_key[key]

        simple_name_counts: dict[str, int] = {}
        component_aliases: dict[str, list[str]] = {}
        for fact in facts.components:
            simple_name_counts[fact.name] = simple_name_counts.get(fact.name, 0) + 1
            component_aliases.setdefault(fact.name, []).append(fact.qualified_name)

        component_ids: set[str] = set()
        components: list[Component] = []
        for fact in facts.components:
            component_ids.add(fact.qualified_name)
            component_evidence = evidence_id(
                "component", fact.source_path, fact.line, fact.qualified_name, fact.excerpt
            )
            display_name = (
                fact.name
                if simple_name_counts[fact.name] == 1
                else fact.qualified_name
            )
            components.append(
                Component(
                    id=fact.qualified_name,
                    name=display_name,
                    kind=fact.kind,
                    description=f"Spring {fact.kind} component ({fact.name}).",
                    path=fact.source_path,
                    evidence_ids=[component_evidence],
                )
            )

        relations: list[Relation] = []
        dependencies: dict[str, list[str]] = {}
        seen_relations: set[tuple[str, str]] = set()
        unresolved_dependencies: list[tuple[str, str, str]] = []
        for fact in facts.dependencies:
            if fact.target is None:
                unresolved_evidence = evidence_id(
                    "relation",
                    fact.source_path,
                    fact.line,
                    f"{fact.source}->unresolved:{fact.target_name}",
                    fact.excerpt,
                )
                unresolved_dependencies.append(
                    (fact.source, fact.target_name, unresolved_evidence)
                )
                continue
            pair = (fact.source, fact.target)
            if pair in seen_relations or fact.source not in component_ids or fact.target not in component_ids:
                continue
            seen_relations.add(pair)
            relation_evidence = evidence_id(
                "relation", fact.source_path, fact.line, f"{fact.source}->{fact.target}", fact.excerpt
            )
            relations.append(
                Relation(
                    source_id=fact.source,
                    target_id=fact.target,
                    kind="DEPENDS_ON",
                    description=f"{fact.source} uses {fact.target}.",
                    evidence_ids=[relation_evidence],
                )
            )
            dependencies.setdefault(fact.source, []).append(fact.target)

        flows: list[Flow] = []
        flow_evidence_ids: list[str] = []
        unresolved_flows: list[dict[str, str | None]] = []
        for sequence, fact in enumerate(facts.endpoints, 1):
            endpoint_evidence = evidence_id(
                "flow",
                fact.source_path,
                fact.line,
                f"{fact.http_method} {fact.path} method-{fact.method_line} seq-{sequence}",
                fact.excerpt,
            )
            flow_evidence_ids.append(endpoint_evidence)
            if fact.path is None:
                flow_name = f"{fact.http_method} <unresolved path>"
                flow_id = (
                    f"flow:{fact.source_path}:{fact.line}:"
                    f"method-{fact.method_line}:seq-{sequence}"
                )
                flow_description = (
                    f"HTTP endpoint handled by {fact.owner}; "
                    "resolution=unresolved; path=None."
                )
                unresolved_flows.append(
                    {
                        "method": fact.http_method,
                        "path": None,
                        "resolution": "unresolved",
                        "source_path": fact.source_path,
                    }
                )
            else:
                flow_name = f"{fact.http_method} {fact.path}"
                flow_id = (
                    f"flow:{fact.source_path}:{fact.line}:"
                    f"method-{fact.method_line}:seq-{sequence}"
                )
                flow_description = f"HTTP endpoint handled by {fact.owner}."
            flows.append(
                Flow(
                    id=flow_id,
                    name=flow_name,
                    description=flow_description,
                    component_ids=[fact.owner] if fact.owner in component_ids else [],
                    evidence_ids=[endpoint_evidence],
                )
            )

        transaction_evidence_ids = [
            evidence_id("topic", fact.source_path, fact.line, "Transaction", fact.excerpt)
            for fact in facts.transactions
        ]
        topics: list[ProjectTopic] = []
        insights: list[Insight] = []
        for index, (source, target_name, unresolved_evidence) in enumerate(
            unresolved_dependencies
        ):
            insights.append(
                Insight(
                    id=f"insight:unresolved-dependency:{index}",
                    kind="unresolved_dependency",
                    summary=f"Could not uniquely resolve {target_name} used by {source}.",
                    topic="Dependency Resolution",
                    score=0,
                    evidence_ids=[unresolved_evidence],
                )
            )
        if flow_evidence_ids:
            topics.append(ProjectTopic(name="HTTP API", score=75, evidence_ids=[flow_evidence_ids[0]]))
            insights.append(
                Insight(
                    id="insight:http-api",
                    kind="capability",
                    summary="The project exposes annotated HTTP endpoints.",
                    topic="HTTP API",
                    score=75,
                    evidence_ids=[flow_evidence_ids[0]],
                )
            )
        if transaction_evidence_ids:
            topics.append(ProjectTopic(name="Transaction", score=70, evidence_ids=[transaction_evidence_ids[0]]))
            insights.append(
                Insight(
                    id="insight:transaction",
                    kind="capability",
                    summary="The project marks a service operation as transactional.",
                    topic="Transaction",
                    score=70,
                    evidence_ids=[transaction_evidence_ids[0]],
                )
            )

        technologies: list[Technology] = []
        for fact in facts.technologies:
            technology_evidence = evidence_id(
                "technology", fact.source_path, fact.line, fact.name, fact.excerpt
            )
            technologies.append(
                Technology(
                    name=fact.name,
                    category="dependency",
                    version=fact.version,
                    evidence_ids=[technology_evidence],
                )
            )

        structure = [
            StructureNode(id="project", name=facts.artifact_name, kind="project"),
        ]
        source_roots = [
            path for path in scanner_structure.get("java_source_roots", []) if isinstance(path, str)
        ]
        structure.extend(
            StructureNode(id=f"directory:{path}", name=path, kind="source_root", path=path)
            for path in source_roots
        )

        return UniversalProjectModel(
            project_id=project_id,
            identity=ProjectIdentity(
                name=facts.artifact_name,
                artifact_type="java_backend",
                goal="Java project understanding",
                description="A Java project analyzed from source and build configuration.",
            ),
            structure=structure,
            technologies=technologies,
            components=components,
            relations=relations,
            flows=flows,
            insights=insights,
            evidence=evidence,
            topics=topics,
            dependencies=dependencies,
            metadata={
                "build_tool": scanner_structure.get("build_tool"),
                "build_file": scanner_structure.get("build_file"),
                "component_aliases": component_aliases,
                "unresolved_flows": unresolved_flows,
            },
        )


__all__ = ["JavaAnalyzer"]
