# Runtime Extensions — Architecture

> Topic deep-dive companion to [`README.md`](README.md).
> Status: **implemented** (v0.4.1; Workflow contributions added in v0.6.5) —
> the first extension (ETF Grid Trading) runs on this contract: in-tree
> loader, toolkit on the Team Leader, versioned router, and Agno Workflows.
>
> Last updated: 2026-11-06 (preserve stored system schedules on restart).

---

## 1. Purpose

Runtime repeatedly gains optional, self-contained domain capabilities: ETF
grid trading signals, later things like budgeting, health tracking, or
home-energy reports. Each needs the same four things: a **domain core**
(business logic), **persistence** (its own tables), an **agent surface**
(Agno tools), and an **HTTP surface** (REST endpoints for standalone Client
pages).

An **extension** bundles those four into one directory, loaded through a
single minimal contract. The goal is a repeatable vertical-slice pattern,
not a general plugin framework (deliberately deferred, §8).

## 2. What an extension is — and is not

An extension is an optional domain capability packaged as a single Python
package under `src/spectres/extensions/<name>/`, exposing a small manifest
object that Runtime loads at startup. It is **not**:

- **Core agent infrastructure.** Master/Team orchestration, memory, session
  handling, AG-UI interfacing, tool ACL live in `spectres/` core. Extensions
  never modify core behavior; they only contribute *surfaces* to it.
- **A sandbox.** Extensions are in-process, trusted first-party code: no
  isolation boundary, no hot reload, no permission system beyond the
  (future) tool ACL that applies to all tools equally.
- **A deployment unit.** Extensions ship and deploy with Runtime.
  Out-of-tree third-party extensions are explicitly deferred (§9).

## 3. Directory layout

Everything belonging to a capability lives in one directory. No extension
code may live elsewhere, and no core code may import from an extension
(dependencies point inward only).

```
src/spectres/extensions/
├── __init__.py
├── loader.py                 # discovery + loading (extension-agnostic)
├── base.py                   # Extension protocol, ExtensionContext, ExtensionContribution
└── etf_grid/                 # ← one directory per extension
    ├── __init__.py           # exposes the module-level `extension` object
    ├── extension.py          # manifest: name, register()
    ├── config.py             # settings fragment (ETF_GRID_* env vars)
    ├── core/                 # pure domain logic — no Agno/FastAPI/SQLAlchemy imports
    │   ├── grid.py           #   anchor, level, signal computation
    │   └── ledger.py         #   lot bookkeeping, position/cost replay
    ├── marketdata.py         # external data access (FTShare SDK client, valuation feed)
    ├── models.py             # SQLAlchemy tables, all prefixed `etf_grid_`
    ├── service.py            # application service: orchestrates core + marketdata + db
    ├── toolkit.py            # Agno Toolkit: the agent surface
    ├── workflows.py          # Agno Workflows: scheduled/background execution
    └── api.py                # FastAPI APIRouter: the HTTP surface
```

Layering inside an extension:

```
toolkit.py ──┐
api.py ──────┼─> service.py ─> core/  (pure functions, testable in isolation)
workflows.py ┘           ├────> marketdata.py
                         └────> models.py (db)
```

`toolkit.py`, `api.py`, and `workflows.py` are thin adapters containing no
business logic; all call the same application services. This keeps the
conversational answer, standalone page, and scheduled execution consistent by
construction.

## 4. The extension contract

Runtime injects its infrastructure into the extension (dependency
injection); the extension returns declarative contributions. Runtime core
does all framework mounting, so extensions never touch AgentOS or the
agent factory directly.

```python
# base.py
@dataclass
class ExtensionContext:
    """Runtime infrastructure injected into each extension at load time."""
    settings: Settings
    db: PostgresDb          # Agno db handle; its public ``db_engine``
                            # attribute backs the extension's own tables

@dataclass
class ScheduleSpec:
    """Declarative scheduled-task definition (ADR 0007)."""
    name: str               # unique, prefixed with the extension id
    cron: str
    endpoint: str           # fired with one HTTP call on the cron cadence
    method: str = "POST"
    # ... payload, timezone, timeout_seconds, max_retries,
    #     retry_delay_seconds, enabled, previous_names — all required except
    #     payload and previous_names; existing rows are never reconfigured

@dataclass
class ExtensionContribution:
    """What an extension gives back to Runtime."""
    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)

class Extension(Protocol):
    name: str                                    # unique id, e.g. "etf_grid"
    def register(self, ctx: ExtensionContext) -> ExtensionContribution: ...
```

Rules:

- **Idempotent `register()`** with side effects limited to table creation and
  idempotent data bootstrap (§6.2). No network calls or scheduler threads at
  load time — schedules
  are only *declared*; core registers them with the AgentOS scheduler after
  loading (`spectres/scheduler.py`).
- An extension may contribute **any combination** of surfaces: tool-only,
  API-only, and schedule-only extensions are all valid.
- Extensions are constructed once at startup and are stateless across
  requests/runs; mutable state lives in the database.
- Extensions contribute **tools, not agents**: toolkits attach to the Team
  Leader directly. Per-extension member agents are a designed future option
  (§9), deferred until the Team milestone (coordinate mode, ADR 0001) lands.

### 4.1 Naming convention

The extension id is defined once in snake_case (`etf_grid`); machine-facing
surfaces derive from it. Rule of thumb: **snake_case for identifiers, except
URLs which use kebab-case**. Schedule names are user-visible display names and
may use human-readable capitalization and spaces.

| Surface | Form | Example |
|---------|------|---------|
| Python package / directory | snake_case (valid identifier) | `spectres/extensions/etf_grid/` |
| Database table prefix | snake_case | `etf_grid_trades` |
| Tool function names | snake_case (provider tool-name charset limits) | `get_grid_status` |
| Env var prefix | UPPER_SNAKE | `ETF_GRID_...` |
| URL paths | kebab-case | `/api/v1/extensions/etf-grid/...` |
| Schedule display name | Human-readable | `ETF Grid Daily Sync` |

The loader rejects ids that are not valid snake_case Python identifiers
at load time, before any `register()` call.

## 5. Discovery and loading

### 5.1 Discovery

`loader.py` scans the `spectres.extensions` namespace with
`pkgutil.iter_modules`; every package exposing a module-level `extension`
object conforming to the `Extension` protocol is loaded. **Discovery is
loading** — there is deliberately no enable/disable gating: extensions are
first-party code shipped in the same repository, so presence in the tree is
already an explicit opt-in. An `ENABLED_EXTENSIONS` allowlist and
out-of-tree discovery via `importlib.metadata.entry_points` are both
deferred until a real need appears (§9).

### 5.2 Startup sequence

In `main.py`, extensions load between db setup and app assembly; routers
mount onto the FastAPI app that `agent_os.get_app()` returns, before
`serve()`:

```python
def create_agent_os() -> tuple[AgentOS, list[ExtensionContribution]]:
    db = get_postgres_db()
    contributions = load_extensions(settings, db)  # discovery + DI, one call
    toolkits = [t for c in contributions for t in c.toolkits]
    workflows = [w for c in contributions for w in c.workflows]
    team_leader_agent = create_team_leader_agent(db, extra_tools=toolkits)
    return AgentOS(..., agents=[team_leader_agent], workflows=workflows, ...), contributions

agent_os, contributions = create_agent_os()
app = agent_os.get_app()
for router in (r for c in contributions for r in c.routers):
    app.include_router(router)
```

`load_extensions()` wraps each `register()` call in error handling: any
extension whose `register()` raises aborts startup with a clear message
naming the extension — a broken extension must never fail silently.

## 6. Surface conventions

### 6.1 Configuration

Each extension owns a settings fragment class in its `config.py`, using the
same pydantic-settings style as core, with env vars prefixed by the
extension name (`ETF_GRID_*`). The fragment is instantiated inside
`register()`; core `Settings` carries nothing extension-specific. Optional
secrets (e.g. `FTSHARE_API_KEY`) never block loading — the dependent
capability fails with an explicit error at call time instead.

### 6.2 Persistence

- Same PostgreSQL database as core; **table names prefixed `<name>_`**
  (`etf_grid_trades`, ...). No extension may touch Agno-managed tables or
  another extension's tables. All data access flows through the single
  process-wide `PostgresDb` handle (`get_postgres_db()`); extensions reach
  the underlying SQLAlchemy engine via its public `db_engine` attribute, so
  the whole Runtime shares one connection pool.
- MVP: `metadata.create_all(ctx.db.db_engine)` during `register()`. The
  project has no migration tooling yet; when it adopts Alembic, each
  extension keeps its revisions in its own directory.
- The extension's tables are the **only** source of truth for its domain
  (e.g. the trade ledger replaces quant-advisor's CSVs).
- **Extension data is outside Agno's automatic isolation plane.** Each
  extension must explicitly distinguish shared rows from user-owned rows and
  scope every private read/write. ETF Grid keeps market inputs and instrument
  selection global but requires `user_id` on trades and signals;
  `user_isolation=True` alone does not isolate extension persistence. See
  [Per-User Data Isolation](data-isolation.md).

### 6.3 Agent surface (tools)

- One Agno `Toolkit` subclass per extension, returned from `register()`.
- Tool function names are descriptive and stable — `get_grid_status`,
  `record_grid_trade` — giving the Client **stable names** to register
  custom card renderers against (§7). (The first extension ships unprefixed
  names; introduce a prefix convention if a collision ever appears.)
- Tools return structured JSON (dicts), not prose; the agent narrates, the
  Client renders. The toolkit adapts — it contains no domain logic.
- Private tools obtain the owner from Agno's injected `RunContext.user_id`.
  Ownership is never an LLM-visible argument; missing identity fails closed.
- Sensitive mutations follow the shared HITL path (README §6): e.g.
  `record_grid_trade` is marked for confirmation so a wrong ledger entry
  can't slip through unnoticed.

### 6.4 HTTP surface (API)

- Routers are mounted under `/api/v1/extensions/<kebab-name>/`
  (`/api/v1/extensions/etf-grid/positions`). Versioned per the project's
  API-stability guideline; extensions never touch `/agui` or AgentOS
  internal routes.
- Read endpoints serve the Client's standalone pages; mutation endpoints
  mirror the tools (`POST .../trades` ≈ `record_grid_trade`) so the page
  and the chat can never disagree — both delegate to `service.py`.
- CORS and authentication are handled globally by AgentOS. Private ownership
  and administrator scope checks are explicit in the extension router; the
  framework's route mappings do not automatically cover custom routes.

### 6.5 Logging

Runtime logging is structured and agent-diagnosable
(`spectres/logging.py`): one shared JSONL file
(`logs/runtime-YYYY-MM-DD.jsonl`, daily rotation + retention) plus stdout,
with a `contextvars`-backed `trace_id` on every record (one per HTTP
request via middleware; tool failures without an active request bind a
fresh one). Extensions participate by convention:

- **Only `logging.getLogger(__name__)`** — extensions never configure
  handlers, formatters, or levels; core owns the sinks. The `extension`
  field on every record derives from the logger name, so per-extension
  filtering is `grep '"extension": "etf_grid"'`.
- **No silent `except`.** Every swallowed or converted failure is logged at
  WARNING or above, with `exc_info` when handling an exception.
- **Sensitive operations are structured audit events** — INFO with an
  `event` name and the business fields as extras, e.g.
  `event=trade_recorded` with symbol/side/quantity/price/net_amount.
- **Tool error contract**: toolkit functions never raise across the tool
  boundary. On failure they log ERROR (with `exc_info`) and return
  `{"ok": false, "error": {"type", "message", "trace_id", "hint"}}` where
  `hint` is a concrete log lookup (`grep <trace_id>
  logs/runtime-<today>.jsonl`); on success `{"ok": true, "data": ...}`.
  The Team Leader instructions document this contract, the log location,
  and the record shape, so the agent can self-diagnose tool failures.
- **Secrets never enter log records**; the redaction filter on core
  handlers is defense in depth, not a license to log carelessly.

### 6.6 Workflow and schedule surfaces (since v0.5.0/v0.6.5)

- Extensions return Agno `Workflow` instances in `contribution.workflows`;
  core mounts them in AgentOS. A Workflow may contain one deterministic step
  or an ordered sequence. There is no Runtime Action abstraction or dispatch
  registry. Private steps obtain the owner from `RunContext.user_id` and fail
  closed when it is absent.
- Extensions declare only automatic system schedules as `ScheduleSpec`s; core
  registers them idempotently at startup (`spectres/scheduler.py`, fail-loud
  like the loader). Personal schedules are created through Agno-native CRUD and
  are never seeded or reconciled by extension startup. Full design:
  [scheduled-tasks.md](scheduled-tasks.md).
- **Workflow run endpoints are the preferred extension carrier** because native
  schedule writes let ordinary users target only component runs covered by
  their scopes. Arbitrary extension REST targets remain admin-only. Workflow
  schedule runs retain linked run/session ids and structured output; ordinary
  HTTP targets retain only status/timings. Schedule-management clients use
  Agno's native `GET /workflows` catalog and derive run targets from Workflow
  ids; there is no separate Runtime target catalog or system-target filter.
- Scheduled work must be **idempotent**: the DB lease coordinates workers but
  side effects are not exactly-once, and a schedule missed during downtime
  fires once on recovery.
- **Operational fields come from the extension's config fragment only when a
  schedule is first created** (cron, timezone, enabled, retries — e.g.
  `ETF_GRID_SYNC_*`); names and endpoints stay in code. Existing rows are
  skipped without changes, including their enabled state and next run time. A
  `previous_names` match migrates only the display name and preserves the row
  identity, stored configuration, and run history.

## 7. Reference extension: ETF Grid Trading (`etf_grid`)

The first extension ports the owner's existing quant-advisor scripts
(MA60-anchored 5%-step grid over a 3-ETF portfolio, valuation gate on one
symbol) into the Runtime. Naming: product name **ETF Grid Trading**,
extension id **`etf_grid`** — deliberately descriptive over a codename,
since the id appears in table names, tool names, env prefixes, and URLs.

- **Ownership model**: candles, valuation, and administrator-controlled
  instrument selection are shared. `ETF_GRID_PORTFOLIO` remains authoritative
  for `name`, `per_grid_amount`, `max_grids`, and `gate` for every user.
  Trades and signals carry `user_id`; positions and P&L derive only from the
  caller's ledger. Admin selection only enables/disables symbols already
  present in configuration and survives idempotent startup bootstrap.
- **Trigger model**: user-initiated and scheduled. Conversation-side,
  `refresh_grid_data` runs an incremental shared market-data sync
  (idempotent, via the official FTShare SDK with `FTSHARE_API_KEY`), then
  recomputes only the current run owner's signals; `get_grid_status` reads
  that owner's latest snapshot. Schedule-side, one unowned
  `ETF Grid Daily Sync` (initially `0 9 * * 1,5`, Asia/Shanghai) runs the
  `etf_grid_data_sync` Workflow only. The former `etf_grid_daily_sync` row is
  renamed in place on startup. Users can create independent personal schedules
  for `etf_grid_recompute`; Runtime never creates them automatically and does
  not guarantee sync-before-recompute ordering.
- **Core** ports the proven computation (`level_of`, anchor scan, ledger
  replay with cost-protection sell pairing); grid parameters live in
  extension config, not hardcoded constants.
- **Tools**: `get_grid_status`, `refresh_grid_data`, `record_grid_trade`,
  `list_grid_trades` — stable names per §6.3, all scoped by injected
  `RunContext.user_id` and returning the §6.5 `{ok, data}` / `{ok, error}`
  envelope (`list_grid_trades` truncates silently at `limit`). HITL
  confirmation for `record_grid_trade` remains unadopted.
- **API**: self-scoped `GET .../status`, `POST .../signals/compute`, and
  `GET/POST .../trades`; shared `GET .../instruments` and authenticated-user
  `POST .../sync`; admin-only `GET .../admin/instruments` and
  `PATCH .../admin/instruments/{symbol}`; manual admin/internal
  `POST .../refresh`, all under `/api/v1/extensions/etf-grid`.
- **Client contract**: chat shows the agent's markdown narration plus
  custom tool cards registered via CopilotKit `useRenderTool`
  (`@copilotkit/react-core/v2`) on the stable tool names; the standalone
  ledger page is plain React over the REST API. A2UI (LLM-composed
  declarative UI over AG-UI activity events) is a tracked option, to be
  re-evaluated when multiple extensions make per-tool cards repetitive —
  today's card components would then serve as its component catalog.
- **REST contract** (since v0.4.4):
  - **Pagination envelope**: `GET .../trades` returns
    `{"items": [...], "total": int, "limit": int, "offset": int}`.
    `limit` defaults to 20 (`1..200`), `offset` to 0; filters (`symbol`,
    `start`, `end`) apply *before* counting, so `total` is the post-filter
    row count and clients can page through the full result set.
  - **Unified 422**: every 422 from the extension router — pydantic body
    validation, query-parameter validation, or domain rejection — returns
    `detail` as a list of objects carrying `loc` / `msg` / `type`. Native
    FastAPI items may additionally carry `input` / `url`; clients must
    ignore extra keys. Domain rejections use a single element with
    `loc: ["body"]` and `type: "value_error"`, and must raise
    `RequestValidationError`, **not** `HTTPException` — AgentOS installs a
    global `HTTPException` handler that renders `detail` via
    `str(exc.detail)`, which would stringify the list.
  - **Portfolio status fields** (since v0.4.5): each `GET .../status` row
    additionally carries `unrealized` and `unrealized_percent`
    (stringified Decimals) — floating P&L derived from the ledger's
    cost-basis convention: `unrealized = close × shares − avg_cost ×
    shares`, `unrealized_percent = unrealized / (avg_cost × shares)` (a
    fraction: 0.12 = 12%). Both are `null` — never a fabricated zero — when
    undefined: no position, no latest close, or a zero cost basis (percent
    only).

## 8. Guardrails (anti-over-engineering)

This design is deliberately the *minimum* that achieves "one directory,
auto-loaded":

- **No abstract plugin framework.** The contract is one Protocol, one
  context dataclass, one contribution dataclass. If the second extension
  reveals the contract is wrong, it is still cheap to change.
- **No lifecycle hooks beyond `register()`** (no start/stop/reload) until a
  real need exists.
- **No cross-extension dependencies.** Shared logic graduates into core or
  a shared library package.
- **Formalization trigger**: only when a *third* capability lands do we
  extract whatever registration boilerplate has actually repeated — the
  earliest point where the right abstraction is knowable.

## 9. Deferred / open questions

- **Entry-point discovery** for out-of-tree extensions (needs packaging,
  versioning, trust policy).
- **Per-extension Alembic migrations** (blocked on the project adopting
  migration tooling at all).
- **Tool ACL integration**: extension tools join the Runtime-owned policy
  layer (README §2.3) once it exists.
- **A2UI** for generative chat cards (§7).
- **Extension-contributed member agents**: a complex extension may
  *optionally* contribute a dedicated Slave agent (own instructions, own
  model, tools naturally isolated) as a member of the Master Team in
  coordinate mode (ADR 0001). When built: `ExtensionContribution` gains an
  `agents` field, core composes the Team from contributed agents, and a
  core-provided agent factory helper keeps model/db conventions
  centralized. Excluded from the first version — it depends on the Team
  milestone. Simple extensions keep contributing plain toolkits even after
  this lands: one agent per trivial capability wastes a leader→member LLM
  round-trip.
- **Enable/disable gating** (`ENABLED_EXTENSIONS` allowlist): deliberately
  omitted (§5.1). Add when an extension needs to be parked without deleting
  its code, or when environments genuinely need different capability sets.
