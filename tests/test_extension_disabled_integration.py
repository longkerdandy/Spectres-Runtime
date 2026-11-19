"""Real-application checks for disabled Extension side effects."""

import pytest
from agno.run import RunContext
from fastapi.testclient import TestClient

from spectres.extensions.base import LoadedExtension
from tests.support import ADMIN_SCOPES, auth_headers

USER_SCOPES = ["agents:read", "agents:*:run", "workflows:run"]

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_disabled_registered_tool_cannot_write_and_reenable_restores_api(
    jwt_application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """A disabled registered write tool cannot add a trade to the ledger."""
    client, extensions = jwt_application
    admin = auth_headers("operator", ADMIN_SCOPES)
    user = auth_headers("alice", USER_SCOPES)
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
    jwt_application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """The real Workflow run route emits a disabled stop result."""
    client, _ = jwt_application
    admin = auth_headers("operator", ADMIN_SCOPES)
    user = auth_headers("alice", USER_SCOPES)
    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200

    response = client.post("/workflows/etf_grid_recompute/runs", headers=user, data={"message": "Recompute"})

    assert response.status_code == 200, response.text
    assert '"status":"disabled"' in response.text
    assert '"extension":"etf_grid"' in response.text


async def test_disabled_sync_and_compute_tools_return_before_business_work(
    jwt_application: tuple[TestClient, list[LoadedExtension]],
) -> None:
    """Both new tools fail closed while disabled and recover after re-enablement."""
    client, extensions = jwt_application
    admin = auth_headers("operator", ADMIN_SCOPES)
    assert client.patch("/api/v1/extensions/etf_grid", headers=admin, json={"enabled": False}).status_code == 200
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
