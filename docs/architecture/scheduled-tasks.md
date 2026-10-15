# Scheduled Tasks — Architecture

> Topic deep-dive companion to [`../architecture.md`](../architecture.md).
> Status: **implemented** (v0.5.0) — decisions frozen in
> [ADR 0007](../adr/0007-scheduled-tasks-agno-scheduler.md) (2026-10-14);
> the first schedule (`etf_grid_daily_sync`) runs on this substrate.
>
> Last updated: 2026-10-14.

---

## 1. Purpose

Scheduled tasks are a **platform capability**: ETF Grid's daily market-data
sync is the first consumer, and future automation (reports, reminders,
routines) builds on the same substrate.

**Current scope is deliberately minimal: deterministic scheduled tasks
only.** A task fires on a cron schedule and calls an HTTP endpoint — no LLM
involvement, no agent execution. Agent-driven scheduled work is a designed
evolution path (§6), not part of this version.

## 2. Relationship to existing decisions

- **ADR 0003** splits automation into three layers. This document
  implements **layer 1 only**: deterministic rules executed directly by the
  scheduler, zero LLM calls, audit log only. It also settles ADR 0003's
  open question about the scheduler entry point: **Agno's built-in AgentOS
  scheduler** (§3).
- **ADR 0002** (single user-facing Master) is untouched in this version:
  no new agents are introduced. The background Automation Agent in §6 is
  deferred design, and would be a non-user-facing executor — the ADR
  wording refinement is deferred together with it.

## 3. Framework foundation: the Agno AgentOS scheduler

Verified against the pinned dependency (**agno 3.1.2**,
`agno/scheduler/{manager,poller,executor}.py`) and the official docs
(https://docs.agno.com/features/scheduling).

### 3.1 Execution model

The scheduler runs **inside the AgentOS process** — no extra service, no
new dependency:

```python
AgentOS(..., scheduler=True, scheduler_poll_interval=15,
        scheduler_base_url="http://127.0.0.1:7777")
```

A poller scans the `agno_schedules` table every `scheduler_poll_interval`
seconds, claims due rows through a database-backed atomic lease, and fires
them. **A schedule is essentially `{cron, endpoint, method, payload}`** —
the unit of scheduling is one HTTP call. The executor has two firing
modes:

- **Run endpoints** (`/agents|teams|workflows/<id>/runs`, matched by regex,
  `POST` only): submits a background run, polls to a terminal state, and
  records the linked `run_id / session_id / output`. Not used in this
  version.
- **Any other endpoint** (our case): a plain JSON request/response —
  **2xx is success**. A schedule therefore points straight at an
  extension's existing REST route; zero new code on the execution path.

### 3.2 Data model

Two Agno-managed tables (already listed in
[database-schema.md](database-schema.md), currently unused):

- **`agno_schedules`**: `name, cron_expr, endpoint, method, payload,
  timezone, timeout_seconds, max_retries, retry_delay_seconds, enabled,
  next_run_at, user_id`, lease columns, and provenance columns (who/which
  run created it).
- **`agno_schedule_runs`**: one row per execution attempt — `status
  (success|failed|...), status_code, error, triggered_at, completed_at`.
  This is the audit log for layer-1 tasks; domain results live in the
  extension's own tables as usual.

### 3.3 Reliability properties

- **Multi-replica safe** via the DB lease, but leases do not make side
  effects exactly-once — **tasks must be idempotent** (ETF Grid's upsert
  pipeline already is).
- **Retries**: per-schedule `max_retries` + `retry_delay_seconds`; every
  attempt persisted.
- **Process-bound**: the scheduler dies with AgentOS. Acceptable for the
  single-host MVP (ADR 0005); recorded as an ADR consequence.
- **Misfire/catch-up** (measured in the v0.5.0 POC): the poller claims any
  schedule whose `next_run_at` is in the past, so a schedule missed during
  downtime **fires once on recovery**, and `next_run_at` then recomputes to
  the next future slot — multiple missed fires collapse into one catch-up
  execution. Scheduled endpoints must tolerate this (ETF Grid's refresh is
  idempotent, so a delayed fire is harmless).
- **Timezone** (measured): `next_run_at` respects the schedule's `timezone`
  (`45 15 * * 1-5` / `Asia/Shanghai` computed to 07:45 UTC as expected).
- **Simple-request run records** (measured): for non-run endpoints,
  `agno_schedule_runs` carries `status` / `status_code` / timings only —
  the response body is *not* captured (`output` is null), so domain results
  must live in the extension's own tables.
- **Dependency**: the scheduler needs the `croniter` package — the project
  depends on `agno[agui,scheduler]` (a missing extra fails loudly at
  registration time).

### 3.4 Management surfaces

- **Code registration** (our primary path): `ScheduleManager(db).create(
  ..., if_exists="update")` at startup — idempotent on restart.
- **REST API**: `/schedules` CRUD and `/schedules/{id}/runs` history —
  for ops and future Client pages.
- **`SchedulerTools`** toolkit: lets an agent manage schedules from
  conversation. Deferred (§6).

## 4. Design: deterministic tasks, direct to REST endpoints

```
agno_schedules row ──cron──> executor ──HTTP POST──> extension REST route
{name, cron, timezone,                              (existing api.py,
 endpoint, payload,                                 zero LLM, idempotent)
 timeout, retries, user_id}
```

- **The carrier is an extension REST route.** ETF Grid's daily sync needs
  no scheduler-specific execution code: the schedule points at one
  composite route contributed by the extension
  (`POST /api/v1/extensions/etf-grid/refresh`, §5).
- **The request is synchronous**: the executor holds the HTTP call open up
  to `timeout_seconds` (default 3600 — ample for our workloads).
- **Failure visibility** comes from `agno_schedule_runs` (status, error
  text) plus the extension's structured logs and own tables.

## 5. Extension integration

Scheduled tasks join the extension contract
([runtime-extensions.md](runtime-extensions.md) §4) as a third contribution
slot:

```python
@dataclass
class ExtensionContribution:
    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)  # NEW
```

`ScheduleSpec` is a declarative dataclass (`name, cron, endpoint, method,
timezone, timeout_seconds, max_retries, retry_delay_seconds, enabled` — all
required; `payload` optional). After `load_extensions()`,
core registers every spec through `ScheduleManager` — startup stays
idempotent and code-registered schedules self-heal on restart.

Reference realization — **ETF Grid** (the first consumer):

The daily task has two steps — network pull then signal recompute — covered
by **one composite route** owned by the extension:

| Schedule | Cron (Asia/Shanghai) | Endpoint |
|----------|----------------------|----------|
| `etf_grid_daily_sync` | `0 9 * * 1,5` (Mon & Fri 09:00) | `POST /api/v1/extensions/etf-grid/refresh` (new) |

The schedule's operational fields (cron, timezone, enabled, retries) load
from the extension's `ETF_GRID_SYNC_*` config, so a deployment can retime
or pause the task without code changes; the structural fields (name,
endpoint) stay in code. Setting `ETF_GRID_SYNC_SCHEDULE_ENABLED=false`
pauses the task — registration converges the DB row to the configured
state on restart.

`POST .../etf-grid/refresh` runs `sync_market_data()` then
`compute_daily_signals()` in one call and returns both results. Error
contract, aligned with the executor's "2xx = success" semantics:

- **All data sources failed** → 5xx, so the schedule run records `failed`
  and the scheduler's `max_retries` kicks in;
- **Partial source failure** → 200 with a per-source `errors` field
  (matching `/sync`'s current body convention) — partial data is still
  worth computing signals over;
- **Compute failure** → 5xx (nothing usable was produced).

The existing granular routes (`/sync`, `/signals/compute`) stay — they
serve the Client page and ad-hoc tool calls; `refresh` is the
schedule-facing composite.

## 6. Evolution path (deferred, not built now)

The following are designed directions this version must not obstruct, in
roughly the order they would land:

1. **Judgment tasks**: schedules pointing at run endpoints — an Agno
  **Workflow** mixing deterministic steps with a conditional agent step
  ("review only when a signal exists"), or an agent run directly for
  pure-judgment tasks.
2. **Automation Agent**: one background, non-user-facing executor agent for
  those judgment steps (isolated `session_id`, shared `user_id` per ADR
  0003). Specialized per-task agents remain possible later — the carrier
  endpoint decides *what* runs, so the role is swappable by configuration.
3. **Notification channel**: agent verdicts (`silent | notify | escalate`)
  are written to a Runtime-side notifications store; the Client renders an
  activity stream; results are never injected into the conversation thread
  (ADR 0003).
4. **Master interaction**, in phases: read schedule results via a toolkit →
  manage schedules via `SchedulerTools` (user-defined tasks in natural
  language) → bidirectional escalation through the shared HITL path.

## 7. Guardrails and open questions

Guardrails:

- **No custom scheduler** (no APScheduler/Celery/system cron).
- **No handler registry or dispatch layer** — a schedule points at an
  endpoint; the route handler is the handler.
- **No agents, workflows, or notification plumbing in this version.**
- **Deterministic stays deterministic** — zero LLM on the sync path, per
  ADR 0003.

Open questions for the next milestones:

- **Result delivery**: how task results reach the user — preliminary
  direction is a push service to a dedicated Client UI (ADR 0007
  decision 5), to be settled with the Client API milestone.
- **Trading-calendar awareness**: the cron fires on weekday holidays too;
  sync is idempotent and simply finds no new candles. Revisit only if the
  wasted calls become a real cost.
