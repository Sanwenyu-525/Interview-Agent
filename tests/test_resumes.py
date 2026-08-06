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
