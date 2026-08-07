"""简历库（Resume Library）领域模块。

负责简历的持久化模型、主张（claims）提取与候选人资料关联。
主张提取第一阶段使用确定性规则，保证本地可测试、结果可回溯；
后续接入 LLM 增强时保持 Resume 数据契约不变。
"""

import copy
import io
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from .memory.profile_store import normalize_candidate_id


CURRENT_RESUME_SCHEMA_VERSION = 1
RESUME_STATUSES = frozenset({"pending", "analyzing", "extracted"})
RESUME_CLAIM_SOURCE = "简历主张"
MAX_CLAIMS = 12
MAX_PDF_BYTES = 10 * 1024 * 1024

_SECTION_HEADINGS = frozenset(
    {
        "基本信息",
        "个人信息",
        "联系方式",
        "求职意向",
        "教育背景",
        "教育经历",
        "工作经历",
        "项目经历",
        "项目经验",
        "专业技能",
        "技能清单",
        "技术栈",
        "自我评价",
        "自我介绍",
        "实习经历",
        "荣誉奖项",
        "证书",
        "个人总结",
        "summary",
        "education",
        "experience",
        "skills",
        "projects",
        "about me",
    }
)

# 主张通常以动作词开头或包含结果性描述；命中任一动词即视为可追问主张。
_CLAIM_VERBS = frozenset(
    {
        "负责",
        "主导",
        "独立",
        "参与",
        "推动",
        "实现",
        "开发",
        "设计",
        "搭建",
        "构建",
        "重构",
        "优化",
        "提升",
        "降低",
        "减少",
        "增长",
        "引入",
        "落地",
        "治理",
        "支持",
        "完成",
        "交付",
        "维护",
        "定位",
        "解决",
        "排查",
        "建模",
        "制定",
        "输出",
        "沉淀",
        "推广",
        "建设",
        "研发",
        "自动化",
        "监控",
        "设计并",
        "负责并",
    }
)

_TIME_LINE = re.compile(
    r"^\s*(?:\d{4}\s*[./-]\s*\d{0,4}|\d{4}\s*年|\d{1,2}\s*月|[（(]?\d{4})",
    re.IGNORECASE,
)
_LEADING_MARKER = re.compile(
    r"^\s*(?:[-*•·▪◦]|\(?\d+[.)、）]|[一二三四五六七八九十]+[、.])\s*"
)
_CONTACT_LINE = re.compile(
    r"^\s*(?:邮箱|电话|手机|微信|github|linkedin|email|phone|tel)\s*[:：]",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connection(database: str):
    connection = sqlite3.connect(database)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _text(value, name: str, *, required=False, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是字符串")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{name} 不能为空")
    if len(normalized) > limit:
        raise ValueError(f"{name} 不能超过 {limit} 个字符")
    return normalized


def normalize_resume_status(value) -> str:
    if not isinstance(value, str) or value not in RESUME_STATUSES:
        raise ValueError(f"status 必须是以下值之一：{', '.join(sorted(RESUME_STATUSES))}")
    return value


def extract_resume_name(resume_text: str) -> str:
    """从简历正文第一行启发式提取姓名（2-4 个汉字），无法确认时返回空串。"""
    if not isinstance(resume_text, str):
        return ""
    for raw in re.split(r"[\r\n]+", resume_text.strip()):
        line = _LEADING_MARKER.sub("", raw).strip(" ：:")
        if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", line):
            return line
    return ""


def extract_claims(resume_text: str) -> tuple[str, ...]:
    """从简历正文提取候选主张。

    规则：按行（或短文本按句）切分，跳过章节标题、时间轴与联系方式行，
    保留以动作词开头或包含结果动词的描述，清理列表符号并去重。
    无法确认时返回空元组，不猜测事实。
    """
    text = _text(resume_text, "resume_text", required=True, limit=100_000)
    raw_lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    if len(raw_lines) < 3:
        raw_lines = [line.strip() for line in re.split(r"[。；;]+", text) if line.strip()]

    claims = []
    for raw in raw_lines:
        line = _LEADING_MARKER.sub("", raw).strip(" ：:")
        if not line:
            continue
        if len(line) < 4:
            continue
        if line.casefold() in _SECTION_HEADINGS:
            continue
        if _TIME_LINE.match(line):
            continue
        if _CONTACT_LINE.match(line):
            continue
        if not any(verb in line for verb in _CLAIM_VERBS):
            continue
        line = line[:240]
        if line not in claims:
            claims.append(line)
        if len(claims) == MAX_CLAIMS:
            break
    return tuple(claims)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """从 PDF 字节提取纯文本层，失败或无文本层时抛 ValueError。

    只提取内嵌文本层，不处理图片型扫描件（需要 OCR，属范围外）。
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF 解析依赖 pypdf 未安装，请先执行 pip install pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        pages = [page.extract_text() for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"PDF 解析失败：{exc}") from exc
    text = "\n".join(part.strip() for part in pages if part and part.strip())
    return text.strip()


@dataclass(frozen=True)
class ResumeClaim:
    claim_id: str
    text: str
    source: str = RESUME_CLAIM_SOURCE
    skip: bool = False


@dataclass(frozen=True)
class Resume:
    resume_id: str
    candidate_id: str
    name: str
    role: str
    domain: str
    resume_text: str
    status: str
    claims: tuple[ResumeClaim, ...] = field(default_factory=tuple)
    project_ids: tuple[int, ...] = field(default_factory=tuple)
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = CURRENT_RESUME_SCHEMA_VERSION

    def __post_init__(self):
        object.__setattr__(self, "claims", tuple(self.claims))
        object.__setattr__(self, "project_ids", tuple(self.project_ids))


def resume_from_dict(payload: dict) -> Resume:
    if not isinstance(payload, dict):
        raise ValueError("resume payload must be an object")
    schema_version = payload.get("schema_version", CURRENT_RESUME_SCHEMA_VERSION)
    if schema_version != CURRENT_RESUME_SCHEMA_VERSION:
        raise ValueError(f"unsupported resume schema_version: {schema_version}")
    try:
        return Resume(
            resume_id=_text(payload["resume_id"], "resume_id", required=True, limit=128),
            candidate_id=normalize_candidate_id(payload["candidate_id"]),
            name=_text(payload["name"], "name", required=True, limit=64),
            role=_text(payload.get("role", ""), "role", limit=64),
            domain=_text(payload.get("domain", ""), "domain", limit=64),
            resume_text=_text(payload["resume_text"], "resume_text", required=True, limit=100_000),
            status=normalize_resume_status(payload.get("status", "extracted")),
            claims=tuple(ResumeClaim(**item) for item in payload.get("claims", [])),
            project_ids=tuple(int(item) for item in payload.get("project_ids", [])),
            sort_order=int(payload.get("sort_order", 0)),
            created_at=_text(payload.get("created_at", ""), "created_at", limit=100),
            updated_at=_text(payload.get("updated_at", ""), "updated_at", limit=100),
            schema_version=schema_version,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("resume payload contains invalid fields") from exc


def active_claim_texts(resume: Resume) -> tuple[str, ...]:
    """返回可用于复盘追问的主张文本，跳过标记为暂不用以提问的条目。"""
    return tuple(claim.text for claim in resume.claims if not claim.skip)


class InMemoryResumeStore:
    def __init__(self):
        self._resumes: dict[str, Resume] = {}
        self._pdfs: dict[str, bytes] = {}

    def save(self, resume: Resume) -> None:
        self._resumes[resume.resume_id] = copy.deepcopy(resume)

    def get(self, resume_id: str) -> Resume:
        try:
            return copy.deepcopy(self._resumes[resume_id])
        except KeyError as exc:
            raise KeyError(f"resume not found: {resume_id}") from exc

    def list(self, candidate_id: str | None = None, limit: int = 50) -> list[Resume]:
        resumes = [
            copy.deepcopy(resume)
            for resume in self._resumes.values()
            if candidate_id is None or resume.candidate_id == candidate_id
        ]
        resumes.sort(key=lambda item: item.updated_at, reverse=True)
        resumes.sort(key=lambda item: item.sort_order)
        return resumes[:limit]

    def reorder(self, ordered_ids: tuple[str, ...]) -> None:
        """按给定顺序重写简历的 sort_order（0 为最前）。"""
        for index, resume_id in enumerate(ordered_ids):
            resume = self._resumes[resume_id]
            self._resumes[resume_id] = replace(resume, sort_order=index)

    def delete(self, resume_id: str) -> None:
        if resume_id not in self._resumes:
            raise KeyError(f"resume not found: {resume_id}")
        del self._resumes[resume_id]
        self._pdfs.pop(resume_id, None)

    def save_pdf(self, resume_id: str, pdf_bytes: bytes) -> None:
        self._pdfs[resume_id] = pdf_bytes

    def get_pdf(self, resume_id: str) -> bytes:
        try:
            return self._pdfs[resume_id]
        except KeyError as exc:
            raise KeyError(f"resume pdf not found: {resume_id}") from exc

    def delete_pdf(self, resume_id: str) -> None:
        self._pdfs.pop(resume_id, None)


class SQLiteResumeStore:
    def __init__(self, database: str):
        self.database = database
        with _connection(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS resumes "
                "(resume_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, "
                "payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS resume_pdf "
                "(resume_id TEXT PRIMARY KEY, pdf BLOB NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS resumes_candidate_updated "
                "ON resumes(candidate_id, updated_at DESC)"
            )

    def save(self, resume: Resume) -> None:
        payload = json.dumps(asdict(resume), ensure_ascii=False)
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO resumes(resume_id, candidate_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(resume_id) DO UPDATE SET "
                "candidate_id=excluded.candidate_id, payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                (resume.resume_id, resume.candidate_id, payload, resume.updated_at),
            )

    def get(self, resume_id: str) -> Resume:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT payload FROM resumes WHERE resume_id = ?", (resume_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"resume not found: {resume_id}")
        return resume_from_dict(json.loads(row[0]))

    def list(self, candidate_id: str | None = None, limit: int = 50) -> list[Resume]:
        if candidate_id is None:
            query = "SELECT payload FROM resumes ORDER BY updated_at DESC"
            parameters = ()
        else:
            query = "SELECT payload FROM resumes WHERE candidate_id = ? " \
                "ORDER BY updated_at DESC"
            parameters = (candidate_id,)
        with _connection(self.database) as connection:
            rows = connection.execute(query, parameters).fetchall()
        resumes = [resume_from_dict(json.loads(row[0])) for row in rows]
        resumes.sort(key=lambda item: item.updated_at, reverse=True)
        resumes.sort(key=lambda item: item.sort_order)
        return resumes[:limit]

    def reorder(self, ordered_ids: tuple[str, ...]) -> None:
        """按给定顺序重写简历的 sort_order（0 为最前）。"""
        for index, resume_id in enumerate(ordered_ids):
            with _connection(self.database) as connection:
                row = connection.execute(
                    "SELECT payload FROM resumes WHERE resume_id = ?", (resume_id,)
                ).fetchone()
            if row is None:
                raise KeyError(f"resume not found: {resume_id}")
            payload = json.loads(row[0])
            payload["sort_order"] = index
            with _connection(self.database) as connection:
                connection.execute(
                    "UPDATE resumes SET payload = ?, updated_at = updated_at "
                    "WHERE resume_id = ?",
                    (json.dumps(payload, ensure_ascii=False), resume_id),
                )

    def delete(self, resume_id: str) -> None:
        with _connection(self.database) as connection:
            cursor = connection.execute(
                "DELETE FROM resumes WHERE resume_id = ?", (resume_id,)
            )
            if cursor.rowcount == 0:
                raise KeyError(f"resume not found: {resume_id}")
        self.delete_pdf(resume_id)

    def save_pdf(self, resume_id: str, pdf_bytes: bytes) -> None:
        with _connection(self.database) as connection:
            connection.execute(
                "INSERT INTO resume_pdf(resume_id, pdf) VALUES (?, ?) "
                "ON CONFLICT(resume_id) DO UPDATE SET pdf=excluded.pdf",
                (resume_id, pdf_bytes),
            )

    def get_pdf(self, resume_id: str) -> bytes:
        with _connection(self.database) as connection:
            row = connection.execute(
                "SELECT pdf FROM resume_pdf WHERE resume_id = ?", (resume_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"resume pdf not found: {resume_id}")
        return row[0]

    def delete_pdf(self, resume_id: str) -> None:
        with _connection(self.database) as connection:
            connection.execute(
                "DELETE FROM resume_pdf WHERE resume_id = ?", (resume_id,)
            )


def normalize_project_ids(value) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError("project_ids 必须是数组")
    if len(value) > 20:
        raise ValueError("project_ids 最多包含 20 个项目")
    normalized = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError("project_ids 必须只包含正整数")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def claims_from_text(resume_id: str, resume_text: str) -> tuple[ResumeClaim, ...]:
    """从简历文本提取主张并生成稳定的 claim_id（同名同序同 id）。"""
    return tuple(
        ResumeClaim(
            claim_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"interview-agent:{resume_id}:claim:{index}:{text}",
            ).hex,
            text=text,
        )
        for index, text in enumerate(extract_claims(resume_text))
    )


def new_resume(
    *,
    candidate_id: str,
    name: str,
    role: str,
    domain: str,
    resume_text: str,
    project_ids: tuple[int, ...],
) -> Resume:
    resume_id = uuid.uuid4().hex
    timestamp = _now()
    claims = claims_from_text(resume_id, resume_text)
    return Resume(
        resume_id=resume_id,
        candidate_id=normalize_candidate_id(candidate_id),
        name=_text(name, "name", required=True, limit=64),
        role=_text(role, "role", limit=64),
        domain=_text(domain, "domain", limit=64),
        resume_text=_text(resume_text, "resume_text", required=True, limit=100_000),
        status="extracted",
        claims=claims,
        project_ids=project_ids,
        created_at=timestamp,
        updated_at=timestamp,
    )


def updated_at() -> str:
    return _now()
