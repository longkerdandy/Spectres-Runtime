"""Compatibility patches for the Agno AG-UI interface."""

from ag_ui.core import BaseEvent
from agno.os.interfaces.agui import handlers
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunContentEvent, RunEvent
from agno.run.base import BaseRunOutputEvent

_ORIGINAL_ON_RUN_CONTENT = handlers.on_run_content
_ORIGINAL_ON_TOOL_CALL_STARTED = handlers.on_tool_call_started


def _on_run_content_with_native_reasoning(chunk: BaseRunOutputEvent, state: StreamState) -> list[BaseEvent]:
    """Map native model reasoning carried by run-content events to AG-UI reasoning events."""
    if not isinstance(chunk, RunContentEvent):
        return _ORIGINAL_ON_RUN_CONTENT(chunk, state)

    events: list[BaseEvent] = []
    reasoning_content = chunk.reasoning_content
    content = chunk.content

    if reasoning_content and reasoning_content != content:
        events.extend(handlers.on_reasoning_content_delta(chunk, state))
        if not content:
            return events

    if state.reasoning_message_id is not None:
        if not content:
            return events
        events.extend(handlers.on_reasoning_completed(chunk, state))

    if not content:
        return events

    events.extend(_ORIGINAL_ON_RUN_CONTENT(chunk, state))
    return events


def _on_tool_call_started_with_native_reasoning(chunk: BaseRunOutputEvent, state: StreamState) -> list[BaseEvent]:
    """Close native reasoning before starting a tool call."""
    if getattr(chunk, "tool", None) is None:
        return _ORIGINAL_ON_TOOL_CALL_STARTED(chunk, state)

    events = handlers.on_reasoning_completed(chunk, state)
    events.extend(_ORIGINAL_ON_TOOL_CALL_STARTED(chunk, state))
    return events


def patch_agui_native_reasoning() -> None:
    """Install native-reasoning support without modifying the installed Agno package."""
    handlers.on_run_content = _on_run_content_with_native_reasoning
    handlers.HANDLERS[RunEvent.run_content.value] = _on_run_content_with_native_reasoning
    handlers.on_tool_call_started = _on_tool_call_started_with_native_reasoning
    handlers.HANDLERS[RunEvent.tool_call_started.value] = _on_tool_call_started_with_native_reasoning
