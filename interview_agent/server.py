import os
from pathlib import Path

from .http_api import create_server
from .ingestion import IngestionService, WorkspaceManager
from .llm import LLMConfig, agent_from_config
from .repository import InMemoryProjectRepository
from .positions import SQLitePositionStore
from .resumes import SQLiteResumeStore
from .service import InterviewService
from .memory.profile_store import SQLiteCandidateProfileStore
from .settings import InMemoryLLMSettingsStore, SQLiteLLMSettingsStore
from .sqlite_store import SQLiteProjectRepository, SQLiteSessionStore


def build_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    database: str | None = None,
    workspace_root: str | Path | None = None,
):
    ingestion_service = (
        IngestionService(WorkspaceManager(Path(workspace_root)))
        if workspace_root is not None
        else None
    )
    repository = SQLiteProjectRepository(database) if database else InMemoryProjectRepository()
    session_store = SQLiteSessionStore(database) if database else None
    profile_store = SQLiteCandidateProfileStore(database) if database else None
    position_store = SQLitePositionStore(database) if database else None
    resume_store = SQLiteResumeStore(database) if database else None
    settings_store = SQLiteLLMSettingsStore(database) if database else InMemoryLLMSettingsStore()
    llm_config = settings_store.get()
    if llm_config is None:
        llm_config = LLMConfig.from_env()
        settings_store.save(llm_config)
    agent = agent_from_config(repository, llm_config)
    service = InterviewService(
        repository=repository,
        agent=agent,
        session_store=session_store,
        profile_store=profile_store,
        position_store=position_store,
        resume_store=resume_store,
        ingestion_service=ingestion_service,
        llm_settings_store=settings_store,
        llm_config=llm_config,
    )
    return create_server(service, host=host, port=port)


if __name__ == "__main__":
    server = build_server(database=os.environ.get("INTERVIEW_AGENT_DB", "interview-agent.db"))
    print(f"Interview Agent API listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
