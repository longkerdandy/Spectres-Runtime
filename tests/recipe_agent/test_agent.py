"""Tests: the recipe agent constructs and registers into AgentOS.

Asserts construction *shape* and that the placeholder model is never silently
usable — its invocation raises ``NotImplementedError``. The app-level checks go
through ``TestClient`` only (no network, DB, or LLM): ``/healthz`` is retained
and the recipe agent is discoverable on the AgentOS surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spectres_runtime.app import app
from spectres_runtime.recipe_agent.agent import (
    RECIPE_AGENT_ID,
    RECIPE_AGENT_NAME,
    build_recipe_agent,
)

client = TestClient(app)


def test_build_recipe_agent_shape() -> None:
    agent = build_recipe_agent()
    assert agent.id == RECIPE_AGENT_ID
    assert agent.name == RECIPE_AGENT_NAME
    assert agent.model is not None


def test_placeholder_model_is_not_invocable() -> None:
    agent = build_recipe_agent()
    assert agent.model is not None
    with pytest.raises(NotImplementedError):
        agent.model.invoke()


def test_healthz_retained() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recipe_agent_registered() -> None:
    response = client.get("/agents")
    assert response.status_code == 200
    ids = {entry["id"] for entry in response.json()}
    assert RECIPE_AGENT_ID in ids
