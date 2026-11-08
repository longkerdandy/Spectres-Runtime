"""Unit tests for Extension REST, Toolkit, and Workflow activation guards."""

import inspect
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from agno.run import RunContext
from agno.tools.toolkit import Toolkit
from agno.workflow import Workflow
from agno.workflow.types import StepInput, StepOutput
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from spectres.extensions.activation import guard_extension_toolkit, guard_extension_workflows, include_extension_routers
from spectres.extensions.base import ExtensionContribution, LoadedExtension
from spectres.extensions.state import ExtensionStateService

pytestmark = pytest.mark.unit


class _SampleToolkit(Toolkit):
    def __init__(self) -> None:
        self.calls: list[str] = []
        super().__init__(name="sample", tools=[self.sync_tool, self.async_tool])

    def sync_tool(self, run_context: RunContext, value: int) -> dict[str, Any]:
        self.calls.append("sync")
        return {"ok": True, "data": {"user_id": run_context.user_id, "value": value}}

    async def async_tool(self, run_context: RunContext) -> dict[str, Any]:
        self.calls.append("async")
        return {"ok": True, "data": run_context.user_id}


def _toolkit_extension(toolkit: Toolkit) -> LoadedExtension:
    return LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(toolkits=[toolkit]))


def test_disabled_sync_tool_preserves_signature_and_skips_business_call() -> None:
    """A disabled sync tool returns an error without entering its business method."""
    toolkit = _SampleToolkit()
    function = toolkit.functions["sync_tool"]
    assert function.entrypoint is not None
    original_signature = inspect.signature(function.entrypoint)
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = False

    guard_extension_toolkit(_toolkit_extension(toolkit), state)

    assert function.entrypoint is not None
    assert inspect.signature(function.entrypoint) == original_signature
    result = function.entrypoint(run_context=RunContext(run_id="run", session_id="session", user_id="alice"), value=3)
    assert result["ok"] is False
    assert result["error"]["type"] == "extension_disabled"
    assert toolkit.calls == []


def test_enabled_sync_tool_calls_original_entrypoint() -> None:
    """An enabled sync tool retains its original result and run context."""
    toolkit = _SampleToolkit()
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = True
    guard_extension_toolkit(_toolkit_extension(toolkit), state)
    function = toolkit.functions["sync_tool"]
    assert function.entrypoint is not None

    result = function.entrypoint(run_context=RunContext(run_id="run", session_id="session", user_id="alice"), value=3)

    assert result == {"ok": True, "data": {"user_id": "alice", "value": 3}}
    assert toolkit.calls == ["sync"]


@pytest.mark.asyncio
async def test_disabled_async_tool_skips_business_call() -> None:
    """The guard supports Agno async functions without executing their body."""
    toolkit = _SampleToolkit()
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = False
    guard_extension_toolkit(_toolkit_extension(toolkit), state)
    function = toolkit.async_functions["async_tool"]
    assert function.entrypoint is not None

    result = await function.entrypoint(run_context=RunContext(run_id="run", session_id="session", user_id="alice"))

    assert result["error"]["type"] == "extension_disabled"
    assert toolkit.calls == []


def _router_app(state: ExtensionStateService) -> tuple[FastAPI, MagicMock]:
    business = MagicMock(return_value={"status": "ok"})
    router = APIRouter(prefix="/api/v1/extensions/sample")

    @router.get("/status")
    def get_status() -> dict[str, str]:
        return cast(dict[str, str], business())

    app = FastAPI()
    extension = LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(routers=[router]))
    include_extension_routers(app, [extension], state)
    return app, business


def test_disabled_router_rejects_before_business_service() -> None:
    """A disabled router fails closed and query input cannot retarget its guard."""
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = False
    app, business = _router_app(state)

    response = TestClient(app).get("/api/v1/extensions/sample/status?extension_name=other")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "extension_disabled"
    business.assert_not_called()


def test_enabled_router_calls_business_service() -> None:
    """An enabled router follows its original business path."""
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = True
    app, business = _router_app(state)

    response = TestClient(app).get("/api/v1/extensions/sample/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    business.assert_called_once()


def test_disabled_workflow_stops_before_business_step() -> None:
    """The activation step stops a disabled Workflow before its business step."""
    business = MagicMock()

    def business_step(step_input: StepInput) -> Any:
        return business(step_input)

    workflow = Workflow(id="sample-workflow", steps=[business_step])
    extension = LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(workflows=[workflow]))
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = False
    guard_extension_workflows(extension, state)

    output = workflow.run(input="test")

    assert output.content == {"status": "disabled", "extension": "sample"}
    business.assert_not_called()


def test_enabled_workflow_continues_to_business_step() -> None:
    """An enabled activation step continues to the original business output."""
    business = MagicMock(return_value=StepOutput(content="done"))

    def business_step(step_input: StepInput) -> Any:
        return business(step_input)

    workflow = Workflow(id="sample-workflow", steps=[business_step])
    extension = LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(workflows=[workflow]))
    state = MagicMock(spec=ExtensionStateService)
    state.is_enabled.return_value = True
    guard_extension_workflows(extension, state)

    output = workflow.run(input="test")

    assert output.content == "done"
    business.assert_called_once()
    assert isinstance(business.call_args.args[0], StepInput)


def test_dynamic_workflow_steps_fail_loud_instead_of_bypassing_guard() -> None:
    """A Workflow shape that cannot receive a static guard aborts assembly."""
    workflow = Workflow(id="dynamic-workflow", steps=cast(Any, lambda: None))
    extension = LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(workflows=[workflow]))
    state = MagicMock(spec=ExtensionStateService)

    with pytest.raises(TypeError, match="static step list"):
        guard_extension_workflows(extension, state)
