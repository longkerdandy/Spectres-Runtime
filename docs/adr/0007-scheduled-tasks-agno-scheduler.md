# ADR 0007: Scheduled Tasks — Agno Built-in Scheduler, Deterministic-Only MVP

- **Status**: Accepted
- **Date**: 2026-10-14
- **Deciders**: Project owner + architecture discussion

## Context

ADR 0003 established the three-layer automation model and explicitly left
the scheduler entry point open. The ETF Grid extension is now feature-
complete and needs its daily market-data sync + signal computation to run
on a schedule; beyond that, scheduled tasks are a **platform capability**
that many future features (reports, reminders, routines) will build on, so
the substrate must be extensible even though the first scope is small.

Requirements at decision time:

- Cron with timezone support (Asia/Shanghai, market-calendar aligned).
- Persistence of definitions and execution history (audit, per ADR 0003).
- Retries and timeouts per schedule.
- No additional infrastructure for the single-host MVP (ADR 0005).
- Multi-tenancy-ready ownership (`user_id`) from day one.
- A path — committed, not optional — to agent-executed scheduled work
  (Workflows, background agents) after the MVP.

Verified facts about the candidate (agno 3.1.2, pinned): the built-in
AgentOS scheduler is an in-process poller over `agno_schedules` /
`agno_schedule_runs`, claims due rows via a DB-backed atomic lease, and
fires a schedule as **one HTTP call to a configurable endpoint**. Run
endpoints (`/agents|teams|workflows/<id>/runs`) get background execution +
status polling + run linkage; any other endpoint gets a plain JSON
request/response where 2xx is success. `ScheduleManager` (Python),
`/schedules` REST CRUD, and `SchedulerTools` (agent-facing) all exist.
Design detail: [docs/architecture/scheduled-tasks.md](../architecture/scheduled-tasks.md).

## Decision

1. **Adopt the Agno built-in AgentOS scheduler.** No custom scheduler, no
   APScheduler/Celery/system cron. The scheduler runs inside the AgentOS
   process (`scheduler=True`); schedules are code-registered via
   `ScheduleManager` with `if_exists="update"` so startup is idempotent.
2. **MVP scope: deterministic scheduled tasks only (ADR 0003 layer 1).**
   The carrier is an **extension-owned REST route** — the schedule points
   at it directly; zero LLM calls on the execution path; tasks must be
   idempotent. The extension contract gains a `schedules` slot
   (`ScheduleSpec`) so extensions declare their tasks declaratively.
3. **First consumer — ETF Grid**: one schedule `etf_grid_daily_sync`
   (`45 15 * * 1-5`, Asia/Shanghai) → one new composite route
   `POST /api/v1/extensions/etf-grid/refresh` (sync → compute). Error
   contract: 5xx when all data sources fail or compute fails (so the
   schedule run records `failed` and retries); 200 + per-source `errors`
   for partial failures. The granular `/sync` and `/signals/compute`
   routes remain for the Client page and ad-hoc tool calls.
4. **Workflow support is committed, not deferred-maybe.** The MVP is the
   deterministic-only slice of a design that *will* add: Workflow carriers
   (deterministic steps + conditional agent judgment steps), one
   background non-user-facing Automation Agent (with the ADR 0002 wording
   refinement that comes with it), a notification channel for proactive
   results, and phased Master interaction (read results → manage schedules
   via `SchedulerTools` → bidirectional escalation). MVP choices must not
   obstruct this path — that constraint is part of this decision.
5. **Result delivery is deliberately left open.** Preliminary direction
   (owner's preference, not yet decided): a push service delivers task
   results to the Client, rendered in a dedicated UI (activity/updates
   stream rather than the conversation thread, per ADR 0003). To be
   settled with the Client API milestone; until then, results are visible
   through `agno_schedule_runs`, the extension's own tables, and
   conversation (the Master reading persisted data via existing tools).

## Alternatives Considered

- **External/custom scheduler (APScheduler, Celery, system cron)**:
  rejected — duplicates polling, persistence, lease coordination, retries,
  and management surfaces that Agno already provides, and would foreclose
  the committed `SchedulerTools` / run-endpoint integration.
- **Workflow as the carrier for everything, from day one**: rejected for
  the MVP — pure deterministic tasks gain nothing from the Workflow
  abstraction (their execution is a single idempotent pipeline already
  exposed as REST), and the composite route needs zero scheduler-specific
  code. Workflows enter with the first judgment-bearing task (decision 4).
- **A custom handler registry / `function | agent` dispatch layer**:
  rejected — a schedule points at an endpoint; the route handler is the
  handler.
- **Two schedules for ETF Grid (separate sync and compute)** instead of a
  composite route: rejected — sync-then-compute is one logical task; a
  composite route gives atomic scheduling and a single, meaningful
  failure/retry semantics.
- **Delivering results into the conversation thread**: rejected per ADR
  0003 (pollution of the live conversation).

## Consequences

- **The scheduler is process-bound**: when AgentOS is down, schedules do
  not fire. Misfire/catch-up behavior after downtime is undocumented in
  Agno and must be validated in the POC; ETF Grid may need a
  data-staleness check.
- **Idempotency is mandatory** for every scheduled endpoint: the DB lease
  coordinates workers but does not make side effects exactly-once.
- **Endpoint HTTP semantics become scheduler-visible**: handlers must map
  "nothing usable was produced" to 5xx or failures go unnoticed (hence the
  `/refresh` error contract; `/sync`'s 200-with-`errors` convention is not
  schedule-safe on its own).
- **ADR 0002 is not amended yet.** No background agents exist in the MVP;
  the "single *user-facing* Master" wording refinement lands with the
  Automation Agent milestone.
- ADR 0003's open scheduler question is settled by this ADR; its three
  layers, session isolation, and HITL mechanisms are unchanged.
- Scheduled tasks become auditable through `agno_schedule_runs` +
  extension tables from the first task onward.
