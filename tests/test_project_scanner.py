import json
import tempfile
import unittest
from pathlib import Path

from interview_agent.analyzers.scanner import (
    ProjectScanner,
    is_ignored_path,
    iter_project_files,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "java_project"
GRADLE_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gradle_java_project"


class ProjectScannerTests(unittest.TestCase):
    def test_scan_returns_serializable_maven_project_structure(self):
        structure = ProjectScanner().scan(FIXTURE_ROOT)

        json.dumps(structure)
        self.assertEqual(structure["build_tool"], "maven")
        self.assertEqual(structure["language_counts"]["java"], 3)
        self.assertIn("src/main/java", structure["java_source_roots"])
        self.assertIn("src/main/resources/application.yml", structure["config_files"])
        self.assertEqual(structure["file_count"], 5)

    def test_scan_detects_gradle_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "build.gradle").write_text("plugins { id 'java' }", encoding="utf-8")
            (root / "src" / "main" / "java").mkdir(parents=True)
            (root / "src" / "main" / "java" / "Main.java").write_text(
                "class Main {}", encoding="utf-8"
            )

            structure = ProjectScanner().scan(root)

        self.assertEqual(structure["build_tool"], "gradle")
        self.assertEqual(structure["language_counts"]["java"], 1)
        self.assertEqual(structure["file_count"], 2)

    def test_scan_detects_gradle_fixture_with_root_build_file_and_java_source(self):
        structure = ProjectScanner.scan(GRADLE_FIXTURE_ROOT)

        self.assertEqual(structure["build_tool"], "gradle")
        self.assertEqual(structure["build_file"], "build.gradle")
        self.assertEqual(structure["language_counts"]["java"], 3)
        self.assertIn("src/main/java", structure["java_source_roots"])

    def test_scan_rejects_non_directory(self):
        with self.assertRaises(ValueError):
            ProjectScanner().scan(FIXTURE_ROOT / "pom.xml")

    def test_nested_pom_does_not_mark_root_as_maven(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "module").mkdir()
            (root / "module" / "pom.xml").write_text("<project />", encoding="utf-8")
            (root / "README.md").write_text("root project", encoding="utf-8")

            structure = ProjectScanner.scan(root)

        self.assertIsNone(structure["build_tool"])

    def test_root_build_file_preserves_case_and_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "POM.XML").write_text("<project />", encoding="utf-8")

            structure = ProjectScanner.scan(root)

        self.assertEqual(structure["build_tool"], "maven")
        self.assertEqual(structure["build_file"], "POM.XML")

    def test_iter_project_files_uses_scanner_generation_directory_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "Main.java").write_text("class Main {}", encoding="utf-8")
            generated = root / "target" / "Generated.java"
            generated.parent.mkdir()
            generated.write_text("class Generated {}", encoding="utf-8")

            files = [path.relative_to(root).as_posix() for path in iter_project_files(root)]

        self.assertEqual(files, ["src/Main.java"])

    def test_scanner_and_public_ignore_helper_exclude_node_modules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "App.tsx").write_text("export const App = 1;", encoding="utf-8")
            (root / "node_modules" / "vendor").mkdir(parents=True)
            (root / "node_modules" / "vendor" / "Vendor.tsx").write_text(
                "export const Vendor = 1;", encoding="utf-8"
            )

            structure = ProjectScanner.scan(root)
            files = [path.relative_to(root).as_posix() for path in iter_project_files(root)]

        self.assertIn("src/App.tsx", files)
        self.assertNotIn("node_modules/vendor/Vendor.tsx", files)
        self.assertEqual(structure["language_counts"], {"typescript": 1})
        self.assertTrue(is_ignored_path("node_modules/vendor/Vendor.tsx"))


if __name__ == "__main__":
    unittest.main()
