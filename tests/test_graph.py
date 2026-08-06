import unittest

from langgraph.checkpoint.memory import InMemorySaver

from interview_agent.agent import InterviewAgent
from interview_agent.graph import InterviewGraph
from interview_agent.models import ProjectKnowledge, Topic
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.service import InterviewService


class RecordingAgent:
    def __init__(self):
        self.calls = []

    def start(self, *, project_id):
        self.calls.append(("start", project_id))
        return {"kind": "started", "project_id": project_id}

    def load_project(self, project_id):
        self.calls.append("load_project")
        return "project"

    def select_initial_topic(self, project):
        self.calls.append("select_initial_topic")
        return "topic"

    def generate_initial_question(self, project, topic):
        self.calls.append("generate_initial_question")
        return {
            "question": "question",
            "question_result": "question_result",
        }

    def assemble_initial_state(
        self, project_id, project, topic, question, question_result
    ):
        self.calls.append("assemble_initial_state")
        return {"kind": "started", "project_id": project_id}

    def validate_answer(self, state, answer):
        self.calls.append("validate")

    def evaluate_answer(self, state, answer):
        self.calls.append("evaluate")
        return {"evaluation": "evaluation", "history": ["history"]}

    def update_profile(self, state, evaluation):
        self.calls.append("update_profile")
        return {
            "working_profile": "profile",
            "pending_profile_update": "profile_update",
        }

    def decide_follow_up(self, state, evaluation, history, working_profile):
        self.calls.append("decide_follow_up")
        return {
            "direction": "deep",
            "next_level": 2,
            "next_topic": "topic",
        }

    def generate_follow_up_question(
        self, state, history, direction, next_level, next_topic
    ):
        self.calls.append("generate_question")
        return {"next_question": "next question", "question_result": "question"}

    def assemble_follow_up(
        self,
        state,
        answer,
        evaluation,
        history,
        working_profile,
        pending_profile_update,
        direction,
        next_level,
        next_topic,
        next_question,
        question_result,
    ):
        self.calls.append("assemble")
        return {
            "kind": "resumed",
            "state": state,
            "answer": answer,
        }


class InterviewGraphTests(unittest.TestCase):
    def test_start_runs_initial_nodes_in_order(self):
        agent = RecordingAgent()

        result = InterviewGraph(agent).start(7)

        self.assertEqual(result, {"kind": "started", "project_id": 7})
        self.assertEqual(
            agent.calls,
            [
                "load_project",
                "select_initial_topic",
                "generate_initial_question",
                "assemble_initial_state",
            ],
        )

    def test_resume_runs_turn_nodes_in_order(self):
        agent = RecordingAgent()
        state = {"question": "question"}

        result = InterviewGraph(agent).resume(state, "answer")

        self.assertEqual(
            result,
            {
                "kind": "resumed",
                "state": state,
                "answer": "answer",
            },
        )
        self.assertEqual(
            agent.calls,
            [
                "validate",
                "evaluate",
                "update_profile",
                "decide_follow_up",
                "generate_question",
                "assemble",
            ],
        )

    def test_service_uses_injected_workflow_factory(self):
        calls = []

        class RecordingWorkflow:
            def __init__(self, agent):
                self.agent = agent

            def start(self, *, project_id):
                calls.append("start")
                return self.agent.start(project_id=project_id)

            def resume(self, state, answer):
                calls.append("resume")
                return self.agent.submit_answer(state, answer)

        class RecordingWorkflowFactory:
            def __call__(self, agent):
                return RecordingWorkflow(agent)

        service = InterviewService(
            repository=InMemoryProjectRepository(),
            workflow_factory=RecordingWorkflowFactory(),
        )
        service.register_project(
            {
                "project_id": 7,
                "project_name": "demo",
                "topics": [{"name": "Transaction", "score": 90}],
            }
        )

        session_id, _ = service.start_session(7)
        service.submit_answer(session_id, "use transaction")

        self.assertEqual(calls, ["start", "resume"])

    def test_optional_checkpointer_persists_thread_state_and_history(self):
        repository = InMemoryProjectRepository()
        repository.save(
            ProjectKnowledge(
                project_id=7,
                project_name="demo",
                topics=[Topic(name="Transaction", score=90)],
            )
        )
        graph = InterviewGraph(
            InterviewAgent(repository=repository),
            checkpointer=InMemorySaver(),
        )

        initial = graph.start(7, thread_id="session-7")
        updated = graph.resume(initial, "use transaction", thread_id="session-7")

        snapshot = graph.get_state(thread_id="session-7")
        history = list(graph.get_state_history(thread_id="session-7"))
        self.assertEqual(snapshot.values["result"], updated)
        self.assertGreaterEqual(len(history), 2)

    def test_service_passes_session_id_to_optional_checkpointer(self):
        repository = InMemoryProjectRepository()
        checkpointer = InMemorySaver()
        service = InterviewService(
            repository=repository,
            workflow_checkpointer=checkpointer,
        )
        service.register_project(
            {
                "project_id": 7,
                "project_name": "demo",
                "topics": [{"name": "Transaction", "score": 90}],
            }
        )

        session_id, _ = service.start_session(7)
        service.submit_answer(session_id, "use transaction")

        checkpoints = list(
            checkpointer.list(
                {"configurable": {"thread_id": session_id}}
            )
        )
        self.assertGreaterEqual(len(checkpoints), 2)
        self.assertEqual(len(service.get_session(session_id).history), 1)


if __name__ == "__main__":
    unittest.main()
