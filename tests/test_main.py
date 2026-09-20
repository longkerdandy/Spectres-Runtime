"""Unit tests for the Spectres Runtime AgentOS entry point."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def spectres_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Return a fresh AgentOS app with mocked external dependencies."""

    async def _fake_arun(*args: Any, **kwargs: Any) -> AsyncIterator[None]:
        # Empty async generator: AG-UI emits RUN_STARTED / RUN_FINISHED on its own.
        if False:
            yield None

    # No spec: agno 3.x touches db attributes (e.g. `id`) beyond the
    # PostgresDb class interface, and a spec'd mock rejects them.
    mock_db = MagicMock()
    # A fresh thread has no persisted session; agno 3.x's user-scope check
    # probes db.get_session() and refuses the run if a row with a different
    # owner comes back.
    mock_db.get_session.return_value = None
    mock_agent = MagicMock()
    mock_agent.id = "team-leader"
    mock_agent.name = "Team Leader Agent"
    mock_agent.db = mock_db
    mock_agent.arun = _fake_arun

    monkeypatch.setattr("spectres.main.get_postgres_db", lambda: mock_db)
    monkeypatch.setattr("spectres.main.create_team_leader_agent", lambda db: mock_agent)

    # Import main inside the fixture so module-level creation uses the patched deps.
    from spectres.main import create_agent_os

    return create_agent_os().get_app()


@pytest.fixture
def test_client(spectres_app: FastAPI) -> TestClient:
    """Return a TestClient for the mocked AgentOS app."""
    return TestClient(spectres_app)


def test_main_app_is_fastapi(spectres_app: FastAPI) -> None:
    """The AgentOS entry point exposes a FastAPI app."""
    assert isinstance(spectres_app, FastAPI)


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
