"""Unit tests for the Spectres Runtime AgentOS entry point."""

from collections.abc import AsyncIterator
from types import ModuleType
from typing import Any, NamedTuple, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


class MockedMain(NamedTuple):
    """The ``spectres.main`` module with its external dependencies replaced."""

    module: ModuleType
    db: MagicMock


@pytest.fixture
def mocked_main(monkeypatch: pytest.MonkeyPatch) -> MockedMain:
    """Patch database, extensions, agent, schedules, and logging used by ``create_agent_os``."""

    async def _fake_arun(*args: Any, **kwargs: Any) -> AsyncIterator[None]:
        # Empty async generator: AG-UI emits RUN_STARTED / RUN_FINISHED on its own.
        if False:
            yield None

    # No spec: agno touches db attributes (e.g. `id`) beyond the PostgresDb
    # class interface, and a spec'd mock rejects them.
    mock_db = MagicMock()
    # A fresh thread has no persisted session; agno's user-scope check probes
    # db.get_session() and refuses the run if a different owner comes back.
    mock_db.get_session.return_value = None
    mock_agent = MagicMock()
    mock_agent.id = "team-leader"
    mock_agent.name = "Team Leader Agent"
    mock_agent.db = mock_db
    mock_agent.arun = _fake_arun

    replacements: dict[str, Any] = {
        "get_postgres_db": lambda: mock_db,
        "load_extensions": lambda *args, **kwargs: [],
        "create_team_leader_agent": lambda db, extra_tools=None: mock_agent,
        "register_schedules": lambda *args, **kwargs: None,
        # Logging wiring is covered by test_logging; keep the root logger untouched here.
        "configure_logging": lambda *args, **kwargs: None,
    }
    source_modules = {
        "get_postgres_db": "spectres.db.postgres",
        "load_extensions": "spectres.extensions.loader",
        "create_team_leader_agent": "spectres.agents.team_leader",
        "register_schedules": "spectres.scheduler",
        "configure_logging": "spectres.logging",
    }
    # Patch source modules first so a first-time import of spectres.main (which
    # builds the app at import) sees the mocks, then patch the names already
    # bound in spectres.main by an earlier import.
    for name, replacement in replacements.items():
        monkeypatch.setattr(f"{source_modules[name]}.{name}", replacement)
    import spectres.main as main_module

    for name, replacement in replacements.items():
        monkeypatch.setattr(main_module, name, replacement)
    return MockedMain(main_module, mock_db)


@pytest.fixture
def spectres_app(mocked_main: MockedMain) -> FastAPI:
    """Return a fresh AgentOS app with mocked external dependencies."""
    agent_os, _contributions, _extension_state = mocked_main.module.create_agent_os()
    return cast(FastAPI, agent_os.get_app())


@pytest.fixture
def test_client(spectres_app: FastAPI) -> TestClient:
    """Return a TestClient for the mocked AgentOS app."""
    return TestClient(spectres_app)


def test_status_returns_200(test_client: TestClient) -> None:
    """The AGUI /status endpoint responds with HTTP 200."""
    response = test_client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "available"}


def test_agui_endpoint_streams_events(test_client: TestClient) -> None:
    """POST /agui accepts a RunAgentInput payload and streams AG-UI events."""
    payload = {
        "thread_id": "test-thread",
        "run_id": "test-run",
        "state": {},
        "messages": [{"id": "msg-1", "role": "user", "content": "你好"}],
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }

    response = test_client.post("/agui", json=payload)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert "RUN_STARTED" in body
    assert "RUN_FINISHED" in body


def test_agui_endpoint_rejects_invalid_payload(test_client: TestClient) -> None:
    """POST /agui returns 422 for a payload that fails validation."""
    response = test_client.post("/agui", json={"invalid": "payload"})
    assert response.status_code == 422


def test_cors_preflight_allows_configured_origin(test_client: TestClient) -> None:
    """CORS preflight reflects an origin from CORS_ALLOWED_ORIGINS (.env.test: http://localhost:3000)."""
    response = test_client.options(
        "/agui",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_rejects_unlisted_origin(test_client: TestClient) -> None:
    """CORS preflight from an origin outside the allowlist gets no allow header."""
    response = test_client.options(
        "/agui",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"


def test_shutdown_lifespan_closes_postgres_db(mocked_main: MockedMain, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exiting the FastAPI lifespan closes the PostgresDb singleton via AgentOS."""
    from spectres.config import settings

    # Keep the scheduler poller out of the lifespan; only database shutdown is asserted.
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    agent_os, _, _ = mocked_main.module.create_agent_os()

    with TestClient(agent_os.get_app()):
        mocked_main.db.close.assert_not_called()

    mocked_main.db.close.assert_called_once()


def test_agent_os_receives_extension_workflows_and_telemetry_setting(mocked_main: MockedMain, monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentOS receives extension Workflows and the configured telemetry switch."""
    from agno.workflow import Workflow

    from spectres.extensions.base import ExtensionContribution, LoadedExtension

    main_module = mocked_main.module
    workflow = Workflow(id="extension-workflow", steps=[])
    monkeypatch.setattr(
        main_module,
        "load_extensions",
        lambda *args, **kwargs: [LoadedExtension(id="test_extension", name="Test Extension", description="Test extension", contribution=ExtensionContribution(workflows=[workflow]))],
    )
    monkeypatch.setattr(main_module, "ExtensionStateService", lambda *args, **kwargs: MagicMock())
    agent_os_cls = MagicMock()
    monkeypatch.setattr(main_module, "AgentOS", agent_os_cls)

    main_module.create_agent_os()

    assert agent_os_cls.call_args.kwargs["workflows"] == [workflow]
    assert agent_os_cls.call_args.kwargs["telemetry"] is False


def test_mount_extension_routers_reuses_initialized_state_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST mounting receives the existing state service instead of constructing another."""
    import spectres.main as main_module

    app = FastAPI()
    state_service = MagicMock()
    include = MagicMock()
    monkeypatch.setattr(main_module, "include_extension_routers", include)

    main_module.mount_extension_routers(app, [], state_service)

    include.assert_called_once_with(app, [], state_service)
