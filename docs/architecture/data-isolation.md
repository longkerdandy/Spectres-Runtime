# Per-User Data Isolation

> How AgentOS partitions user-owned data after JWT authentication. Implemented
> in v0.6.1 ([plan](../plan/v0.6.1-user-data-isolation.md)); the extension
> data-sharing exception is part of the v0.6.x contract.

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

`etf_grid_daily_sync` remains unowned (`user_id IS NULL`). Regular users do
not see it in `/schedules`; admins and the internal executor do. It targets
an extension endpoint and creates no Agent session/run rows, only the
unowned `agno_schedule_runs` audit records.

## 6. Extension exclusion

AgentOS authentication middleware protects extension HTTP routes, but Agno's
user-isolation plane does not automatically scope extension-owned tables or
service calls. ETF Grid tables intentionally have no `user_id`: every
authenticated user reads and mutates the same portfolio, market data, and
signals. Agent tool calls share that same data.

A future per-user extension must make isolation an explicit part of its API,
tool, and persistence design, using `get_scoped_user_id(request)` on every
read and `enforce_owner_on_entity(...)` or equivalent owner validation on
every write. Setting `user_isolation=True` alone is insufficient.

## 7. Rollout and verification

The project has no production dataset. v0.6.1 starts directly with isolation
enabled and includes no migration or backfill; development data may be reset.

`tests/test_user_isolation.py` uses real PostgreSQL, JWT dev tokens, and
AgentOS routes to cover sessions, runs, memories, AG-UI cross-user writes,
admin break-glass, and unowned scheduler visibility/execution. The final
release walkthrough uses two real browser accounts to confirm the same
behavior through the Web Client.
