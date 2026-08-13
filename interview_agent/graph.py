import inspect
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .agent import InterviewAgent
from .models import InterviewState


class _InterviewGraphState(TypedDict, total=False):
    operation: Literal["start", "resume"]
    project_id: int
    topic_name: str
    resume_claims: Any
    project: Any
    topic: Any
    initial_question: str
    initial_question_result: Any
    state: InterviewState
    answer: str
    evaluation: Any
    history: Any
    working_profile: Any
    pending_profile_update: Any
    direction: str
    next_level: int
    next_topic: Any
    stop: bool
    director_reason: str
    next_question: str
    question_result: Any
    result: InterviewState


class InterviewGraph:
    """面试工作流的 LangGraph 适配器。

    会话持久化仍由 InterviewService 的 SessionStore 负责；本图只执行一次
    start/resume 工作流，不在图内写数据库或保存 checkpoint。
    """

    def __init__(self, agent: InterviewAgent, checkpointer=None):
        self.agent = agent
        self.checkpointer = checkpointer
        self._graph = self._build_graph()

    @staticmethod
    def _call_with_resume_claims(method, *args, resume_claims):
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "resume_claims" in parameters:
            return method(*args, resume_claims=resume_claims)
        return method(*args)

    def _build_graph(self):
        builder = StateGraph(_InterviewGraphState)
        builder.add_node("load_project", self._load_project)
        builder.add_node("select_initial_topic", self._select_initial_topic)
        builder.add_node(
            "generate_initial_question", self._generate_initial_question
        )
        builder.add_node("assemble_initial_state", self._assemble_initial_state)
        builder.add_node("validate_answer", self._validate_answer)
        builder.add_node("evaluate_answer", self._evaluate_answer)
        builder.add_node("update_profile", self._update_profile)
        builder.add_node("decide_follow_up", self._decide_follow_up)
        builder.add_node(
            "generate_follow_up_question", self._generate_follow_up_question
        )
        builder.add_node("assemble_follow_up", self._assemble_follow_up)
        builder.add_node("assemble_stop", self._assemble_stop)
        builder.add_conditional_edges(
            START,
            self._route_operation,
            {
                "start": "load_project",
                "resume": "validate_answer",
            },
        )
        builder.add_edge("load_project", "select_initial_topic")
        builder.add_edge("select_initial_topic", "generate_initial_question")
        builder.add_edge("generate_initial_question", "assemble_initial_state")
        builder.add_edge("assemble_initial_state", END)
        builder.add_edge("validate_answer", "evaluate_answer")
        builder.add_edge("evaluate_answer", "update_profile")
        builder.add_edge("update_profile", "decide_follow_up")
        builder.add_conditional_edges(
            "decide_follow_up",
            self._route_follow_up,
            {
                "continue": "generate_follow_up_question",
                "stop": "assemble_stop",
            },
        )
        builder.add_edge("generate_follow_up_question", "assemble_follow_up")
        builder.add_edge("assemble_follow_up", END)
        builder.add_edge("assemble_stop", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _config(self, thread_id: str | None) -> dict:
        if self.checkpointer is None:
            if thread_id is not None:
                raise ValueError("thread_id requires a configured checkpointer")
            return {}
        if not thread_id or not str(thread_id).strip():
            raise ValueError("thread_id is required when a checkpointer is configured")
        return {"configurable": {"thread_id": str(thread_id)}}

    @staticmethod
    def _route_operation(state: _InterviewGraphState) -> str:
        operation = state.get("operation")
        if operation not in {"start", "resume"}:
            raise ValueError("InterviewGraph operation must be start or resume")
        return operation

    def _load_project(self, state: _InterviewGraphState) -> dict[str, Any]:
        return {"project": self.agent.load_project(state["project_id"])}

    def _select_initial_topic(self, state: _InterviewGraphState) -> dict[str, Any]:
        topic_name = state.get("topic_name", "")
        resume_claims = state.get("resume_claims", ())
        if topic_name:
            topic = self._call_with_resume_claims(
                self.agent.select_initial_topic,
                state["project"],
                topic_name,
                resume_claims=resume_claims,
            )
        else:
            topic = self._call_with_resume_claims(
                self.agent.select_initial_topic,
                state["project"],
                resume_claims=resume_claims,
            )
        return {
            "topic": topic,
        }

    def _generate_initial_question(
        self, state: _InterviewGraphState
    ) -> dict[str, Any]:
        question = self._call_with_resume_claims(
            self.agent.generate_initial_question,
            state["project"],
            state["topic"],
            resume_claims=state.get("resume_claims", ()),
        )
        return {
            "initial_question": question["question"],
            "initial_question_result": question["question_result"],
        }

    def _assemble_initial_state(self, state: _InterviewGraphState) -> dict[str, Any]:
        return {
            "result": self._call_with_resume_claims(
                self.agent.assemble_initial_state,
                state["project_id"],
                state["project"],
                state["topic"],
                state["initial_question"],
                state["initial_question_result"],
                resume_claims=state.get("resume_claims", ()),
            )
        }

    def _validate_answer(self, state: _InterviewGraphState) -> dict[str, Any]:
        self.agent.validate_answer(state["state"], state["answer"])
        return {}

    def _evaluate_answer(self, state: _InterviewGraphState) -> dict[str, Any]:
        return self.agent.evaluate_answer(state["state"], state["answer"])

    def _update_profile(self, state: _InterviewGraphState) -> dict[str, Any]:
        return self.agent.update_profile(state["state"], state["evaluation"])

    def _decide_follow_up(self, state: _InterviewGraphState) -> dict[str, Any]:
        return self.agent.decide_follow_up(
            state["state"],
            state["evaluation"],
            state["history"],
            state["working_profile"],
        )

    @staticmethod
    def _route_follow_up(state: _InterviewGraphState) -> str:
        return "stop" if state.get("stop") else "continue"

    def _assemble_stop(self, state: _InterviewGraphState) -> dict[str, Any]:
        return {
            "result": self.agent.assemble_stop(
                state["state"],
                state["answer"],
                state["evaluation"],
                state["history"],
                state["working_profile"],
                state["pending_profile_update"],
                state.get("director_reason", ""),
            )
        }

    def _generate_follow_up_question(
        self, state: _InterviewGraphState
    ) -> dict[str, Any]:
        return self._call_with_resume_claims(
            self.agent.generate_follow_up_question,
            state["state"],
            state["history"],
            state["direction"],
            state["next_level"],
            state["next_topic"],
            resume_claims=getattr(state["state"], "resume_claims", ()) or (),
        )

    def _assemble_follow_up(self, state: _InterviewGraphState) -> dict[str, Any]:
        return {
            "result": self.agent.assemble_follow_up(
                state["state"],
                state["answer"],
                state["evaluation"],
                state["history"],
                state["working_profile"],
                state["pending_profile_update"],
                state["direction"],
                state["next_level"],
                state["next_topic"],
                state["next_question"],
                state["question_result"],
            ),
        }

    def start(
        self,
        project_id: int,
        *,
        thread_id: str | None = None,
        topic_name: str = "",
        resume_claims=(),
    ) -> InterviewState:
        result = self._graph.invoke(
            {
                "operation": "start",
                "project_id": project_id,
                "topic_name": topic_name,
                "resume_claims": tuple(resume_claims),
            },
            config=self._config(thread_id),
        )
        return result["result"]

    def resume(
        self,
        state: InterviewState,
        answer: str,
        *,
        thread_id: str | None = None,
    ) -> InterviewState:
        result = self._graph.invoke(
            {
                "operation": "resume",
                "state": state,
                "answer": answer,
            },
            config=self._config(thread_id),
        )
        return result["result"]

    def get_state(self, *, thread_id: str):
        if self.checkpointer is None:
            raise ValueError("get_state requires a configured checkpointer")
        return self._graph.get_state(self._config(thread_id))

    def get_state_history(self, *, thread_id: str):
        if self.checkpointer is None:
            raise ValueError("get_state_history requires a configured checkpointer")
        return self._graph.get_state_history(self._config(thread_id))
