# ADR 0004: AG-UI Visibility Strategy for Agent Teams

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Project owner + architecture discussion

## Context

With the Master/Slave model mounted via `AGUI(team=master)`, we assessed how
much of the team's internal activity the AG-UI frontend can display. Findings
from `agno` 3.0.10's AG-UI mapping layer and the installed `ag-ui-protocol`
0.1.19:

- Member activity is **flattened** into a single assistant message stream.
  Member text deltas are appended to the leader's message (at best with a
  literal `"Team member: "` text prefix); member tool calls carry no agent
  attribution; member completion/failure events are swallowed by the mapping
  layer.
- Member identity *exists* in agno events (`agent_id`, `agent_name`,
  `parent_run_id`) but is discarded by the handlers; it survives only in
  pass-through `RAW` events that CopilotKit does not consume by default.
- HITL pause cards render as generic tool calls — the user cannot see *which
  Slave* requested a sensitive action.
- The upstream AG-UI specification has since defined first-class **Subagent
  Events**, but `ag-ui-protocol` 0.1.19 does not include them and Agno 3.0.10
  does not use `name` fields, Activity events, or any attribution mechanism.
- One free win: with `mode=TeamMode.tasks`, the shared task list is stored in
  `session_state` and synchronized to the frontend via `STATE_SNAPSHOT`, which
  can drive a task-board UI with no mapping changes.

## Decision

Adopt a three-phase visibility strategy:

**Phase 1 (MVP) — accept flattening, curate the surface.**

- Ship with default mapping; consider `stream_member_events=False` if mixed
  member text confuses the conversation (tool events still flow).
- Register a custom renderer for the `delegate_task_to_member` tool call so
  users see "dispatched to home-device agent: <task>" cards — the one
  attribution signal available for free.
- Keep HITL confirmation cards (works out of the box and is a hard requirement
  for sensitive operations).

**Phase 2 — custom AG-UI event mapping for per-Slave transparency.**

When multiple Slaves are live and users need "why did the assistant do that"
transparency (a Claude Code-style expandable subtask UI), replace the mapping
for three handlers: give member text its own message with the `name` field set
(protocol 0.1.19 already supports it), prefix member tool calls as
`{member}:{tool}`, and emit `CUSTOM` events at member run boundaries carrying
`agent_id` / `agent_name` / timing. The frontend aggregates member activity
into collapsible task cards.

**Phase 3 — adopt protocol-native Subagent Events.**

Track `ag-ui-protocol` releases and Agno's adoption of Subagent Events; when
available, migrate and delete the custom mapping.

## Alternatives Considered

- **Invest in custom mapping immediately**: rejected — the MVP has a single
  Master and few tools; full subagent transparency has no audience yet.
- **Parse `RAW` events on the frontend only**: rejected as the main mechanism
  — member tool-call events are consumed by Agno handlers and never reach RAW,
  so the attribution chain breaks exactly where it matters.

## Consequences

- Phase 2 requires maintaining a customized copy of Agno's AG-UI handlers
  (fork or an ASGI overlay); this carries an upgrade-following cost, contained
  by keeping the customization small and event-driven.
- The Phase 1 constraint "users see only the Master's voice" reinforces the
  single-persona experience of ADR 0002.
- Frontend work for Phase 1 is limited to tool-call renderers, well within
  CopilotKit's standard capabilities.
