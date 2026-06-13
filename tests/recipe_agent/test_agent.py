"""Tests: the recipe agent constructs, runs offline, and registers into AgentOS.

The unit tier is hermetic — no network, no database, no live LLM. Construction is
checked by injecting a scripted model; a scripted run proves the wiring is invocable
end-to-end; and the AgentOS surface is exercised through ``TestClient`` against
``/health`` and ``/agents``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAILike
from fastapi.testclient import TestClient

from spectres_runtime.app import build_app
from spectres_runtime.config import Settings
from spectres_runtime.recipe_agent.agent import (
    DEFAULT_USER_ID,
    RECIPE_AGENT_ID,
    RECIPE_AGENT_NAME,
    build_recipe_agent,
)
from tests.conftest import SCRIPTED_RESPONSE, ScriptedModel, run_agent


def test_build_recipe_agent_shape(settings: Settings) -> None:
    agent = build_recipe_agent(settings)

    assert agent.id == RECIPE_AGENT_ID
    assert agent.name == RECIPE_AGENT_NAME
    # The real chat model is constructed (offline) — no placeholder.
    assert isinstance(agent.model, OpenAILike)
    assert agent.model.id == settings.recipe_agent.chat_model
    # The shared db handle is attached.
    assert agent.db is not None
    # Instructions and history depth flow from Settings, not hardcoded.
    assert agent.instructions == settings.recipe_agent.instructions
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == settings.recipe_agent.num_history_runs
    # Single-household default identity, overridable per request.
    assert agent.user_id == DEFAULT_USER_ID
    # Telemetry is explicitly off (Agno defaults it on).
    assert agent.telemetry is False


def test_recipe_agent_runs_offline(
    settings: Settings,
    scripted_model: ScriptedModel,
    tmp_path: Path,
) -> None:
    # A throwaway SQLite file (auto-cleaned by tmp_path) + scripted model keep the run
    # hermetic: history reads/writes stay local and the model never calls out.
    agent = build_recipe_agent(
        settings,
        model=scripted_model,
        db=SqliteDb(db_file=str(tmp_path / "history.db")),
    )

    result = agent.run("What can I cook tonight?")

    assert result.content == SCRIPTED_RESPONSE


@pytest.fixture
def client(settings: Settings, scripted_model: ScriptedModel) -> TestClient:
    agent = build_recipe_agent(settings, model=scripted_model)
    return TestClient(build_app([agent], settings.spectres_web_origin))


def test_health_responds(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recipe_agent_registered(client: TestClient) -> None:
    response = client.get("/agents")
    assert response.status_code == 200
    ids = {entry["id"] for entry in response.json()}
    assert RECIPE_AGENT_ID in ids


@pytest.fixture
def run_client(
    settings: Settings,
    scripted_model: ScriptedModel,
    tmp_path: Path,
) -> TestClient:
    """An AgentOS client backed by a throwaway SQLite db, so the run/session
    endpoints persist locally instead of reaching Postgres."""
    agent = build_recipe_agent(
        settings,
        model=scripted_model,
        db=SqliteDb(db_file=str(tmp_path / "sessions.db")),
    )
    return TestClient(build_app([agent], settings.spectres_web_origin))


def test_run_endpoint_returns_grounded_answer_offline(run_client: TestClient) -> None:
    """`POST /agents/recipe/runs` is functional end-to-end (offline): the scripted
    model proves the Run wiring without a live LLM."""
    response = run_agent(run_client, "晚餐推荐", session_id="s-run", stream=False)

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == SCRIPTED_RESPONSE
    # Runs default to the single-household identity when the request omits user_id.
    assert body["user_id"] == DEFAULT_USER_ID
    assert body["session_id"] == "s-run"


def test_session_is_created_and_scoped_to_default_user(run_client: TestClient) -> None:
    """A run creates a durable session, retrievable via the Sessions endpoint and
    scoped to the default user."""
    run_agent(run_client, "番茄炒蛋怎么做", session_id="s-scope")

    response = run_client.get("/sessions", params={"user_id": DEFAULT_USER_ID})

    assert response.status_code == 200
    sessions = response.json()["data"]
    assert any(s["session_id"] == "s-scope" and s["user_id"] == DEFAULT_USER_ID for s in sessions)


def test_multi_turn_accumulates_runs_in_one_session(run_client: TestClient) -> None:
    """Two turns under one session_id persist as two runs on that session — the
    durable multi-turn wiring (history is replayed; context resolution is proven
    live at the integration tier)."""
    session_id = "s-multi"
    assert run_agent(run_client, "宫保鸡丁怎么做", session_id=session_id).status_code == 200
    assert run_agent(run_client, "那它要炒几分钟？", session_id=session_id).status_code == 200

    response = run_client.get(f"/sessions/{session_id}/runs", params={"user_id": DEFAULT_USER_ID})

    assert response.status_code == 200
    assert len(response.json()) == 2
