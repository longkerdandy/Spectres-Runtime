"""Runtime activation guards shared by Extension HTTP and Toolkit surfaces."""

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any

from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from fastapi import Depends, FastAPI, HTTPException, status

from spectres.extensions.base import LoadedExtension
from spectres.extensions.state import ExtensionStateService


def disabled_tool_result(extension_id: str) -> dict[str, Any]:
    """Return the standard tool-error envelope for a disabled Extension."""
    return {
        "ok": False,
        "error": {
            "type": "extension_disabled",
            "message": f"Extension {extension_id} is disabled",
        },
    }


def _route_guard(extension_id: str, state_service: ExtensionStateService) -> Callable[[], None]:
    def require_enabled() -> None:
        if not state_service.is_enabled(extension_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "extension_disabled",
                    "message": f"Extension {extension_id} is disabled",
                },
            )

    return require_enabled


def include_extension_routers(
    app: FastAPI,
    extensions: list[LoadedExtension],
    state_service: ExtensionStateService,
) -> None:
    """Mount Extension routers with their shared activation guard."""
    for extension in extensions:
        for router in extension.contribution.routers:
            app.include_router(router, dependencies=[Depends(_route_guard(extension.id, state_service))])


def _guarded_entrypoint(
    entrypoint: Callable[..., Any],
    extension_id: str,
    state_service: ExtensionStateService,
) -> Callable[..., Any]:
    signature = inspect.signature(entrypoint)
    if inspect.iscoroutinefunction(entrypoint):

        @wraps(entrypoint)
        async def guarded_async(*args: Any, **kwargs: Any) -> Any:
            if not state_service.is_enabled(extension_id):
                return disabled_tool_result(extension_id)
            return await entrypoint(*args, **kwargs)

        guarded_async.__signature__ = signature  # type: ignore[attr-defined]
        return guarded_async

    @wraps(entrypoint)
    def guarded_sync(*args: Any, **kwargs: Any) -> Any:
        if not state_service.is_enabled(extension_id):
            return disabled_tool_result(extension_id)
        return entrypoint(*args, **kwargs)

    guarded_sync.__signature__ = signature  # type: ignore[attr-defined]
    return guarded_sync


def guard_extension_toolkit(
    extension: LoadedExtension,
    state_service: ExtensionStateService,
) -> None:
    """Wrap every registered Agno Function while preserving its public schema."""
    for toolkit in extension.contribution.toolkits:
        for function in [*toolkit.functions.values(), *toolkit.async_functions.values()]:
            if function.entrypoint is not None:
                function.entrypoint = _guarded_entrypoint(function.entrypoint, extension.id, state_service)


def _workflow_activation_step(extension_id: str, workflow_id: str, state_service: ExtensionStateService) -> Callable[..., StepOutput]:
    def activation(step_input: StepInput, run_context: RunContext | None = None) -> StepOutput:
        del step_input, run_context
        if state_service.is_enabled(extension_id):
            return StepOutput()
        return StepOutput(
            content={"status": "disabled", "extension": extension_id},
            stop=True,
        )

    activation.__name__ = f"{extension_id}_{workflow_id}_activation"
    return activation


def guard_extension_workflows(extension: LoadedExtension, state_service: ExtensionStateService) -> None:
    """Prepend a non-retryable stop step to every Extension Workflow."""
    for workflow in extension.contribution.workflows:
        if not isinstance(workflow.steps, list):
            raise TypeError(f"extension Workflow {workflow.id or extension.id!r} must use a static step list")
        workflow.steps.insert(0, _workflow_activation_step(extension.id, workflow.id or extension.id, state_service))
