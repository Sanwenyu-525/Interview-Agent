import json
import time
import uuid
import zipfile
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .llm import LLMError
from .memory.profile_store import normalize_candidate_id
from .models import ProfileConflictError, SessionConflictError
from .service import (
    InterviewService,
    PositionNotFoundError,
    ProjectAnalysisError,
    ProjectNotFoundError,
    ResumeNotFoundError,
    SessionNotFoundError,
)


PUBLIC_API_OPERATIONS = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/projects"),
        ("POST", "/projects/upload"),
        ("GET", "/projects/{project_id}/status"),
        ("GET", "/projects/{project_id}/knowledge"),
        ("GET", "/positions"),
        ("POST", "/positions"),
        ("GET", "/positions/{position_id}"),
        ("PATCH", "/positions/{position_id}"),
        ("DELETE", "/positions/{position_id}"),
        ("POST", "/positions/{position_id}/questions"),
        ("GET", "/resumes"),
        ("POST", "/resumes"),
        ("GET", "/resumes/{resume_id}"),
        ("PATCH", "/resumes/{resume_id}"),
        ("DELETE", "/resumes/{resume_id}"),
        ("POST", "/sessions"),
        ("GET", "/sessions"),
        ("GET", "/sessions/{session_id}"),
        ("PATCH", "/sessions/{session_id}"),
        ("DELETE", "/sessions/{session_id}"),
        ("GET", "/sessions/{session_id}/report"),
        ("POST", "/sessions/{session_id}/answers"),
        ("POST", "/sessions/{session_id}/answers/stream"),
        ("POST", "/sessions/{session_id}/complete"),
        ("GET", "/candidates/{candidate_id}/profile"),
        ("GET", "/settings/llm"),
        ("POST", "/settings/llm"),
        ("POST", "/settings/llm/models"),
        ("POST", "/settings/llm/test"),
        ("GET", "/settings/llm/profiles"),
        ("POST", "/settings/llm/profiles"),
        ("PUT", "/settings/llm/profiles/{profile_id}"),
        ("DELETE", "/settings/llm/profiles/{profile_id}"),
        ("POST", "/settings/llm/profiles/{profile_id}/activate"),
        ("POST", "/settings/llm/profiles/{profile_id}/test"),
    }
)
ALLOWED_CORS_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "tauri.localhost", "terminal.local"}
)


def _json_value(value):
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def create_server(service: InterviewService, host: str = "127.0.0.1", port: int = 0):
    class Handler(BaseHTTPRequestHandler):
        def _current_request_id(self) -> str:
            request_id = getattr(self, "_interview_request_id", "")
            if not request_id:
                request_id = uuid.uuid4().hex
                self._interview_request_id = request_id
            return request_id

        def _allowed_cors_origin(self) -> str:
            origin = self.headers.get("Origin", "").strip()
            if not origin:
                return ""
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https", "tauri"}:
                return ""
            return origin if parsed.hostname in ALLOWED_CORS_HOSTS else ""

        def _send(self, status: int, payload):
            body = json.dumps(_json_value(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            allowed_origin = self._allowed_cors_origin()
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "X-Request-ID")
            self.send_header("X-Request-ID", self._current_request_id())
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_stream_headers(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            allowed_origin = self._allowed_cors_origin()
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "X-Request-ID")
            self.send_header("X-Request-ID", self._current_request_id())
            self.end_headers()
            self.close_connection = True

        def _send_stream_event(self, event: str, payload):
            body = json.dumps(_json_value(payload), ensure_ascii=False)
            self.wfile.write(f"event: {event}\ndata: {body}\n\n".encode("utf-8"))
            self.wfile.flush()

        def _stream_answer(self, session_id: str, payload: dict):
            self._send_stream_headers()
            try:
                self._send_stream_event(
                    "status",
                    {"stage": "preparing", "message": "正在读取当前问题和项目证据"},
                )
                self._send_stream_event("status", {"stage": "evaluating", "message": "正在评价回答"})
                submit_kwargs = {}
                if "candidate_id" in payload:
                    submit_kwargs["candidate_id"] = normalize_candidate_id(
                        payload["candidate_id"]
                    )
                state = service.submit_answer(
                    session_id, str(payload["answer"]), **submit_kwargs
                )
                self._send_stream_event(
                    "status",
                    {"stage": "reviewed", "message": "评价完成，正在整理评分和改进建议"},
                )
                reference_answer = getattr(state.evaluation, "reference_answer", "")
                if reference_answer:
                    self._send_stream_event(
                        "status", {"stage": "answering", "message": "正在生成参考回答"}
                    )
                    for index in range(0, len(reference_answer), 24):
                        self._send_stream_event(
                            "chunk", {"text": reference_answer[index : index + 24]}
                        )
                        time.sleep(0.018)
                self._send_stream_event(
                    "status", {"stage": "next_question", "message": "已生成下一道追问"}
                )
                self._send_stream_event(
                    "done", {"session_id": session_id, "state": state}
                )
            except Exception as exc:
                retryable = isinstance(exc, LLMError)
                self._send_stream_event(
                    "error",
                    {
                        "error": str(exc),
                        "code": "llm_upstream_error" if retryable else "answer_stream_failed",
                        "retryable": retryable,
                        "request_id": self._current_request_id(),
                    },
                )

        def _send_error(
            self,
            status: int,
            code: str,
            message: str,
            *,
            retryable: bool = False,
            extra: dict | None = None,
        ):
            payload = dict(extra or {})
            payload.update(
                {
                    "error": message,
                    "code": code,
                    "retryable": retryable,
                    "request_id": self._current_request_id(),
                }
            )
            self._send(status, payload)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "").strip()
            if origin and not self._allowed_cors_origin():
                self._send_error(403, "origin_not_allowed", "请求来源不在本地允许列表中")
                return
            self.send_response(204)
            allowed_origin = self._allowed_cors_origin()
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "X-Request-ID")
            self.send_header("X-Request-ID", self._current_request_id())
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _body(self):
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query, keep_blank_values=True)

            def query_value(name):
                values = query.get(name, [])
                if len(values) > 1:
                    raise ValueError(f"query parameter {name} must appear once")
                return values[0] if values else None

            try:
                if parts == ["health"]:
                    self._send(
                        200,
                        {"status": "ok", "service": "interview-agent", "api_version": "1"},
                    )
                    return
                if parts == ["sessions"]:
                    raw_limit = query_value("limit")
                    limit = int(raw_limit) if raw_limit is not None else 50
                    self._send(
                        200,
                        service.list_sessions(
                            candidate_id=query_value("candidate_id"),
                            project_id=query_value("project_id"),
                            position_id=query_value("position_id"),
                            limit=limit,
                        ),
                    )
                    return
                if parts == ["positions"]:
                    raw_limit = query_value("limit")
                    limit = int(raw_limit) if raw_limit is not None else 50
                    self._send(
                        200,
                        service.list_positions(
                            candidate_id=query_value("candidate_id") or "default",
                            limit=limit,
                        ),
                    )
                    return
                if parts == ["resumes"]:
                    raw_limit = query_value("limit")
                    limit = int(raw_limit) if raw_limit is not None else 50
                    self._send(
                        200,
                        service.list_resumes(
                            candidate_id=query_value("candidate_id"),
                            limit=limit,
                        ),
                    )
                    return
                if len(parts) == 2 and parts[0] == "positions":
                    self._send(200, service.get_position(parts[1]))
                    return
                if len(parts) == 2 and parts[0] == "resumes":
                    self._send(200, service.get_resume(parts[1]))
                    return
                if len(parts) == 2 and parts[0] == "sessions":
                    self._send(200, {"session_id": parts[1], "state": service.get_session(parts[1])})
                    return
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "report":
                    self._send(200, service.get_session_report(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "candidates" and parts[2] == "profile":
                    self._send(200, service.get_candidate_profile_summary(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "projects" and parts[2] == "status":
                    self._send(200, service.get_project_analysis(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "projects" and parts[2] == "knowledge":
                    self._send(200, service.get_project_knowledge(parts[1]))
                    return
                if parts == ["settings", "llm"]:
                    self._send(200, service.get_llm_settings())
                    return
                if parts == ["settings", "llm", "profiles"]:
                    self._send(200, service.get_llm_profiles())
                    return
                self._send_error(404, "route_not_found", "路由不存在")
            except (SessionConflictError, ProfileConflictError) as exc:
                self._send_error(409, "version_conflict", str(exc), retryable=True)
            except LLMError as exc:
                self._send_error(502, "llm_upstream_error", str(exc), retryable=True)
            except PositionNotFoundError as exc:
                self._send_error(404, "position_not_found", str(exc))
            except ResumeNotFoundError as exc:
                self._send_error(404, "resume_not_found", str(exc))
            except KeyError as exc:
                self._send_error(404, "resource_not_found", str(exc))
            except (TypeError, ValueError) as exc:
                self._send_error(400, "invalid_request", str(exc))

        def do_POST(self):
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "complete":
                    state = service.complete_session(parts[1])
                    self._send(200, {"session_id": parts[1], "state": state})
                    return
                if len(parts) == 3 and parts[0] == "positions" and parts[2] == "questions":
                    self._send(200, service.regenerate_position_questions(parts[1]))
                    return
                payload = self._body()
                if len(parts) == 4 and parts[0] == "sessions" and parts[2] == "answers" and parts[3] == "stream":
                    self._stream_answer(parts[1], payload)
                    return
                if parts == ["projects"]:
                    project = service.register_project(payload)
                    self._send(201, project)
                    return
                if parts == ["projects", "upload"]:
                    result = service.ingest_and_analyze_project(payload)
                    self._send(201, result)
                    return
                if parts == ["positions"]:
                    self._send(201, service.create_position(payload))
                    return
                if parts == ["resumes"]:
                    self._send(201, service.create_resume(payload))
                    return
                if parts == ["settings", "llm"]:
                    self._send(200, service.update_llm_settings(payload))
                    return
                if parts == ["settings", "llm", "models"]:
                    self._send(200, service.list_llm_models(payload))
                    return
                if parts == ["settings", "llm", "profiles"]:
                    self._send(201, service.create_llm_profile(payload))
                    return
                if len(parts) == 5 and parts[:3] == ["settings", "llm", "profiles"]:
                    profile_id = parts[3]
                    if parts[4] == "activate":
                        self._send(200, service.activate_llm_profile(profile_id))
                        return
                    if parts[4] == "test":
                        self._send(200, service.test_llm_profile(profile_id))
                        return
                if parts == ["settings", "llm", "test"]:
                    self._send(200, service.test_llm_settings(payload))
                    return
                if parts == ["sessions"]:
                    session_id, state = service.start_session(
                        payload["project_id"],
                        payload.get("candidate_id", "default"),
                        review_mode=payload.get("review_mode", "technical_interview"),
                        title=payload.get("title"),
                        topic_name=payload.get("topic"),
                        position_id=payload.get("position_id"),
                        position_question_id=payload.get("position_question_id"),
                    )
                    self._send(201, {"session_id": session_id, "state": state})
                    return
                if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "answers":
                    submit_kwargs = {}
                    if "candidate_id" in payload:
                        submit_kwargs["candidate_id"] = normalize_candidate_id(
                            payload["candidate_id"]
                        )
                    state = service.submit_answer(
                        parts[1], str(payload["answer"]), **submit_kwargs
                    )
                    self._send(200, {"session_id": parts[1], "state": state})
                    return
                self._send_error(404, "route_not_found", "路由不存在")
            except ProjectNotFoundError as exc:
                self._send_error(404, "project_not_found", str(exc))
            except SessionNotFoundError as exc:
                self._send_error(404, "session_not_found", str(exc))
            except PositionNotFoundError as exc:
                self._send_error(404, "position_not_found", str(exc))
            except ResumeNotFoundError as exc:
                self._send_error(404, "resume_not_found", str(exc))
            except (SessionConflictError, ProfileConflictError) as exc:
                self._send_error(409, "version_conflict", str(exc), retryable=True)
            except LLMError as exc:
                self._send_error(502, "llm_upstream_error", str(exc), retryable=True)
            except ProjectAnalysisError as exc:
                try:
                    analysis = _json_value(service.get_project_analysis(exc.project_id))
                    self._send_error(
                        422,
                        "project_analysis_failed",
                        str(exc),
                        extra=analysis,
                    )
                except KeyError:
                    self._send_error(
                        422,
                        "project_analysis_failed",
                        str(exc),
                        extra={"analysis_status": "FAILED"},
                    )
            except zipfile.BadZipFile as exc:
                response = {}
                try:
                    response = _json_value(
                        service.get_project_analysis(payload["project_id"])
                    )
                except (KeyError, TypeError, ValueError):
                    pass
                self._send_error(
                    400,
                    "invalid_archive",
                    f"{exc.__class__.__name__}: {exc}",
                    extra=response,
                )
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_error(400, "invalid_request", str(exc))

        def do_PUT(self):
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                payload = self._body()
                if len(parts) == 4 and parts[:3] == ["settings", "llm", "profiles"]:
                    self._send(200, service.update_llm_profile(parts[3], payload))
                    return
                self._send_error(404, "route_not_found", "路由不存在")
            except LLMError as exc:
                self._send_error(502, "llm_upstream_error", str(exc), retryable=True)
            except KeyError as exc:
                self._send_error(404, "resource_not_found", str(exc))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_error(400, "invalid_request", str(exc))

        def do_PATCH(self):
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                payload = self._body()
                if len(parts) == 2 and parts[0] == "sessions":
                    state = service.rename_session(parts[1], payload["title"])
                    self._send(200, {"session_id": parts[1], "state": state})
                    return
                if len(parts) == 2 and parts[0] == "positions":
                    self._send(200, service.update_position(parts[1], payload))
                    return
                if len(parts) == 2 and parts[0] == "resumes":
                    self._send(200, service.update_resume(parts[1], payload))
                    return
                self._send_error(404, "route_not_found", "路由不存在")
            except SessionNotFoundError as exc:
                self._send_error(404, "session_not_found", str(exc))
            except PositionNotFoundError as exc:
                self._send_error(404, "position_not_found", str(exc))
            except ResumeNotFoundError as exc:
                self._send_error(404, "resume_not_found", str(exc))
            except (SessionConflictError, ProfileConflictError) as exc:
                self._send_error(409, "version_conflict", str(exc), retryable=True)
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_error(400, "invalid_request", str(exc))

        def do_DELETE(self):
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            try:
                if len(parts) == 2 and parts[0] == "sessions":
                    service.delete_session(parts[1])
                    self._send(200, {"session_id": parts[1], "deleted": True})
                    return
                if len(parts) == 2 and parts[0] == "positions":
                    service.delete_position(parts[1])
                    self._send(200, {"position_id": parts[1], "deleted": True})
                    return
                if len(parts) == 2 and parts[0] == "resumes":
                    service.delete_resume(parts[1])
                    self._send(200, {"resume_id": parts[1], "deleted": True})
                    return
                if len(parts) == 4 and parts[:3] == ["settings", "llm", "profiles"]:
                    self._send(200, service.delete_llm_profile(parts[3]))
                    return
                self._send_error(404, "route_not_found", "路由不存在")
            except LLMError as exc:
                self._send_error(502, "llm_upstream_error", str(exc), retryable=True)
            except SessionNotFoundError as exc:
                self._send_error(404, "session_not_found", str(exc))
            except PositionNotFoundError as exc:
                self._send_error(404, "position_not_found", str(exc))
            except ResumeNotFoundError as exc:
                self._send_error(404, "resume_not_found", str(exc))
            except KeyError as exc:
                self._send_error(404, "resource_not_found", str(exc))
            except (ValueError, TypeError) as exc:
                self._send_error(400, "invalid_request", str(exc))

        def log_message(self, format, *args):
            return

    if host != "127.0.0.1":
        raise ValueError("Interview Agent API 只能绑定到本地回环地址 127.0.0.1")
    return ThreadingHTTPServer((host, port), Handler)
