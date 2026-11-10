# Runtime Extensions

> Implementation contract for built-in Extensions and the ETF Grid reference.
> Last updated: 2026-11-10.

## 1. Boundaries and Layering

An Extension is a trusted, in-process domain capability under
`src/spectres/extensions/<name>/`. It may contribute agent tools, REST routes,
Agno Workflows, and declarative system Schedules. It is not an independent
deployment, sandbox, third-party plugin, or Edge.

Mi Health is a planned built-in Extension under
`src/spectres/extensions/mi_health/`; its code, routes, tables, and schedules are
not implemented yet. Its migrated protocol evidence lives in
[Mi Health research](../research/mi-health/mi-fitness-cloud-api.md) and is not
production behavior.

Core code must not import Extension code. Extensions must not modify AgentOS or
agent factories directly.

```text
src/spectres/extensions/
├── base.py                 # Context, contribution, loaded record, protocol
├── loader.py               # Static discovery and registration
├── activation.py           # Shared REST/Toolkit/Workflow guards
├── state.py                # Persistent global activation
└── etf_grid/
    ├── extension.py        # Manifest and register()
    ├── config.py           # ETF_GRID_* settings
    ├── core/               # Pure domain logic
    ├── service/            # Business services and persistence orchestration
    ├── models.py           # SQLAlchemy models
    ├── marketdata.py       # External providers
    ├── toolkit.py          # Agno adapter
    ├── workflows.py        # Agno adapter
    └── api.py              # FastAPI adapter
```

Keep `toolkit.py`, `api.py`, and `workflows.py` thin. Business rules belong in
`service/` or pure `core/`; `core/` must not import Agno, FastAPI, or SQLAlchemy.
Conversation, HTTP, and scheduled execution must use the same domain services.

## 2. Manifest, Registration, and Discovery

`base.py` defines:

- `ExtensionContext`: core `Settings` and shared `PostgresDb`.
- `ExtensionContribution`: `toolkits`, `routers`, `workflows`, and `schedules`.
- `LoadedExtension`: stable `id`, display `name`/`description`, and contribution.
- `Extension`: manifest protocol with `register(ctx)`.

`ScheduleSpec` is defined in `src/spectres/scheduler.py`, not in the Extension
package. It declares initial system-Schedule configuration.

`loader.py` scans direct child packages in sorted package-name order. A package
participates only when its `__init__.py` exposes an `extension` object with:

- A unique snake_case `id` and non-empty display metadata.
- A callable `register(ctx)` returning `ExtensionContribution`.

There is no entry-point or out-of-tree discovery. Import errors, invalid or
duplicate metadata, and registration failures abort startup with the Extension
identity.

`register()` must be idempotent. Its side effects are limited to table creation:
no network calls, threads, or Schedule execution. Keep mutable business state in
PostgreSQL. Extensions currently contribute tools, not agents.

Use snake_case for packages, tables, tools, and Workflow ids; UPPER_SNAKE for
environment prefixes; kebab-case for URL paths. Display metadata does not derive
routes, table names, or ownership.

## 3. Activation and Schedule Semantics

`runtime_extension_states` stores one global enabled flag per discovered
Extension. Startup adds missing ids as enabled and preserves administrator
choices. Catalog reads require authentication; changes require
`agent_os:admin`.

Disabled code remains registered so re-enablement needs no restart:

- REST guards return 403 `extension_disabled` before route business work.
- Toolkit guards preserve sync/async entry-point signatures and public schemas,
  and return the structured `extension_disabled` tool error.
- Workflow guards prepend a stop step returning
  `{status: disabled, extension: <id>}` before business work. Workflows must use
  a static `steps` list; other step containers fail startup.
- Disabling does not delete data, cancel in-flight work, or rewrite native
  Schedule configuration.

System Schedules are declared as `ScheduleSpec`s and registered by core. Existing
rows are preserved; configuration applies only when a row is created. Personal
Schedules use native CRUD and are never seeded or reconciled. Scheduled work must
be idempotent because leases do not provide exactly-once side effects. See
[System Architecture](system-architecture.md) for scheduler contracts.

## 4. Surface Implementation Rules

### Configuration

Each Extension owns a pydantic-settings fragment in `config.py`; core `Settings`
contains no Extension-specific fields. Required values use explicit environment
variables. Optional credentials must not block unrelated startup; the dependent
operation should fail clearly when called.

### Persistence

- Use the shared `PostgresDb.db_engine` and connection pool.
- Prefix tables with `<extension>_`; never access Agno-managed or another
  Extension's tables.
- `metadata.create_all()` runs during registration and does not alter existing
  tables. No migration tool is configured.
- Agno isolation does not cover Extension tables. Classify data as shared or
  private and filter every private operation by verified ownership.

### Agent Tools

Return Agno `Toolkit`s with stable names and structured results. Private tools
use injected `RunContext.user_id`, never LLM-supplied ownership, and fail closed
without identity. Current ETF Grid tools do not request HITL confirmation.

ETF Grid's normal tool envelope is:

```text
success: {"ok": true, "data": ...}
failure: {"ok": false, "error": {"type", "message", "trace_id", "hint"}}
```

Log handled failures and convert them to this envelope rather than raising across
the tool boundary. Activation-disabled errors use the shared guard's smaller
`extension_disabled` envelope.

### HTTP API

Mount routers under `/api/v1/extensions/<kebab-name>/`. AgentOS supplies global
authentication and CORS, but routes must explicitly enforce ownership and any
additional scopes. Derive owners from `request.state.user_id`; HTTP and tool
adapters call the same services.

### Workflows and Logging

Return Agno `Workflow` instances directly: no Action wrapper, handler registry,
or custom dispatcher. Private steps use `RunContext.user_id` and fail closed.

Use `logging.getLogger(__name__)`; core owns handlers and formatting. Log handled
failures with `exc_info` and sensitive mutations as structured audit events,
without credentials, tokens, or health data.

## 5. ETF Grid Reference

- **Shared**: candles, valuation history, and the in-memory portfolio.
- **Private**: trades and signals carry `user_id`; positions and P&L derive only
  from that owner's append-only ledger.
- **Tools**: `get_grid_status`, `refresh_grid_data`, `record_grid_trade`,
  `list_grid_trades`. Refresh syncs shared data and recomputes only the caller.
- **Workflows**: `etf_grid_data_sync` never enumerates ledger owners;
  `etf_grid_recompute` requires an authenticated owner.
- **Schedule**: unowned `ETF Grid Daily Sync` targets data sync. Personal
  recompute Schedules have no ordering guarantee relative to sync.

Routes under `/api/v1/extensions/etf-grid`:

| Route | Access and behavior |
|-------|---------------------|
| `GET /status` | Current user's positions, P&L, and latest signals |
| `POST /signals/compute` | Recompute current user's signals |
| `POST /sync` | Shared sync for an authenticated user or internal caller |
| `GET, POST /trades` | Current user's trade list/create |
| `POST /refresh` | Admin/internal sync plus all-ledger-owner recompute; not scheduled |

`GET /trades` returns `{items, total, limit, offset}`; `limit` is 1–200
(default 20), and filters apply before `total` is counted. Validation failures
and trade-domain rejections use FastAPI's structured 422 `detail` list.

## 6. Guardrails

Do not add lifecycle hooks, cross-Extension dependencies, generic plugin
frameworks, custom schedulers, or parallel Schedule APIs. Out-of-tree plugins,
migrations, tool ACL, Extension-contributed agents, per-user activation, and
dynamic installation remain deferred until explicitly designed.
