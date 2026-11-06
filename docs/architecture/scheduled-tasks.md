# Scheduled Tasks — Architecture

> Topic deep-dive companion to [`README.md`](README.md).
> Status: **implemented** (v0.5.0; native CRUD and extension Workflow targets
> completed in v0.6.5) — decisions recorded in
> [ADR 0007](../adr/0007-scheduled-tasks-agno-scheduler.md) and
> [ADR 0011](../adr/0011-extension-workflows-for-scheduled-tasks.md).
>
> Last updated: 2026-11-06 (preserve stored system schedules on restart).

---

## 1. Purpose

Scheduled tasks are a **platform capability**: ETF Grid's shared market-data
sync and user-managed signal recompute are the first consumers, and future
automation (reports, reminders, routines) builds on the same substrate.

**Current Workflows are deterministic.** A schedule targets an Agno
Agent/Team/Workflow run endpoint or makes one ordinary HTTP request. Extensions
contribute Workflow instances directly; one-step and sequential multi-step
Workflows use the same native scheduler contract without an Action wrapper.
No LLM or agent execution is used by the ETF Grid Workflows.

This implements **layer 1** of ADR 0003's three automation layers and
settles its open question about the scheduler entry point: **Agno's
built-in AgentOS scheduler**. ADR 0002 (single user-facing Master) is
untouched — no new agents; the background Automation Agent in §5 is
deferred design.

## 2. Framework foundation: the Agno AgentOS scheduler

Verified against the pinned dependency (**agno 3.1.2**,
`agno/scheduler/{manager,poller,executor}.py`) and the official docs
(https://docs.agno.com/features/scheduling).

### 2.1 Execution model

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
  records the linked `run_id / session_id / output`. ETF Grid uses this mode
  for both extension Workflows.
- **Any other endpoint**: a plain JSON request/response — **2xx is success**.
  This mode remains available for admin-managed extension HTTP targets but is
  not selectable by ordinary users through native schedule writes.

### 2.2 Data model

Two Agno-managed schedule tables (see [database-schema.md](database-schema.md)):

- **`agno_schedules`**: `name, cron_expr, endpoint, method, payload,
  timezone, timeout_seconds, max_retries, retry_delay_seconds, enabled,
  next_run_at, user_id`, lease columns, and provenance columns.
- **`agno_schedule_runs`**: one row per execution attempt — `status
  (success|failed|...), status_code, error, triggered_at, completed_at,
  user_id`. The owner is copied from the parent schedule so history queries
  use the same isolation filter. Workflow targets also link the Workflow run,
  session, and structured output. Domain results continue to live in the
  extension's own tables.

With `user_isolation=True`, schedule management and history are scoped to
`user_id`. An owned schedule executes with its owner forwarded in
`X-Schedule-Owner` and as the native Workflow run `user_id`; an unowned
(`NULL`) schedule executes unscoped under the internal service token. NULL
means a system task, not a schedule shared with every regular user. See
[Per-User Data Isolation](data-isolation.md).

### 2.3 Reliability properties

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
  execution. Scheduled endpoints must tolerate this.
- **Timezone** (measured): `next_run_at` respects the schedule's `timezone`
  (`45 15 * * 1-5` / `Asia/Shanghai` computed to 07:45 UTC as expected).
- **Simple-request run records** (measured): for non-run endpoints,
  `agno_schedule_runs` carries `status` / `status_code` / timings only —
  the response body is *not* captured (`output` is null). Component run
  targets instead retain linked run/session ids and structured output.
- **Dependency**: the scheduler needs the `croniter` package — the project
  depends on `agno[agui,scheduler]` (a missing extra fails loudly at
  registration time).

### 2.4 Management surfaces

- **Code registration** (system tasks): startup looks up each unowned schedule
  by name and skips an existing row without modifying it. Missing rows are
  created with `if_exists="skip"`; `enabled=False` is applied only to a newly
  created row. ETF Grid uses this only for its sole unowned data-sync schedule.
  Configuration therefore supplies initial values, while subsequent cron,
  targeting, retry, timing, and enable/disable changes belong to the database
  and survive restarts.
- **REST API** (personal tasks and administration): native `/schedules` CRUD,
  state changes, manual trigger, and run history. Runtime never seeds personal
  schedules.
- **`SchedulerTools`** toolkit: lets an agent manage schedules from
  conversation. Deferred (§5).

The management API contract is Agno-native:

| Method | Path | Required scope |
|--------|------|----------------|
| POST | `/schedules` | `schedules:write` plus target run permission |
| GET | `/schedules` | `schedules:read` or `agent_os:admin` |
| GET | `/schedules/{schedule_id}` | `schedules:read` or `agent_os:admin` |
| PATCH | `/schedules/{schedule_id}` | `schedules:write` plus target run permission when retargeting |
| DELETE | `/schedules/{schedule_id}` | `schedules:delete` or `agent_os:admin` |
| POST | `/schedules/{schedule_id}/enable` | `schedules:write` plus target run permission |
| POST | `/schedules/{schedule_id}/disable` | `schedules:write` or `agent_os:admin` |
| POST | `/schedules/{schedule_id}/trigger` | `schedules:write` plus target run permission |
| GET | `/schedules/{schedule_id}/runs` | `schedules:read` or `agent_os:admin` |
| GET | `/schedules/{schedule_id}/runs/{run_id}` | `schedules:read` or `agent_os:admin` |

Schedule-management clients discover Workflows through Agno's native
`GET /workflows`. Workflow definitions have no system/personal flag or owner;
the native catalog filters them by the caller's Workflow scopes. Clients derive
a run target as `/workflows/{workflow_id}/runs`. Visibility in this catalog does
not grant execution: creating, retargeting, enabling, or triggering a schedule
still requires permission to run its target.

The schedule list supports `enabled`, `limit`, and `page`; run history supports
`limit` and `page`. Both return Agno's `{data, meta}` pagination envelope.
Detail reads and cross-user writes return 404 for nonexistent and out-of-scope
rows alike. Run detail also requires the run's `schedule_id` to match the path.
Creating or retargeting a non-run HTTP endpoint requires `agent_os:admin`;
ordinary users can target only component runs covered by their scopes.

An unowned schedule is a **public/system task** in product terminology, but
“public” does not mean readable or writable by every user. Ordinary users
receive only their owned personal tasks and runs; administrators receive every
public and personal task and run. No `user_id` query parameter or payload field
can broaden this scope.

## 3. Design: deterministic extension Workflows

```
agno_schedules row ──cron──> executor ──background run──> extension Workflow
{name, cron, timezone,                                  one or more ordered,
 endpoint, payload,                                     deterministic steps
 timeout, retries, user_id}
```

- **The carrier is an Agno component run endpoint.** For ETF Grid the target is
  a Workflow contributed by the extension, not a generic Action dispatcher or a
  scheduler-specific REST adapter. The executor submits a background run and
  polls it to a terminal state.
- **One and multiple steps share one contract.** A simple operation is a
  one-step Workflow; sequential operations use an ordered Workflow. This
  milestone does not add a separate DAG, dependency, or parallel-step layer.
- **Failure visibility** comes from `agno_schedule_runs` (status, error text,
  linked run/session/output), Workflow run records, extension structured logs,
  and extension tables.

## 4. Extension integration

Scheduled tasks join the extension contract
([runtime-extensions.md](runtime-extensions.md) §4) through Workflow and
ScheduleSpec contributions:

```python
@dataclass
class ExtensionContribution:
    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)
```

After `load_extensions()`, core passes all Workflows to AgentOS and registers
each declarative `ScheduleSpec` through `ScheduleManager`. Workflow ids are
stable and extension-prefixed. Code registration is used only for system
schedules: an existing current-name row is skipped, while a row found under a
declared `previous_names` entry is renamed without changing any other field.
Personal schedules use native REST CRUD and are not reconciled or recreated at
startup.

Reference realization — **ETF Grid**:

| Workflow | Ownership | Automatic schedule |
|----------|-----------|--------------------|
| `etf_grid_data_sync` | Unowned system execution | One `ETF Grid Daily Sync`, initially using the configured cron and timezone; migrated from `etf_grid_daily_sync` |
| `etf_grid_recompute` | Required JWT/schedule owner | None; each user creates and manages their own |

The data-sync Workflow calls `sync_market_data()` once for enabled configured
symbols and never enumerates private ledger owners. Total source failure
returns an unsuccessful step so schedule retries apply; partial source failure
remains successful with a body-level `errors` field. Its schedule uses
`ETF_GRID_SYNC_*` for initial operational configuration and retains its stored
configuration, identity, and unowned run history on later restarts.

The recompute Workflow calls `compute_daily_signals(user_id=...)` with
`RunContext.user_id`. Missing identity fails closed, and payload user ids are
ignored. It reads the latest persisted shared candles and valuation when it
runs; there is no strict ordering with data sync and no automatic personal
schedule migration. Users who want recurring recompute must explicitly create
a schedule targeting `POST /workflows/etf_grid_recompute/runs` with the native
Workflow `message` payload.

The existing granular routes stay: `/sync` is an authenticated-user/internal
shared-data operation, while `/signals/compute` is self-scoped to the
authenticated caller. `refresh_grid_data` performs shared sync plus only the
current run owner's computation. The admin/internal `/refresh` route remains a
manual composite operation but is no longer a scheduled target.

## 5. Evolution path (deferred, not built now)

Designed directions this version must not obstruct, in roughly the order
they would land:

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

## 6. Guardrails and open questions

Guardrails:

- **No custom scheduler** (no APScheduler/Celery/system cron).
- **No Action wrapper, handler registry, dispatch layer, or parallel schedule
  API** — extensions provide Agno Workflows and native schedule targets.
- **No agents, notification plumbing, or cross-schedule dependencies in this
  version.** Deterministic Workflows stay at zero LLM calls, per ADR 0003.

Open questions for the next milestones:

- **Result delivery**: how task results reach the user — preliminary
  direction is a push service to a dedicated Client UI (ADR 0007
  decision 5), to be settled with the Client API milestone.
- **Trading-calendar awareness**: the cron fires on weekday holidays too;
  sync is idempotent and simply finds no new candles. Revisit only if the
  wasted calls become a real cost.
