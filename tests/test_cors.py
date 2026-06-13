"""Unit tests for CORS wiring — pure, no DB, no network.

AgentOS mounts CORS middleware based on the origin passed to ``build_app()``.
These tests assert that the configured Spectres-Web origin is allowed and that
an arbitrary third-party origin is not.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from spectres_runtime.app import build_app
from spectres_runtime.recipe_agent.agent import build_recipe_agent
from tests.conftest import ScriptedModel, make_settings


def _build_client(origin: str) -> TestClient:
    settings = make_settings(spectres_web_origin=origin)
    agent = build_recipe_agent(settings, model=ScriptedModel(id="scripted", name="Scripted", provider="scripted"))
    app = build_app([agent], settings.spectres_web_origin)
    return TestClient(app)


def test_preflight_allows_configured_origin() -> None:
    client = _build_client("http://localhost:3000")

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]


def test_preflight_rejects_unconfigured_origin() -> None:
    client = _build_client("http://localhost:3000")

    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_actual_request_includes_cors_headers_for_configured_origin() -> None:
    client = _build_client("http://localhost:3000")

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


def test_actual_request_omits_cors_headers_for_unconfigured_origin() -> None:
    client = _build_client("http://localhost:3000")

    response = client.get("/health", headers={"Origin": "http://evil.com"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
