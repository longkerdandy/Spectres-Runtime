"""Team Leader Agent stub for Spectres Runtime."""

from typing import Any

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai.like import OpenAILike

from spectres.config import settings
from spectres.tools.builtin import get_builtin_tools


def create_team_leader_agent(db: PostgresDb, extra_tools: list[Any] | None = None) -> Agent:
    """Create and return the Team Leader Agent stub.

    Args:
        db: Persistent PostgreSQL storage for sessions and chat history.
        extra_tools: Extension toolkits appended after the built-in tools
            (loaded via ``spectres.extensions.loader``).

    Returns:
        Configured Agno Agent instance.
    """
    return Agent(
        id="team-leader",
        name="Team Leader Agent",
        model=OpenAILike(
            id=settings.team_leader_llm_model,
            api_key=settings.team_leader_llm_api_key,
            base_url=settings.team_leader_llm_base_url,
            temperature=settings.team_leader_llm_temperature,
            max_completion_tokens=settings.team_leader_llm_max_completion_tokens,
            extra_headers=settings.team_leader_llm_extra_headers,
        ),
        db=db,
        tools=[*get_builtin_tools(), *(extra_tools or [])],
        instructions=[
            "You are the Team Leader Agent for Spectres Runtime.",
            "Answer user questions using the available tools when needed.",
            "Extension tools (e.g. etf_grid) never raise: they return a JSON envelope — "
            '{"ok": true, "data": ...} on success, {"ok": false, "error": {"type", "message", "trace_id", "hint"}} on failure.',
            'When a tool returns "ok": false, follow error.hint: use the shell tool to grep the Runtime log '
            "(logs/runtime-YYYY-MM-DD.jsonl — one JSON object per line with ts/level/logger/extension/event/message/trace_id fields) "
            "for error.trace_id to see the full failure context, then explain or retry accordingly.",
        ],
        add_history_to_context=True,
        num_history_runs=3,
        add_datetime_to_context=True,
        markdown=True,
    )
