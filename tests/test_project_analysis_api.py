import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from interview_agent.http_api import create_server
from interview_agent.analyzers.java import JavaAnalyzer
from interview_agent.analyzers.registry import AnalyzerRegistry
from interview_agent.ingestion import FolderSource, IngestionService, WorkspaceManager, ZipSource
from interview_agent.models import AnalysisStatus
from interview_agent.service import InterviewService, ProjectAnalysisError
from interview_agent.sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


JAVA_FILES = {
    "pom.xml": (
        "<project><modelVersion>4.0.0</modelVersion>"
        "<artifactId>analysis-fixture</artifactId></project>"
    ).encode(),
    "src/main/java/demo/Api.java": (
        "package demo;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.RestController;\n"
        "@RestController\n"
        "class Api { @GetMapping(\"/items\") String items() { return \"ok\"; } }\n"
    ).encode(),
}


def _service(workspace: Path, repository=None, session_store=None):
    return InterviewService(
        repository=repository,
        session_store=session_store,
        ingestion_service=IngestionService(WorkspaceManager(workspace)),
    )


def _request_json(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


class ProjectAnalysisServiceTests(unittest.TestCase):
    def test_project_id_validation_rejects_bool_and_float_at_service_boundaries(self):
        service = InterviewService()
        for invalid_id in (True, False, 1.5):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ValueError):
                    service.register_project(
                        {"project_id": invalid_id, "project_name": "bad", "topics": []}
                    )
                with self.assertRaises(ValueError):
                    service.start_session(invalid_id)

    def test_folder_ingestion_and_analysis_reaches_ready_with_knowledge(self):
        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")

            created = service.ingest_project(FolderSource(JAVA_FILES), "21", "订单服务")
            self.assertEqual(created.analysis_status, AnalysisStatus.SOURCE_READY)

            ready = service.analyze_project(21)

            self.assertEqual(ready.analysis_status, AnalysisStatus.READY)
            self.assertEqual(ready.analyzer_id, "java")
            self.assertEqual(ready.knowledge.project_name, "订单服务")
            self.assertEqual(ready.universal_model.project_id, 21)
            self.assertTrue(ready.knowledge.topics)

    def test_zip_ingestion_and_analysis_reaches_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "project.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                for path, content in JAVA_FILES.items():
                    zipped.writestr(f"project/{path}", content)
            service = _service(Path(directory) / "workspace")

            service.ingest_project(ZipSource(archive), 22)
            result = service.analyze_project(22)

            self.assertEqual(result.analysis_status, AnalysisStatus.READY)
            self.assertEqual(result.knowledge.project_id, 22)

    def test_empty_project_is_failed_and_keeps_readable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")
            service.ingest_project(FolderSource(()), 23)

            with self.assertRaises(ProjectAnalysisError):
                service.analyze_project(23)

            failed = service.get_project_analysis(23)
            self.assertEqual(failed.analysis_status, AnalysisStatus.FAILED)
            self.assertIn("supports", failed.error)

    def test_reingest_clears_old_knowledge_before_new_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")
            service.register_project(
                {
                    "project_id": 29,
                    "project_name": "旧项目",
                    "topics": [{"name": "Old", "score": 90}],
                }
            )

            service.ingest_project(FolderSource(()), 29, "新项目")
            with self.assertRaises(KeyError):
                service.repository.get(29)
            with self.assertRaises(ProjectAnalysisError):
                service.analyze_project(29)
            with self.assertRaises(KeyError):
                service.get_project_knowledge(29)

    def test_retrying_ready_project_clears_old_results_before_failed_analysis(self):
        class FailingAnalyzer:
            analyzer_id = "failing"

            def supports(self, structure):
                return True

            def analyze(self, artifact_root, project_id):
                raise RuntimeError("retry failed")

        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")
            service.ingest_project(FolderSource(JAVA_FILES), 30, "可重试项目")
            ready = service.analyze_project(30)
            self.assertIsNotNone(ready.universal_model)
            self.assertIsNotNone(ready.knowledge)
            service.analyzer_registry = AnalyzerRegistry([FailingAnalyzer()])

            with self.assertRaises(ProjectAnalysisError):
                service.analyze_project(30)

            failed = service.get_project_analysis(30)
            self.assertEqual(failed.analysis_status, AnalysisStatus.FAILED)
            self.assertIsNone(failed.universal_model)
            self.assertIsNone(failed.knowledge)
            with self.assertRaises(KeyError):
                service.get_project_knowledge(30)
            with self.assertRaises(KeyError):
                service.repository.get(30)

    def test_analyzer_project_id_mismatch_fails_without_saving_wrong_knowledge(self):
        class WrongProjectIdAnalyzer:
            analyzer_id = "wrong-project-id"

            def supports(self, structure):
                return True

            def analyze(self, artifact_root, project_id):
                model = JavaAnalyzer().analyze(artifact_root, project_id)
                return replace(model, project_id=project_id + 1000)

        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")
            service.analyzer_registry = AnalyzerRegistry([WrongProjectIdAnalyzer()])
            service.ingest_project(FolderSource(JAVA_FILES), 31, "错误模型项目")

            with self.assertRaisesRegex(ProjectAnalysisError, "project_id"):
                service.analyze_project(31)

            failed = service.get_project_analysis(31)
            self.assertEqual(failed.analysis_status, AnalysisStatus.FAILED)
            self.assertIsNone(failed.universal_model)
            self.assertIsNone(failed.knowledge)
            with self.assertRaises(KeyError):
                service.repository.get(31)

    def test_sqlite_recreates_ready_and_failed_analysis_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = str(root / "analysis.db")
            repository = SQLiteProjectRepository(database)
            first = _service(
                root / "workspace",
                repository=repository,
                session_store=SQLiteSessionStore(database),
            )
            first.ingest_project(FolderSource(JAVA_FILES), 24)
            first.analyze_project(24)
            first.ingest_project(FolderSource(()), 25)
            with self.assertRaises(ProjectAnalysisError):
                first.analyze_project(25)

            second = _service(
                root / "workspace",
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
            )

            self.assertEqual(
                second.get_project_analysis(24).analysis_status, AnalysisStatus.READY
            )
            self.assertEqual(second.get_project_analysis(24).analyzer_id, "java")
            self.assertEqual(
                second.get_project_analysis(24).universal_model.identity.name,
                "analysis-fixture",
            )
            self.assertEqual(
                second.get_project_analysis(25).analysis_status, AnalysisStatus.FAILED
            )
            self.assertEqual(second.get_project_analysis(25).analyzer_id, "")
            self.assertTrue(second.get_project_knowledge(24).topics)


class ProjectAnalysisHttpTests(unittest.TestCase):
    def test_upload_status_and_knowledge_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            service = _service(Path(directory) / "workspace")
            server = create_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                status, uploaded = _request_json(
                    f"{base_url}/projects/upload",
                    "POST",
                    {
                        "project_id": "26",
                        "project_name": "HTTP 项目",
                        "source": {
                            "type": "folder",
                            "files": [
                                {"path": path, "content": content.decode()}
                                for path, content in JAVA_FILES.items()
                            ],
                        },
                    },
                )
                self.assertEqual(status, 201)
                self.assertEqual(uploaded["analysis_status"], "READY")

                status, project_status = _request_json(
                    f"{base_url}/projects/26/status"
                )
                self.assertEqual(status, 200)
                self.assertEqual(project_status["analysis_status"], "READY")

                status, knowledge = _request_json(
                    f"{base_url}/projects/26/knowledge"
                )
                self.assertEqual(status, 200)
                self.assertEqual(knowledge["project_id"], 26)
                self.assertTrue(knowledge["topics"])
            finally:
                server.shutdown()
                server.server_close()

    def test_upload_unsupported_project_returns_failed_status(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(_service(Path(directory) / "workspace"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, body = _request_json(
                    f"http://127.0.0.1:{server.server_port}/projects/upload",
                    "POST",
                    {
                        "project_id": 27,
                        "source": {"type": "folder", "files": []},
                    },
                )
                self.assertEqual(status, 422)
                self.assertEqual(body["analysis_status"], "FAILED")
                self.assertIn("supports", body["error"])
            finally:
                server.shutdown()
                server.server_close()

    def test_upload_rejects_bool_and_float_project_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(_service(Path(directory) / "workspace"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for invalid_id in (True, 1.5):
                    with self.subTest(invalid_id=invalid_id):
                        status, body = _request_json(
                            f"http://127.0.0.1:{server.server_port}/projects/upload",
                            "POST",
                            {
                                "project_id": invalid_id,
                                "source": {"type": "folder", "files": []},
                            },
                        )
                        self.assertEqual(status, 400)
                        self.assertIn("project_id", body["error"])
            finally:
                server.shutdown()
                server.server_close()

    def test_upload_zip_source_path_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "project.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                for path, content in JAVA_FILES.items():
                    zipped.writestr(path, content)
            server = create_server(_service(root / "workspace"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, body = _request_json(
                    f"http://127.0.0.1:{server.server_port}/projects/upload",
                    "POST",
                    {
                        "project_id": 28,
                        "source": {"type": "zip", "source_path": str(archive)},
                    },
                )
                self.assertEqual(status, 201)
                self.assertEqual(body["analysis_status"], "READY")
                self.assertEqual(body["analyzer_id"], "java")
            finally:
                server.shutdown()
                server.server_close()

    def test_upload_corrupt_zip_returns_json_error_and_persists_failed_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "corrupt.zip"
            archive.write_bytes(b"not a zip archive")
            service = _service(root / "workspace")
            server = create_server(service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, body = _request_json(
                    f"http://127.0.0.1:{server.server_port}/projects/upload",
                    "POST",
                    {
                        "project_id": 32,
                        "source": {"type": "zip", "source_path": str(archive)},
                    },
                )
                self.assertEqual(status, 400)
                self.assertEqual(body["analysis_status"], "FAILED")
                self.assertIn("BadZipFile", body["error"])
                self.assertEqual(
                    service.get_project_analysis(32).analysis_status,
                    AnalysisStatus.FAILED,
                )
                with self.assertRaises(KeyError):
                    service.get_project_knowledge(32)
            finally:
                server.shutdown()
                server.server_close()

    def test_sessions_distinguish_missing_project_from_invalid_project_id(self):
        server = create_server(InterviewService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _request_json(
                f"http://127.0.0.1:{server.server_port}/sessions",
                "POST",
                {"project_id": 9999},
            )
            self.assertEqual(status, 404)
            self.assertIn("error", body)

            for invalid_id in (True, 1.5):
                with self.subTest(invalid_id=invalid_id):
                    status, body = _request_json(
                        f"http://127.0.0.1:{server.server_port}/sessions",
                        "POST",
                        {"project_id": invalid_id},
                    )
                    self.assertEqual(status, 400)
            self.assertIn("project_id", body["error"])

            status, body = _request_json(
                f"http://127.0.0.1:{server.server_port}/sessions/missing/answers",
                "POST",
                {"answer": "answer"},
            )
            self.assertEqual(status, 404)
            self.assertIn("error", body)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
