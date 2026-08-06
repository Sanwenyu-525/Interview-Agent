import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from interview_agent.analyzers.frontend import FrontendAnalyzer
from interview_agent.analyzers.java import JavaAnalyzer
from interview_agent.analyzers.gradle_java import GradleJavaAnalyzer
from interview_agent.analyzers.python import PythonAnalyzer
from interview_agent.analyzers.registry import AnalyzerRegistry
from interview_agent.analyzers.scanner import ProjectScanner
from interview_agent.ingestion import FolderSource, IngestionService, WorkspaceManager
from interview_agent.models import AnalysisStatus
from interview_agent.service import InterviewService


JAVA_FIXTURE = Path(__file__).parent / "fixtures" / "java_project"
GRADLE_FIXTURE = Path(__file__).parent / "fixtures" / "gradle_java_project"


class AnalyzerRegistryTests(unittest.TestCase):
    def test_with_defaults_registers_java_python_and_frontend(self):
        registry = AnalyzerRegistry.with_defaults()

        self.assertEqual(
            {
                registry.get(analyzer_id).analyzer_id
                for analyzer_id in ("java", "gradle-java", "python", "frontend")
            },
            {"java", "gradle-java", "python", "frontend"},
        )

    def test_registry_selects_registered_builtin_adapter_by_scanner_structure(self):
        registry = AnalyzerRegistry(
            [GradleJavaAnalyzer(), JavaAnalyzer(), PythonAnalyzer(), FrontendAnalyzer()]
        )

        self.assertIsInstance(
            registry.select(ProjectScanner.scan(JAVA_FIXTURE)), JavaAnalyzer
        )
        self.assertIsInstance(
            registry.select(ProjectScanner.scan(GRADLE_FIXTURE)), GradleJavaAnalyzer
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            self.assertIsInstance(
                registry.select(ProjectScanner.scan(root)), PythonAnalyzer
            )

            (root / "package.json").write_text(
                '{"name":"web-app","scripts":{"build":"vite build"}}',
                encoding="utf-8",
            )
            (root / "app.ts").write_text("export const app = true;\n", encoding="utf-8")
            self.assertIsInstance(
                registry.select(ProjectScanner.scan(root)), FrontendAnalyzer
            )

    def test_registry_deterministically_separates_maven_and_gradle_java(self):
        registry = AnalyzerRegistry([JavaAnalyzer(), GradleJavaAnalyzer()])

        self.assertIsInstance(registry.select(ProjectScanner.scan(JAVA_FIXTURE)), JavaAnalyzer)
        self.assertIsInstance(
            registry.select(ProjectScanner.scan(GRADLE_FIXTURE)), GradleJavaAnalyzer
        )

    def test_registry_reports_no_supporter(self):
        with self.assertRaisesRegex(LookupError, "No analyzer supports scanner structure"):
            AnalyzerRegistry([PythonAnalyzer()]).select(
                {"build_tool": "maven", "language_counts": {"java": 1}}
            )

    def test_registry_reports_all_conflicting_supporters(self):
        class SupportingAnalyzer:
            analyzer_id = "supporting"

            def supports(self, structure):
                return True

            def analyze(self, artifact_root, project_id):
                raise AssertionError("not called")

        class AnotherSupportingAnalyzer(SupportingAnalyzer):
            analyzer_id = "another-supporting"

        registry = AnalyzerRegistry([SupportingAnalyzer(), AnotherSupportingAnalyzer()])

        with self.assertRaisesRegex(
            ValueError, "Multiple analyzers support scanner structure: supporting, another-supporting"
        ):
            registry.select({"files": []})


class AnalyzerFixtureTests(unittest.TestCase):
    def test_python_adapter_extracts_modules_entrypoint_dependencies_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text(
                "requests==2.32.0\nfastapi>=0.100\n", encoding="utf-8"
            )
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'sample-python'\n", encoding="utf-8"
            )
            (root / "src" / "sample_app").mkdir(parents=True)
            (root / "src" / "sample_app" / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            (root / "src" / "sample_app" / "main.py").write_text(
                "# module header\n"
                "# evidence must not use this line\n"
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "def main():\n    return app\n\n"
                "if __name__ == '__main__':\n    main()\n",
                encoding="utf-8",
            )
            (root / "src" / "sample_app" / "service.py").write_text(
                "class OrderService:\n    pass\n", encoding="utf-8"
            )

            scanned_files = set(ProjectScanner.scan(root)["files"])
            analyzer = PythonAnalyzer()
            model = analyzer.analyze(root, 11)

        self.assertEqual(model.identity.artifact_type, "python_project")
        self.assertIn("sample_app.main", {node.name for node in model.structure})
        self.assertIn("main", {component.name for component in model.components})
        self.assertIn("requirements.txt", model.metadata["dependency_files"])
        self.assertIn("pyproject.toml", model.metadata["dependency_files"])
        self.assertIn("requests", model.dependencies["requirements.txt"])
        self.assertIn("fastapi", model.dependencies["requirements.txt"])
        evidence_paths = {item.source_path for item in model.evidence}
        self.assertIn("src/sample_app/main.py", evidence_paths)
        self.assertIn("requirements.txt", evidence_paths)
        self.assertTrue(evidence_paths.issubset(scanned_files))
        self.assertTrue(all(item.evidence_ids for item in model.components))
        main_evidence = next(
            item for item in model.evidence
            if item.kind == "python_symbol" and "(main)" in item.locator
        )
        self.assertIn("line 7", main_evidence.locator)
        self.assertEqual(main_evidence.excerpt, "def main():")
        self.assertEqual(model.topics, [])
        json.dumps(asdict(model), ensure_ascii=False)

    def test_frontend_adapter_extracts_components_routes_api_and_build_tool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "sample-web",
                        "scripts": {"dev": "vite", "build": "vite build"},
                        "dependencies": {"react": "18.3.0", "axios": "1.7.0"},
                        "devDependencies": {"vite": "5.4.0", "typescript": "5.5.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src" / "App.tsx").write_text(
                "export function App() { return null; }\n", encoding="utf-8"
            )
            (root / "src" / "routes.tsx").write_text(
                "const routes = [\n"
                "  { path: '/orders', element: Orders },\n"
                "  { path: '/a/b', element: A },\n"
                "  { path: '/a-b', element: B },\n"
                "];\n",
                encoding="utf-8",
            )
            (root / "src" / "api.ts").write_text(
                "export async function loadOrders() {\n"
                "  return fetch('/api/orders');\n}\n",
                encoding="utf-8",
            )
            (root / "src" / "other.ts").write_text(
                "export function loadAgain() { return fetch('/api/orders'); }\n"
                "export const otherRoute = { path: '/orders' };\n",
                encoding="utf-8",
            )
            (root / "src" / "duplicates.tsx").write_text(
                "function Card() { return null; }\n"
                "function Card() { return null; }\n"
                "function Card() { return null; }\n",
                encoding="utf-8",
            )

            model = FrontendAnalyzer().analyze(root, 12)

        self.assertEqual(model.identity.artifact_type, "frontend_project")
        self.assertIn("App", {component.name for component in model.components})
        component_ids = [component.id for component in model.components]
        self.assertEqual(len(component_ids), len(set(component_ids)))
        self.assertEqual(len(model.components), len({item.name for item in model.components}))
        self.assertTrue(any("src/duplicates.tsx" in item and ":line:" in item for item in component_ids))
        self.assertIn("/orders", {flow.name for flow in model.flows})
        route_flows = [flow for flow in model.flows if flow.name in {"/a/b", "/a-b"}]
        self.assertEqual(len(route_flows), 2)
        self.assertEqual(len({flow.id for flow in route_flows}), 2)
        orders_flows = [flow for flow in model.flows if flow.name == "/orders"]
        self.assertEqual(len(orders_flows), 2)
        self.assertEqual(
            {
                item.source_path
                for flow in orders_flows
                for item in model.evidence
                if item.id in flow.evidence_ids
            },
            {"src/routes.tsx", "src/other.ts"},
        )
        api_relations = [relation for relation in model.relations if relation.target_id == "/api/orders"]
        self.assertEqual(len(api_relations), 2)
        self.assertEqual({relation.source_id for relation in api_relations}, {"src/api.ts", "src/other.ts"})
        self.assertIn("vite", {technology.name for technology in model.technologies})
        self.assertTrue(any(item.source_path == "package.json" for item in model.evidence))
        self.assertEqual(model.topics, [])
        json.dumps(asdict(model), ensure_ascii=False)

    def test_frontend_source_path_ids_do_not_collide_after_sanitizing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text('{"name":"collision"}', encoding="utf-8")
            (root / "a").mkdir()
            (root / "a" / "b.ts").write_text("export const Left = 1;\n", encoding="utf-8")
            (root / "a-b.ts").write_text("export const Right = 1;\n", encoding="utf-8")

            model = FrontendAnalyzer().analyze(root, 19)

        evidence_ids = [item.id for item in model.evidence]
        self.assertEqual(len(evidence_ids), len(set(evidence_ids)))
        source_evidence = [item for item in model.evidence if item.kind == "frontend_source"]
        self.assertEqual({item.source_path for item in source_evidence}, {"a/b.ts", "a-b.ts"})

    def test_python_module_ids_keep_distinct_relative_file_shapes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a").mkdir()
            (root / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "a" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "a" / "b.py").write_text("VALUE = 3\n", encoding="utf-8")
            (root / "a-b.py").write_text("VALUE = 4\n", encoding="utf-8")

            model = PythonAnalyzer().analyze(root, 20)

        module_nodes = [item for item in model.structure if item.kind == "module"]
        self.assertEqual(
            {item.path for item in module_nodes},
            {"a.py", "a/__init__.py", "a/b.py", "a-b.py"},
        )
        self.assertEqual(len(module_nodes), len({item.id for item in module_nodes}))
        self.assertTrue(all(item.path in item.id for item in module_nodes))
        evidence_ids = [item.id for item in model.evidence]
        self.assertEqual(len(evidence_ids), len(set(evidence_ids)))

    def test_python_multiple_entrypoints_keep_all_source_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a").mkdir()
            (root / "a.py").write_text(
                "def main():\n    return 'file'\n", encoding="utf-8"
            )
            (root / "a" / "__init__.py").write_text(
                "def main():\n    return 'package'\n", encoding="utf-8"
            )

            model = PythonAnalyzer().analyze(root, 21)

        entrypoint_components = [item for item in model.components if item.kind == "entrypoint"]
        entrypoint_evidence_ids = {
            evidence_id
            for component in entrypoint_components
            for evidence_id in component.evidence_ids
        }
        flow = next(item for item in model.flows if item.id == "python-entrypoint")
        self.assertEqual(len(entrypoint_components), 2)
        self.assertEqual(set(flow.component_ids), {item.id for item in entrypoint_components})
        self.assertEqual(set(flow.evidence_ids), entrypoint_evidence_ids)
        self.assertEqual(len(flow.evidence_ids), 2)
        self.assertEqual(
            {item.source_path for item in model.evidence if item.id in flow.evidence_ids},
            {"a.py", "a/__init__.py"},
        )

    def test_python_repeated_same_file_symbol_names_are_unique_and_traceable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "repeat.py").write_text(
                "def run():\n    return 1\n\n"
                "def run():\n    return 2\n\n"
                "def run():\n    return 3\n",
                encoding="utf-8",
            )

            model = PythonAnalyzer().analyze(root, 22)

        components = [item for item in model.components if item.path == "repeat.py"]
        self.assertEqual(len(components), 3)
        self.assertEqual(len({item.name for item in components}), 3)
        self.assertTrue(all(item.evidence_ids for item in components))
        self.assertTrue(all("repeat.py" in item.id for item in components))

    def test_python_duplicate_symbols_have_stable_unique_source_position_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "duplicate.py").write_text(
                "def run():\n    return 1\n\n"
                "def run():\n    return 2\n",
                encoding="utf-8",
            )

            model = PythonAnalyzer().analyze(root, 16)

        components = [item for item in model.components if item.name in {"run", "duplicate.run"}]
        component_ids = [item.id for item in components]
        self.assertEqual(len(component_ids), 2)
        self.assertEqual(len(component_ids), len(set(component_ids)))
        self.assertTrue(all("src/duplicate.py" in item and ":line:" in item for item in component_ids))

    def test_frontend_rejects_non_object_root_package_json_with_path(self):
        for manifest, expected_status, expected_message in (
            ("{", "invalid_json", "invalid JSON"),
            ("[]", "invalid_shape", "top-level object"),
            ("null", "invalid_shape", "top-level object"),
        ):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "package.json").write_text(manifest, encoding="utf-8")
                (root / "app.ts").write_text("export const app = true;\n", encoding="utf-8")

                structure = ProjectScanner.scan(root)
                self.assertEqual(structure["manifest_status"], expected_status)
                self.assertFalse(FrontendAnalyzer().supports(structure))
                with self.assertRaisesRegex(ValueError, rf"package\.json.*{expected_message}") as context:
                    FrontendAnalyzer().analyze(root, 17)
                self.assertIn(str(root / "package.json"), str(context.exception))

    def test_python_syntax_error_reports_source_path_and_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "broken.py").write_text(
                "def valid():\n    return True\n\ndef broken(:\n    pass\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, r"src[\\/]broken\.py.*line 4"):
                PythonAnalyzer().analyze(root, 18)

    def test_analyzers_use_root_entrypoints_and_ignore_nested_packages_and_node_modules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "backend.py").write_text(
                "def serve():\n    return True\n", encoding="utf-8"
            )
            (root / "src" / "package.json").write_text(
                '{"name":"nested-frontend"}', encoding="utf-8"
            )
            python_structure = ProjectScanner.scan(root)

            self.assertTrue(PythonAnalyzer().supports(python_structure))
            self.assertEqual(PythonAnalyzer().analyze(root, 15).identity.artifact_type, "python_project")
            self.assertFalse(FrontendAnalyzer().supports(python_structure))

            (root / "package.json").write_text(
                '{"name":"root-frontend","scripts":{"build":"vite build"}}',
                encoding="utf-8",
            )
            (root / "src" / "App.tsx").write_text(
                "export function App() { return null; }\n", encoding="utf-8"
            )
            (root / "node_modules" / "vendor").mkdir(parents=True)
            (root / "node_modules" / "vendor" / "package.json").write_text(
                '{"name":"vendor"}', encoding="utf-8"
            )
            (root / "node_modules" / "vendor" / "Library.tsx").write_text(
                "export function Library() { return null; }\n", encoding="utf-8"
            )
            frontend_structure = ProjectScanner.scan(root)

            self.assertTrue(FrontendAnalyzer().supports(frontend_structure))
            frontend_model = FrontendAnalyzer().analyze(root, 14)
            self.assertIn("App", {item.name for item in frontend_model.components})
            self.assertNotIn("Library", {item.name for item in frontend_model.components})
            self.assertNotIn("node_modules/package.json", frontend_model.metadata["source_files"])

    def test_default_service_analyzes_python_and_frontend_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = InterviewService(
                ingestion_service=IngestionService(
                    WorkspaceManager(Path(temp_dir) / "workspace")
                )
            )
            service.ingest_project(
                FolderSource(
                    {
                        "requirements.txt": b"requests\n",
                        "app.py": b"def main():\n    return True\n",
                    }
                ),
                41,
            )
            service.ingest_project(
                FolderSource(
                    {
                        "package.json": b'{"name":"web"}',
                        "src/App.tsx": b"export function App() { return null; }\n",
                    }
                ),
                42,
            )

            python_result = service.analyze_project(41)
            frontend_result = service.analyze_project(42)

        self.assertEqual(python_result.analysis_status, AnalysisStatus.READY)
        self.assertEqual(python_result.analyzer_id, "python")
        self.assertEqual(frontend_result.analysis_status, AnalysisStatus.READY)
        self.assertEqual(frontend_result.analyzer_id, "frontend")

    def test_java_maven_project_remains_java_analyzer_with_all_adapters_registered(self):
        registry = AnalyzerRegistry([PythonAnalyzer(), FrontendAnalyzer(), JavaAnalyzer()])

        selected = registry.select(ProjectScanner.scan(JAVA_FIXTURE))

        self.assertIsInstance(selected, JavaAnalyzer)
        model = selected.analyze(JAVA_FIXTURE, 13)
        self.assertEqual(model.identity.artifact_type, "java_backend")


if __name__ == "__main__":
    unittest.main()
