"""Java/Spring V1 规则提取器。

规则扫描使用经过 mask 的源码做识别，使用原文做路径和证据提取；这让注释、字符串
中的注解文本不会被误认为代码，同时保留证据的原始内容和行号。
"""

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .scanner import iter_project_files


_CLASS_RE = re.compile(
    r"\b(?:class|interface|enum|record)\s+(?P<name>[A-Za-z_$][\w$]*)"
)
_METHOD_RE = re.compile(
    r"\b(?:(?:public|protected|private)\s+)?"
    r"(?:static\s+|final\s+|synchronized\s+|abstract\s+)*"
    r"[\w$<>,.?\[\] ]+\s+(?P<name>[A-Za-z_$][\w$]*)\s*\([^;]*\)"
)
_ANNOTATION_RE = re.compile(r"@(?:[A-Za-z_$][\w$]*\.)*(?P<name>[A-Za-z_$][\w$]*)\b")
_QUOTED_VALUE_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
_GRADLE_COORDINATE_RE = re.compile(
    r"\b(?:implementation|api|compileOnly|runtimeOnly|"
    r"testImplementation|testRuntimeOnly|classpath)\s*\(?\s*"
    r"['\"](?P<coordinate>[^'\"]+)['\"]"
)
_GRADLE_PLUGIN_RE = re.compile(
    r"\bid\s*\(?\s*['\"](?P<plugin>[^'\"]+)['\"]\s*\)?"
    r"(?:\s+version\s+['\"](?P<version>[^'\"]+)['\"])?"
)

_COMPONENT_KINDS = (
    "RestController",
    "Service",
    "Repository",
    "Entity",
    "Configuration",
    "Component",
)
_COMPONENT_KIND_SET = set(_COMPONENT_KINDS)


@dataclass(frozen=True)
class JavaComponentFact:
    name: str
    qualified_name: str
    kind: str
    source_path: str
    line: int
    excerpt: str


@dataclass(frozen=True)
class JavaDependencyFact:
    source: str
    target: str | None
    target_name: str
    source_path: str
    line: int
    excerpt: str


@dataclass(frozen=True)
class JavaEndpointFact:
    owner: str
    http_method: str
    path: str | None
    path_resolution: str
    source_path: str
    line: int
    method_line: int
    excerpt: str


@dataclass(frozen=True)
class JavaTransactionFact:
    owner: str
    source_path: str
    line: int
    excerpt: str


@dataclass(frozen=True)
class PomTechnologyFact:
    name: str
    version: str
    source_path: str
    line: int
    excerpt: str


@dataclass(frozen=True)
class JavaProjectFacts:
    components: list[JavaComponentFact]
    dependencies: list[JavaDependencyFact]
    endpoints: list[JavaEndpointFact]
    transactions: list[JavaTransactionFact]
    technologies: list[PomTechnologyFact]
    artifact_name: str


def parse_java_project(root: Path, build_file: str | Path | None = None) -> JavaProjectFacts:
    root = Path(root)
    components: list[JavaComponentFact] = []
    dependencies: list[JavaDependencyFact] = []
    endpoints: list[JavaEndpointFact] = []
    transactions: list[JavaTransactionFact] = []

    java_files = sorted(
        (
            path
            for path in iter_project_files(root)
            if path.is_file()
            and path.suffix.lower() == ".java"
        ),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )
    all_component_names: dict[str, list[str]] = {}
    parsed_sources: list[
        tuple[str, list[str], list[str], str, list[str], list[tuple[str, int, int, list[str]]]]
    ] = []

    for path in java_files:
        source_path = path.relative_to(root).as_posix()
        original_text = path.read_text(encoding="utf-8", errors="replace")
        masked_text = _mask_java_source(original_text)
        original_lines = original_text.splitlines()
        masked_lines = masked_text.splitlines()
        package = _parse_package(masked_text)
        imports = _parse_imports(masked_text)
        classes = _find_classes(masked_lines)
        parsed_sources.append((source_path, original_lines, masked_lines, package, imports, classes))
        for name, _, _, annotations in classes:
            kind = _component_kind(annotations)
            if kind:
                qualified_name = _qualified_name(package, name)
                all_component_names.setdefault(name, []).append(qualified_name)

    for source_path, original_lines, masked_lines, package, imports, classes in parsed_sources:
        for class_name, declaration_line, end_line, annotations in classes:
            kind = _component_kind(annotations)
            qualified_name = _qualified_name(package, class_name)
            if kind:
                annotation_line = _annotation_location(
                    masked_lines, declaration_line, kind
                )
                components.append(
                    JavaComponentFact(
                        name=class_name,
                        qualified_name=qualified_name,
                        kind=kind,
                        source_path=source_path,
                        line=annotation_line + 1,
                        excerpt="\n".join(
                            line.strip()
                            for line in original_lines[
                                annotation_line : declaration_line + 1
                            ]
                        ),
                    )
                )

            class_base_method, class_base_path, class_base_resolution = _class_mapping_spec(
                original_lines, masked_lines, declaration_line
            )
            pending_routes: list[tuple[str, str | None, str, int, str]] = []
            mapping_events = _collect_mapping_annotations(
                original_lines, masked_lines, declaration_line, end_line
            )
            events_by_line: dict[int, list[tuple[str, int, int, str, str]]] = {}
            for event in mapping_events:
                events_by_line.setdefault(event[1], []).append(event)
            for line_index in range(declaration_line, end_line):
                original_line = original_lines[line_index]
                masked_line = masked_lines[line_index]
                annotation_names = _annotation_names(masked_line)
                for annotation_name, _, _, original_fragment, masked_fragment in events_by_line.get(
                    line_index, []
                ):
                    method, path, path_resolution = _mapping_info(
                        original_fragment, masked_fragment, annotation_name
                    )
                    if method == "REQUEST" and class_base_method != "REQUEST":
                        method = class_base_method
                    if class_base_resolution == "unresolved":
                        path_resolution = "unresolved"
                    pending_routes.append(
                        (
                            method,
                            path,
                            line_index + 1,
                            original_fragment.strip(),
                            path_resolution,
                        )
                    )

                if "Transactional" in annotation_names:
                    transactions.append(
                        JavaTransactionFact(
                            owner=qualified_name,
                            source_path=source_path,
                            line=line_index + 1,
                            excerpt=original_line.strip(),
                        )
                    )

                method_match = _METHOD_RE.search(masked_line)
                if method_match and pending_routes:
                    http_method, method_path, annotation_line, annotation_excerpt, path_resolution = (
                        pending_routes.pop(0)
                    )
                    full_path = _join_paths(class_base_path, method_path)
                    diagnostic = (
                        " [path resolution=unresolved]"
                        if path_resolution == "unresolved"
                        else " [path defaulted to /]"
                        if path_resolution == "root"
                        else ""
                    )
                    endpoints.append(
                        JavaEndpointFact(
                            owner=qualified_name,
                            http_method=http_method,
                            path=full_path,
                            path_resolution=path_resolution,
                            source_path=source_path,
                            line=annotation_line,
                            method_line=line_index + 1,
                            excerpt=(
                                f"{annotation_excerpt} (method line {line_index + 1})"
                                f"{diagnostic}"
                            ),
                        )
                    )

            if kind:
                for line_index in range(declaration_line, end_line):
                    masked_line = masked_lines[line_index]
                    original_line = original_lines[line_index]
                    for target_name, candidates in sorted(all_component_names.items()):
                        if target_name == class_name:
                            continue
                        if not re.search(
                            rf"\b{re.escape(target_name)}\s+[A-Za-z_$][\w$]*\b",
                            masked_line,
                        ):
                            continue
                        target = _resolve_component(
                            target_name, candidates, package, imports
                        )
                        dependencies.append(
                            JavaDependencyFact(
                                source=qualified_name,
                                target=target,
                                target_name=target_name,
                                source_path=source_path,
                                line=line_index + 1,
                                excerpt=original_line.strip(),
                            )
                        )

    descriptor_path = _resolve_pom_path(root, build_file)
    pom_tree = (
        _parse_pom(descriptor_path)
        if descriptor_path and descriptor_path.name.casefold() == "pom.xml"
        else None
    )
    if descriptor_path and descriptor_path.name.casefold() in {"build.gradle", "build.gradle.kts"}:
        technologies = _parse_gradle_technologies(root, descriptor_path)
        artifact_name = _parse_gradle_artifact_name(root, descriptor_path)
    else:
        technologies = _parse_pom_technologies(root, descriptor_path, pom_tree)
        artifact_name = _parse_artifact_name(root, pom_tree)
    return JavaProjectFacts(
        components=components,
        dependencies=dependencies,
        endpoints=endpoints,
        transactions=transactions,
        technologies=technologies,
        artifact_name=artifact_name,
    )


def _mask_java_source(source: str) -> str:
    """Mask comments and Java string/char literals while preserving length/newlines."""
    chars = list(source)
    state = "normal"
    index = 0

    def blank(position: int) -> None:
        if chars[position] not in "\r\n":
            chars[position] = " "

    while index < len(chars):
        if state == "normal":
            if source.startswith("//", index):
                blank(index)
                blank(index + 1)
                index += 2
                state = "line_comment"
            elif source.startswith("/*", index):
                blank(index)
                blank(index + 1)
                index += 2
                state = "block_comment"
            elif source.startswith('"""', index):
                for offset in range(3):
                    blank(index + offset)
                index += 3
                state = "text_block"
            elif source[index] == '"':
                blank(index)
                index += 1
                state = "string"
            elif source[index] == "'":
                blank(index)
                index += 1
                state = "char"
            else:
                index += 1
        elif state == "line_comment":
            if source[index] in "\r\n":
                state = "normal"
            else:
                blank(index)
                index += 1
        elif state == "block_comment":
            if source.startswith("*/", index):
                blank(index)
                blank(index + 1)
                index += 2
                state = "normal"
            else:
                blank(index)
                index += 1
        else:
            if state == "text_block" and source.startswith('"""', index):
                for offset in range(3):
                    blank(index + offset)
                index += 3
                state = "normal"
            elif state in {"string", "char"} and source[index] == "\\":
                blank(index)
                index += 1
                if index < len(chars):
                    blank(index)
                    index += 1
            elif state == "string" and source[index] == '"':
                blank(index)
                index += 1
                state = "normal"
            elif state == "char" and source[index] == "'":
                blank(index)
                index += 1
                state = "normal"
            else:
                blank(index)
                index += 1
    return "".join(chars)


def _find_classes(lines: list[str]) -> list[tuple[str, int, int, list[str]]]:
    found: list[tuple[str, int, list[str]]] = []
    pending_annotations: list[str] = []
    for index, line in enumerate(lines):
        names = _annotation_names(line)
        pending_annotations.extend(
            name for name in names if name in _COMPONENT_KIND_SET or name == "RequestMapping"
        )
        match = _CLASS_RE.search(line)
        if not match:
            continue
        found.append((match.group("name"), index, list(dict.fromkeys(pending_annotations))))
        pending_annotations.clear()

    return [
        (
            name,
            start,
            found[position + 1][1] if position + 1 < len(found) else len(lines),
            annotations,
        )
        for position, (name, start, annotations) in enumerate(found)
    ]


def _annotation_location(lines: list[str], declaration_line: int, annotation: str) -> int:
    for index in range(declaration_line - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if annotation in _annotation_names(lines[index]):
            return index
        if not stripped.startswith("@"):
            break
    return declaration_line


def _class_mapping_spec(
    original_lines: list[str], masked_lines: list[str], declaration_line: int
) -> tuple[str, str | None, str]:
    events = _collect_mapping_annotations(
        original_lines, masked_lines, 0, declaration_line
    )
    for event in reversed(events):
        name, start_line, end_line, original_fragment, masked_fragment = event
        if name != "RequestMapping":
            continue
        if all(
            not masked_lines[index].strip()
            or masked_lines[index].strip().startswith("@")
            for index in range(end_line + 1, declaration_line)
        ):
            method, path, resolution = _mapping_info(
                original_fragment, masked_fragment, name
            )
            return method, path, resolution
    return "REQUEST", "", "root"


def _annotation_names(line: str) -> list[str]:
    return [match.group("name") for match in _ANNOTATION_RE.finditer(line)]


def _component_kind(annotations: list[str]) -> str:
    for kind in _COMPONENT_KINDS:
        if kind in annotations:
            return kind
    return ""


def _collect_mapping_annotations(
    original_lines: list[str],
    masked_lines: list[str],
    start_line: int,
    end_line: int,
) -> list[tuple[str, int, int, str, str]]:
    events: list[tuple[str, int, int, str, str]] = []
    names = ("GetMapping", "PostMapping", "RequestMapping")
    for line_index in range(start_line, end_line):
        matches = []
        for name in names:
            for match in re.finditer(
                rf"@(?:[A-Za-z_$][\w$]*\.)*{name}\b", masked_lines[line_index]
            ):
                matches.append((match.start(), name, match.end()))
        for start_column, name, match_end in sorted(matches):
            annotation_end_line, annotation_end_column = _annotation_end(
                masked_lines, line_index, match_end, end_line
            )
            original_fragment = _slice_lines(
                original_lines,
                line_index,
                start_column,
                annotation_end_line,
                annotation_end_column,
            )
            masked_fragment = _slice_lines(
                masked_lines,
                line_index,
                start_column,
                annotation_end_line,
                annotation_end_column,
            )
            events.append(
                (
                    name,
                    line_index,
                    annotation_end_line,
                    original_fragment,
                    masked_fragment,
                )
            )
    return events


def _annotation_end(
    masked_lines: list[str], start_line: int, match_end: int, limit: int
) -> tuple[int, int]:
    depth = 0
    saw_parenthesis = False
    for line_index in range(start_line, limit):
        start_column = match_end if line_index == start_line else 0
        for column in range(start_column, len(masked_lines[line_index])):
            char = masked_lines[line_index][column]
            if char == "(":
                depth += 1
                saw_parenthesis = True
            elif char == ")" and saw_parenthesis:
                depth -= 1
                if depth == 0:
                    return line_index, column + 1
        if line_index == start_line and not saw_parenthesis:
            return start_line, match_end
        if saw_parenthesis and depth == 0:
            return line_index, len(masked_lines[line_index])
    return start_line, match_end


def _slice_lines(
    lines: list[str], start_line: int, start_column: int, end_line: int, end_column: int
) -> str:
    if start_line == end_line:
        return lines[start_line][start_column:end_column]
    parts = [lines[start_line][start_column:]]
    parts.extend(lines[index] for index in range(start_line + 1, end_line))
    parts.append(lines[end_line][:end_column])
    return "\n".join(parts)


def _mapping_info(
    original_line: str, masked_line: str, annotation_name: str
) -> tuple[str, str | None, str]:
    match = re.search(
        rf"@(?:[A-Za-z_$][\w$]*\.)*{annotation_name}\b(?:\s*\([^)]*\))?",
        masked_line,
    )
    fragment = original_line[match.start() : match.end()] if match else original_line
    masked_fragment = masked_line[match.start() : match.end()] if match else masked_line
    if annotation_name == "GetMapping":
        method = "GET"
    elif annotation_name == "PostMapping":
        method = "POST"
    else:
        method_fragment = _named_attribute_fragment(
            fragment, masked_fragment, "method"
        ) or ""
        method_match = re.search(
            r"RequestMethod\.([A-Z]+)", method_fragment
        )
        method = method_match.group(1) if method_match else "REQUEST"
    path_fragment = _named_attribute_fragment(fragment, masked_fragment, "path")
    if path_fragment is None:
        path_fragment = _named_attribute_fragment(fragment, masked_fragment, "value")
    if path_fragment is None:
        arguments = re.search(r"\((.*)\)", fragment, re.DOTALL)
        if arguments is None or not arguments.group(1).strip():
            return method, "/", "root"
        path_fragment = (
            fragment
            if not re.search(r"\b[A-Za-z_$][\w$]*\s*=", masked_fragment)
            else None
        )
    if path_fragment is None:
        return method, "/", "root"
    path_match = _QUOTED_VALUE_RE.search(path_fragment)
    if path_match:
        path = path_match.group(1)
        if "${" in path or "#{" in path:
            return method, None, "unresolved"
        return method, path, "resolved"
    return method, None, "unresolved"


def _named_attribute_fragment(
    original: str, masked: str, name: str
) -> str | None:
    match = re.search(rf"\b{re.escape(name)}\s*=", masked)
    if not match:
        return None
    next_attribute = re.search(
        r"\b[A-Za-z_$][\w$]*\s*=", masked[match.end() :]
    )
    end = match.end() + next_attribute.start() if next_attribute else len(masked)
    return original[match.end() : end]


def _join_paths(base: str | None, child: str | None) -> str | None:
    if base is None or child is None:
        return None
    base_part = (base or "").strip("/")
    child_part = (child or "/").strip("/")
    if not base_part:
        return f"/{child_part}" if child_part else "/"
    if not child_part:
        return f"/{base_part}"
    return f"/{base_part}/{child_part}"


def _parse_package(masked_text: str) -> str:
    match = re.search(r"\bpackage\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", masked_text)
    return match.group(1) if match else ""


def _parse_imports(masked_text: str) -> list[str]:
    return re.findall(
        r"\bimport\s+(?:static\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\.\*)*)\s*;",
        masked_text,
    )


def _qualified_name(package: str, name: str) -> str:
    return f"{package}.{name}" if package else name


def _resolve_component(
    simple_name: str, candidates: list[str], package: str, imports: list[str]
) -> str | None:
    imported = [candidate for candidate in candidates if candidate in imports]
    if len(imported) == 1:
        return imported[0]
    wildcard_packages = [item[:-2] for item in imports if item.endswith(".*")]
    wildcard_matches = [
        candidate
        for candidate in candidates
        if candidate.rsplit(".", 1)[0] in wildcard_packages
    ]
    if len(wildcard_matches) == 1:
        return wildcard_matches[0]
    same_package = f"{package}.{simple_name}" if package else simple_name
    if same_package in candidates:
        return same_package
    if len(candidates) == 1:
        return candidates[0]
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _resolve_pom_path(root: Path, build_file: str | Path | None) -> Path | None:
    root = Path(root)
    if build_file:
        pom = root / Path(build_file)
        return pom if pom.is_file() else None
    return next(
        (
            path
            for path in iter_project_files(root)
            if path.parent == root and path.name.casefold() == "pom.xml"
        ),
        None,
    )


def _parse_pom(pom: Path | None) -> ET.ElementTree | None:
    if pom is None or not pom.is_file():
        return None
    try:
        return ET.parse(pom)
    except ET.ParseError as exc:
        raise ValueError(f"Unable to parse Maven descriptor {pom}: {exc}") from exc


def _parse_gradle_artifact_name(root: Path, build_file: Path) -> str:
    for line in build_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"\b(?:rootProject\.name|archivesBaseName)\s*=\s*['\"]([^'\"]+)['\"]", line)
        if match:
            return match.group(1)
    return root.name


def _parse_gradle_technologies(root: Path, build_file: Path) -> list[PomTechnologyFact]:
    lines = build_file.read_text(encoding="utf-8", errors="replace").splitlines()
    source_path = build_file.relative_to(root).as_posix()
    values: list[tuple[str, str, int, str]] = [("Gradle", "", 1, lines[0].strip() if lines else "Gradle")]

    for line_number, line in enumerate(lines, 1):
        plugin_match = _GRADLE_PLUGIN_RE.search(line)
        if plugin_match:
            plugin = plugin_match.group("plugin")
            version = plugin_match.group("version") or ""
            technology = (
                "Spring Boot"
                if plugin == "org.springframework.boot"
                else _dependency_technology(plugin, plugin)
            )
            if technology:
                values.append((technology, version, line_number, line.strip()))

        for coordinate_match in _GRADLE_COORDINATE_RE.finditer(line):
            coordinate = coordinate_match.group("coordinate").split(":")
            if len(coordinate) < 2:
                continue
            group, artifact = coordinate[:2]
            version = coordinate[2] if len(coordinate) > 2 else ""
            technology = _dependency_technology(group, artifact)
            if technology:
                values.append((technology, version, line_number, line.strip()))

    result: list[PomTechnologyFact] = []
    seen: set[str] = set()
    for name, version, line_number, excerpt in values:
        if name in seen:
            continue
        seen.add(name)
        result.append(
            PomTechnologyFact(
                name=name,
                version=version,
                source_path=source_path,
                line=line_number,
                excerpt=excerpt,
            )
        )
    return result


def _parse_artifact_name(root: Path, tree: ET.ElementTree | None) -> str:
    if tree is None:
        return root.name
    for element in tree.getroot():
        if _local_name(element.tag) == "artifactId" and element.text:
            return element.text.strip()
    return root.name


def _parse_pom_technologies(
    root: Path, pom: Path | None, tree: ET.ElementTree | None
) -> list[PomTechnologyFact]:
    if tree is None or pom is None:
        return []
    lines = pom.read_text(encoding="utf-8", errors="replace").splitlines()
    source_path = pom.relative_to(root).as_posix()
    values: list[tuple[str, str, str]] = []
    for element in tree.getroot().iter():
        if _local_name(element.tag) not in {"dependency", "parent"}:
            continue
        artifact = ""
        group = ""
        version = ""
        for child in element:
            name = _local_name(child.tag)
            value = (child.text or "").strip()
            if name == "artifactId":
                artifact = value
            elif name == "groupId":
                group = value
            elif name == "version":
                version = value
        technology = _dependency_technology(group, artifact)
        if technology:
            values.append((technology, version, artifact))

    result: list[PomTechnologyFact] = []
    seen: set[str] = set()
    for name, version, artifact in values:
        if name in seen:
            continue
        seen.add(name)
        line_number = next(
            (index for index, line in enumerate(lines, 1) if artifact in line),
            1,
        )
        result.append(
            PomTechnologyFact(
                name=name,
                version=version,
                source_path=source_path,
                line=line_number,
                excerpt=lines[line_number - 1].strip() if lines else artifact,
            )
        )
    return result


def _dependency_technology(group: str, artifact: str) -> str:
    value = f"{group}:{artifact}".lower()
    if "spring-boot-starter-web" in value:
        return "Spring Web"
    if "spring-boot-starter-security" in value:
        return "Spring Security"
    if artifact == "spring-boot-starter-parent" or "spring-boot" in group:
        return "Spring Boot"
    if "mysql" in value:
        return "MySQL"
    if "redis" in value:
        return "Redis"
    if "kafka" in value:
        return "Kafka"
    if "spring-boot-starter-data-jpa" in value:
        return "Spring Data JPA"
    return ""


__all__ = [
    "JavaComponentFact",
    "JavaDependencyFact",
    "JavaEndpointFact",
    "JavaProjectFacts",
    "JavaTransactionFact",
    "PomTechnologyFact",
    "parse_java_project",
]
