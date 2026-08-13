"""通用 OpenAI 兼容 LLM 客户端与面试领域适配器。"""

from __future__ import annotations

import contextvars
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

try:
    from openai import APIError as _OpenAIError
except ImportError:  # pragma: no cover - langchain-openai 依赖 openai SDK
    _OpenAIError = OSError

from .agent import InterviewAgent, RuleBasedEvaluator, RuleBasedQuestionGenerator
from .models import Evaluation, ProjectKnowledge, QuestionResult
from .review import InterviewOutlineBuilder, LlmReviewPolicy


class LLMError(RuntimeError):
    """LLM 请求或响应失败。"""


class LLMResponseError(LLMError):
    """LLM 返回了无法映射到领域模型的内容。"""


class StreamSink:
    """接收 LLM 流式输出片段与用量统计的线程局部回调容器。"""

    def __init__(self, on_token=None, on_usage=None, cancel_event=None):
        self._on_token = on_token or (lambda text: None)
        self._on_usage = on_usage or (lambda usage: None)
        self._cancel_event = cancel_event

    def token(self, text: str) -> None:
        self._on_token(text)

    def usage(self, usage: Mapping[str, Any]) -> None:
        self._on_usage(dict(usage))

    @property
    def cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()


_stream_sink_var = contextvars.ContextVar(
    "interview_agent_stream_sink", default=None
)


def set_stream_sink(sink):
    return _stream_sink_var.set(sink)


def reset_stream_sink(token):
    _stream_sink_var.reset(token)


def get_stream_sink():
    return _stream_sink_var.get()


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    api_mode: str = "chat_completions"
    timeout: float = 60.0
    temperature: float = 0.7
    provider: str = "openai_compatible"
    provider_name: str = "custom"

    @property
    def enabled(self) -> bool:
        return self.provider == "openai_compatible"

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        existing_api_key: str = "",
        require_model: bool = True,
    ) -> "LLMConfig":
        provider = str(payload.get("provider", "rule_based")).strip().lower()
        if provider in {"", "rule_based", "local"}:
            return cls("", "", "", provider="rule_based", provider_name="local")
        if provider != "openai_compatible":
            raise ValueError(f"不支持的 LLM provider: {provider}")

        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", existing_api_key) or "").strip()
        model = str(payload.get("model", "")).strip()
        provider_name = str(payload.get("provider_name", "custom")).strip() or "custom"
        missing = [name for name, value in (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key)) if not value]
        if require_model and not model:
            missing.append("LLM_MODEL")
        if missing:
            raise ValueError(f"LLM 配置缺少: {', '.join(missing)}")

        api_mode = str(payload.get("api_mode", "chat_completions")).strip().lower()
        if api_mode != "chat_completions":
            raise ValueError("当前只支持 api_mode=chat_completions")
        try:
            timeout = float(payload.get("timeout", 60))
            temperature = float(payload.get("temperature", 0.2))
        except ValueError as exc:
            raise ValueError("timeout 和 temperature 必须是数字") from exc
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if temperature < 0:
            raise ValueError("temperature 不能小于 0")
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            api_mode=api_mode,
            timeout=timeout,
            temperature=temperature,
            provider_name=provider_name,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        values = os.environ if env is None else env
        return cls.from_payload(
            {
                "provider": values.get("LLM_PROVIDER", "rule_based"),
                "provider_name": values.get("LLM_PROVIDER_NAME", "custom"),
                "base_url": values.get("LLM_BASE_URL", ""),
                "api_key": values.get("LLM_API_KEY", ""),
                "model": values.get("LLM_MODEL", ""),
                "api_mode": values.get("LLM_API_MODE", "chat_completions"),
                "timeout": values.get("LLM_TIMEOUT_SECONDS", "60"),
                "temperature": values.get("LLM_TEMPERATURE", "0.2"),
            }
        )

    def public_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_name": self.provider_name,
            "base_url": self.base_url,
            "model": self.model,
            "api_mode": self.api_mode,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "configured": self.enabled,
            "api_key_set": bool(self.api_key),
        }


class OpenAICompatibleClient:
    """基于 LangChain ChatOpenAI 的 OpenAI 兼容适配器。

    LangChain 负责与上游模型通信；本类只保留 Chat Completions 的领域适配，
    并把 LangChain/OpenAI 异常归一化为项目的 LLMError / LLMResponseError。
    """

    def __init__(self, config: LLMConfig, llm: BaseChatModel | None = None, transport=None):
        if not config.enabled:
            raise ValueError("OpenAICompatibleClient 需要启用 openai_compatible 配置")
        if config.api_mode != "chat_completions":
            raise ValueError("当前客户端只支持 chat_completions")
        self.config = config
        self._llm = llm or ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            timeout=config.timeout,
        )
        # transport 参数为旧版手写 HTTP 客户端的兼容入口，已由 LangChain 取代。
        self._transport = transport

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        response_format: dict[str, str] | None = None,
    ) -> str:
        sink = _stream_sink_var.get()
        if sink is not None and sink.cancelled:
            raise LLMError("回答生成已取消")
        langchain_messages = [_to_langchain_message(message) for message in messages]
        llm = self._llm
        if response_format is not None:
            try:
                llm = self._llm.bind(response_format=response_format)
            except TypeError:
                # 注入的测试模型可能不支持 bind 参数，回退为直接调用。
                llm = self._llm
        try:
            response = llm.invoke(langchain_messages)
        except (_OpenAIError, OSError) as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc
        return self._response_text(response)

    @staticmethod
    def _response_text(response) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            result = "".join(text_parts).strip()
            if result:
                return result
        raise LLMResponseError("LLM 响应 content 不是可读文本")

    @staticmethod
    def _chunk_text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return ""

    def chat_streamed(
        self,
        messages: list[dict[str, Any]],
        *,
        response_format: dict[str, str] | None = None,
        sink: StreamSink,
    ) -> str:
        langchain_messages = [_to_langchain_message(message) for message in messages]
        llm = self._llm
        if response_format is not None:
            try:
                llm = self._llm.bind(response_format=response_format)
            except TypeError:
                # 注入的测试模型可能不支持 bind 参数，回退为直接调用。
                llm = self._llm
        parts = []
        usage = {}
        try:
            for chunk in llm.stream(langchain_messages):
                if sink.cancelled:
                    raise LLMError("回答生成已取消")
                text = self._chunk_text(getattr(chunk, "content", ""))
                if text:
                    sink.token(text)
                    parts.append(text)
                meta = getattr(chunk, "usage_metadata", None)
                if isinstance(meta, dict) and meta.get("total_tokens"):
                    usage = meta
        except LLMError:
            raise
        except (_OpenAIError, OSError) as exc:
            if sink.cancelled:
                raise LLMError("回答生成已取消") from exc
            # 流式不可用时回退为一次调用，避免评价流程失败。
            try:
                response = llm.invoke(langchain_messages)
            except (_OpenAIError, OSError) as exc2:
                raise LLMError(f"LLM 请求失败: {exc2}") from exc2
            content = self._response_text(response)
            sink.token(content)
            meta = getattr(response, "usage_metadata", None)
            if isinstance(meta, dict):
                usage = meta
            parts = [content]
        if usage:
            sink.usage(
                {
                    "prompt_tokens": int(usage.get("input_tokens") or 0),
                    "completion_tokens": int(usage.get("output_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                }
            )
        return "".join(parts).strip()

    def list_models(self) -> tuple[str, ...]:
        client = getattr(self._llm, "client", None)
        if client is None:
            return ()
        try:
            entries = client.models.list()
            model_ids = [
                str(entry.id).strip()
                for entry in entries
                if getattr(entry, "id", "") and str(entry.id).strip()
            ]
        except (_OpenAIError, AttributeError, TypeError) as exc:
            raise LLMError(f"LLM 模型列表请求失败: {exc}") from exc
        return tuple(dict.fromkeys(model_ids))

    def bind_tools(self, tools):
        """返回绑定了工具定义的底层 ChatModel，供 tool-calling 决策使用。"""
        return self._llm.bind_tools(list(tools))


def _to_langchain_message(message: Mapping[str, Any]):
    role = str(message.get("role", "user"))
    content = message.get("content", "")
    if role == "system":
        return SystemMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def ocr_jd_text(client: OpenAICompatibleClient, image_base64: str, mime_type: str) -> str:
    """用视觉模型从 JD 截图图片中提取原文文本。

    视觉消息使用 OpenAI 兼容的 image_url 内容块；部分视觉模型不支持
    json_object 响应格式，因此直接要求纯文本输出。
    """
    content = [
        {
            "type": "text",
            "text": (
                "你是岗位 JD 提取器。请从图片中提取完整的岗位描述原文"
                "（岗位职责、任职要求、加分项等），只输出 JD 原文文本；"
                "不要总结、不要改写、不要添加任何解释、标题或 markdown 标记。"
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
        },
    ]
    return client.chat([{"role": "user", "content": content}])


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("LLM 未返回合法 JSON") from exc
    if not isinstance(payload, dict):
        raise LLMResponseError("LLM JSON 响应必须是对象")
    return payload


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _allowed_ids(value: Any, allowed: tuple[str, ...]) -> tuple[str, ...]:
    values = _string_list(value)
    return tuple(item for item in values if not allowed or item in allowed)


def _project_payload(project: ProjectKnowledge) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "topics": [
            {"name": topic.name, "score": topic.score, "evidence": list(topic.evidence)}
            for topic in project.topics
        ],
        "components": project.components,
        # 全量 evidence 可达数十万字符；prompt 只保留当前选中证据，避免思考型模型耗尽输出预算
        "dependencies": project.dependencies,
        "weaknesses": project.weaknesses,
    }


def _context_payload(evidence, evidence_ids, context) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    context_evidence = tuple(getattr(context, "evidence", ()) or ()) if context else ()
    context_ids = tuple(getattr(context, "evidence_ids", ()) or ()) if context else ()
    selected_evidence = tuple(evidence or context_evidence)
    selected_ids = tuple(evidence_ids or context_ids)
    return [dict(item) for item in selected_evidence], selected_ids


def _history_payload(history) -> list[dict[str, str]]:
    return [
        {
            "question": record.question,
            "answer": record.answer,
            "topic": record.topic,
            "score": str(record.evaluation.score),
        }
        for record in history
    ]


def _mentions_evidence_location(question: str) -> bool:
    """问题直接暴露证据位置（文件路径、源码后缀或行号）时视为不合格。"""
    normalized = question.casefold()
    if re.search(r"\b[^\s/\\]+\.(?:java|py|js|jsx|ts|tsx|go|rs|cs|cpp|c|h)\b", normalized):
        return True
    return bool(
        re.search(r"(?:src[\\/]|[\\/]\w+\.(?:java|py|js|go|rs|cs)|文件|第\s*\d+\s*行)", question, re.IGNORECASE)
    )


class LlmQuestionGenerator:
    def __init__(self, client: OpenAICompatibleClient, persona: str | None = None):
        self.client = client
        self.persona = persona
        role = persona or "严谨的项目领域面试官"
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"你是{role}，只输出 JSON；question 必须是非空字符串。",
                ),
                ("human", "请根据以下项目知识生成问题：\n{payload}"),
            ]
        )
        self._parser = JsonOutputParser()

    def _chat_messages(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        rendered = self._prompt.invoke(
            {"payload": json.dumps(payload, ensure_ascii=False, default=str)}
        )
        return [
            {"role": message.type, "content": str(message.content)}
            for message in rendered.to_messages()
        ]

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            return self._parser.parse(content)
        except Exception as exc:
            # 兼容 markdown 代码块等容错解析；失败时抛 LLMResponseError。
            return _json_object(content)

    @staticmethod
    def _fallback_question(topic, project, level, history, review_direction, context, selected_ids):
        """LLM 不可用或输出非法时，回退到本地规则出题。"""
        question = RuleBasedQuestionGenerator().generate(
            topic=topic,
            project=project,
            level=level,
            history=history,
            review_direction=review_direction or getattr(context, "review_direction", ""),
            context=context,
        )
        return QuestionResult(
            question=question,
            evidence_ids=selected_ids,
            covered_points=(topic.name,),
        )

    def generate(
        self,
        *,
        topic,
        project,
        level,
        history,
        evidence=None,
        evidence_ids=None,
        context=None,
        review_direction=None,
    ):
        selected_evidence, selected_ids = _context_payload(evidence, evidence_ids, context)
        position_context = None
        if context is not None:
            position_requirement = str(getattr(context, "position_requirement", "") or "")
            if position_requirement:
                position_context = {
                    "岗位名称": str(getattr(context, "position_title", "") or ""),
                    "岗位要求": position_requirement,
                }
        prompt = {
            "任务": "基于项目知识生成一道面试追问，不要脱离项目事实",
            "项目知识": _project_payload(project),
            "当前主题": {"name": topic.name, "level": level},
            "追问方向": review_direction or getattr(context, "review_direction", ""),
            "岗位要求上下文": position_context,
            "当前证据": selected_evidence,
            "可引用证据 ID": list(selected_ids),
            "历史回答": _history_payload(history),
            "提问建议": {
                "level_1": "优先系统级大方向：目标、边界、参与方和整体协作方案",
                "level_2": "优先围绕一条核心流程追问职责划分、数据流转和异常处理",
                "level_3": "优先讨论边界条件、方案权衡和验证方式",
                "level_4": "优先讨论容量、稳定性和架构演进",
                "岗位要求": "存在岗位要求时，追问必须围绕该岗位要求与候选人项目实现的差距展开，让回答能直接支撑该要求的评估；不存在时忽略本建议",
                "自由度": "可以像真人面试官一样自然追问实现细节，允许涉及具体类、方法如何协作，不要因此换成模板",
                "禁止": "不得把证据的文件路径、行号或源代码片段写进问题；问题应当让不掌握项目目录的人也能回答",
            },
            "先分析再提问": {
                "要求": "先写一段 analysis 作为思考沉淀：当前证据已覆盖哪些点、候选人历史回答暴露的薄弱点、上一问与本题的衔接；最终问题必须由这段分析引出",
                "analysis 归属": "只写进响应的 analysis 字段，问题文案本身不得包含 analysis 内容",
            },
            "输出格式": {
                "analysis": "字符串，生成问题的推理过程",
                "question": "字符串",
                "evidence_ids": ["只填写当前证据中的 ID"],
                "covered_points": ["本题覆盖点"],
                "missing_points": ["仍需追问点"],
            },
        }
        try:
            result = self._parse_json(
                self.client.chat(
                    self._chat_messages(prompt),
                    response_format={"type": "json_object"},
                )
            )
        except Exception:
            return self._fallback_question(
                topic, project, level, history, review_direction, context, selected_ids
            )
        question = str(result.get("question") or "").strip()
        if not question or _mentions_evidence_location(question):
            return self._fallback_question(
                topic, project, level, history, review_direction, context, selected_ids
            )
        return QuestionResult(
            question=question,
            evidence_ids=_allowed_ids(result.get("evidence_ids"), selected_ids),
            covered_points=_string_list(result.get("covered_points")),
            missing_points=_string_list(result.get("missing_points")),
            analysis=str(result.get("analysis") or "").strip(),
        )


class LlmEvaluator:
    def __init__(self, client: OpenAICompatibleClient, persona: str | None = None):
        self.client = client
        self.persona = persona
        role = persona or "基于证据评分的项目面试评价官"
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"你是{role}，只输出 JSON。"
                    "除非回答完整、准确且可验证并评分 100，否则必须给出 reference_answer。",
                ),
                ("human", "请评价以下回答：\n{payload}"),
            ]
        )
        self._parser = JsonOutputParser()

    def evaluate(
        self,
        *,
        question,
        answer,
        topic,
        project,
        evidence=None,
        evidence_ids=None,
        context=None,
    ):
        selected_evidence, selected_ids = _context_payload(evidence, evidence_ids, context)
        prompt = {
            "任务": "评价面试者回答，评分必须基于项目证据",
            "项目知识": _project_payload(project),
            "当前主题": topic.name,
            "问题": question,
            "回答": answer,
            "当前证据": selected_evidence,
            "可引用证据 ID": list(selected_ids),
            "先比对再评分": {
                "要求": "评分前先写一段 analysis：逐条比对回答与当前证据，说明回答覆盖了哪些证据、漏掉了哪些事实、哪些说法缺证据支撑",
                "analysis 归属": "只写进响应的 analysis 字段，不进入 feedback 或 reference_answer",
            },
            "输出格式": {
                "analysis": "字符串，证据比对与评分推理过程",
                "score": "0 到 100 的整数",
                "strengths": ["回答做得好的点"],
                "weaknesses": ["回答缺失或不准确的点"],
                "feedback": "可执行的反馈",
                "reference_answer": "如果回答不是 100 分，给出一段基于项目证据的完整参考回答；如果回答完美则为空字符串",
                "evidence_ids": ["回答实际使用到的证据 ID"],
                "covered_points": ["回答覆盖点"],
                "missing_points": ["回答缺失点"],
            },
        }
        try:
            rendered = self._prompt.invoke(
                {"payload": json.dumps(prompt, ensure_ascii=False, default=str)}
            )
            messages = [
                {"role": message.type, "content": str(message.content)}
                for message in rendered.to_messages()
            ]
            sink = get_stream_sink()
            if sink is not None:
                content = self.client.chat_streamed(
                    messages,
                    response_format={"type": "json_object"},
                    sink=sink,
                )
            else:
                content = self.client.chat(
                    messages,
                    response_format={"type": "json_object"},
                )
            result = self._parse_json(content)
            score = int(result["score"])
        except Exception:
            return RuleBasedEvaluator().evaluate(
                question=question, answer=answer, topic=topic, project=project
            )
        return Evaluation(
            score=max(0, min(100, score)),
            strengths=list(_string_list(result.get("strengths"))),
            weaknesses=list(_string_list(result.get("weaknesses"))),
            feedback=str(result.get("feedback", "")).strip(),
            reference_answer=str(result.get("reference_answer") or "").strip(),
            evidence_ids=_allowed_ids(result.get("evidence_ids"), selected_ids),
            covered_points=_string_list(result.get("covered_points")),
            missing_points=_string_list(result.get("missing_points")),
            analysis=str(result.get("analysis") or "").strip(),
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            return self._parser.parse(content)
        except Exception as exc:
            return _json_object(content)


class LlmPositionQuestionGenerator:
    """用 LLM 为岗位题库生成题目；校验失败的条目丢弃，全部失败时由调用方回退本地规则。"""

    def __init__(self, client: OpenAICompatibleClient):
        self.client = client
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的岗位面试出题官，只输出 JSON；questions 必须是数组。",
                ),
                ("human", "请根据岗位要求与项目知识生成题目：\n{payload}"),
            ]
        )
        self._parser = JsonOutputParser()

    def generate(
        self,
        *,
        position_id: str,
        requirements: tuple[str, ...],
        projects: tuple[ProjectKnowledge, ...],
    ) -> tuple["PositionQuestion", ...]:
        from .positions import PositionQuestion

        prompt = {
            "任务": "为每条岗位要求生成一道面试题：能用项目证据支撑的要求生成项目证据题，其余生成经历题",
            "岗位要求": list(requirements),
            "项目知识": [_project_payload(project) for project in projects],
            "题目要求": {
                "每题只针对一条岗位要求，不得合并多条",
                "project_evidence 题必须要求结合具体项目的真实实现、可验证证据和关键权衡",
                "experience 题要求用真实项目或工作经历说明做法、结果和可验证证据",
                "不得暴露文件路径、行号或源码片段",
                "证据 ID 只能从项目知识中主题的 evidence 列表里选取",
            },
            "输出格式": {
                "questions": [
                    {
                        "text": "题目文本",
                        "requirement": "对应的一条岗位要求原文，必须与岗位要求列表逐字一致",
                        "category": "project_evidence 或 experience",
                        "difficulty": "1 到 3 的整数",
                        "project_id": "项目知识中的 project_id 或 null",
                        "evidence_ids": ["证据 ID 列表，最多 3 条；没有则为空数组"],
                    }
                ],
                "数量": "与岗位要求数量一致，最多 8 道",
            },
        }
        rendered = self._prompt.invoke(
            {"payload": json.dumps(prompt, ensure_ascii=False, default=str)}
        )
        messages = [
            {"role": message.type, "content": str(message.content)}
            for message in rendered.to_messages()
        ]
        result = self._parse_json(
            self.client.chat(
                messages,
                response_format={"type": "json_object"},
            )
        )
        raw_items = result.get("questions")
        if not isinstance(raw_items, list):
            raise LLMResponseError("LLM 题库响应缺少 questions 数组")
        questions = []
        for index, item in enumerate(raw_items):
            question = self._validate_item(
                item, position_id, requirements, projects
            )
            if question is not None:
                questions.append(question)
        if not questions:
            raise LLMResponseError("LLM 题库响应没有任何可用的题目")
        return tuple(questions)

    def _validate_item(
        self,
        item: Any,
        position_id: str,
        requirements: tuple[str, ...],
        projects: tuple[ProjectKnowledge, ...],
    ) -> "PositionQuestion | None":
        from .positions import PositionQuestion

        if not isinstance(item, dict):
            return None
        text = str(item.get("text") or "").strip()
        requirement = str(item.get("requirement") or "").strip()
        if not text or not requirement:
            return None
        matched = next(
            (candidate for candidate in requirements if candidate.casefold() == requirement.casefold()),
            "",
        )
        if not matched:
            return None
        category = str(item.get("category") or "experience")
        if category not in {"project_evidence", "experience"}:
            category = "experience"
        try:
            difficulty = int(item.get("difficulty", 2))
        except (TypeError, ValueError):
            difficulty = 2
        difficulty = max(1, min(3, difficulty))
        project_id = item.get("project_id")
        project = None
        if project_id is not None and projects:
            try:
                project = next(
                    (candidate for candidate in projects if candidate.project_id == int(project_id)),
                    None,
                )
            except (TypeError, ValueError):
                project = None
        evidence_ids = ()
        if project is not None:
            allowed = set(project.evidence)
            evidence_ids = tuple(
                dict.fromkeys(
                    str(evidence_id)
                    for evidence_id in _string_list(item.get("evidence_ids"))
                    if str(evidence_id) in allowed
                )
            )[:3]
        if category == "project_evidence" and project is None:
            return None
        return PositionQuestion(
            question_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"interview-agent:{position_id}:{matched}:{project.project_id if project else None}",
            ).hex,
            text=text,
            requirement=matched,
            category=category,
            difficulty=difficulty,
            project_id=project.project_id if project else None,
            evidence_ids=evidence_ids,
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            return self._parser.parse(content)
        except Exception as exc:
            return _json_object(content)


def agent_from_config(repository, config: LLMConfig) -> InterviewAgent:
    client = OpenAICompatibleClient(config) if config.enabled else None
    return InterviewAgent(
        repository=repository,
        question_generator=LlmQuestionGenerator(client),
        evaluator=LlmEvaluator(client),
        outline_builder=InterviewOutlineBuilder(),
        policy=LlmReviewPolicy(client),
        policy_builder=lambda mode: LlmReviewPolicy(client, mode),
    )


def agent_from_environment(repository, env: Mapping[str, str] | None = None) -> InterviewAgent:
    config = LLMConfig.from_env(env)
    return agent_from_config(repository, config)


__all__ = [
    "LLMConfig",
    "LLMError",
    "LLMResponseError",
    "LlmEvaluator",
    "LlmPositionQuestionGenerator",
    "LlmQuestionGenerator",
    "OpenAICompatibleClient",
    "StreamSink",
    "agent_from_config",
    "agent_from_environment",
    "get_stream_sink",
    "ocr_jd_text",
    "reset_stream_sink",
    "set_stream_sink",
]
