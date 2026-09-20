# ADR 0003: Automation Triggers — Layered Handling and Session Isolation

- **Status**: Accepted
- **Date**: 2026-09-19
- **Deciders**: Project owner + architecture discussion

## Context

A personal assistant must handle many scheduled and event-triggered tasks.
Running all of them through the Master raised a conflict concern: automation
runs could pollute the user's active conversation, race on shared session
state, block user-facing runs, or act against the user's immediate intent
(e.g., a schedule turning off a light the user just turned on).

Analysis split the conflicts into two kinds:

- **Technical conflicts** (session-state races, context pollution, blocking)
  stem from sharing a *session*, not from sharing the *Master*.
- **Logical conflicts** (automation vs. live user intent, automation vs.
  automation) are independent of which agent executes. A separate "automation
  agent" would make these *worse* — two divergent brains issuing commands.

Agno's model supports the needed separation natively: memory and profile
aggregate by `user_id` (shared across sessions), while history and state are
isolated by `session_id`. Team instances are stateless; runs on different
sessions are concurrency-safe.

## Decision

One Master, many sessions. Scheduled/event-triggered work runs as the **same
Master** (same instructions, tools, and user profile) in **separate sessions**
(distinct `session_id`, same `user_id`). Automation outcomes still enrich the
user's long-term profile but never pollute the live conversation.

Triggers are handled in three layers by nature:

| Layer | Examples | Handling |
|-------|----------|----------|
| Deterministic rules | "Turn off lights at 23:00" | Scheduler invokes tools/Workflows directly — **zero LLM calls**, audit log only |
| Judgment-needed triggers | "Air quality dropped — ventilate or run the purifier?" | A Master run in an isolated session, deciding with user-profile context |
| High-frequency raw events | Per-second sensor reports | Filtered and aggregated at the **Edge**; only semantic events ("temperature above threshold for 10 min") reach Runtime |

Logical conflicts are resolved by two mechanisms, not by agent separation:

1. **Edge is the single source of truth for device state.** Any Master run —
   however triggered — must query current state before acting, never assume.
2. **Sensitive actions share one HITL approval path** (Agno
   `requires_confirmation` / `@approval`), whether initiated by the user or
   by automation; the human is the final arbiter.

Proactive results are delivered through a notification channel (or a separate
"activity/updates" stream in the Client), **not** injected into the
conversation thread. The exact Client protocol for this is deferred to the
Client API milestone.

## Alternatives Considered

- **A dedicated automation agent**: rejected — duplicates context, worsens
  logical conflicts, and creates a second owner of the user relationship
  (violates ADR 0002).
- **All triggers invoke the LLM**: rejected on cost and latency; deterministic
  rules and Edge-level filtering absorb the bulk.

## Consequences

- The scheduler/event entry point is an open implementation question
  (in-Runtime scheduler — Agno 3.x ships a `scheduler` module — vs. an
  external component); to be settled when the automation milestone is planned.
- Automation runs are auditable through the same session persistence as
  conversational runs.
- Cost scales with the number of *judgment-needed* triggers only.
