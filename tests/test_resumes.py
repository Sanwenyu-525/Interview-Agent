import base64
import json
import tempfile
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from interview_agent.http_api import create_server
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.resumes import (
    SQLiteResumeStore,
    active_claim_texts,
    extract_claims,
    extract_pdf_text,
    extract_resume_name,
    resume_from_dict,
)
from interview_agent.service import InterviewService, ResumeNotFoundError
from interview_agent.sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


PROJECTS = (
    {
        "project_id": 21,
        "project_name": "OrderFlow Service",
        "topics": [{"name": "订单", "score": 90, "evidence": ["e-order"]}],
        "evidence": {"e-order": {"source_path": "OrderService.java", "excerpt": "order"}},
    },
    {
        "project_id": 22,
        "project_name": "DataViz Portal",
        "topics": [{"name": "可视化", "score": 85, "evidence": ["e-chart"]}],
        "evidence": {"e-chart": {"source_path": "ChartPanel.java", "excerpt": "chart"}},
    },
)

SAMPLE_RESUME = """林澈
后端工程师 · 交易系统
联系方式：lin@example.com
教育背景
2016.09 - 2020.06  某大学 计算机科学与技术
工作经历
- 主导订单创建与幂等校验链路设计，将关键查询延迟降低 38%
- 负责 Redis 缓存失效与监控告警，实现故障自动恢复
- 参与交易系统容量评估，推动分库分表方案落地
专业技能
Java、Spring、MySQL、Redis
"""


def create_service(**kwargs):
    service = InterviewService(repository=kwargs.pop("repository", InMemoryProjectRepository()), **kwargs)
    for project in PROJECTS:
        service.register_project(project)
    return service


def make_pdf_bytes(text: str) -> bytes:
    """构造一个含文本层的单页 PDF（ASCII 文本），供 pypdf 提取。"""
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = b"BT /F1 12 Tf 72 720 Td (%s) Tj ET\n" % escaped.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    header = b"%PDF-1.4\n"
    body = b""
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body += b"%d 0 obj\n" % index + obj + b"\nendobj\n"
    xref_position = len(header) + len(body)
    xref = b"xref\n0 %d\n" % (len(objects) + 1)
    xref += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        xref += b"%010d 00000 n \n" % offset
    trailer = (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_position)
    )
    return header + body + xref + trailer


class ResumeExtractionTests(unittest.TestCase):
    def test_extract_name_from_first_line(self):
        self.assertEqual(extract_resume_name(SAMPLE_RESUME), "林澈")
        self.assertEqual(extract_resume_name("这份简历没有姓名行"), "")

    def test_extract_claims_skips_headings_timeline_and_contact(self):
        claims = extract_claims(SAMPLE_RESUME)
        self.assertEqual(
            claims,
            (
                "主导订单创建与幂等校验链路设计，将关键查询延迟降低 38%",
                "负责 Redis 缓存失效与监控告警，实现故障自动恢复",
                "参与交易系统容量评估，推动分库分表方案落地",
            ),
        )

    def test_extract_claims_returns_empty_without_guesswork(self):
        self.assertEqual(extract_claims("无动词描述的纯文本内容，无法确认任何事实"), ())

    def test_extract_pdf_text_reads_the_text_layer(self):
        pdf = make_pdf_bytes("Zhang San\nBackend engineer\nOrder system refactor")
        self.assertEqual(
            extract_pdf_text(pdf),
            "Zhang San\nBackend engineer\nOrder system refactor",
        )

    def test_extract_pdf_text_empty_layer_returns_empty_string(self):
        self.assertEqual(extract_pdf_text(make_pdf_bytes(" ")), "")

    def test_extract_pdf_text_rejects_binary_garbage(self):
        with self.assertRaises(ValueError):
            extract_pdf_text(b"not a pdf at all")


class ResumeServiceTests(unittest.TestCase):
    def test_create_resume_extracts_claims_and_links_projects(self):
        service = create_service()
        resume = service.create_resume(
            {
                "name": "林澈",
                "role": "后端工程师",
                "domain": "交易系统",
                "resume_text": SAMPLE_RESUME,
                "project_ids": [21, 22],
            }
        )
        self.assertEqual(resume.status, "extracted")
        self.assertEqual(len(resume.claims), 3)
        self.assertTrue(all(claim.source == "简历主张" for claim in resume.claims))
        self.assertEqual(resume.project_ids, (21, 22))

        summary = service.list_resumes()["resumes"][0]
        self.assertEqual(summary["name"], "林澈")
        self.assertEqual(summary["claims_count"], 3)
        self.assertEqual(summary["project_names"], ["OrderFlow Service", "DataViz Portal"])

    def test_resumes_are_candidate_scoped(self):
        service = create_service()
        service.create_resume({"name": "林澈", "resume_text": SAMPLE_RESUME, "candidate_id": "alice"})
        service.create_resume(
            {"name": "周屿", "resume_text": "周屿\n负责 API 网关的稳定性治理", "candidate_id": "bob"}
        )
        self.assertEqual(service.list_resumes("alice")["count"], 1)
        self.assertEqual(service.list_resumes("bob")["count"], 1)
        self.assertEqual(service.list_resumes("default")["count"], 0)

    def test_update_resume_merges_fields_and_claim_skips(self):
        service = create_service()
        resume = service.create_resume({"name": "林澈", "resume_text": SAMPLE_RESUME})
        claim = resume.claims[0]
        updated = service.update_resume(
            resume.resume_id,
            {"role": "高级后端工程师", "project_ids": [21], "claims": [{"claim_id": claim.claim_id, "skip": True}]},
        )
        self.assertEqual(updated.role, "高级后端工程师")
        self.assertEqual(updated.project_ids, (21,))
        self.assertTrue(updated.claims[0].skip)
        self.assertFalse(updated.claims[1].skip)

    def test_update_resume_renames_and_replaces_pdf(self):
        service = create_service()
        first_pdf = make_pdf_bytes("Zhang San\nLed legacy order refactor")
        resume = service.upload_resume(
            {"name": "Zhang San", "file_base64": base64.b64encode(first_pdf).decode("ascii")}
        )

        second_pdf = make_pdf_bytes("Zhang San\nLed capacity review for the sharding rollout")
        updated = service.update_resume(
            resume.resume_id,
            {
                "name": "Zhang Si",
                "role": "Senior Backend Engineer",
                "file_base64": base64.b64encode(second_pdf).decode("ascii"),
            },
        )
        self.assertEqual(updated.name, "Zhang Si")
        self.assertEqual(updated.role, "Senior Backend Engineer")
        self.assertIn("capacity review for the sharding rollout", updated.resume_text)
        # PDF 替换后按新文本重新提取主张；夹具 PDF 仅含英文文本，无法命中规则动词，主张为空。
        self.assertEqual(updated.claims, ())
        self.assertEqual(service.get_resume_pdf(resume.resume_id), second_pdf)

    def test_update_resume_rejects_invalid_pdf(self):
        service = create_service()
        resume = service.create_resume({"name": "林澈", "resume_text": SAMPLE_RESUME})
        with self.assertRaises(ValueError):
            service.update_resume(resume.resume_id, {"file_base64": "not-base64!"})
        with self.assertRaises(ValueError):
            service.update_resume(
                resume.resume_id,
                {"file_base64": base64.b64encode(b"not a pdf").decode("ascii")},
            )

    def test_reorder_resumes_persists_list_order(self):
        service = create_service()
        first = service.create_resume({"name": "甲", "resume_text": "甲\n负责模块 A"})
        second = service.create_resume({"name": "乙", "resume_text": "乙\n负责模块 B"})
        third = service.create_resume({"name": "丙", "resume_text": "丙\n负责模块 C"})

        ordered = [third.resume_id, first.resume_id, second.resume_id]
        service.reorder_resumes(ordered)
        listing = [item["resume_id"] for item in service.list_resumes()["resumes"]]
        self.assertEqual(listing, ordered)
        self.assertEqual([item["sort_order"] for item in service.list_resumes()["resumes"]], [0, 1, 2])

    def test_reorder_resumes_validates_input(self):
        service = create_service()
        resume = service.create_resume({"name": "甲", "resume_text": "甲\n负责模块 A"})
        with self.assertRaises(ValueError):
            service.reorder_resumes([])
        with self.assertRaises(ValueError):
            service.reorder_resumes([resume.resume_id, resume.resume_id])
        with self.assertRaises(ResumeNotFoundError):
            service.reorder_resumes(["missing"])

    def test_get_missing_resume_raises_not_found(self):
        service = create_service()
        with self.assertRaises(ResumeNotFoundError):
            service.get_resume("missing")

    def test_resume_round_trip_via_dict(self):
        service = create_service()
        resume = service.create_resume({"name": "林澈", "resume_text": SAMPLE_RESUME})
        restored = resume_from_dict(asdict(resume))
        self.assertEqual(restored, resume)


class ResumePersistenceTests(unittest.TestCase):
    def test_sqlite_store_survives_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "resumes.db")
            repository = SQLiteProjectRepository(database)
            first = create_service(
                repository=repository,
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            created = first.create_resume(
                {"name": "林澈", "role": "后端工程师", "resume_text": SAMPLE_RESUME, "project_ids": [21]}
            )
            second = create_service(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            restored = second.get_resume(created.resume_id)
            self.assertEqual(restored.name, "林澈")
            self.assertEqual(len(restored.claims), 3)

    def test_sqlite_reorder_survives_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "resumes-order.db")
            repository = SQLiteProjectRepository(database)
            first = create_service(
                repository=repository,
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            created = first.create_resume({"name": "甲", "resume_text": "甲\n负责模块 A"})
            other = first.create_resume({"name": "乙", "resume_text": "乙\n负责模块 B"})
            first.reorder_resumes([other.resume_id, created.resume_id])

            second = create_service(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            listing = [item["resume_id"] for item in second.list_resumes()["resumes"]]
            self.assertEqual(listing, [other.resume_id, created.resume_id])

    def test_sqlite_legacy_payload_without_sort_order_defaults_to_zero(self):
        resume = resume_from_dict(
            {
                "resume_id": "legacy-id",
                "candidate_id": "default",
                "name": "旧数据",
                "role": "",
                "domain": "",
                "resume_text": "旧数据\n负责模块 A",
                "status": "extracted",
                "claims": [],
                "project_ids": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "schema_version": 1,
            }
        )
        self.assertEqual(resume.sort_order, 0)


class ResumeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service = create_service()
        cls.service = service
        cls.server = create_server(service)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _request(self, method, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(f"{self.base_url}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_create_list_get_and_update_resume(self):
        status, created = self._request(
            "POST",
            "/resumes",
            {"name": "林澈", "role": "后端工程师", "resume_text": SAMPLE_RESUME, "project_ids": [21]},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["status"], "extracted")
        self.assertEqual(len(created["claims"]), 3)

        status, listing = self._request("GET", "/resumes")
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["resumes"][0]["name"], "林澈")
        self.assertEqual(listing["resumes"][0]["project_names"], ["OrderFlow Service"])

        status, detail = self._request("GET", f"/resumes/{created['resume_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["resume_text"], SAMPLE_RESUME.strip())

        claim = created["claims"][0]
        status, updated = self._request(
            "PATCH",
            f"/resumes/{created['resume_id']}",
            {"claims": [{"claim_id": claim["claim_id"], "skip": True}]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(updated["claims"][0]["skip"])

    def test_missing_resume_returns_structured_404(self):
        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/resumes/missing")
        error = context.exception
        payload = json.loads(error.read().decode("utf-8"))
        self.assertEqual(error.code, 404)
        self.assertEqual(payload["code"], "resume_not_found")
        self.assertFalse(payload["retryable"])

    def test_delete_resume_removes_it_from_the_library(self):
        status, created = self._request(
            "POST",
            "/resumes",
            {"name": "待删除", "resume_text": "待删除\n负责临时简历的删除验证"},
        )
        self.assertEqual(status, 201)

        status, deleted = self._request("DELETE", f"/resumes/{created['resume_id']}")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/resumes/{created['resume_id']}")
        self.assertEqual(context.exception.code, 404)

    def test_upload_pdf_creates_resume_with_extracted_text_and_claims(self):
        pdf = make_pdf_bytes(
            "Zhang San\nBackend engineer\nOrder system refactor with Redis"
        )
        status, created = self._request(
            "POST",
            "/resumes/upload",
            {
                "name": "张三",
                "role": "后端工程师",
                "domain": "交易系统",
                "file_base64": base64.b64encode(pdf).decode("ascii"),
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["name"], "张三")
        self.assertEqual(created["status"], "extracted")
        self.assertIn("Order system refactor with Redis", created["resume_text"])

        status, detail = self._request("GET", f"/resumes/{created['resume_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(
            detail["resume_text"], "Zhang San\nBackend engineer\nOrder system refactor with Redis"
        )

    def test_upload_resume_missing_or_invalid_base64_returns_400(self):
        for payload in ({}, {"file_base64": ""}, {"file_base64": "!!not-base64!!"}):
            with self.assertRaises(HTTPError) as context:
                self._request("POST", "/resumes/upload", payload)
            error = context.exception
            self.assertEqual(error.code, 400)
            body = json.loads(error.read().decode("utf-8"))
            self.assertEqual(body["code"], "invalid_request")

    def test_upload_non_pdf_bytes_returns_400(self):
        with self.assertRaises(HTTPError) as context:
            self._request(
                "POST",
                "/resumes/upload",
                {"name": "张三", "file_base64": base64.b64encode(b"not a pdf").decode("ascii")},
            )
        error = context.exception
        self.assertEqual(error.code, 400)
        body = json.loads(error.read().decode("utf-8"))
        self.assertEqual(body["code"], "invalid_request")

    def test_uploaded_pdf_is_served_back_verbatim(self):
        pdf = make_pdf_bytes("Zhang San\nBackend engineer")
        status, created = self._request(
            "POST",
            "/resumes/upload",
            {"name": "张三", "file_base64": base64.b64encode(pdf).decode("ascii")},
        )
        self.assertEqual(status, 201)
        with urlopen(f"{self.base_url}/resumes/{created['resume_id']}/pdf") as response:
            self.assertEqual(response.headers["Content-Type"], "application/pdf")
            self.assertEqual(response.read(), pdf)

    def test_missing_pdf_for_resume_returns_structured_404(self):
        with self.assertRaises(HTTPError) as context:
            urlopen(f"{self.base_url}/resumes/missing/pdf")
        self.assertEqual(context.exception.code, 404)

    def test_patch_resume_with_name_and_replacement_pdf(self):
        pdf = make_pdf_bytes("Zhang San\nLed legacy order refactor")
        status, created = self._request(
            "POST",
            "/resumes/upload",
            {"name": "Zhang San", "file_base64": base64.b64encode(pdf).decode("ascii")},
        )
        self.assertEqual(status, 201)

        replacement = make_pdf_bytes("Zhang San\nPushed the capacity plan for rollout")
        status, updated = self._request(
            "PATCH",
            f"/resumes/{created['resume_id']}",
            {
                "name": "Zhang Si",
                "file_base64": base64.b64encode(replacement).decode("ascii"),
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["name"], "Zhang Si")
        self.assertIn("capacity plan for rollout", updated["resume_text"])
        self.assertEqual(updated["claims"], [])
        with urlopen(f"{self.base_url}/resumes/{created['resume_id']}/pdf") as response:
            self.assertEqual(response.read(), replacement)

    def test_patch_resume_rejects_invalid_pdf(self):
        status, created = self._request(
            "POST",
            "/resumes",
            {"name": "林澈", "resume_text": SAMPLE_RESUME},
        )
        self.assertEqual(status, 201)
        for payload in ({"file_base64": "!!not-base64!!"}, {"file_base64": base64.b64encode(b"nope").decode("ascii")}):
            with self.assertRaises(HTTPError) as context:
                self._request("PATCH", f"/resumes/{created['resume_id']}", payload)
            self.assertEqual(context.exception.code, 400)

    def test_reorder_resumes_via_http(self):
        status, first = self._request("POST", "/resumes", {"name": "甲", "resume_text": "甲\n负责模块 A"})
        status, second = self._request("POST", "/resumes", {"name": "乙", "resume_text": "乙\n负责模块 B"})
        status, third = self._request("POST", "/resumes", {"name": "丙", "resume_text": "丙\n负责模块 C"})
        ordered = [third["resume_id"], first["resume_id"], second["resume_id"]]
        status, response = self._request("PUT", "/resumes/order", {"resume_ids": ordered})
        self.assertEqual(status, 200)
        self.assertEqual(response["reordered"], 3)
        status, listing = self._request("GET", "/resumes")
        ids = [item["resume_id"] for item in listing["resumes"]]
        # 共享 service 里还有其它测试创建的简历，只校验 ordered 三项保持相对顺序。
        indexes = [ids.index(item) for item in ordered]
        self.assertEqual(indexes, sorted(indexes))

    def test_reorder_resumes_with_unknown_id_returns_404(self):
        status, created = self._request("POST", "/resumes", {"name": "甲", "resume_text": "甲\n负责模块 A"})
        with self.assertRaises(HTTPError) as context:
            self._request(
                "PUT",
                "/resumes/order",
                {"resume_ids": [created["resume_id"], "missing-id"]},
            )
        error = context.exception
        self.assertEqual(error.code, 404)
        body = json.loads(error.read().decode("utf-8"))
        self.assertEqual(body["code"], "resume_not_found")


class ResumeClaimIntegrationTests(unittest.TestCase):
    def test_active_claims_skip_marked_entries(self):
        service = create_service()
        resume = service.create_resume(
            {"name": "林澈", "resume_text": SAMPLE_RESUME}
        )
        claim = resume.claims[0]
        service.update_resume(
            resume.resume_id,
            {"claims": [{"claim_id": claim.claim_id, "skip": True}]},
        )
        updated = service.get_resume(resume.resume_id)
        active = active_claim_texts(updated)
        self.assertEqual(len(active), 2)
        self.assertNotIn(claim.text, active)

    def test_session_uses_resume_claims_for_question_and_persists_them(self):
        service = create_service()
        service.create_resume(
            {
                "candidate_id": "alice",
                "name": "林澈",
                "role": "后端工程师",
                "resume_text": SAMPLE_RESUME,
                "project_ids": [21],
            }
        )
        session_id, state = service.start_session(21, candidate_id="alice")
        self.assertTrue(state.resume_claims)
        self.assertTrue(
            any("主导订单创建与幂等校验链路设计" in claim for claim in state.resume_claims)
        )
        self.assertIn("简历主张提到", state.question)

        # 提交回答后，追问也应引用简历主张并继续携带会话状态。
        state = service.submit_answer(session_id, "我主导了订单链路的设计，并验证了性能提升。")
        self.assertTrue(state.resume_claims)
        self.assertIn("简历主张提到", state.question)

        restored = service.get_session(session_id)
        self.assertEqual(restored.resume_claims, state.resume_claims)

    def test_skipped_claims_do_not_enter_session(self):
        service = create_service()
        resume = service.create_resume(
            {
                "candidate_id": "bob",
                "name": "周屿",
                "resume_text": "周屿\n负责 API 网关的稳定性治理\n参与容量评估与降级方案",
            }
        )
        first = resume.claims[0]
        service.update_resume(
            resume.resume_id,
            {"claims": [{"claim_id": first.claim_id, "skip": True}]},
        )
        session_id, state = service.start_session(21, candidate_id="bob")
        self.assertNotIn(first.text, state.resume_claims)
        self.assertTrue(any("容量评估" in claim for claim in state.resume_claims))

    def test_session_accepts_resume_id_as_candidate_identity(self):
        service = create_service()
        resume = service.create_resume(
            {"name": "林澈", "resume_text": SAMPLE_RESUME, "project_ids": [21]}
        )
        session_id, state = service.start_session(
            21, candidate_id=resume.resume_id
        )
        self.assertTrue(state.resume_claims)
        self.assertIn("简历主张提到", state.question)
        self.assertEqual(state.candidate_id, resume.resume_id)

    def test_resume_claims_survive_sqlite_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "resume-claims.db")
            repository = SQLiteProjectRepository(database)
            first = create_service(
                repository=repository,
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            first.create_resume(
                {
                    "candidate_id": "alice",
                    "name": "林澈",
                    "resume_text": SAMPLE_RESUME,
                    "project_ids": [21],
                }
            )
            session_id, state = first.start_session(21, candidate_id="alice")

            second = create_service(
                repository=SQLiteProjectRepository(database),
                session_store=SQLiteSessionStore(database),
                resume_store=SQLiteResumeStore(database),
            )
            restored = second.get_session(session_id)
            self.assertEqual(restored.resume_claims, state.resume_claims)


if __name__ == "__main__":
    unittest.main()
