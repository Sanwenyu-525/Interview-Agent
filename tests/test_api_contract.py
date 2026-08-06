import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from interview_agent.http_api import PUBLIC_API_OPERATIONS, create_server
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.service import InterviewService


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "docs" / "api" / "openapi.json"
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    def test_openapi_contract_covers_every_public_operation(self):
        documented = {
            (method.upper(), path)
            for path, path_item in self.contract["paths"].items()
            for method in path_item
            if method in HTTP_METHODS
        }
        self.assertEqual(documented, PUBLIC_API_OPERATIONS)

    def test_operation_ids_are_present_and_unique(self):
        operation_ids = [
            operation["operationId"]
            for path_item in self.contract["paths"].values()
            for method, operation in path_item.items()
            if method in HTTP_METHODS
        ]
        self.assertEqual(len(operation_ids), len(PUBLIC_API_OPERATIONS))
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_all_local_openapi_references_resolve(self):
        def visit(value):
            if isinstance(value, dict):
                reference = value.get("$ref")
                if reference is not None:
                    self.assertTrue(reference.startswith("#/"), reference)
                    target = self.contract
                    for part in reference[2:].split("/"):
                        self.assertIn(part, target, reference)
                        target = target[part]
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.contract)

    def test_error_schema_keeps_legacy_message_and_structured_fields(self):
        required = set(
            self.contract["components"]["schemas"]["ErrorResponse"]["required"]
        )
        self.assertEqual(required, {"error", "code", "retryable", "request_id"})

    def test_runtime_health_and_error_responses_match_contract(self):
        service = InterviewService(repository=InMemoryProjectRepository())
        server = create_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(f"{base_url}/health") as response:
                health = json.loads(response.read().decode("utf-8"))
                self.assertEqual(health["status"], "ok")
                self.assertTrue(response.headers["X-Request-ID"])

            with self.assertRaises(HTTPError) as context:
                urlopen(f"{base_url}/missing")
            error = context.exception
            payload = json.loads(error.read().decode("utf-8"))
            self.assertEqual(error.code, 404)
            self.assertEqual(payload["code"], "route_not_found")
            self.assertFalse(payload["retryable"])
            self.assertEqual(error.headers["X-Request-ID"], payload["request_id"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
