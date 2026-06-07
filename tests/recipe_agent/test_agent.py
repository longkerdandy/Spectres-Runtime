"""Tests: the recipe agent constructs, runs offline, and registers into AgentOS.

The unit tier is hermetic — no network, no database, no live LLM. Construction is
checked by injecting hermetic doubles (a scripted model, a fake knowledge base);
a scripted run proves the wiring is invocable end-to-end; and the AgentOS surface
is exercised through ``TestClient`` against ``/health`` and ``/agents``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agno.db.sqlite import SqliteDb
from agno.models.moonshot import MoonShot
from fastapi.testclient import TestClient

from spectres_runtime.app import build_app
from spectres_runtime.config import Settings
from spectres_runtime.recipe_agent.agent import (
    RECIPE_AGENT_ID,
    RECIPE_AGENT_NAME,
    build_recipe_agent,
)
from tests.conftest import SCRIPTED_RESPONSE, FakeKnowledge, ScriptedModel


def test_build_recipe_agent_shape(settings: Settings, fake_knowledge: FakeKnowledge) -> None:
    agent = build_recipe_agent(settings, knowledge=fake_knowledge)

    assert agent.id == RECIPE_AGENT_ID
    assert agent.name == RECIPE_AGENT_NAME
    # The real chat model is constructed (offline) — no placeholder.
    assert isinstance(agent.model, MoonShot)
    assert agent.model.id == settings.chat_model
    # Injected knowledge is wired through; the shared db handle is attached.
    assert agent.knowledge is fake_knowledge
    assert agent.db is not None
    # Instructions and history depth flow from Settings, not hardcoded.
    assert agent.instructions == settings.recipe_agent_instructions
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == settings.recipe_agent_num_history_runs
    # Telemetry is explicitly off (Agno defaults it on).
    assert agent.telemetry is False


def test_recipe_agent_runs_offline(
    settings: Settings,
    scripted_model: ScriptedModel,
    fake_knowledge: FakeKnowledge,
    tmp_path: Path,
) -> None:
    # A throwaway SQLite file (auto-cleaned by tmp_path) + scripted model keep the run
    # hermetic: history reads/writes stay local and the model never calls out.
    agent = build_recipe_agent(
        settings,
        model=scripted_model,
        knowledge=fake_knowledge,
        db=SqliteDb(db_file=str(tmp_path / "history.db")),
    )

    result = agent.run("What can I cook tonight?")

    assert result.content == SCRIPTED_RESPONSE


@pytest.fixture
def client(settings: Settings, scripted_model: ScriptedModel, fake_knowledge: FakeKnowledge) -> TestClient:
    agent = build_recipe_agent(settings, model=scripted_model, knowledge=fake_knowledge)
    return TestClient(build_app([agent]))


def test_health_responds(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recipe_agent_registered(client: TestClient) -> None:
    response = client.get("/agents")
    assert response.status_code == 200
    ids = {entry["id"] for entry in response.json()}
    assert RECIPE_AGENT_ID in ids
