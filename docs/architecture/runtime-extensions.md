# Runtime Extensions

> Current extension contract and the ETF Grid reference implementation.
> Last updated: 2026-11-06.

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
    ├── extension.py           # name + register()
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
- `ExtensionContribution`: lists of `toolkits`, `routers`, `workflows`, and
  `schedules`; each defaults to an empty list.
- `ScheduleSpec`: `name`, `cron`, `endpoint`, `method`, `timezone`,
  `timeout_seconds`, `max_retries`, `retry_delay_seconds`, and `enabled` are
  required; `payload` and `previous_names` are optional.
- `Extension`: a snake_case `name` plus `register(ctx)`.

`register()` must be idempotent. Its side effects are limited to table creation
and idempotent bootstrap; it performs no network calls and starts no threads.
Extensions are constructed at startup and keep mutable state in PostgreSQL.
They currently contribute tools, not agents.

Names use snake_case for packages, tables, tools, and Workflow ids; UPPER_SNAKE
for environment prefixes; and kebab-case for URL path segments. Schedule names
may be human-readable.

## 4. Discovery and Startup

`loader.py` scans direct child packages with `pkgutil.iter_modules`, sorted by
package name. A package is loaded only when its `__init__.py` exposes an
`extension` object with a valid name and callable `register()`. Presence in the
tree is the opt-in; there is no enable list or entry-point discovery. Import,
manifest, and registration failures abort startup with the extension name.

Startup order in `main.py`:

```text
PostgresDb → load_extensions() → register_schedules()
           → Team Leader(extra_tools=...) → AgentOS(workflows=...)
           → app.include_router(...) for each extension router
```

## 5. Surface Contracts

### Configuration

Each extension owns a pydantic-settings fragment in `config.py`; core `Settings`
contains no extension-specific fields. Required fields use explicit environment
variables. Optional credentials must not block unrelated startup; the dependent
operation should fail clearly when called.

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
Existing rows are preserved; `previous_names` permits a rename without changing
identity, stored configuration, or history. See [Scheduled Tasks](scheduled-tasks.md).

## 6. ETF Grid Reference Implementation

- **Shared data**: forward-adjusted candles, valuation history, configured
  strategy parameters, and administrator-controlled instrument enablement.
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
| `GET /instruments` | Enabled shared instruments for an authenticated user |
| `POST /sync` | Shared-data sync for an authenticated user or internal caller |
| `GET, POST /trades` | Current user's trade list/create |
| `GET /admin/instruments` | Admin/internal full instrument selection |
| `PATCH /admin/instruments/{symbol}` | Admin/internal enablement change |
| `POST /refresh` | Manual admin/internal sync plus all-ledger-owner recompute; not scheduled |

`GET /trades` returns `{items, total, limit, offset}`; `limit` is 1–200
(default 20), and filters apply before `total` is counted. Validation errors and
trade/instrument domain rejections use FastAPI's structured 422 `detail` list.
Status `unrealized` is
`close × shares − avg_cost × shares`; `unrealized_percent` divides that by the
cost basis. Undefined values are `null`, not zero.

## 7. Guardrails and Deferred Work

Keep the contract minimal: no extra lifecycle hooks, cross-extension
dependencies, generic plugin framework, or parallel scheduling API. Out-of-tree
plugins, migrations, tool ACL, extension-contributed agents, and enable/disable
gating remain deferred until required.
