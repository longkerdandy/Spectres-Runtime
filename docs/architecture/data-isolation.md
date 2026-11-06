# Per-User Data Isolation

> How AgentOS partitions user-owned data after JWT authentication. Framework
> isolation was implemented in v0.6.1; ETF Grid added explicit private-ledger
> and signal isolation in v0.6.3; native schedule management and Workflow owner
> propagation were verified in v0.6.4–v0.6.5.

---

## 1. Mechanism

`src/spectres/main.py` builds `AgentOS(..., user_isolation=True)` and emits a
`user_isolation_enabled` startup log event. JWT `sub` remains the user id
established by [Authentication](authentication.md); isolation adds data
scoping, not another identity or permission model.

Agno uses one PostgreSQL database and shared tables. Framework routes pass
the scoped user id to queries (`WHERE user_id = :uid`) and coerce new entities
to the authenticated owner. This is route-level filtering, **not PostgreSQL
RLS**, per-user schemas, or per-user databases. Any future Runtime-owned route
that handles user data must explicitly use Agno's `user_scope.py` helpers;
omitting them bypasses isolation without a framework error.

The Runtime enables isolation unconditionally. Authenticated deployments get
JWT-backed scoping; the open local-development mode retains Agno's no-auth
identity behavior and is not a deployment security configuration.

## 2. Ownership semantics

| Data | Owned rows | `user_id IS NULL` under isolation |
|------|------------|-----------------------------------|
| Sessions, runs, memories | Visible only to their owner and admins | Not visible to regular users |
| Traces | Filtered to the caller | Not visible to regular users |
| Metrics | Per-user buckets for regular callers; admins get cross-user daily aggregates | Legacy unowned buckets are excluded from a regular user's owned view |
| Knowledge | Private to the uploader | **Shared with every user** |
| Schedules and schedule runs | Private to the owner | **Unowned system tasks**, not user-shared resources |

Knowledge and schedules deliberately give NULL different meanings: NULL
knowledge is shared, while a NULL schedule is visible to admins and the
scheduler rather than to every regular user.

The Team Leader currently does not enable long-term memories, knowledge/RAG,
metrics, or tracing. Memory isolation is covered through the framework's
memory REST API; knowledge's shared-NULL behavior is documented from Agno's
schema and deferred for an end-to-end check until knowledge is enabled.

## 3. AG-UI ownership checks

AG-UI's client-supplied `thread_id` becomes the session id. On each run,
Agno pins the effective user id to the authenticated JWT subject and checks
the existing session before starting the model stream. Reusing another
user's `thread_id` returns 404, preventing both history disclosure and a
cross-user run being appended to the victim's session.

Client-supplied `forwarded_props.user_id` cannot override the authenticated
owner. The Web Client needs no isolation-specific change.

## 4. Admin break-glass

A caller with the `agent_os:admin` token scope is unscoped and can read
across users for operational debugging. Production admin authority comes
from the Logto `admin` role and its custom `scopes` claim; there is no
Runtime managed-role store or `/authz` API. Ordinary Logto users receive the
separate `user` scope set and remain isolated.

For local development only, mint a token with the development verification
key, never the production Logto key:

```python
from agno.os.auth import create_dev_token

token = create_dev_token(
    "operator",
    secret=<JWT_VERIFICATION_KEY>,
    audience=<JWT_AUDIENCE>,
    scopes=["agent_os:admin"],
)
```

Use it as the normal Bearer token against AgentOS read endpoints. Admin
access is intentionally powerful; do not assign this scope to ordinary
users or commit the token/key.

## 5. Scheduler behavior

A single scheduler polls both owned and unowned tasks. Its executor uses the
AgentOS internal service token; for an owned schedule it forwards the owner
in `X-Schedule-Owner`, and for an unowned schedule it sends no owner header.
Only the authenticated internal scheduler identity may use that header.
Consequently, an owned Agent/Team/Workflow run executes in its owner's data
scope, while an unowned schedule executes unscoped. Schedule-run records
copy the parent schedule's `user_id` so history queries follow the same
ownership rule.

`ETF Grid Daily Sync` remains the only automatically registered ETF Grid
schedule and is unowned (`user_id IS NULL`). Regular users do not see it in
`/schedules`; admins and the internal executor do. It targets the unowned
`etf_grid_data_sync` Workflow. Personal recompute schedules are never seeded:
each user creates them through native CRUD and owns both the schedule and its
Workflow runs. Recompute reads `RunContext.user_id`, which Agno derives from
the verified caller or schedule owner rather than payload input.

The native management surface includes POST/PATCH/DELETE, enable/disable,
manual trigger, `GET /schedules`, `GET /schedules/{schedule_id}`,
`GET /schedules/{schedule_id}/runs`, and
`GET /schedules/{schedule_id}/runs/{run_id}`. Reads require `schedules:read`;
writes additionally use `schedules:write` or `schedules:delete`, plus run
permission for the target Workflow where Agno requires it. An ordinary
caller's list is filtered to the JWT subject; direct reads and writes of
public, cross-user, or nonexistent rows all return 404. Admin access is
unscoped. Run history follows the parent's owner, and run detail validates
both owner scope and the path's schedule/run relationship. Query parameters
and payload user ids never override these ownership rules.

## 6. Extension-owned data

AgentOS authentication middleware protects extension HTTP routes, but Agno's
user-isolation plane does not automatically scope extension-owned tables or
service calls. Every extension must make its ownership model explicit;
setting `user_isolation=True` alone is insufficient.

ETF Grid separates public inputs from private state:

- `etf_grid_candles`, `etf_grid_valuation`, and `etf_grid_instruments` are
  global. Strategy parameters still come from `ETF_GRID_PORTFOLIO`; only the
  administrator-controlled enabled/disabled selection lives in the database.
- `etf_grid_trades` and `etf_grid_signals` carry a required `user_id`. Every
  ledger read/write/count/replay and signal read/upsert filters by owner, and
  the signal key is `(user_id, symbol, trade_date)`. Positions are derived
  only from the caller's ledger.
- Normal REST routes self-scope to `request.state.user_id`, including when an
  administrator uses them. They do not propagate the `None` returned for an
  admin by `get_scoped_user_id()` into an unscoped query. Client-supplied
  ownership fields are never authoritative.
- Agent tools and the recompute Workflow receive the same owner through Agno's
  injected `RunContext.user_id`; neither the LLM nor schedule payload has an
  ownership argument. An unowned recompute run fails closed.
- The unowned data-sync Workflow never enumerates ledger owners. Personal
  recompute schedules execute independently and affect only their owner's
  signals; Runtime does not automatically create those schedules.

Other per-user extensions should follow Agno's `user_scope.py` helper pattern
or an equivalent explicit owner-validation contract on every read and write.

## 7. Rollout and verification

The project has no production dataset. v0.6.1 started directly with isolation
enabled and included no migration or backfill; v0.6.3 likewise permits a
development database rebuild because `create_all()` cannot alter the existing
ledger and signal keys. Preserving an old shared ETF ledger requires an
explicit, reviewed one-owner backfill rather than copying it to every user.

`tests/test_user_isolation.py` uses real PostgreSQL, JWT dev tokens, and
AgentOS routes to cover sessions, runs, memories, AG-UI cross-user writes,
admin break-glass, and unowned scheduler visibility/execution. The final
release walkthrough uses two real browser accounts to confirm the same
behavior through the Web Client.
