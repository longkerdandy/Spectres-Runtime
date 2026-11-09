# Runtime Extensions

> Current extension contract and the ETF Grid reference implementation.
> Last updated: 2026-11-08.

## 1. Purpose and Boundaries

An extension is a trusted, in-process domain capability under
`src/spectres/extensions/<name>/`. It can contribute agent tools, REST routes,
Agno Workflows, and automatic system schedules through one registration
contract.

Extensions are not core agent infrastructure, sandboxes, independent deployment
units, or third-party plugins. Core code must not import extension code, and
extensions must not modify AgentOS or agent factories directly.

## 2. Layout and Layering

```text
src/spectres/extensions/
├── base.py                    # Extension, ExtensionContext, contributions
├── loader.py                  # In-tree discovery and registration
└── etf_grid/
    ├── __init__.py            # Re-exports the extension manifest
    ├── extension.py           # id + name + description + register()
    ├── config.py              # ETF_GRID_* settings
    ├── core/                  # Pure domain logic
    ├── service/               # Application services and persistence orchestration
    ├── marketdata.py          # External market/valuation sources
    ├── models.py              # SQLAlchemy tables
    ├── toolkit.py             # Agno Toolkit adapter
    ├── workflows.py           # Agno Workflow adapters
    └── api.py                 # FastAPI router adapter
```

`toolkit.py`, `api.py`, and `workflows.py` are thin adapters over `service/`.
Business rules belong in services or `core/`; `core/` must not import Agno,
FastAPI, or SQLAlchemy. This keeps conversational, HTTP, and scheduled execution
on the same code path.

## 3. Registration Contract

`base.py` defines:

- `ExtensionContext`: core `Settings` and the shared `PostgresDb`.
- `ExtensionContribution`: lists of `toolkits`, `routers`, `workflows`,
  `default_configs`, and `schedules`; each defaults to an empty list.
- `LoadedExtension`: discovered `id`, `name`, and `description` metadata paired
  with its `contribution`.
- `ScheduleSpec`: a core `spectres.scheduler` declaration with `name`, `cron`,
  `endpoint`, `method`, `timezone`, `timeout_seconds`, `max_retries`,
  `retry_delay_seconds`, and `enabled` required; `payload` is optional.
- `DefaultConfigSpec`: a core `spectres.config` declaration with a stable
  collection `name`, an emptiness check, and an initialization callback that
  writes the complete collection in one transaction.

Both core spec types can be used without an Extension. Their initialization
functions accept spec sequences directly; Extension contributions are flattened
by `main.py` before these functions are called.
- `Extension`: a stable snake_case `id`, non-empty human-readable `name` and
  `description`, plus `register(ctx)`.

`id` keys persisted activation and administration APIs. `name` and `description`
are display metadata and do not derive routes, table names, or ownership. A
separate version field is unnecessary because built-in Extension code releases
with Runtime.

`register()` must be idempotent. Its side effects are limited to table creation;
it performs no network calls and starts no threads. Extensions are constructed
at startup and keep mutable state in PostgreSQL. They currently contribute tools,
not agents.

Names use snake_case for packages, tables, tools, and Workflow ids; UPPER_SNAKE
for environment prefixes; and kebab-case for URL path segments. Schedule names
may be human-readable.

## 4. Discovery and Startup

`loader.py` scans direct child packages with `pkgutil.iter_modules`, sorted by
package name. A package is loaded only when its `__init__.py` exposes an
`extension` object with a valid id, non-empty display metadata, and callable
`register()`. Duplicate ids and missing or malformed metadata fail startup.
Presence selects built-in code; there is no entry-point discovery. Import,
manifest, and registration failures abort startup with the extension id.

Each result is a `LoadedExtension(id, name, description, contribution)`,
preserving metadata for the catalog and the owner id for activation guards and
administration. `runtime_extension_states` stores one global enabled flag per
discovered Extension. Startup inserts missing ids as enabled and preserves
existing administrator choices. Disabled code remains registered; shared guards
reject REST and tool execution, while a prepended Workflow step returns
`{status: disabled, extension: <id>}` with `stop=True` before business work.
Disabling does not delete data, cancel in-flight work, or change native Schedule
configuration. `GET /api/v1/extensions` returns id, display name, description,
enabled state, and update time to authenticated users;
`PATCH /api/v1/extensions/{id}` requires `agent_os:admin` and returns the same
contract.

Startup order in `main.py`:

```text
PostgresDb → load_extensions() → initialize_default_configs()
           → initialize/reconcile Extension state → register_schedules()
           → guard Toolkits and Workflows → Team Leader(extra_tools=...)
           → AgentOS(workflows=...) → mount guarded extension routers
```

## 5. Surface Contracts

### Configuration

Each extension owns a pydantic-settings fragment in `config.py`; core `Settings`
contains no extension-specific fields. Required fields use explicit environment
variables. Optional credentials must not block unrelated startup; the dependent
operation should fail clearly when called.

A database-backed collection declares a `DefaultConfigSpec`. During startup,
core skips the entire default when its target contains any row; otherwise the
owner writes the complete configured collection in one transaction. There is no
per-item reconciliation: later configuration changes do not add, update, or
remove stored rows, and deleting one stored row does not restore it on restart.
Empty means uninitialized, so an interface that permits deleting the whole
collection must also introduce a persisted initialization marker.
Initialization failures abort startup with the collection name.

### Persistence

- Use the shared `PostgresDb.db_engine` and connection pool.
- Prefix tables with `<extension>_`; never access Agno-managed or another
  extension's tables.
- Current schema setup uses `metadata.create_all()` during registration. There
  is no migration tool, and `create_all()` does not alter existing tables.
- Agno isolation does not cover extension tables. Explicitly distinguish shared
  data from owner-scoped data and filter every private operation. See
  [Data Isolation](data-isolation.md).

### Agent tools

Return an Agno `Toolkit` from `register()`. Keep tool names stable and return
structured dictionaries rather than prose. Private tools obtain the owner from
injected `RunContext.user_id`; ownership is never an LLM argument and missing
identity fails closed. Current ETF Grid tools do not request HITL confirmation.

ETF Grid tools use a common envelope:

```text
success: {"ok": true, "data": ...}
failure: {"ok": false, "error": {"type", "message", "trace_id", "hint"}}
```

Tool failures are logged and converted to this envelope rather than raised
across the tool boundary.

### HTTP API

Mount routers under `/api/v1/extensions/<kebab-name>/`. AgentOS supplies global
authentication middleware and CORS, but custom routes must explicitly implement
ownership and any administrator-scope checks. HTTP and tool adapters call the
same services so their behavior remains consistent.

### Logging

Use only `logging.getLogger(__name__)`; core owns handlers and formatting.
Runtime writes stdout plus daily JSONL files under `LOG_DIR`, correlated by
`trace_id`. Log handled failures with `exc_info`, emit structured audit events
for sensitive mutations, and never log secrets. Redaction is defense in depth.

### Workflows and schedules

Extensions return Agno Workflow instances directly; there is no Action wrapper,
handler registry, or custom dispatcher. Private Workflow steps use
`RunContext.user_id` and fail closed without it. Scheduled work must be
idempotent because leases do not make side effects exactly-once.

Only automatic system schedules are declared as `ScheduleSpec`s. Personal
schedules use Agno-native CRUD and are never seeded at startup. Configuration
supplies initial cron/timezone/retry/enabled values only when a row is created.
Existing rows are preserved without legacy-name or database-format migration.
See [Scheduled Tasks](scheduled-tasks.md).

## 6. ETF Grid Reference Implementation

- **Shared data and configuration**: forward-adjusted candles and valuation
  history are stored in PostgreSQL. `ETF_GRID_PORTFOLIO` supplies the complete
  in-memory strategy collection, including each symbol's grid step, sizing,
  maximum grids, and optional valuation gate; changes take effect on restart.
- **Private data**: trades and signals carry `user_id`; positions and P&L derive
  only from that owner's ledger.
- **Tools**: `get_grid_status`, `refresh_grid_data`, `record_grid_trade`, and
  `list_grid_trades`. Refresh synchronizes shared data, then recomputes only the
  current owner's signals.
- **Workflows**: `etf_grid_data_sync` synchronizes shared inputs without
  enumerating ledger owners; `etf_grid_recompute` requires an authenticated owner.
- **Automatic schedule**: one unowned `ETF Grid Daily Sync` targets data sync.
  Personal recompute schedules are user-created and have no ordering guarantee
  relative to sync.

All routes below are under `/api/v1/extensions/etf-grid`:

| Route | Access and behavior |
|-------|---------------------|
| `GET /status` | Current user's positions, P&L, and latest signals |
| `POST /signals/compute` | Recompute current user's signals |
| `POST /sync` | Shared-data sync for an authenticated user or internal caller |
| `GET, POST /trades` | Current user's trade list/create |
| `POST /refresh` | Manual admin/internal sync plus all-ledger-owner recompute; not scheduled |

`GET /trades` returns `{items, total, limit, offset}`; `limit` is 1–200
(default 20), and filters apply before `total` is counted. Validation errors and
trade domain rejections use FastAPI's structured 422 `detail` list.
Status `unrealized` is
`close × shares − avg_cost × shares`; `unrealized_percent` divides that by the
cost basis. Undefined values are `null`, not zero.

## 7. Guardrails and Deferred Work

Keep the contract minimal: no extra lifecycle hooks, cross-extension
dependencies, generic plugin framework, or parallel scheduling API. Out-of-tree
plugins, migrations, tool ACL, extension-contributed agents, per-user activation,
and dynamic installation remain deferred until required.
