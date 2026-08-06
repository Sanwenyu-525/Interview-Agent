import json
import tempfile
import unittest
from pathlib import Path

from interview_agent.analyzers.java import JavaAnalyzer
from interview_agent.analyzers.gradle_java import GradleJavaAnalyzer
from interview_agent.analyzers.registry import AnalyzerRegistry
from interview_agent.analyzers.scanner import ProjectScanner


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "java_project"
GRADLE_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gradle_java_project"


class JavaAnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.structure = ProjectScanner().scan(FIXTURE_ROOT)
        cls.model = JavaAnalyzer().analyze(FIXTURE_ROOT, 42)

    def test_analyzer_supports_maven_java_structure_and_project_id_is_int(self):
        analyzer = JavaAnalyzer()
        self.assertEqual(analyzer.analyzer_id, "java")
        self.assertTrue(analyzer.supports(self.structure))
        self.assertIsInstance(self.model.project_id, int)

    def test_model_has_identity_structure_technologies_and_serializable_evidence(self):
        self.assertEqual(self.model.identity.name, "order-service")
        self.assertTrue(self.model.structure)
        source_roots = {
            node.path for node in self.model.structure if node.kind == "source_root"
        }
        self.assertIn("src/main/java", source_roots)
        self.assertNotIn("src/main/java/demo", source_roots)
        technology_names = {technology.name for technology in self.model.technologies}
        self.assertTrue({"Spring Boot", "Spring Web", "Spring Security", "MySQL", "Redis", "Kafka"} <= technology_names)
        payload = json.loads(json.dumps(self.model, default=lambda value: value.__dict__))
        self.assertEqual(payload["project_id"], 42)

    def test_extracts_spring_components_and_known_type_dependencies(self):
        component_kinds = {component.name: component.kind for component in self.model.components}
        self.assertEqual(component_kinds["OrderController"], "RestController")
        self.assertEqual(component_kinds["OrderService"], "Service")
        self.assertEqual(component_kinds["OrderRepository"], "Repository")
        self.assertEqual(component_kinds["Order"], "Entity")
        self.assertEqual(component_kinds["OrderConfiguration"], "Configuration")
        self.assertEqual(component_kinds["OrderMetrics"], "Component")
        relations = {(relation.source_id, relation.target_id, relation.kind) for relation in self.model.relations}
        self.assertIn(("demo.OrderController", "demo.OrderService", "DEPENDS_ON"), relations)
        self.assertIn(("demo.OrderService", "demo.OrderRepository", "DEPENDS_ON"), relations)

    def test_extracts_http_flows_and_transaction_topic_with_evidence(self):
        flow_names = {flow.name for flow in self.model.flows}
        self.assertIn("GET /orders/{id}", flow_names)
        self.assertIn("POST /orders", flow_names)
        self.assertIn("GET /orders/internal", flow_names)
        topics = {topic.name for topic in self.model.topics}
        self.assertIn("Transaction", topics)
        evidence_ids = {evidence.id for evidence in self.model.evidence}
        for item in [*self.model.components, *self.model.flows, *self.model.topics, *self.model.relations]:
            self.assertTrue(set(item.evidence_ids) <= evidence_ids)
        transaction = next(topic for topic in self.model.topics if topic.name == "Transaction")
        evidence = next(item for item in self.model.evidence if item.id in transaction.evidence_ids)
        self.assertEqual(evidence.source_path, "src/main/java/demo/OrderService.java")
        self.assertIn("line", evidence.locator)

        get_flow = next(flow for flow in self.model.flows if flow.name == "GET /orders/{id}")
        get_evidence = next(item for item in self.model.evidence if item.id in get_flow.evidence_ids)
        annotation_line = next(
            index
            for index, line in enumerate(
                (FIXTURE_ROOT / "src/main/java/demo/OrderController.java").read_text(
                    encoding="utf-8"
                ).splitlines(),
                1,
            )
            if "@GetMapping" in line
        )
        self.assertIn(f"line {annotation_line}", get_evidence.locator)

    def test_analyzer_rejects_empty_readme_only_and_unbuilt_projects(self):
        analyzer = JavaAnalyzer()
        project_shapes = [
            (),
            (("README.md", "project"),),
            (("src/main/java/demo/Main.java", "class Main {}"),),
        ]
        for files in project_shapes:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for relative_path, content in files:
                    target = root / relative_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "JavaAnalyzer|support"):
                    analyzer.analyze(root, 99)

    def test_dynamic_mapping_path_is_unresolved_not_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Api {
    @GetMapping(path = API_PATH)
    public String dynamic() { return \"ok\"; }
    @GetMapping(method = RequestMethod.GET)
    public String root() { return \"ok\"; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 101)

        dynamic_flow = next(flow for flow in model.flows if "unresolved" in flow.name)
        self.assertIn("resolution=unresolved", dynamic_flow.description)
        self.assertTrue(
            any(item.get("path") is None for item in model.metadata["unresolved_flows"])
        )
        self.assertIn("GET /", {flow.name for flow in model.flows})

    def test_request_mapping_method_arrays_and_default_path_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMethod;
@RestController
public class Api {
    @RequestMapping(method = RequestMethod.GET, path = {\"/items\", \"/ignored\"})
    public String list() { return \"ok\"; }
    @RequestMapping(method = RequestMethod.POST, value = {\"/items\", \"/ignored\"})
    public String create() { return \"ok\"; }
    @RequestMapping(method = RequestMethod.GET)
    public String root() { return \"ok\"; }
}
""",
                },
            )

            model = JavaAnalyzer().analyze(root, 7)

        self.assertIn("GET /items", {flow.name for flow in model.flows})
        self.assertIn("POST /items", {flow.name for flow in model.flows})
        self.assertIn("GET /", {flow.name for flow in model.flows})
        default_flow = next(flow for flow in model.flows if flow.name == "GET /")
        default_evidence = next(
            evidence for evidence in model.evidence if evidence.id in default_flow.evidence_ids
        )
        self.assertIn("path defaulted to /", default_evidence.excerpt)

    def test_class_request_mapping_searches_annotation_block_beyond_eight_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController

// spacing comment








@RequestMapping(\"/orders\")
public class Api {
    @GetMapping(\"/one\")
    public String one() { return \"ok\"; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 8)

        self.assertIn("GET /orders/one", {flow.name for flow in model.flows})

    def test_comments_and_strings_do_not_create_spring_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
// @Service class FakeService {}
/* @GetMapping(\"/fake\") */
@RestController
public class Api {
    String text = \"@Service @GetMapping('/fake')\";
    @GetMapping(\"/real\")
    public String real() { return text; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 9)

        self.assertEqual([component.name for component in model.components], ["Api"])
        self.assertEqual([flow.name for flow in model.flows], ["GET /real"])

    def test_flow_without_spring_component_has_no_invalid_owner_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/PlainApi.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
public class PlainApi {
    @GetMapping(\"/plain\")
    public String plain() { return \"ok\"; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 10)

        flow = next(flow for flow in model.flows if flow.name == "GET /plain")
        self.assertEqual(flow.component_ids, [])

    def test_component_evidence_points_to_spring_annotation(self):
        controller = next(
            component for component in self.model.components if component.name == "OrderController"
        )
        evidence = next(
            evidence for evidence in self.model.evidence if evidence.id in controller.evidence_ids
        )
        self.assertIn("@RestController", evidence.excerpt)
        self.assertIn("line 8", evidence.locator)

    def test_invalid_pom_raises_value_error_with_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pom.xml").write_text("<project>", encoding="utf-8")
            source = root / "src/main/java/demo/App.java"
            source.parent.mkdir(parents=True)
            source.write_text("package demo; class App {}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"pom\.xml"):
                JavaAnalyzer().analyze(root, 11)

    def test_uppercase_java_suffix_is_scanned_and_analyzed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {"src/main/java/demo/App.JAVA": "package demo;\n@Service\nclass App {}"},
            )

            structure = ProjectScanner.scan(root)
            model = JavaAnalyzer().analyze(root, 12)

        self.assertEqual(structure["language_counts"]["java"], 1)
        self.assertIn("App", {component.name for component in model.components})

    def test_uppercase_root_pom_and_package_private_handler_are_analyzed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "POM.XML").write_text(
                "<project><modelVersion>4.0.0</modelVersion>"
                "<artifactId>uppercase-fixture</artifactId></project>",
                encoding="utf-8",
            )
            source = root / "src/main/java/demo/PackageApi.java"
            source.parent.mkdir(parents=True)
            source.write_text(
                """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController
class PackageApi {
    @GetMapping(\"/package\")
    String packageHandler() { return \"ok\"; }
}
""",
                encoding="utf-8",
            )

            structure = ProjectScanner.scan(root)
            model = JavaAnalyzer().analyze(root, 18)

        self.assertEqual(structure["build_file"], "POM.XML")
        self.assertEqual(model.identity.name, "uppercase-fixture")
        self.assertIn("GET /package", {flow.name for flow in model.flows})

    def test_flow_ids_include_source_location_and_sequence_for_unresolved_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Api {
    @GetMapping(path = FIRST_PATH) @GetMapping(path = SECOND_PATH)
    public String first() { return \"ok\"; }
    public String second() { return \"ok\"; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 19)

        unresolved = [flow for flow in model.flows if "unresolved" in flow.name]
        self.assertEqual(len(unresolved), 2)
        flow_ids = [flow.id for flow in unresolved]
        self.assertEqual(len(flow_ids), len(set(flow_ids)))
        self.assertTrue(all("src/main/java/demo/Api.java" in flow_id for flow_id in flow_ids))
        self.assertTrue(all(":6:" in flow_id for flow_id in flow_ids))

    def test_same_simple_class_names_keep_distinct_qualified_ids_and_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/a/SharedService.java": "package a;\n@Service\npublic class SharedService {}",
                    "src/main/java/b/SharedService.java": "package b;\n@Service\npublic class SharedService {}",
                    "src/main/java/demo/Controller.java": """package demo;
import a.SharedService;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Controller {
    private final SharedService service;
    public Controller(SharedService service) { this.service = service; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 13)

        component_ids = {component.id for component in model.components}
        self.assertIn("a.SharedService", component_ids)
        self.assertIn("b.SharedService", component_ids)
        self.assertIn(
            ("demo.Controller", "a.SharedService", "DEPENDS_ON"),
            {(relation.source_id, relation.target_id, relation.kind) for relation in model.relations},
        )

    def test_mapping_named_attributes_and_multiline_annotations_use_correct_path_and_method(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/demo/Api.java": """package demo;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMethod;
@RestController
@RequestMapping(
    produces = \"application/json\",
    path = {\"/api\", \"/ignored\"},
    method = RequestMethod.GET
)
public class Api {
    @GetMapping(
        produces = \"application/json\",
        path = {\"/items\", \"/ignored\"}
    )
    public String list() { return \"ok\"; }
    @RequestMapping(
        method = RequestMethod.POST,
        value = {\"/items\", \"/ignored\"}
    )
    public String create() { return \"ok\"; }
    @RequestMapping(path = {\"/generic\", \"/ignored\"})
    public String generic() { return \"ok\"; }
}
""",
                },
            )
            annotation_line = next(
                index
                for index, line in enumerate(
                    (root / "src/main/java/demo/Api.java").read_text(encoding="utf-8").splitlines(),
                    1,
                )
                if "@GetMapping" in line
            )
            model = JavaAnalyzer().analyze(root, 14)

        self.assertIn("GET /api/items", {flow.name for flow in model.flows})
        self.assertIn("POST /api/items", {flow.name for flow in model.flows})
        self.assertIn("GET /api/generic", {flow.name for flow in model.flows})
        self.assertNotIn("GET /api/application/json", {flow.name for flow in model.flows})
        get_flow = next(flow for flow in model.flows if flow.name == "GET /api/items")
        get_evidence = next(
            evidence for evidence in model.evidence if evidence.id in get_flow.evidence_ids
        )
        self.assertIn(f"line {annotation_line}", get_evidence.locator)

    def test_scanner_and_analyzer_ignore_generated_directories_and_case_insensitive_java_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {"src/main/Java/App.JAVA": "package demo;\n@Service\nclass App {}"},
            )
            for directory in ("target", "build", ".gradle", "out"):
                generated = root / directory / "src/main/java/Generated.JAVA"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_text(
                    "package generated;\n@Service\nclass Generated {}", encoding="utf-8"
                )

            structure = ProjectScanner.scan(root)
            model = JavaAnalyzer().analyze(root, 15)

        self.assertIn("src/main/Java", structure["java_source_roots"])
        self.assertEqual(structure["language_counts"]["java"], 1)
        self.assertEqual({component.name for component in model.components}, {"App"})

    def test_wildcard_import_resolves_unique_known_component(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/a/SharedService.java": "package a;\n@Service\npublic class SharedService {}",
                    "src/main/java/demo/Controller.java": """package demo;
import a.*;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Controller {
    private final SharedService service;
    public Controller(SharedService service) { this.service = service; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 16)

        self.assertIn(
            ("demo.Controller", "a.SharedService", "DEPENDS_ON"),
            {(relation.source_id, relation.target_id, relation.kind) for relation in model.relations},
        )

    def test_ambiguous_wildcard_dependency_is_recorded_as_unresolved_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_maven_project(
                root,
                {
                    "src/main/java/a/SharedService.java": "package a;\n@Service\npublic class SharedService {}",
                    "src/main/java/b/SharedService.java": "package b;\n@Service\npublic class SharedService {}",
                    "src/main/java/demo/Controller.java": """package demo;
import a.*;
import b.*;
import org.springframework.web.bind.annotation.RestController;
@RestController
public class Controller {
    private final SharedService service;
    public Controller(SharedService service) { this.service = service; }
}
""",
                },
            )
            model = JavaAnalyzer().analyze(root, 17)

        self.assertTrue(
            any("unresolved" in insight.kind for insight in model.insights)
        )
        self.assertTrue(
            any("SharedService" in evidence.excerpt for evidence in model.evidence)
        )

    @staticmethod
    def _write_maven_project(root, files):
        (root / "pom.xml").write_text(
            "<project><modelVersion>4.0.0</modelVersion><artifactId>fixture</artifactId></project>",
            encoding="utf-8",
        )
        for relative_path, content in files.items():
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


class AnalyzerRegistryTests(unittest.TestCase):
    def test_registry_selects_java_analyzer_from_scanner_structure(self):
        structure = ProjectScanner().scan(FIXTURE_ROOT)
        registry = AnalyzerRegistry()
        registry.register(JavaAnalyzer())
        self.assertIsInstance(registry.select(structure), JavaAnalyzer)

    def test_registry_rejects_unsupported_structure_explicitly(self):
        registry = AnalyzerRegistry([JavaAnalyzer()])
        with self.assertRaisesRegex(LookupError, "No analyzer supports"):
            registry.select({"build_tool": "node", "language_counts": {"typescript": 1}})

    def test_registry_rejects_multiple_supporting_analyzers(self):
        class SupportingAnalyzer:
            analyzer_id = "supporting"

            def supports(self, structure):
                return True

            def analyze(self, artifact_root, project_id):
                raise AssertionError("not called")

        registry = AnalyzerRegistry([JavaAnalyzer(), SupportingAnalyzer()])
        with self.assertRaisesRegex(ValueError, "Multiple analyzers support"):
            registry.select(ProjectScanner().scan(FIXTURE_ROOT))

    def test_java_supports_rejects_invalid_language_counts(self):
        analyzer = JavaAnalyzer()
        self.assertFalse(analyzer.supports({"build_tool": "maven", "language_counts": {"java": "3"}}))
        self.assertFalse(analyzer.supports({"build_tool": "maven", "language_counts": {"java": True}}))


class GradleJavaAnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.structure = ProjectScanner.scan(GRADLE_FIXTURE_ROOT)
        cls.model = GradleJavaAnalyzer().analyze(GRADLE_FIXTURE_ROOT, 43)

    def test_analyzer_supports_gradle_java_and_is_not_maven_java_analyzer(self):
        self.assertEqual(GradleJavaAnalyzer().analyzer_id, "gradle-java")
        self.assertTrue(GradleJavaAnalyzer().supports(self.structure))
        self.assertFalse(JavaAnalyzer().supports(self.structure))

    def test_extracts_gradle_build_tool_spring_facts_dependencies_flows_transactions_and_evidence(self):
        self.assertEqual(self.model.metadata["build_tool"], "gradle")
        self.assertEqual(self.model.metadata["build_file"], "build.gradle")
        technology_names = {technology.name for technology in self.model.technologies}
        self.assertTrue(
            {"Gradle", "Spring Boot", "Spring Web", "Spring Data JPA", "MySQL"}
            <= technology_names
        )
        component_kinds = {component.name: component.kind for component in self.model.components}
        self.assertEqual(component_kinds["OrderController"], "RestController")
        self.assertEqual(component_kinds["OrderService"], "Service")
        self.assertEqual(component_kinds["OrderRepository"], "Repository")
        self.assertIn(
            ("demo.OrderController", "demo.OrderService", "DEPENDS_ON"),
            {(item.source_id, item.target_id, item.kind) for item in self.model.relations},
        )
        self.assertIn("GET /orders/{id}", {flow.name for flow in self.model.flows})
        self.assertIn("Transaction", {topic.name for topic in self.model.topics})
        evidence_ids = {item.id for item in self.model.evidence}
        self.assertTrue(all(set(item.evidence_ids) <= evidence_ids for item in self.model.components))
        self.assertTrue(any(item.source_path == "build.gradle" for item in self.model.evidence))

    def test_analyzer_supports_gradle_kotlin_build_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "build.gradle.kts").write_text(
                'plugins { id("java") }\n', encoding="utf-8"
            )
            source = root / "src/main/java/App.java"
            source.parent.mkdir(parents=True)
            source.write_text("class App {}\n", encoding="utf-8")

            structure = ProjectScanner.scan(root)

        self.assertTrue(GradleJavaAnalyzer().supports(structure))


if __name__ == "__main__":
    unittest.main()
