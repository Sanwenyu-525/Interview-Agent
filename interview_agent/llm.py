"""通用 OpenAI 兼容 LLM 客户端与面试领域适配器。"""

from __future__ import annotations

import json
import os
import re
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

from .agent import InterviewAgent, RuleBasedQuestionGenerator
from .models import Evaluation, ProjectKnowledge, QuestionResult
from .review import InterviewOutlineBuilder


class LLMError(RuntimeError):
    """LLM 请求或响应失败。"""


class LLMResponseError(LLMError):
    """LLM 返回了无法映射到领域模型的内容。"""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    api_mode: str = "chat_completions"
    timeout: float = 60.0
    temperature: float = 0.2
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
        messages: list[dict[str, str]],
        *,
        response_format: dict[str, str] | None = None,
    ) -> str:
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
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            result = "".join(text_parts).strip()
            if result:
                return result
        raise LLMResponseError("LLM 响应 content 不是可读文本")

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


def _to_langchain_message(message: Mapping[str, Any]):
    role = str(message.get("role", "user"))
    content = message.get("content", "")
    if role == "system":
        return SystemMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


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


def _mentions_code_detail(question: str, project: ProjectKnowledge) -> bool:
    normalized = question.casefold()
    if re.search(r"\b[^\s/\\]+\.(?:java|py|js|jsx|ts|tsx|go|rs|cs|cpp|c|h)\b", normalized):
        return True
    if re.search(r"\b[a-z_$][\w$]{2,}\s*(?:方法|函数|类|文件|第\s*\d+\s*行)", question, re.IGNORECASE):
        return True
    return any(
        len(str(component)) >= 3 and str(component).casefold() in normalized
        for component in project.components
    )


class LlmQuestionGenerator:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的项目领域面试官，只输出 JSON；question 必须是非空字符串。",
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
        prompt = {
            "任务": "基于项目知识生成一道面试追问，不要脱离项目事实",
            "项目知识": _project_payload(project),
            "当前主题": {"name": topic.name, "level": level},
            "追问方向": review_direction or getattr(context, "review_direction", ""),
            "当前证据": selected_evidence,
            "可引用证据 ID": list(selected_ids),
            "历史回答": _history_payload(history),
            "问题层级约束": {
                "level_1": "只问系统级大方向：目标、边界、参与方、协作方式和总体方案",
                "level_2": "围绕一条核心流程追问职责划分、数据流转和异常处理",
                "level_3": "讨论边界条件、方案权衡和验证方式",
                "level_4": "讨论容量、稳定性和架构演进",
                "禁止": "不得询问类名、函数名、文件路径、注解或逐行代码",
                "证据用途": "代码证据只用于保证问题来自真实项目，不要把证据位置写进问题",
            },
            "输出格式": {
                "question": "字符串",
                "evidence_ids": ["只填写当前证据中的 ID"],
                "covered_points": ["本题覆盖点"],
                "missing_points": ["仍需追问点"],
            },
        }
        result = self._parse_json(
            self.client.chat(
                self._chat_messages(prompt),
                response_format={"type": "json_object"},
            )
        )
        question = str(result.get("question") or "").strip()
        if not question:
            question = RuleBasedQuestionGenerator().generate(
                topic=topic,
                project=project,
                level=level,
                history=history,
                review_direction=review_direction
                or getattr(context, "review_direction", ""),
            )
            return QuestionResult(
                question=question,
                evidence_ids=selected_ids,
                covered_points=(topic.name,),
            )
        if _mentions_code_detail(question, project):
            question = RuleBasedQuestionGenerator().generate(
                topic=topic,
                project=project,
                level=level,
                history=history,
                review_direction=review_direction
                or getattr(context, "review_direction", ""),
            )
            return QuestionResult(
                question=question,
                evidence_ids=selected_ids,
                covered_points=(topic.name,),
            )
        return QuestionResult(
            question=question,
            evidence_ids=_allowed_ids(result.get("evidence_ids"), selected_ids),
            covered_points=_string_list(result.get("covered_points")),
            missing_points=_string_list(result.get("missing_points")),
        )


class LlmEvaluator:
    def __init__(self, client: OpenAICompatibleClient):
        self.client = client
        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是基于证据评分的项目面试评价官，只输出 JSON。"
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
            "输出格式": {
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
        try:
            score = int(result["score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("LLM 评价响应缺少有效 score") from exc
        return Evaluation(
            score=max(0, min(100, score)),
            strengths=list(_string_list(result.get("strengths"))),
            weaknesses=list(_string_list(result.get("weaknesses"))),
            feedback=str(result.get("feedback", "")).strip(),
            reference_answer=str(result.get("reference_answer") or "").strip(),
            evidence_ids=_allowed_ids(result.get("evidence_ids"), selected_ids),
            covered_points=_string_list(result.get("covered_points")),
            missing_points=_string_list(result.get("missing_points")),
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            return self._parser.parse(content)
        except Exception as exc:
            return _json_object(content)


def agent_from_config(repository, config: LLMConfig) -> InterviewAgent:
    if not config.enabled:
        return InterviewAgent(repository=repository)
    client = OpenAICompatibleClient(config)
    return InterviewAgent(
        repository=repository,
        question_generator=LlmQuestionGenerator(client),
        evaluator=LlmEvaluator(client),
        outline_builder=InterviewOutlineBuilder(),
    )


def agent_from_environment(repository, env: Mapping[str, str] | None = None) -> InterviewAgent:
    config = LLMConfig.from_env(env)
    return agent_from_config(repository, config)


__all__ = [
    "LLMConfig",
    "LLMError",
    "LLMResponseError",
    "LlmEvaluator",
    "LlmQuestionGenerator",
    "OpenAICompatibleClient",
    "agent_from_config",
    "agent_from_environment",
]
