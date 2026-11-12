"""Tests for Agno AG-UI compatibility behavior."""

from collections.abc import AsyncIterator, Iterator
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from ag_ui.core import EventType, ReasoningMessageContentEvent, ReasoningStartEvent, TextMessageContentEvent, TextMessageStartEvent, ToolCallStartEvent
from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui.handlers import process_event
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.stream import stream_agno_response_as_agui_events
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunErrorEvent, RunOutputEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.agui import patch_agui_native_reasoning


@pytest.fixture(autouse=True)
def install_agui_patch() -> None:
    """Install the compatibility patch for every AG-UI test."""
    patch_agui_native_reasoning()


def test_run_content_without_reasoning_keeps_default_mapping() -> None:
    """Ordinary assistant content keeps Agno's original text-message mapping."""
    state = StreamState(thread_id="thread", run_id="run")

    events = process_event(RunContentEvent(content="Answer"), state)

    assert [event.type for event in events] == [EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_CONTENT]
    assert isinstance(events[1], TextMessageContentEvent)
    assert events[1].delta == "Answer"


def test_native_reasoning_streams_before_answer_and_closes_cleanly() -> None:
    """Native reasoning deltas form a complete reasoning span before the answer."""
    chunks: Iterator[RunOutputEvent] = iter(
        [
            RunContentEvent(reasoning_content="Weighing "),
            RunContentEvent(reasoning_content="the options."),
            RunContentEvent(content="Answer"),
            RunCompletedEvent(),
        ]
    )

    events = list(stream_agno_response_as_agui_events(chunks, thread_id="thread", run_id="run"))

    assert [event.type for event in events] == [
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_END,
        EventType.RUN_FINISHED,
    ]
    reasoning_deltas = [event.delta for event in events if isinstance(event, ReasoningMessageContentEvent)]
    assert reasoning_deltas == ["Weighing ", "the options."]
    text_deltas = [event.delta for event in events if isinstance(event, TextMessageContentEvent)]
    assert text_deltas == ["Answer"]


def test_native_reasoning_closes_before_each_tool_call() -> None:
    """Interleaved reasoning and tools produce separate ordered reasoning spans."""
    chunks: Iterator[RunOutputEvent] = iter(
        [
            RunContentEvent(reasoning_content="Thinking 1"),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="first_tool", tool_args={})),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="first_tool", result="first result")),
            RunContentEvent(reasoning_content="Thinking 2"),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="second_tool", tool_args={})),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="second_tool", result="second result")),
            RunContentEvent(content="Answer"),
            RunCompletedEvent(),
        ]
    )

    events = list(stream_agno_response_as_agui_events(chunks, thread_id="thread", run_id="run"))

    lifecycle_events = [
        event.type
        for event in events
        if event.type
        in {
            EventType.REASONING_START,
            EventType.REASONING_MESSAGE_CONTENT,
            EventType.REASONING_END,
            EventType.TOOL_CALL_START,
            EventType.TEXT_MESSAGE_CONTENT,
        }
    ]
    assert lifecycle_events == [
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_END,
        EventType.TOOL_CALL_START,
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_END,
        EventType.TOOL_CALL_START,
        EventType.TEXT_MESSAGE_CONTENT,
    ]
    reasoning_ids = [event.message_id for event in events if isinstance(event, ReasoningStartEvent)]
    assert len(reasoning_ids) == 2
    assert reasoning_ids[0] != reasoning_ids[1]
    reasoning_deltas = [(event.message_id, event.delta) for event in events if isinstance(event, ReasoningMessageContentEvent)]
    assert reasoning_deltas == [(reasoning_ids[0], "Thinking 1"), (reasoning_ids[1], "Thinking 2")]
    tool_call_ids = [event.tool_call_id for event in events if isinstance(event, ToolCallStartEvent)]
    assert tool_call_ids == ["call-1", "call-2"]


def test_agui_endpoint_streams_native_reasoning() -> None:
    """The HTTP AG-UI route emits native reasoning before the assistant answer."""

    async def fake_arun(*args: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        yield RunContentEvent(reasoning_content="Thinking")
        yield RunContentEvent(content="Answer")
        yield RunCompletedEvent()

    db = MagicMock()
    db.get_session.return_value = None
    agent = MagicMock()
    agent.id = "team-leader"
    agent.name = "Team Leader Agent"
    agent.db = db
    agent.user_id = None
    agent.arun = fake_arun
    app = FastAPI()
    app.include_router(AGUI(agent=cast(Agent, agent)).get_router())
    payload = {
        "thread_id": "test-thread",
        "run_id": "test-run",
        "state": {},
        "messages": [{"id": "msg-1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }

    response = TestClient(app).post("/agui", json=payload)

    assert response.status_code == 200
    body = response.text
    assert '"type":"REASONING_MESSAGE_CONTENT"' in body
    assert '"delta":"Thinking"' in body
    assert '"delta":"Answer"' in body
    assert body.index("REASONING_MESSAGE_CONTENT") < body.index("TEXT_MESSAGE_CONTENT")
    assert body.index("REASONING_END") < body.index("TEXT_MESSAGE_START")


def test_metadata_only_run_content_does_not_open_text_message() -> None:
    """Provider metadata without text does not create an empty assistant message."""
    state = StreamState(thread_id="thread", run_id="run")

    events = process_event(RunContentEvent(model_provider_data={"id": "response"}), state)

    assert events == []
    assert state.text_message_open is False


def test_reasoning_only_run_closes_at_completion_without_text() -> None:
    """A reasoning-only run closes its span without manufacturing assistant text."""
    chunks: Iterator[RunOutputEvent] = iter(
        [
            RunContentEvent(reasoning_content="Thinking"),
            RunCompletedEvent(),
        ]
    )

    events = list(stream_agno_response_as_agui_events(chunks, thread_id="thread", run_id="run"))

    assert [event.type for event in events] == [
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.RUN_FINISHED,
    ]


def test_parallel_tools_share_one_required_empty_parent() -> None:
    """Parallel tool calls retain one AG-UI parent without text content events."""
    chunks: Iterator[RunOutputEvent] = iter(
        [
            RunContentEvent(reasoning_content="Thinking"),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="first_tool", tool_args={})),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="second_tool", tool_args={})),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="first_tool", result="first result")),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="second_tool", result="second result")),
            RunContentEvent(content="Answer"),
            RunCompletedEvent(),
        ]
    )

    events = list(stream_agno_response_as_agui_events(chunks, thread_id="thread", run_id="run"))

    text_starts = [event for event in events if isinstance(event, TextMessageStartEvent)]
    tool_starts = [event for event in events if isinstance(event, ToolCallStartEvent)]
    assert len(text_starts) == 2
    assert text_starts[0].message_id != text_starts[1].message_id
    assert [event.parent_message_id for event in tool_starts] == [text_starts[0].message_id, text_starts[0].message_id]
    assert not any(isinstance(event, TextMessageContentEvent) and event.message_id == text_starts[0].message_id for event in events)


def test_run_error_closes_reasoning_without_opening_text() -> None:
    """An error closes active reasoning and remains the terminal event."""
    chunks: Iterator[RunOutputEvent] = iter(
        [
            RunContentEvent(reasoning_content="Thinking"),
            RunErrorEvent(content="Failed"),
        ]
    )

    events = list(stream_agno_response_as_agui_events(chunks, thread_id="thread", run_id="run"))

    assert [event.type for event in events] == [
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.RUN_ERROR,
    ]
