"""Smoke test for the app skeleton.

Verifies that the FastAPI app boots and ``/healthz`` returns the expected
payload. Intentionally trivial.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from spectres_runtime.app import app

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
