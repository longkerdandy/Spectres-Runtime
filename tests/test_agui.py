"""Tests for the AG-UI interface mounted on AgentOS."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.main import agent_os
from spectres.main import app as main_app


@pytest.fixture
def test_client() -> TestClient:
    """Return a FastAPI TestClient for the AgentOS app."""
    return TestClient(main_app)


@pytest.fixture
def patched_team_leader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the Team Leader Agent's arun so tests do not call a live LLM."""

    async def _fake_arun(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        # Yield no chunks; AGUI will synthesize completion events.
        if False:
            yield None

    agents = agent_os.agents
    assert agents is not None and len(agents) > 0
    team_leader = agents[0]
    monkeypatch.setattr(team_leader, "arun", _fake_arun)


def test_status_returns_200(test_client: TestClient) -> None:
    """Verify the AGUI /status endpoint responds with HTTP 200."""
    response = test_client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "available"}


def test_agui_endpoint_streams_events(
    test_client: TestClient,
    patched_team_leader: None,
) -> None:
    """Verify POST /agui accepts a RunAgentInput payload and streams AG-UI events."""
    payload = {
        "thread_id": "test-thread",
        "run_id": "test-run",
        "state": {},
        "messages": [
            {"id": "msg-1", "role": "user", "content": "你好"},
        ],
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


def test_main_app_is_fastapi() -> None:
    """Verify the AgentOS entry point exposes a FastAPI app."""
    assert isinstance(main_app, FastAPI)
