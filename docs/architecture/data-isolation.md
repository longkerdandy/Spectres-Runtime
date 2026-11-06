# Per-User Data Isolation

> Current owner-scoping behavior for AgentOS, AG-UI, schedules, and extension
> data. Last updated: 2026-11-06.

## 1. Mechanism

`src/spectres/main.py` always builds AgentOS with `user_isolation=True`. JWT
`sub` supplies the user id established by [Authentication](authentication.md).
Isolation filters data; it is not another identity or permission model.

Agno and extensions share PostgreSQL, but framework isolation is route/query
level filtering, not PostgreSQL RLS, per-user schemas, or per-user databases.
Runtime-owned routes must explicitly apply Agno's user-scope helpers or an
equivalent owner check. Open no-auth local mode is not a deployment security
configuration.

## 2. Framework Ownership

| Data | Owner behavior | `user_id IS NULL` |
|------|----------------|-------------------|
| Sessions, runs, memories | Owner and admins only | Hidden from regular users |
| Traces | Filtered to caller | Hidden from regular users |
| Metrics | Per-user buckets; admin aggregate access | Excluded from regular users' owned view |
| Knowledge | Private to uploader | Shared with every user |
| Schedules and schedule runs | Private to owner | System tasks, visible to admins/scheduler |

The Team Leader does not currently enable long-term memory, knowledge/RAG, or
tracing. Memory APIs are covered by integration tests; knowledge's shared-NULL
rule comes from Agno's current schema and has not been exercised end to end in
Runtime.

## 3. AG-UI

The client-supplied `thread_id` becomes the session id. Before streaming, Agno
pins the run owner to the authenticated JWT subject and checks an existing
session. Reusing another user's thread returns 404 and cannot append a run to
that user's history. `forwarded_props.user_id` cannot override the verified
owner.

## 4. Administrator Access

`agent_os:admin` bypasses framework owner filters for operational break-glass
access. Production authority comes from Logto's `admin` role and custom `scopes`
claim. Do not assign this scope to ordinary users or commit development tokens
or verification keys.

Admin break-glass does not make ETF Grid portfolio routes cross-user: those
routes deliberately self-scope administrators to their own identity.

## 5. Scheduler and Workflows

The scheduler polls owned and unowned rows using the AgentOS internal service
token. For an owned schedule it forwards the verified owner in
`X-Schedule-Owner`; an unowned schedule has no owner header. Component runs and
schedule-run history retain the same owner. Only the verified internal scheduler
identity may use the owner-forwarding header.

`ETF Grid Daily Sync` is the only automatically registered ETF Grid schedule
and is unowned, so regular users do not see it in `/schedules`. It targets
`etf_grid_data_sync`, which changes only shared data and never enumerates
ledger owners. Users may also create their own schedule for this Workflow under
the current global `workflows:run` grant; that owned schedule still changes only
shared data.

Personal recompute schedules are never seeded. `etf_grid_recompute` reads
`RunContext.user_id` from the verified caller or schedule owner, ignores payload
user ids, and fails closed when no owner exists.

Native schedule CRUD, state changes, trigger, and run history filter ordinary
callers to their own rows. Cross-user/nonexistent detail reads and writes return
404. Run detail also validates the schedule/run relationship. See
[Scheduled Tasks](scheduled-tasks.md).

## 6. Extension-Owned Data

AgentOS authentication middleware protects extension HTTP routes, but Agno does
not automatically isolate extension tables or service calls. Every extension
must define shared versus private data and scope every private read/write.

ETF Grid implements this explicitly:

- `etf_grid_candles`, `etf_grid_valuation`, and `etf_grid_instruments` are
  shared. Strategy parameters come from `ETF_GRID_PORTFOLIO`; only instrument
  enablement is administrator-managed in PostgreSQL.
- `etf_grid_trades` and `etf_grid_signals` require `user_id`. Ledger reads,
  writes, counts, replay, and signal reads/upserts filter by owner. Signal keys
  are `(user_id, symbol, trade_date)`.
- Normal REST routes use `request.state.user_id`, including for administrators.
  Client-provided ownership fields are never authoritative.
- Agent tools and recompute Workflows use injected `RunContext.user_id`; neither
  the LLM nor a schedule payload supplies ownership.

`tests/test_user_isolation.py`, `tests/test_schedule_read_api.py`, and
`tests/test_schedule_write_api.py` exercise framework, AG-UI, schedule, and
extension ownership with real PostgreSQL and development JWTs.
