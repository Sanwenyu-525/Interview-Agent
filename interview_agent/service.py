import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import binascii
import inspect
from threading import Lock
from threading import RLock
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from .agent import InterviewAgent, RuleBasedEvaluator, RuleBasedQuestionGenerator
from .agents import AgentDefinition, InMemoryAgentStore, STAGES, _validate_agent_payload
from .analyzers.registry import AnalyzerRegistry
from .analyzers.scanner import ProjectScanner
from .graph import InterviewGraph
from .ingestion import (
    DirectorySource,
    FolderFile,
    FolderSource,
    IngestionService,
    ProjectSource,
    ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE,
    ZIP_DESCRIPTOR_DEFAULT_MAX_FILES,
    ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE,
    ZipSource,
)
from .ingestion.security import normalize_project_id
from .llm import (
    LLMConfig,
    LLMError,
    LlmEvaluator,
    LlmPositionQuestionGenerator,
    LlmQuestionGenerator,
    OpenAICompatibleClient,
    agent_from_config,
    ocr_jd_text,
)
from .models import (
    AnalysisStatus,
    InterviewState,
    ProjectAnalysis,
    ProjectKnowledge,
    ProfileConflictError,
    SessionConflictError,
    Topic,
    project_model_to_knowledge,
)
from .memory.profile_store import (
    CURRENT_PROFILE_SCHEMA_VERSION,
    CandidateProfileStore,
    InMemoryCandidateProfileStore,
    normalize_candidate_id,
)
from .profile import ProfileUpdate, WeaknessSource
from .positions import (
    InMemoryPositionStore,
    TargetPosition,
    extract_requirements,
    generate_questions,
    new_position,
    normalize_project_ids,
    position_from_dict,
    updated_at,
)
from .repository import InMemoryProjectRepository
from .resumes import (
    MAX_PDF_BYTES,
    active_claim_texts,
    claims_from_text,
    InMemoryResumeStore,
    Resume,
    extract_pdf_text,
    extract_resume_name,
    new_resume,
    normalize_resume_status,
    resume_from_dict,
    updated_at,
)
from .review import InterviewOutlineBuilder, ReviewMode
from .review.director import ToolCallingDirector
from .review.llm_policy import LlmReviewPolicy
from .settings import InMemoryLLMSettingsStore, LLMProfile


class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, InterviewState] = {}
        self._candidate_ids: dict[str, str] = {}
        self._versions: dict[str, int] = {}
        self._updated_at: dict[str, str] = {}
        self._lock = RLock()

    def save(
        self,
        session_id: str,
        state: InterviewState,
        expected_version: int | None = None,
    ) -> int:
        with self._lock:
            exists = session_id in self._sessions
            current_version = self._versions.get(session_id, 0)
            if expected_version is not None:
                if expected_version != current_version:
                    raise SessionConflictError(
                        f"session version conflict: {session_id} "
                        f"expected {expected_version}, current {current_version}"
                    )
            candidate_id = str(state.candidate_id or "default")
            self._candidate_ids[session_id] = candidate_id
            self._sessions[session_id] = copy.deepcopy(state)
            self._updated_at[session_id] = datetime.now(timezone.utc).isoformat()
            version = current_version + 1 if exists else 0
            self._versions[session_id] = version
            return version

    def save_if_version(self, session_id, state, expected_version):
        return self.save(session_id, state, expected_version=expected_version)

    def get(self, session_id: str) -> InterviewState:
        return self.get_with_version(session_id)[0]

    def get_with_version(self, session_id: str) -> tuple[InterviewState, int]:
        with self._lock:
            try:
                state = self._sessions[session_id]
                owner = self._candidate_ids.get(session_id, "default")
                if state.candidate_id != owner:
                    state = replace(state, candidate_id=owner)
                return copy.deepcopy(state), self._versions.get(session_id, 0)
            except KeyError as exc:
                raise KeyError("session not found") from exc

    def list(
        self,
        *,
        candidate_id: str | None = None,
        project_id: int | None = None,
        position_id: str | None = None,
        limit: int = 50,
    ) -> list[tuple[str, InterviewState, str]]:
        with self._lock:
            rows = []
            for session_id, state in self._sessions.items():
                owner = self._candidate_ids.get(session_id, "default")
                if candidate_id is not None and owner != candidate_id:
                    continue
                if project_id is not None and state.project_id != project_id:
                    continue
                if position_id is not None and state.position_id != position_id:
                    continue
                rows.append(
                    (
                        session_id,
                        copy.deepcopy(replace(state, candidate_id=owner)),
                        self._updated_at.get(session_id, ""),
                    )
                )
            rows.sort(key=lambda item: item[2], reverse=True)
            return rows[:limit]


    def get_candidate_id(self, session_id: str) -> str:
        with self._lock:
            try:
                return self._candidate_ids[session_id]
            except KeyError as exc:
                raise KeyError(f"session not found: {session_id}") from exc

    def delete(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"session not found: {session_id}")
            self._sessions.pop(session_id)
            self._candidate_ids.pop(session_id, None)
            self._versions.pop(session_id, None)
            self._updated_at.pop(session_id, None)


class ProjectAnalysisError(ValueError):
    """Task 6 service compatibility boundary."""

    def __init__(self, project_id: int, message: str):
        self.project_id = project_id
        self.message = message
        super().__init__(message)


class ProjectNotFoundError(KeyError):
    """Task 6 service compatibility boundary."""


class SessionNotFoundError(KeyError):
    """Task 6 service compatibility boundary."""


class PositionNotFoundError(KeyError):
    """Requested target position does not exist."""


class ResumeNotFoundError(KeyError):
    """Requested resume does not exist."""


_MISSING_CANDIDATE_ID = object()
_SESSION_TITLE_MAX_LENGTH = 80


def _session_title(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("会话标题必须是字符串")
    title = " ".join(value.split())
    if not title:
        raise ValueError("会话标题不能为空")
    if len(title) > _SESSION_TITLE_MAX_LENGTH:
        raise ValueError(f"会话标题不能超过 {_SESSION_TITLE_MAX_LENGTH} 个字符")
    return title


class InterviewService:
    """Task 6 service compatibility boundary."""

    def __init__(
        self,
        repository=None,
        agent=None,
        session_store=None,
        ingestion_service: IngestionService | None = None,
        scanner=ProjectScanner,
        analyzer_registry: AnalyzerRegistry | None = None,
        profile_store: CandidateProfileStore | None = None,
        position_store=None,
        resume_store=None,
        llm_settings_store=None,
        llm_config: LLMConfig | None = None,
        llm_client: OpenAICompatibleClient | None = None,
        workflow_factory=InterviewGraph,
        workflow_checkpointer=None,
        agent_store=None,
    ):
        self.repository = repository or InMemoryProjectRepository()
        self.llm_settings_store = llm_settings_store or InMemoryLLMSettingsStore()
        self.agent_store = agent_store or InMemoryAgentStore()
        self.llm_config = llm_config or self.llm_settings_store.get()
        self._llm_client = llm_client
        self.agent = agent or agent_from_config(self.repository, self.llm_config)
        self.workflow_factory = workflow_factory
        self.workflow_checkpointer = workflow_checkpointer
        self.session_store = session_store or InMemorySessionStore()
        self.ingestion_service = ingestion_service or IngestionService()
        self.scanner = scanner
        self.analyzer_registry = analyzer_registry or AnalyzerRegistry.with_defaults()
        self.profile_store = profile_store or InMemoryCandidateProfileStore()
        self.position_store = position_store or InMemoryPositionStore()
        self.resume_store = resume_store or InMemoryResumeStore()
        self._analysis_records: dict[int, ProjectAnalysis] = {}
        self._session_locks: dict[str, Lock] = {}
        self._session_locks_guard = Lock()
        self._candidate_locks: dict[str, Lock] = {}
        self._candidate_locks_guard = Lock()

    def _resolve_agent_definitions(
        self,
        agent_mode: str,
        agent_ids: Mapping[str, str] | None,
    ) -> dict[str, AgentDefinition]:
        if agent_ids is None:
            agent_ids = {}
        if not isinstance(agent_ids, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in agent_ids.items()
        ):
            raise ValueError("agent_ids 必须是字符串映射")
        default_id = "builtin-generalist"
        if agent_mode == "multi":
            resolved = {}
            for stage in STAGES:
                agent_id = agent_ids.get(stage, "")
                resolved[stage] = (
                    self.agent_store.get(agent_id) if agent_id else self.agent_store.get(default_id)
                )
            return resolved
        agent_id = agent_ids.get("all", "") or default_id
        definition = self.agent_store.get(agent_id)
        return {stage: definition for stage in STAGES}

    def _config_for_agent(self, definition: AgentDefinition) -> LLMConfig:
        if not definition.profile_id:
            return self.llm_config
        try:
            return self.llm_settings_store.get_profile(definition.profile_id).config
        except KeyError:
            # 绑定的配置档案被删除后回退到当前激活配置
            return self.llm_config

    def _client_for_definition(self, definition: AgentDefinition):
        """按 agent 绑定的配置创建 LLM 客户端；未启用时返回 None，组件回退本地规则。"""
        config = self._config_for_agent(definition)
        return OpenAICompatibleClient(config) if config.enabled else None

    def _agent_for_profile(
        self,
        profile,
        review_mode=ReviewMode.TECHNICAL_INTERVIEW,
        agent_mode: str = "single",
        agent_ids: Mapping[str, str] | None = None,
    ):
        definitions = self._resolve_agent_definitions(agent_mode, agent_ids)
        questioner = definitions["questioner"]
        evaluator_def = definitions["evaluator"]
        director = definitions["director"]
        question_client = self._client_for_definition(questioner)
        evaluator_client = self._client_for_definition(evaluator_def)
        director_client = self._client_for_definition(director)

        # 默认组件（规则或未带 persona 的 LLM）升级为带 persona 的 LLM 组件；显式注入的自定义组件保留
        question_generator = self.agent.question_generator
        if isinstance(question_generator, (RuleBasedQuestionGenerator, LlmQuestionGenerator)):
            question_generator = LlmQuestionGenerator(question_client, persona=questioner.persona)
        evaluator = self.agent.evaluator
        if isinstance(evaluator, (RuleBasedEvaluator, LlmEvaluator)):
            evaluator = LlmEvaluator(evaluator_client, persona=evaluator_def.persona)

        return InterviewAgent(
            repository=self.repository,
            question_generator=question_generator,
            evaluator=evaluator,
            profile=profile,
            profile_updater=self.agent.profile_updater,
            outline_builder=self.agent.outline_builder or InterviewOutlineBuilder(),
            policy=LlmReviewPolicy(director_client, review_mode, persona=director.persona),
            policy_builder=lambda mode, client=director_client, persona=director.persona: LlmReviewPolicy(
                client, mode, persona=persona
            ),
            director=ToolCallingDirector(director_client, review_mode, persona=director.persona),
        )

    def _workflow_for_agent(self, agent):
        if self.workflow_checkpointer is None:
            return self.workflow_factory(agent)
        return self.workflow_factory(
            agent,
            checkpointer=self.workflow_checkpointer,
        )

    def get_llm_settings(self):
        return self.llm_config.public_payload()

    def get_llm_profiles(self):
        active_id = self.llm_settings_store.active_profile_id()
        return {
            "active_id": active_id,
            "profiles": [profile.public_payload(profile.profile_id == active_id) for profile in self.llm_settings_store.list_profiles()],
        }

    def _switch_llm_runtime(self, config: LLMConfig) -> None:
        if config.enabled and self._llm_client is None:
            self._llm_client = OpenAICompatibleClient(config)
        if not config.enabled:
            self._llm_client = None
        self.agent = agent_from_config(self.repository, config)
        self.llm_config = config

    def list_agents(self):
        return {
            "agents": [agent.public_payload() for agent in self.agent_store.list_agents()]
        }

    def create_agent(self, payload: dict):
        fields = _validate_agent_payload(payload)
        agent = AgentDefinition(
            uuid.uuid4().hex,
            fields["name"],
            fields["role"],
            fields["persona"],
            fields["profile_id"],
        )
        self.agent_store.save_agent(agent)
        return agent.public_payload()

    def update_agent(self, agent_id: str, payload: dict):
        current = self.agent_store.get(agent_id)
        if current.builtin:
            raise ValueError("内置 agent 不可修改")
        merged = {
            "name": payload.get("name", current.name),
            "role": payload.get("role", current.role),
            "persona": payload.get("persona", current.persona),
            "profile_id": payload.get("profile_id", current.profile_id),
        }
        fields = _validate_agent_payload(merged)
        agent = AgentDefinition(
            agent_id,
            fields["name"],
            fields["role"],
            fields["persona"],
            fields["profile_id"],
        )
        self.agent_store.save_agent(agent)
        return agent.public_payload()

    def delete_agent(self, agent_id: str):
        self.agent_store.delete_agent(agent_id)
        return {"agent_id": agent_id, "deleted": True}

    def update_llm_settings(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError("大模型配置必须是 JSON 对象")
        config = self.llm_settings_store.config_from_payload(
            payload,
            existing_api_key=self.llm_config.api_key,
        )
        self.llm_settings_store.save(config)
        self._switch_llm_runtime(config)
        return config.public_payload()

    def create_llm_profile(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError("大模型配置必须是 JSON 对象")
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("大模型配置名称不能为空")
        config = self.llm_settings_store.config_from_payload(
            payload,
            existing_api_key=self.llm_config.api_key,
        )
        if not config.enabled:
            raise ValueError("只能保存远程大模型配置")
        profile = LLMProfile(uuid.uuid4().hex, name, config)
        self.llm_settings_store.save_profile(profile)
        return profile.public_payload(False)

    def update_llm_profile(self, profile_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError("大模型配置必须是 JSON 对象")
        current = self.llm_settings_store.get_profile(profile_id)
        name = str(payload.get("name", current.name)).strip()
        if not name:
            raise ValueError("大模型配置名称不能为空")
        merged_payload = {
            "provider": current.config.provider,
            "provider_name": current.config.provider_name,
            "base_url": current.config.base_url,
            "model": current.config.model,
            "api_mode": current.config.api_mode,
            "timeout": current.config.timeout,
            "temperature": current.config.temperature,
            **payload,
        }
        config = self.llm_settings_store.config_from_payload(
            merged_payload,
            existing_api_key=current.config.api_key,
        )
        profile = LLMProfile(profile_id, name, config)
        self.llm_settings_store.save_profile(profile)
        if self.llm_settings_store.active_profile_id() == profile_id:
            self._switch_llm_runtime(config)
        return profile.public_payload(profile_id == self.llm_settings_store.active_profile_id())

    def delete_llm_profile(self, profile_id: str):
        was_active = self.llm_settings_store.active_profile_id() == profile_id
        self.llm_settings_store.delete_profile(profile_id)
        if was_active:
            self._switch_llm_runtime(self.llm_settings_store.get())
        return self.get_llm_profiles()

    def activate_llm_profile(self, profile_id: str):
        profile = self.llm_settings_store.get_profile(profile_id)
        self.llm_settings_store.set_active(profile_id)
        self._switch_llm_runtime(profile.config)
        return profile.public_payload(True)

    def _test_llm_config(self, config: LLMConfig, profile_id: str | None = None):
        if not config.enabled:
            return {"ok": True, "message": "当前使用本地规则引擎，无需测试远程连接", "profile_id": profile_id}
        client = OpenAICompatibleClient(config)
        client.chat(
            [
                {"role": "system", "content": "你是连接测试助手，只需回复 OK。"},
                {"role": "user", "content": "请回复 OK。"},
            ]
        )
        return {"ok": True, "message": f"已连接 {config.model}", "profile_id": profile_id}

    def test_llm_settings(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError("大模型配置必须是 JSON 对象")
        config = self.llm_settings_store.config_from_payload(
            payload,
            existing_api_key=self.llm_config.api_key,
        )
        return self._test_llm_config(config)

    def test_llm_profile(self, profile_id: str):
        profile = self.llm_settings_store.get_profile(profile_id)
        return self._test_llm_config(profile.config, profile_id)

    def list_llm_models(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError("大模型配置必须是 JSON 对象")
        config = self.llm_settings_store.config_from_payload(
            payload,
            existing_api_key=self.llm_config.api_key,
            require_model=False,
        )
        if not config.enabled:
            return {"provider_name": config.provider_name, "models": []}
        models = OpenAICompatibleClient(config).list_models()
        return {"provider_name": config.provider_name, "models": list(models)}

    def register_project(self, payload: dict) -> ProjectKnowledge:
        project = ProjectKnowledge(
            project_id=normalize_project_id(payload["project_id"]),
            project_name=str(payload["project_name"]),
            topics=[
                Topic(
                    name=str(topic["name"]),
                    score=int(topic["score"]),
                    evidence=list(topic.get("evidence", [])),
                )
                for topic in payload.get("topics", [])
            ],
            components=dict(payload.get("components", {})),
            evidence=dict(payload.get("evidence", {})),
            dependencies={
                key: list(value) for key, value in payload.get("dependencies", {}).items()
            },
            weaknesses=list(payload.get("weaknesses", [])),
        )
        self.repository.save(project)
        self._save_analysis(
            ProjectAnalysis(
                project_id=project.project_id,
                project_name=project.project_name,
                source_type="manual",
                analysis_status=AnalysisStatus.READY,
                analyzer_id="manual",
                knowledge=project,
            )
        )
        return project

    def list_projects(self) -> dict:
        projects = self.repository.list()
        return {
            "projects": [
                {"project_id": project.project_id, "project_name": project.project_name}
                for project in projects
            ],
            "count": len(projects),
        }

    def _position_projects(self, project_ids) -> tuple[ProjectKnowledge, ...]:
        normalized_ids = normalize_project_ids(project_ids)
        projects = []
        for project_id in normalized_ids:
            try:
                projects.append(self.repository.get(project_id))
            except KeyError as exc:
                raise ProjectNotFoundError(f"项目不存在: {project_id}") from exc
        return tuple(projects)

    def _position_questions(
        self,
        position_id: str,
        requirements: tuple[str, ...],
        projects: tuple[ProjectKnowledge, ...],
    ) -> tuple:
        """LLM 优先生成岗位题库；未配置 LLM 或生成失败时回退本地规则。"""
        client = self._llm_client
        if client is not None:
            try:
                generated = LlmPositionQuestionGenerator(client).generate(
                    position_id=position_id,
                    requirements=requirements,
                    projects=projects,
                )
            except LLMError:
                generated = ()
            if generated:
                return generated
        return generate_questions(position_id, requirements, projects)

    def ocr_position_jd(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise TypeError("OCR 请求必须是 JSON 对象")
        raw_base64 = str(payload.get("image_base64") or "").strip()
        if not raw_base64:
            raise ValueError("image_base64 不能为空")
        mime_type = str(payload.get("mime_type") or "image/png").strip()
        if not mime_type.startswith("image/"):
            raise ValueError("mime_type 必须是 image/* 类型")
        if self._llm_client is None:
            raise ValueError("未配置大模型，无法识别图片 JD；请先在应用设置中配置并启用大模型")
        try:
            image_bytes = base64.b64decode(raw_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 不是合法的 Base64 编码") from exc
        if not image_bytes:
            raise ValueError("图片内容为空")
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("图片不能超过 10MB")
        try:
            text = ocr_jd_text(self._llm_client, raw_base64, mime_type)
        except LLMError as exc:
            raise LLMError(f"图片 JD 识别失败：{exc}") from exc
        text = text.strip()
        if not text:
            raise ValueError("未能从图片中识别出 JD 文本，请尝试更清晰的截图")
        return {"text": text, "chars": len(text)}

    def create_position(self, payload: dict) -> TargetPosition:
        if not isinstance(payload, dict):
            raise TypeError("岗位必须是 JSON 对象")
        allowed = {
            "candidate_id", "title", "company", "jd_text", "source_url", "status", "project_ids"
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"岗位包含未知字段：{sorted(unknown)}")
        project_ids = normalize_project_ids(payload.get("project_ids", []))
        projects = self._position_projects(project_ids)
        position = new_position(
            candidate_id=payload.get("candidate_id", "default"),
            title=payload["title"],
            company=payload.get("company", ""),
            jd_text=payload["jd_text"],
            source_url=payload.get("source_url", ""),
            status=payload.get("status", "preparing"),
            project_ids=project_ids,
            projects=projects,
        )
        questions = self._position_questions(
            position.position_id, position.requirements, projects
        )
        position = replace(position, questions=questions)
        self.position_store.save(position)
        return position

    def get_position(self, position_id: str) -> TargetPosition:
        try:
            return self.position_store.get(str(position_id).strip())
        except KeyError as exc:
            raise PositionNotFoundError(f"position not found: {position_id}") from exc

    def list_positions(self, candidate_id: str = "default", limit: int = 50) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        positions = self.position_store.list(normalize_candidate_id(candidate_id), limit)
        return {
            "positions": self._position_practice_payloads(positions),
            "count": len(positions),
        }

    def _position_practice_payloads(self, positions: list) -> list:
        if not positions:
            return []
        candidate_id = positions[0].candidate_id
        sessions = self.list_sessions(candidate_id=candidate_id, limit=100)["sessions"]
        stats_by_key: dict[tuple, dict] = {}
        for summary in sessions:
            position_id = summary.get("position_id")
            question_id = summary.get("position_question_id")
            if not position_id or not question_id or summary.get("average_score") is None:
                continue
            entry = stats_by_key.setdefault(
                (position_id, question_id), {"count": 0, "scores": [], "last": ""}
            )
            entry["count"] += 1
            entry["scores"].append(summary["average_score"])
            if summary.get("updated_at", "") > entry["last"]:
                entry["last"] = summary["updated_at"]
        payloads = []
        for position in positions:
            payload = asdict(position)
            questions = []
            for question in payload["questions"]:
                stats = stats_by_key.get((position.position_id, question["question_id"]))
                questions.append(
                    {
                        **question,
                        "practice_count": stats["count"] if stats else 0,
                        "average_score": (
                            round(sum(stats["scores"]) / len(stats["scores"]))
                            if stats and stats["scores"]
                            else None
                        ),
                        "last_practiced_at": stats["last"] if stats else None,
                    }
                )
            payload["questions"] = questions
            payloads.append(payload)
        return payloads

    def update_position(self, position_id: str, payload: dict) -> TargetPosition:
        if not isinstance(payload, dict) or not payload:
            raise ValueError("岗位更新必须包含至少一个字段")
        allowed = {"title", "company", "jd_text", "source_url", "status", "project_ids"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"岗位更新包含未知字段：{sorted(unknown)}")
        current = self.get_position(position_id)
        merged = asdict(current)
        merged.update(payload)
        merged["updated_at"] = updated_at()
        validated = position_from_dict(merged)
        regenerate = "jd_text" in payload or "project_ids" in payload
        if regenerate:
            projects = self._position_projects(validated.project_ids)
            requirements = extract_requirements(validated.jd_text)
            validated = replace(
                validated,
                requirements=requirements,
                questions=self._position_questions(
                    validated.position_id, requirements, projects
                ),
            )
        self.position_store.save(validated)
        return validated

    def regenerate_position_questions(self, position_id: str) -> TargetPosition:
        current = self.get_position(position_id)
        requirements = extract_requirements(current.jd_text)
        projects = self._position_projects(current.project_ids)
        updated = replace(
            current,
            requirements=requirements,
            questions=self._position_questions(
                current.position_id, requirements, projects
            ),
            updated_at=updated_at(),
        )
        self.position_store.save(updated)
        return updated

    def delete_position(self, position_id: str) -> None:
        try:
            self.position_store.delete(str(position_id).strip())
        except KeyError as exc:
            raise PositionNotFoundError(f"position not found: {position_id}") from exc

    def _resume_projects(self, project_ids) -> tuple[ProjectKnowledge, ...]:
        normalized_ids = normalize_project_ids(project_ids)
        projects = []
        for project_id in normalized_ids:
            try:
                projects.append(self.repository.get(project_id))
            except KeyError as exc:
                raise ProjectNotFoundError(f"项目不存在: {project_id}") from exc
        return tuple(projects)

    def _resume_project_names(self, resume: Resume) -> tuple[str, ...]:
        names = []
        for project_id in resume.project_ids:
            try:
                names.append(self.repository.get(project_id).project_name)
            except KeyError:
                names.append("")
        return tuple(names)

    def _resume_claims_for_candidate(self, candidate_id: str) -> tuple[str, ...]:
        """取候选人最新一份简历中可用于追问的主张（跳过 skip 标记）。

        会话可能以简历 ID 作为候选人标识，因此先按 candidate_id 过滤，
        查不到时再按 resume_id 直接读取，保证前端“选择简历”后主张可注入。
        """
        try:
            resumes = self.resume_store.list(
                normalize_candidate_id(candidate_id), limit=1
            )
        except (KeyError, ValueError):
            resumes = []
        if not resumes:
            try:
                resumes = [self.resume_store.get(str(candidate_id).strip())]
            except KeyError:
                return ()
        if not resumes:
            return ()
        return active_claim_texts(resumes[0])

    def _resume_summary(self, resume: Resume) -> dict:
        project_names = self._resume_project_names(resume)
        return {
            "resume_id": resume.resume_id,
            "candidate_id": resume.candidate_id,
            "name": resume.name,
            "role": resume.role,
            "domain": resume.domain,
            "status": resume.status,
            "claims_count": len(resume.claims),
            "project_ids": list(resume.project_ids),
            "project_names": list(project_names),
            "sort_order": resume.sort_order,
            "created_at": resume.created_at,
            "updated_at": resume.updated_at,
        }

    def create_resume(self, payload: dict) -> Resume:
        if not isinstance(payload, dict):
            raise TypeError("简历必须是 JSON 对象")
        allowed = {
            "candidate_id", "name", "role", "domain", "resume_text", "project_ids"
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"简历包含未知字段：{sorted(unknown)}")
        resume_text = payload.get("resume_text")
        if not isinstance(resume_text, str) or not resume_text.strip():
            raise ValueError("resume_text 不能为空")
        name = str(payload.get("name", "")).strip()
        if not name:
            name = extract_resume_name(resume_text)
        if not name:
            raise ValueError("无法从简历文本识别姓名，请显式提供 name")
        project_ids = normalize_project_ids(payload.get("project_ids", []))
        self._resume_projects(project_ids)
        resume = new_resume(
            candidate_id=payload.get("candidate_id", "default"),
            name=name,
            role=payload.get("role", ""),
            domain=payload.get("domain", ""),
            resume_text=resume_text,
            project_ids=project_ids,
        )
        self.resume_store.save(resume)
        return resume

    def upload_resume(self, payload: dict) -> Resume:
        """接收 Base64 编码的 PDF 简历，提取文本层后按文本简历入库。"""
        if not isinstance(payload, dict):
            raise TypeError("简历必须是 JSON 对象")
        allowed = {"candidate_id", "name", "role", "domain", "file_base64"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"简历上传包含未知字段：{sorted(unknown)}")
        resume_text, pdf_bytes = self._decode_pdf(payload.get("file_base64"))
        resume = self.create_resume(
            {
                "candidate_id": payload.get("candidate_id", "default"),
                "name": payload.get("name", ""),
                "role": payload.get("role", ""),
                "domain": payload.get("domain", ""),
                "resume_text": resume_text,
            }
        )
        self.resume_store.save_pdf(resume.resume_id, pdf_bytes)
        return resume

    def get_resume_pdf(self, resume_id: str) -> bytes:
        try:
            return self.resume_store.get_pdf(str(resume_id).strip())
        except KeyError as exc:
            raise ResumeNotFoundError(f"resume pdf not found: {resume_id}") from exc

    def get_resume(self, resume_id: str) -> Resume:
        try:
            return self.resume_store.get(str(resume_id).strip())
        except KeyError as exc:
            raise ResumeNotFoundError(f"resume not found: {resume_id}") from exc

    def list_resumes(self, candidate_id: str | None = None, limit: int = 50) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        normalized = None
        if candidate_id not in (None, ""):
            normalized = normalize_candidate_id(candidate_id)
        resumes = self.resume_store.list(normalized, limit)
        return {
            "resumes": [self._resume_summary(resume) for resume in resumes],
            "count": len(resumes),
        }

    def update_resume(self, resume_id: str, payload: dict) -> Resume:
        if not isinstance(payload, dict) or not payload:
            raise ValueError("简历更新必须包含至少一个字段")
        allowed = {"name", "role", "domain", "project_ids", "status", "claims", "file_base64"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"简历更新包含未知字段：{sorted(unknown)}")
        current = self.get_resume(resume_id)
        merged = asdict(current)
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise ValueError("name 不能为空")
            if len(name) > 64:
                raise ValueError("name 不能超过 64 个字符")
            merged["name"] = name
        if "role" in payload:
            merged["role"] = payload["role"]
        if "domain" in payload:
            merged["domain"] = payload["domain"]
        if "status" in payload:
            merged["status"] = normalize_resume_status(payload["status"])
        if "project_ids" in payload:
            project_ids = normalize_project_ids(payload["project_ids"])
            self._resume_projects(project_ids)
            merged["project_ids"] = list(project_ids)
        if "claims" in payload:
            if not isinstance(payload["claims"], list):
                raise ValueError("claims 必须是数组")
            claim_patch = {}
            for item in payload["claims"]:
                if not isinstance(item, dict) or "claim_id" not in item:
                    raise ValueError("claims 每项必须包含 claim_id")
                claim_patch[str(item["claim_id"])] = bool(item.get("skip", False))
            merged["claims"] = [
                {
                    **asdict(claim),
                    "skip": claim_patch.get(claim.claim_id, claim.skip),
                }
                for claim in current.claims
            ]
        if "file_base64" in payload:
            resume_text, pdf_bytes = self._decode_pdf(payload["file_base64"])
            merged["resume_text"] = resume_text
            merged["claims"] = [
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "source": claim.source,
                    "skip": False,
                }
                for claim in claims_from_text(resume_id, resume_text)
            ]
            merged["status"] = "extracted"
            self.resume_store.save_pdf(resume_id, pdf_bytes)
        merged["updated_at"] = updated_at()
        validated = resume_from_dict(merged)
        self.resume_store.save(validated)
        return validated

    def _decode_pdf(self, raw: str) -> tuple[str, bytes]:
        """校验 Base64 PDF，返回提取的文本层与原始字节。"""
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("file_base64 不能为空")
        try:
            pdf_bytes = base64.b64decode(raw.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("file_base64 不是合法的 Base64 编码") from exc
        if not pdf_bytes:
            raise ValueError("PDF 文件为空")
        if len(pdf_bytes) > MAX_PDF_BYTES:
            raise ValueError("PDF 文件不能超过 10MB")
        resume_text = extract_pdf_text(pdf_bytes)
        if not resume_text.strip():
            raise ValueError(
                "无法从 PDF 提取文本：该文件可能是扫描件或图片型 PDF，请改用文本粘贴"
            )
        return resume_text, pdf_bytes

    def reorder_resumes(self, ordered_ids: list[str]) -> dict:
        """按给定顺序持久化简历列表排序（0 为最前）。"""
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise ValueError("resume_ids 必须是至少包含一个元素的数组")
        normalized = []
        for item in ordered_ids:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("resume_ids 必须只包含字符串")
            if item.strip() in normalized:
                raise ValueError(f"resume_ids 包含重复项：{item.strip()}")
            normalized.append(item.strip())
        try:
            self.resume_store.reorder(tuple(normalized))
        except KeyError as exc:
            raise ResumeNotFoundError(str(exc)) from exc
        return {"reordered": len(normalized)}

    def delete_resume(self, resume_id: str) -> None:
        try:
            self.resume_store.delete(str(resume_id).strip())
        except KeyError as exc:
            raise ResumeNotFoundError(f"resume not found: {resume_id}") from exc

    def ingest_project(
        self,
        source: ProjectSource,
        project_id: int | str,
        project_name: str | None = None,
    ) -> ProjectAnalysis:
        normalized_id = normalize_project_id(project_id)
        self._delete_project_knowledge(normalized_id)
        name = str(project_name) if project_name is not None else str(normalized_id)
        source_type = str(getattr(source, "source_type", ""))
        record = ProjectAnalysis(
            project_id=normalized_id,
            project_name=name,
            source_type=source_type,
            analysis_status=AnalysisStatus.CREATED,
        )
        self._save_analysis(record)
        try:
            result = self.ingestion_service.ingest(normalized_id, source)
            record = replace(
                record,
                workspace_path=str(result.project_root),
                analysis_status=AnalysisStatus.SOURCE_READY,
            )
            self._save_analysis(record)
            return record
        except Exception as exc:
            self._save_failed(record, exc)
            raise

    def analyze_project(self, project_id: int | str) -> ProjectAnalysis:
        normalized_id = normalize_project_id(project_id)
        record = self.get_project_analysis(normalized_id)
        if not record.workspace_path:
            raise ValueError(f"project has no ingested source: {normalized_id}")
        try:
            self._delete_project_knowledge(normalized_id)
            record = replace(
                record,
                analysis_status=AnalysisStatus.SCANNING,
                analyzer_id="",
                universal_model=None,
                knowledge=None,
                error="",
            )
            self._save_analysis(record)
            artifact_root = Path(record.workspace_path)
            structure = self.scanner.scan(artifact_root)
            record = replace(record, analysis_status=AnalysisStatus.ANALYZING)
            self._save_analysis(record)
            try:
                analyzer = self.analyzer_registry.select(structure)
            except LookupError as root_error:
                nested_matches = []
                for child in sorted(artifact_root.iterdir(), key=lambda item: item.name.casefold()):
                    if not child.is_dir():
                        continue
                    child_structure = self.scanner.scan(child)
                    try:
                        child_analyzer = self.analyzer_registry.select(child_structure)
                    except LookupError:
                        continue
                    nested_matches.append((child, child_analyzer))
                if len(nested_matches) != 1:
                    raise root_error
                artifact_root, analyzer = nested_matches[0]
            record = replace(record, analyzer_id=str(getattr(analyzer, "analyzer_id", "")))
            self._save_analysis(record)
            universal_model = analyzer.analyze(artifact_root, normalized_id)
            if getattr(universal_model, "project_id", None) != normalized_id:
                raise ValueError(
                    "UniversalProjectModel project_id does not match requested project_id: "
                    f"{getattr(universal_model, 'project_id', None)} != {normalized_id}"
                )
            knowledge = project_model_to_knowledge(universal_model)
            if record.project_name and record.project_name != str(normalized_id):
                knowledge = replace(knowledge, project_name=record.project_name)
            self.repository.save(knowledge)
            ready = replace(
                record,
                project_name=knowledge.project_name,
                analysis_status=AnalysisStatus.READY,
                universal_model=universal_model,
                knowledge=knowledge,
                error="",
            )
            self._save_analysis(ready)
            return ready
        except Exception as exc:
            self._save_failed(record, exc)
            raise ProjectAnalysisError(normalized_id, self._error_message(exc)) from exc

    def get_project_analysis(self, project_id: int | str) -> ProjectAnalysis:
        normalized_id = normalize_project_id(project_id)
        try:
            get_analysis = getattr(self.repository, "get_analysis", None)
            if callable(get_analysis):
                return get_analysis(normalized_id)
            return self._analysis_records[normalized_id]
        except KeyError:
            try:
                project = self.repository.get(normalized_id)
            except KeyError:
                raise KeyError(f"项目不存在: {normalized_id}") from None
            record = ProjectAnalysis(
                project_id=normalized_id,
                project_name=project.project_name,
                source_type="manual",
                analysis_status=AnalysisStatus.READY,
                knowledge=project,
            )
            self._analysis_records[normalized_id] = record
            return record

    def get_project_knowledge(self, project_id: int | str) -> ProjectKnowledge:
        record = self.get_project_analysis(project_id)
        if record.knowledge is not None:
            return record.knowledge
        try:
            return self.repository.get(record.project_id)
        except KeyError:
            raise KeyError(f"项目知识不存在: {record.project_id}") from None

    def ingest_and_analyze_project(self, payload: dict[str, Any]) -> ProjectAnalysis:
        project_id = payload["project_id"]
        source_descriptor = payload.get("source", payload)
        source = self.source_from_descriptor(source_descriptor)
        self.ingest_project(source, project_id, payload.get("project_name"))
        return self.analyze_project(project_id)

    @staticmethod
    def source_from_descriptor(descriptor: dict[str, Any]) -> ProjectSource:
        if not isinstance(descriptor, dict):
            raise TypeError("source must be an object")
        source_type = descriptor.get("type", descriptor.get("source_type"))
        if source_type in {"zip", "directory"}:
            if not descriptor.get("source_path"):
                raise ValueError(f"{source_type} source requires source_path")
            limits = InterviewService._quota_limits(descriptor)
            source = (
                ZipSource(Path(descriptor["source_path"]), **limits)
                if source_type == "zip"
                else DirectorySource(Path(descriptor["source_path"]), **limits)
            )
            return source
        if source_type == "folder":
            files = []
            for item in descriptor.get("files", []):
                if not isinstance(item, dict) or "path" not in item or "content" not in item:
                    raise ValueError("Folder source files require path and content")
                content = item["content"]
                if not isinstance(content, str):
                    raise TypeError("Folder source content must be a string")
                files.append(FolderFile(path=str(item["path"]), content=content.encode("utf-8")))
            return FolderSource(files)
        raise ValueError("source type must be zip, directory or folder")

    @staticmethod
    def _quota_limits(descriptor: Mapping[str, Any]) -> dict[str, int]:
        """读取并校验 zip / directory 描述符的配额字段。"""
        limits = {}
        defaults = {
            "max_total_size": ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE,
            "max_file_size": ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE,
            "max_files": ZIP_DESCRIPTOR_DEFAULT_MAX_FILES,
        }
        for name, default in defaults.items():
            value = descriptor.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"{name} must be a non-negative integer"
                )
            if value > default:
                raise ValueError(
                    f"{name} exceeds server maximum: {value} > {default}"
                )
            limits[name] = value
        return limits

    def _save_analysis(self, record: ProjectAnalysis) -> None:
        self._analysis_records[record.project_id] = record
        save_analysis = getattr(self.repository, "save_analysis", None)
        if callable(save_analysis):
            save_analysis(record)

    def _delete_project_knowledge(self, project_id: int) -> None:
        self._analysis_records.pop(project_id, None)
        delete = getattr(self.repository, "delete", None)
        if callable(delete):
            delete(project_id)

    def _save_failed(self, record: ProjectAnalysis, exc: Exception) -> ProjectAnalysis:
        failed = replace(
            record,
            analysis_status=AnalysisStatus.FAILED,
            error=self._error_message(exc),
        )
        self._save_analysis(failed)
        return failed

    @staticmethod
    def _error_message(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"

    def start_session(
        self,
        project_id: int | str,
        candidate_id: str = "default",
        review_mode: ReviewMode | str = ReviewMode.TECHNICAL_INTERVIEW,
        title: str | None = None,
        topic_name: str | None = None,
        position_id: str | None = None,
        position_question_id: str | None = None,
        agent_mode: str = "single",
        agent_ids: Mapping[str, str] | None = None,
    ) -> tuple[str, InterviewState]:
        normalized_id = normalize_project_id(project_id)
        candidate_id = normalize_candidate_id(candidate_id)
        resolved_review_mode = (
            review_mode
            if isinstance(review_mode, ReviewMode)
            else ReviewMode(review_mode)
        )
        resolved_agent_mode = str(agent_mode).strip() or "single"
        if resolved_agent_mode not in ("single", "multi"):
            raise ValueError("agent_mode 必须是 single 或 multi")
        requested_title = _session_title(title) if title is not None else ""
        requested_topic_name = str(topic_name).strip() if topic_name is not None else ""
        if topic_name is not None and not requested_topic_name:
            raise ValueError("主题名称不能为空")
        requested_position_id = str(position_id).strip() if position_id is not None else ""
        requested_question_id = (
            str(position_question_id).strip() if position_question_id is not None else ""
        )
        if position_question_id is not None and not requested_question_id:
            raise ValueError("岗位题目 ID 不能为空")
        if requested_question_id and not requested_position_id:
            raise ValueError("position_question_id 必须和 position_id 一起传入")
        position_question = None
        position = None
        if requested_position_id:
            position = self.get_position(requested_position_id)
            if position.candidate_id != candidate_id:
                raise ValueError("岗位与面试者不匹配")
            if normalized_id not in position.project_ids:
                raise ValueError("当前项目未关联到该岗位")
            candidates = [
                question
                for question in position.questions
                if question.project_id in (None, normalized_id)
            ]
            if requested_question_id:
                position_question = next(
                    (question for question in candidates if question.question_id == requested_question_id),
                    None,
                )
                if position_question is None:
                    raise ValueError("岗位题库中不存在该题目")
            elif candidates:
                position_question = candidates[0]
                requested_question_id = position_question.question_id
            if position_question and not requested_topic_name and position_question.evidence_ids:
                project = self.repository.get(normalized_id)
                evidence_ids = set(position_question.evidence_ids)
                matched_topic = next(
                    (topic for topic in project.topics if evidence_ids.intersection(topic.evidence)),
                    None,
                )
                if matched_topic:
                    requested_topic_name = matched_topic.name
        session_id = uuid.uuid4().hex
        resume_claims = self._resume_claims_for_candidate(str(candidate_id))
        profile = self.profile_store.get(candidate_id)
        definitions = self._resolve_agent_definitions(resolved_agent_mode, agent_ids)
        resolved_agent_ids = {
            stage: definition.agent_id for stage, definition in definitions.items()
        }
        agent = self._agent_for_profile(
            profile,
            resolved_review_mode,
            resolved_agent_mode,
            resolved_agent_ids,
        )
        try:
            workflow = self._workflow_for_agent(agent)
            start_kwargs = {"project_id": normalized_id}
            if requested_topic_name:
                start_kwargs["topic_name"] = requested_topic_name
            if resume_claims:
                start_kwargs["resume_claims"] = resume_claims
            if self.workflow_checkpointer is None:
                state = workflow.start(**start_kwargs)
            else:
                state = workflow.start(
                    thread_id=session_id,
                    **start_kwargs,
                )
        except KeyError as exc:
            raise ProjectNotFoundError(f"项目不存在: {normalized_id}") from exc
        state = replace(
            state,
            candidate_id=str(candidate_id),
            review_mode=resolved_review_mode.value,
            title=requested_title
            or (
                f"{position.company + ' · ' if position and position.company else ''}{position.title}"
                if position
                else f"{state.project.project_name} · {state.current_topic.name}"
            ),
            question=position_question.text if position_question else state.question,
            question_evidence_ids=(
                position_question.evidence_ids
                if position_question
                else state.question_evidence_ids
            ),
            question_covered_points=(
                (position_question.requirement,)
                if position_question
                else state.question_covered_points
            ),
            resume_claims=resume_claims,
            position_id=requested_position_id,
            position_question_id=requested_question_id,
            position_requirement=(
                position_question.requirement if position_question else ""
            ),
            position_title=position.title if position else "",
            agent_mode=resolved_agent_mode,
            agent_ids=resolved_agent_ids,
        )
        self._save_session(session_id, state, expected_version=0)
        return session_id, state

    def get_session(self, session_id: str) -> InterviewState:
        try:
            state = self.session_store.get(session_id)
            get_candidate_id = getattr(self.session_store, "get_candidate_id", None)
            owner = (
                str(get_candidate_id(session_id))
                if callable(get_candidate_id)
                else str(state.candidate_id or "default")
            )
            return state if state.candidate_id == owner else replace(state, candidate_id=owner)
        except KeyError as exc:
            raise SessionNotFoundError(f"session not found: {session_id}") from exc

    def list_sessions(
        self,
        *,
        candidate_id: str | None = None,
        project_id: int | str | None = None,
        position_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        normalized_candidate = (
            normalize_candidate_id(candidate_id) if candidate_id is not None else None
        )
        normalized_project = (
            normalize_project_id(project_id) if project_id is not None else None
        )
        list_sessions = getattr(self.session_store, "list", None)
        if not callable(list_sessions):
            raise ValueError("session store does not support listing sessions")
        list_kwargs = {
            "candidate_id": normalized_candidate,
            "project_id": normalized_project,
            "limit": limit,
        }
        if position_id is not None:
            list_kwargs["position_id"] = str(position_id).strip()
        rows = list_sessions(**list_kwargs)
        summaries = []
        for session_id, state, updated_at in rows:
            scores = [record.evaluation.score for record in state.history]
            summaries.append(
                {
                    "session_id": session_id,
                    "title": state.title
                    or f"{state.project.project_name} · {state.current_topic.name}",
                    "project_id": state.project_id,
                    "project_name": state.project.project_name,
                    "candidate_id": state.candidate_id,
                    "review_mode": state.review_mode,
                    "status": state.status,
                    "current_topic": state.current_topic.name,
                    "question": state.question,
                    "question_count": len(state.history),
                    "average_score": round(sum(scores) / len(scores)) if scores else None,
                    "next_direction": state.next_direction,
                    "updated_at": updated_at,
                    "completed_at": state.completed_at,
                    "position_id": state.position_id,
                    "position_question_id": state.position_question_id,
                    "position_requirement": state.position_requirement,
                }
            )
        return {"sessions": summaries, "count": len(summaries)}

    def rename_session(self, session_id: str, title: str) -> InterviewState:
        normalized_title = _session_title(title)
        with self._session_lock(session_id):
            state, version = self._read_session_with_version(session_id)
            renamed = replace(state, title=normalized_title)
            self._save_session(session_id, renamed, expected_version=version)
            return renamed

    def delete_session(self, session_id: str) -> None:
        with self._session_lock(session_id):
            delete = getattr(self.session_store, "delete", None)
            if not callable(delete):
                raise ValueError("session store does not support deleting sessions")
            try:
                delete(session_id)
            except KeyError as exc:
                raise SessionNotFoundError(f"session not found: {session_id}") from exc

    def complete_session(self, session_id: str) -> InterviewState:
        with self._session_lock(session_id):
            state, version = self._read_session_with_version(session_id)
            if state.status == "completed":
                return state
            if state.status != "waiting_answer":
                raise ValueError("当前会话不在可结束状态")
            if not state.history:
                raise ValueError("至少完成一次回答后才能结束会话")
            completed = replace(
                state,
                status="completed",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._save_session(session_id, completed, expected_version=version)
            return completed

    def _read_session_with_version(
        self, session_id: str
    ) -> tuple[InterviewState, int | None]:
        try:
            get_with_version = getattr(self.session_store, "get_with_version", None)
            if callable(get_with_version):
                state, version = get_with_version(session_id)
            else:
                state = self.session_store.get(session_id)
                version = None
                get_candidate_id = getattr(self.session_store, "get_candidate_id", None)
                if callable(get_candidate_id):
                    owner = str(get_candidate_id(session_id))
                    if state.candidate_id != owner:
                        state = replace(state, candidate_id=owner)
            return state, version
        except KeyError as exc:
            raise SessionNotFoundError(str(exc)) from exc

    def _save_session(self, session_id, state, expected_version=None):
        save_if_version = getattr(self.session_store, "save_if_version", None)
        if callable(save_if_version):
            return save_if_version(session_id, state, expected_version)
        save = self.session_store.save
        try:
            parameters = inspect.signature(save).parameters.values()
            supports_version = any(
                parameter.name == "expected_version"
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_version = False
        if supports_version:
            return save(session_id, state, expected_version=expected_version)
        return save(session_id, state)

    def submit_answer(
        self,
        session_id: str,
        answer: str,
        candidate_id=_MISSING_CANDIDATE_ID,
    ) -> InterviewState:
        with self._session_lock(session_id):
            state, version = self._read_session_with_version(session_id)
            owner = normalize_candidate_id(state.candidate_id or "default")
            with self._candidate_lock(owner):
                return self._submit_answer_locked(
                    session_id, state, version, answer, candidate_id
                )

    @contextmanager
    def _session_lock(self, session_id: str) -> Lock:
        with self._registered_lock(
            self._session_locks, self._session_locks_guard, session_id
        ) as lock:
            yield lock

    @contextmanager
    def _candidate_lock(self, candidate_id: str) -> Lock:
        with self._registered_lock(
            self._candidate_locks, self._candidate_locks_guard, candidate_id
        ) as lock:
            yield lock

    @staticmethod
    @contextmanager
    def _registered_lock(registry, registry_guard, key):
        with registry_guard:
            entry = registry.get(key)
            if entry is None:
                entry = (Lock(), 0)
            lock, references = entry
            registry[key] = (lock, references + 1)
        lock.acquire()
        try:
            yield lock
        finally:
            lock.release()
            with registry_guard:
                current = registry.get(key)
                if current is not None and current[0] is lock:
                    references = current[1] - 1
                    if references == 0:
                        registry.pop(key, None)
                    else:
                        registry[key] = (lock, references)

    def _read_profile_with_version(self, candidate_id):
        get_with_version = getattr(self.profile_store, "get_with_version", None)
        if callable(get_with_version):
            return get_with_version(candidate_id)
        return self.profile_store.get(candidate_id), None

    def _restore_profile_after_failure(
        self,
        candidate_id,
        old_profile,
        old_version,
        working_profile,
    ):
        if old_version is None:
            return self._restore_profile(candidate_id, old_profile)
        get_with_version = getattr(self.profile_store, "get_with_version", None)
        if not callable(get_with_version):
            raise ProfileConflictError(
                f"candidate profile restore requires version support: {candidate_id}"
            )
        current_profile, current_version = get_with_version(candidate_id)
        if current_version == old_version:
            return None
        if current_version != old_version + 1:
            raise ProfileConflictError(
                f"candidate profile restore conflict: {candidate_id} "
                f"expected commit version {old_version + 1}, current {current_version}"
            )
        if working_profile is not None and current_profile != working_profile:
            raise ProfileConflictError(
                f"candidate profile restore conflict: {candidate_id} "
                "profile changed before rollback"
            )
        return self._restore_profile(
            candidate_id,
            old_profile,
            expected_version=current_version,
        )

    def _submit_answer_locked(
        self,
        session_id: str,
        state: InterviewState,
        expected_version: int | None,
        answer: str,
        candidate_id=_MISSING_CANDIDATE_ID,
    ) -> InterviewState:
        owner = str(state.candidate_id or "default")
        if candidate_id is not _MISSING_CANDIDATE_ID:
            requested = normalize_candidate_id(candidate_id)
            if requested != owner:
                raise ValueError("candidate_id does not match session owner")
        old_profile, old_profile_version = self._read_profile_with_version(owner)
        profile = copy.deepcopy(old_profile)
        agent = self._agent_for_profile(
            profile,
            ReviewMode(state.review_mode),
            state.agent_mode,
            state.agent_ids,
        )
        workflow = self._workflow_for_agent(agent)
        if self.workflow_checkpointer is None:
            updated = workflow.resume(state, answer)
        else:
            updated = workflow.resume(
                state,
                answer,
                thread_id=session_id,
            )
        pending_update = getattr(agent, "pending_profile_update", None)
        pending_update = self._attach_weakness_sources(
            session_id,
            pending_update,
            updated,
        )
        if (
            isinstance(pending_update, ProfileUpdate)
            and pending_update.weakness_sources
            and hasattr(agent, "profile")
        ):
            agent.profile.merge_weakness_sources(
                pending_update.topic,
                pending_update.weakness_sources,
            )

        try:
            committed_version = self._save_session(
                session_id,
                updated,
                expected_version=expected_version,
            )
        except SessionConflictError:
            raise
        except Exception as original:
            rollback_error = self._restore_session(
                session_id, state, expected_version=expected_version
            )
            if rollback_error is not None:
                raise RuntimeError(
                    f"{original}; rollback failed: {rollback_error}"
                ) from original
            raise

        try:
            self._commit_profile(owner, agent, pending_update, updated)
        except Exception as original:
            rollback_errors = []
            session_error = self._restore_session(
                session_id, state, expected_version=committed_version
            )
            if session_error is not None:
                rollback_errors.append(f"session: {session_error}")
            profile_error = self._restore_profile_after_failure(
                owner,
                old_profile,
                old_profile_version,
                getattr(agent, "profile", None),
            )
            if profile_error is not None:
                rollback_errors.append(f"profile: {profile_error}")
            if rollback_errors:
                raise RuntimeError(
                    f"{original}; rollback failed: {', '.join(rollback_errors)}"
                ) from original
            raise

        return updated

    @staticmethod
    def _attach_weakness_sources(session_id, pending_update, updated):
        if not isinstance(pending_update, ProfileUpdate) or not updated.history:
            return pending_update
        record_index = len(updated.history) - 1
        record = updated.history[record_index]
        retained_weaknesses = set(pending_update.weaknesses)
        sources = tuple(
            WeaknessSource(
                weakness=weakness,
                session_id=session_id,
                project_id=updated.project_id,
                record_index=record_index,
                question=record.question,
                evidence_ids=record.evaluation.evidence_ids,
            )
            for weakness in record.evaluation.weaknesses
            if weakness and weakness in retained_weaknesses
        )
        return replace(pending_update, weakness_sources=sources)

    def _commit_profile(self, owner, agent, pending_update, updated):
        if pending_update is None:
            if updated.evaluation is not None and hasattr(agent, "profile"):
                return self.profile_store.save(owner, agent.profile)
            return None
        commit = getattr(self.profile_store, "commit", None)
        if callable(commit):
            return commit(owner, pending_update)
        else:
            merge = getattr(self.profile_store, "merge", None)
            if callable(merge):
                merge(owner, pending_update)
            else:
                self.profile_store.save(owner, agent.profile)
            return None

    def _restore_session(self, session_id, state, expected_version=None):
        try:
            self._save_session(
                session_id,
                state,
                expected_version=expected_version,
            )
        except Exception as exc:
            return exc
        return None

    def _restore_profile(self, owner, profile, expected_version=None):
        try:
            if expected_version is None:
                self.profile_store.save(owner, profile)
            else:
                restore = getattr(self.profile_store, "restore_if_version", None)
                if not callable(restore):
                    raise ProfileConflictError(
                        f"candidate profile restore requires CAS support: {owner}"
                    )
                restore(owner, profile, expected_version)
        except Exception as exc:
            return exc
        return None

    def get_candidate_profile(self, candidate_id: str = "default"):
        return self.profile_store.get(normalize_candidate_id(candidate_id))

    def get_candidate_profile_summary(self, candidate_id: str = "default") -> dict:
        candidate_id = normalize_candidate_id(candidate_id)
        get_with_version = getattr(self.profile_store, "get_with_version", None)
        if callable(get_with_version):
            profile, version = get_with_version(candidate_id)
        else:
            profile, version = self.profile_store.get(candidate_id), 0
        return {
            "candidate_id": candidate_id,
            "schema_version": CURRENT_PROFILE_SCHEMA_VERSION,
            "version": version,
            "skills": {
                topic: asdict(snapshot)
                for topic, snapshot in profile.skills.items()
            },
        }

    def get_session_report(self, session_id: str) -> dict:
        state = self.get_session(session_id)
        records = list(state.history)
        scores = [record.evaluation.score for record in records]

        def unique(values):
            return list(dict.fromkeys(value for value in values if value))

        topic_rows = {}
        for record in records:
            row = topic_rows.setdefault(record.topic, {"scores": [], "count": 0})
            row["count"] += 1
            row["scores"].append(record.evaluation.score)

        return {
            "session_id": session_id,
            "project_id": state.project_id,
            "project_name": state.project.project_name,
            "candidate_id": state.candidate_id,
            "review_mode": state.review_mode,
            "status": state.status,
            "completed_at": state.completed_at,
            "question_count": len(records),
            "average_score": round(sum(scores) / len(scores)) if scores else None,
            "strengths": unique(
                strength
                for record in records
                for strength in record.evaluation.strengths
            ),
            "weaknesses": unique(
                weakness
                for record in records
                for weakness in record.evaluation.weaknesses
            ),
            "evidence_ids": unique(
                evidence_id
                for record in records
                for evidence_id in record.evaluation.evidence_ids
            ),
            "topics": [
                {
                    "name": topic,
                    "count": row["count"],
                    "average_score": round(sum(row["scores"]) / len(row["scores"])),
                }
                for topic, row in topic_rows.items()
            ],
            "records": [
                {
                    "question": record.question,
                    "answer": record.answer,
                    "topic": record.topic,
                    "level": record.level,
                    "evaluation": asdict(record.evaluation),
                }
                for record in records
            ],
            "next_direction": state.next_direction,
        }
