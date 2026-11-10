"""Real-application checks for disabled Extension side effects."""

from collections.abc import Iterator

import pytest
from agno.run import RunContext
from fastapi.testclient import TestClient

from spectres.extensions.base import LoadedExtension

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
USER_SCOPES = ["agents:read", "agents:*:run", "workflows:run"]
ADMIN_SCOPES = ["agent_os:admin"]

pytestmark = pytest.mark.db


def _headers(sub: str, scopes: list[str]) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def application() -> Iterator[tuple[TestClient, list[LoadedExtension]]]:
    """Build a real application and expose its loaded Extension surfaces."""
    from spectres import main as main_module
    from spectres.config import settings

    old_key, old_audience, old_algorithm = settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm
    settings.jwt_verification_key = DEV_KEY
    settings.jwt_audience = DEV_AUDIENCE
    settings.jwt_algorithm = "HS256"
    try:
        agent_os, extensions, extension_state = main_module.create_agent_os()
        app = agent_os.get_app()
        main_module.mount_extension_routers(app, extensions, extension_state)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, extensions
    finally:
        settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm = old_key, old_audience, old_algorithm


def test_disabled_registered_tool_cannot_write_and_reenable_restores_api(
    application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """A disabled registered write tool cannot add a trade to the ledger."""
    client, extensions = application
    admin = _headers("operator", ADMIN_SCOPES)
    user = _headers("alice", USER_SCOPES)
    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200

    extension = next(extension for extension in extensions if extension.id == "etf_grid")
    toolkit = extension.contribution.toolkits[0]
    function = toolkit.functions["record_grid_trade"]
    assert function.entrypoint is not None
    result = function.entrypoint(
        run_context=RunContext(run_id="run", session_id="session", user_id="alice"),
        symbol="513330.XSHG",
        trade_date="2026-11-06",
        side="buy",
        price="0.4100",
        quantity=100,
        commission_rate="0.001",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "extension_disabled"

    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True}).status_code == 200
    trades = client.get("/api/v1/extensions/etf-grid/trades", headers=user)
    assert trades.status_code == 200
    assert trades.json()["items"] == []


def test_disabled_workflow_run_returns_stop_result_without_recompute(
    application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """The real Workflow run route emits a disabled stop result."""
    client, _ = application
    admin = _headers("operator", ADMIN_SCOPES)
    user = _headers("alice", USER_SCOPES)
    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200

    response = client.post("/workflows/etf_grid_recompute/runs", headers=user, data={"message": "Recompute"})

    assert response.status_code == 200, response.text
    assert '"status":"disabled"' in response.text
    assert '"extension":"etf_grid"' in response.text


async def test_disabled_sync_and_compute_tools_return_before_business_work(
    application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """Both new tools fail closed while disabled and recover after re-enablement."""
    client, extensions = application
    admin = _headers("operator", ADMIN_SCOPES)
    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200
    try:
        extension = next(extension for extension in extensions if extension.id == "etf_grid")
        toolkit = extension.contribution.toolkits[0]
        sync_function = toolkit.async_functions["sync_grid_data"]
        compute_function = toolkit.functions["compute_grid_signals"]
        assert sync_function.entrypoint is not None
        assert compute_function.entrypoint is not None
        context = RunContext(run_id="run", session_id="session", user_id="alice")

        sync_result = await sync_function.entrypoint(run_context=context)
        compute_result = compute_function.entrypoint(run_context=context)

        assert sync_result["error"]["type"] == "extension_disabled"
        assert compute_result["error"]["type"] == "extension_disabled"
    finally:
        assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": True}).status_code == 200
