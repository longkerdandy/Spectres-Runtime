# Scheduled Tasks

> Current AgentOS scheduler and extension Workflow design, verified against
> Agno 3.1.2. Decision history: ADR 0007 and ADR 0011.
> Last updated: 2026-11-08.

## 1. Execution Model

The scheduler runs inside AgentOS. It polls `agno_schedules`, claims due rows
with a PostgreSQL lease, and fires one HTTP request per schedule. Runtime does
not run a separate scheduler service.

A target can be:

- **Component run**: `POST /agents|teams|workflows/<id>/runs`. The executor
  submits a background run, polls to a terminal state, and stores linked run,
  session, and output data. ETF Grid uses Workflow targets.
- **Ordinary HTTP endpoint**: one JSON request; a 2xx response is success.
  Native schedule writes allow only administrators to select these arbitrary
  targets.

Extensions contribute one-step or sequential Agno Workflows directly. Current
ETF Grid Workflows are deterministic and make no LLM calls.

## 2. Persistence and Reliability

- `agno_schedules` stores target, cron/timezone, payload, timeout/retry policy,
  enabled state, next run time, owner, lease, and provenance.
- `agno_schedule_runs` stores each attempt, status/error/timings, owner, and any
  linked component run/session/output. Domain results remain in extension tables.
- `agno_jobs` supports background component execution.

The lease coordinates workers but does not make side effects exactly-once;
tasks must be idempotent. Retries are per schedule. A schedule missed during
downtime fires once on recovery, not once per missed interval. The scheduler
stops with the AgentOS process. Cron evaluation uses the stored IANA timezone.
Ordinary HTTP run records omit the response body; component runs retain linked
output.

## 3. Ownership and Authorization

Owned schedules execute with their owner forwarded by the internal scheduler;
owned Workflow runs receive that `user_id`. Unowned schedules execute without a
user owner. Schedule-run rows copy the parent owner.

`user_id IS NULL` means a system schedule, not a schedule shared with regular
users. Ordinary users see only their own schedules and history; administrators
with `agent_os:admin` see all. Query parameters and payload user ids cannot
override ownership. Out-of-scope detail reads and writes return 404.

Native management routes:

| Method and path | Required permission |
|-----------------|---------------------|
| `POST /schedules` | `schedules:write` + target run permission |
| `GET /schedules` | `schedules:read` |
| `GET /schedules/{id}` | `schedules:read` |
| `PATCH /schedules/{id}` | `schedules:write` + target run permission when retargeting |
| `DELETE /schedules/{id}` | `schedules:delete` |
| `POST /schedules/{id}/enable` | `schedules:write` + target run permission |
| `POST /schedules/{id}/disable` | `schedules:write` |
| `POST /schedules/{id}/trigger` | `schedules:write` + target run permission |
| `GET /schedules/{id}/runs` | `schedules:read` |
| `GET /schedules/{id}/runs/{run_id}` | `schedules:read` |

`agent_os:admin` can perform all operations. Lists support pagination; schedule
lists also support `enabled`. Run detail validates that the run belongs to the
schedule in the path.

Clients discover Workflow targets through `GET /workflows` and use
`/workflows/{workflow_id}/runs`. Catalog visibility alone does not grant run
permission. The current ordinary role has global `workflows:run`, so it can run
and schedule **both** ETF Grid Workflows, including data sync; arbitrary
extension HTTP targets remain admin-only.

## 4. Registration and Extension Integration

`ExtensionContribution` carries `workflows` and `schedules`. Core mounts all
Workflows in AgentOS and registers declarative system schedules through
`ScheduleManager`.

System registration is intentionally convergent but non-destructive:

- Look up an unowned row by its current name; if found, change nothing.
- Otherwise create the row from `ScheduleSpec`; apply `enabled=False` only to
  this new row.

Thus cron, target, retry, timing, and enabled-state changes stored in PostgreSQL
survive restarts. Registration does not perform legacy-name or database-format
migration. Personal schedules are created only through native REST CRUD and are
never seeded, reconciled, or recreated at startup. Registration failures abort
startup with the schedule name.

## 5. ETF Grid Workflows

| Workflow | Behavior | Automatic schedule |
|----------|----------|--------------------|
| `etf_grid_data_sync` | Synchronize enabled shared candles and valuation; never enumerate private ledger owners | One unowned `ETF Grid Daily Sync` |
| `etf_grid_recompute` | Recompute signals for required `RunContext.user_id` using latest persisted shared data | None |

The automatic data-sync schedule initially uses `ETF_GRID_SYNC_*` configuration.
Total source failure returns an unsuccessful Workflow step so retries apply;
partial failure remains successful with an `errors` field.

When the owning Extension is disabled, a prepended activation step returns a
successful `{status: disabled, extension: etf_grid}` result with `stop=True`.
Business steps do not execute and Scheduler does not retry this deliberate skip.
Extension state changes do not alter the Schedule's own enabled flag, ownership,
target, cron, or retry configuration.

Recompute ignores payload-supplied ownership and fails closed without an
authenticated/schedule owner. Sync and recompute are independent: they may run
in either order, and Runtime does not create personal recompute schedules.

Related manual surfaces remain available:

- `POST /api/v1/extensions/etf-grid/sync`: shared sync for authenticated users
  or internal callers.
- `POST /api/v1/extensions/etf-grid/signals/compute`: current-user recompute.
- `refresh_grid_data` tool: shared sync plus current-owner recompute.
- `POST /api/v1/extensions/etf-grid/refresh`: manual admin/internal composite
  operation; no longer a scheduled target.

## 6. Constraints and Deferred Work

Do not add a custom scheduler, Action abstraction, handler registry, generic
dispatcher, parallel schedule API, or cross-schedule dependency layer. Current
Workflows have no agent steps, notifications, `SchedulerTools`, or automatic
result delivery. Those capabilities require separate design and implementation.
