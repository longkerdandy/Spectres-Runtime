# ADR 0001: Adopt Agno Team as the Multi-Agent Foundation

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Project owner + architecture discussion

## Context

Spectres Runtime needs a Master Agent (user-facing entry, intent understanding,
task decomposition) that delegates to Slave Agents (domain specialists such as
home-device, calendar, weather, knowledge). We evaluated whether Agno 3.0.10
provides enough multi-agent infrastructure or whether we need a custom
dispatcher.

Findings from source-level research of the installed `agno` 3.0.10 package:

- `agno.team.Team` is a first-class abstraction with four modes:
  `coordinate` (supervisor; default), `route` (forward to one expert verbatim),
  `broadcast` (fan-out to all members), and `tasks` (autonomous task-list loop
  with a dependency DAG).
- Members can be `Agent` or nested `Team` instances, each with its own model,
  tools, knowledge, and memory. Delegation is built in
  (`delegate_task_to_member`), with member results flowing back into the
  leader's context and into a single persisted `TeamSession`.
- Streaming member events bubble to the top-level stream by default
  (`stream_member_events=True`), which matters for AG-UI rendering.
- Human-in-the-loop is end-to-end: `@tool(requires_confirmation=True)` /
  `@approval` on a member tool pauses the member run, the pause propagates to
  the team run, AgentOS exposes `/approvals`, and `continue_run` resumes the
  correct (nested) member.
- AgentOS mounts teams directly (`AgentOS(teams=[...])`,
  `AGUI(team=master_team)`), with REST routes for runs/cancel/resume/continue.
- `TeamFactory` builds a team per request — the official hook for future
  per-user customization.

## Decision

Adopt Agno `Team` with `mode=TeamMode.coordinate` as the carrier for the
Master/Slave model. Do not build a custom orchestration dispatcher. Use
`route` mode or direct leader answers for trivial requests to avoid
unnecessary coordination cost.

The following gaps are explicitly acknowledged and will be addressed in
Runtime code rather than in the framework:

1. **No member-level state isolation** — team `session_state` is shared and
   merged wholesale; per-slave private state requires a namespacing
   convention.
2. **No per-member tool ACL** — Agno controls *whether* a tool needs human
   confirmation, not *which agent may invoke which tool*. A policy layer
   (Toolkit wrappers / `tool_hooks` / guardrails) must be built to satisfy the
   tool-level permission requirement.
3. **No per-member user/tenant isolation** — all members share one `user_id`
   and one `TeamSession`. Acceptable for the single-user phase; multi-tenancy
   will require `TeamFactory` + db-level filtering + `user_isolation`, with
   member-memory cross-user leakage verified separately.
4. **Remote agents cannot be team members** — `members` accepts only local
   `Agent`/`Team`. Device control therefore takes the shape of a local Slave
   Agent plus a custom Toolkit that proxies to the Edge Gateway, never direct
   hardware access.

## Alternatives Considered

- **Custom thin dispatcher**: rejected — would duplicate delegation, session
  persistence, streaming, and HITL plumbing that Team already provides.
- **Agno Workflow as the primary model**: rejected for conversational
  orchestration — Workflow is deterministic topology (fixed
  steps/loops/conditions), while Master/Slave routing must be decided at
  runtime by the LLM. Workflow remains the right tool for fixed automations.

## Consequences

- The existing `team_leader.py` single-agent stub migrates to a `Team`; the
  AG-UI interface switches from `AGUI(agent=...)` to `AGUI(team=...)`.
- Coordination reliability depends on the Master model's capability; the
  Master must run a strong model (framework notes warn that small models
  under-delegate).
- Each delegation costs extra model calls; request classification (direct
  answer vs. route vs. coordinate) becomes a standing design concern.
