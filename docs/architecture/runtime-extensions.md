# Runtime Extensions — Architecture

> Topic deep-dive companion to [`../architecture.md`](../architecture.md).
> Status: **implemented** (v0.4.1; logging conventions added in v0.4.2) —
> the first extension (ETF Grid Trading) runs on this contract: in-tree
> loader, toolkit on the Team Leader, versioned router.
>
> Last updated: 2026-09-30.

---

## 1. Purpose

Runtime will repeatedly gain optional, self-contained domain capabilities:
ETF grid trading signals, later things like budgeting, health tracking, or
home-energy reports. Each such capability needs the same four things:

- **Domain core** — business logic and computation.
- **Persistence** — its own tables (trade ledgers, configuration, history).
- **Agent surface** — Agno tools the Master/Team Leader can invoke in
  conversation.
- **HTTP surface** — REST endpoints so the Client can render standalone
  pages outside the chat stream.

This document defines the **extension** as the unit that bundles those four
things into one directory, and the mechanism by which Runtime discovers and
loads them. The goal is not a general plugin framework — it is a repeatable
vertical-slice pattern with a single, minimal loading contract. A formal
plugin system is deliberately deferred (see §8).

## 2. What an extension is — and is not

An **extension** is an optional domain capability packaged as a single
Python package under `src/spectres/extensions/<name>/`, exposing a small
manifest object that Runtime loads at startup.

An extension is **not**:

- **Core agent infrastructure.** Master/Team orchestration, memory,
  session handling, AG-UI interfacing, tool ACL — these live in
  `spectres/` core and are always present. Extensions never modify core
  behavior; they only contribute *surfaces* to it.
- **A sandbox.** Extensions are in-process, trusted first-party code. There
  is no isolation boundary, no hot reload, no permission system beyond the
  (future) tool ACL that applies to all tools equally.
- **A deployment unit.** Extensions ship and deploy with Runtime. Out-of-tree
  third-party extensions are an explicitly deferred possibility (§9).

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
    ├── marketdata.py         # external data access (FTShare MCP client, valuation feed)
    ├── models.py             # SQLAlchemy tables, all prefixed `etf_grid_`
    ├── service.py            # application service: orchestrates core + marketdata + db
    ├── toolkit.py            # Agno Toolkit: the agent surface
    └── api.py                # FastAPI APIRouter: the HTTP surface
```

Layering inside an extension:

```
toolkit.py ─┐
            ├─> service.py ─> core/  (pure functions, testable in isolation)
api.py ─────┘           ├────> marketdata.py
                        └────> models.py (db)
```

`toolkit.py` and `api.py` are thin adapters containing no business logic;
both call the same `service.py`. This keeps the conversational answer and
the standalone page consistent by construction.

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
    #     retry_delay_seconds, enabled — all required except payload;
    #     registration always uses if_exists="update"

@dataclass
class ExtensionContribution:
    """What an extension gives back to Runtime."""
    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)

class Extension(Protocol):
    name: str                                    # unique id, e.g. "etf_grid"
    def register(self, ctx: ExtensionContext) -> ExtensionContribution: ...
```

Rules:

- **Idempotent, side-effect-free `register()`** apart from table creation
  (§6.2). No network calls, no scheduler threads at load time — schedules
  are only *declared*; core registers them with the AgentOS scheduler after
  loading (`spectres/scheduler.py`).
- An extension may contribute **any combination** of surfaces. A tool-only
  extension (chat interaction only), an API-only extension (pure data
  page), and a schedule-only extension (pure automation) are all valid.
- Extensions are constructed once at startup and are stateless across
  requests/runs; mutable state lives in the database.
- Extensions contribute **tools, not agents**, in this version: toolkits
  attach to the Team Leader directly. A dedicated per-extension member
  agent under the Master Team is a designed future option (§9), deferred
  until the Team milestone (coordinate mode, ADR 0001) lands.

### 4.1 Naming convention

The extension id is defined once, in snake_case (`etf_grid`), and every
surface derives from it. Rule of thumb: **snake_case everywhere, except
URLs which use kebab-case** — the only surface that transforms the id.

| Surface | Form | Example |
|---------|------|---------|
| Python package / directory | snake_case (must be a valid identifier) | `spectres/extensions/etf_grid/` |
| Database table prefix | snake_case | `etf_grid_trades` |
| Tool function names | snake_case (provider tool-name charset limits) | `get_grid_status` |
| Env var prefix | UPPER_SNAKE | `ETF_GRID_...` |
| URL paths | kebab-case | `/api/v1/extensions/etf-grid/...` |

The loader rejects ids that are not valid snake_case Python identifiers
at load time, before any `register()` call.

## 5. Discovery and loading

Both mechanisms the name suggests are used: **auto-discovery** finds
candidates, **dependency injection** wires them.

### 5.1 Discovery

`loader.py` scans the `spectres.extensions` namespace with
`pkgutil.iter_modules`; every package exposing a module-level `extension`
object conforming to the `Extension` protocol is loaded. **Discovery is
loading** — there is deliberately no enable/disable gating in this first
version: extensions are first-party code shipped in the same repository,
so presence in the tree is already an explicit opt-in. An
`ENABLED_EXTENSIONS` allowlist is deferred until a real need appears
(parking a broken extension without deleting code, per-environment
capability switches); see §9.

Out-of-tree discovery via `importlib.metadata.entry_points(group=
"spectres.extensions")` is reserved for the day a genuine third-party
extension exists (§9); the in-tree scan needs zero packaging work.

### 5.2 Startup sequence

In `main.py`, extensions load between db setup and app assembly; routers
mount onto the FastAPI app that `agent_os.get_app()` returns, before
`serve()`:

```python
def create_agent_os() -> tuple[AgentOS, list[ExtensionContribution]]:
    db = get_postgres_db()
    contributions = load_extensions(settings, db)  # discovery + DI, one call
    toolkits = [t for c in contributions for t in c.toolkits]
    team_leader_agent = create_team_leader_agent(db, extra_tools=toolkits)
    return AgentOS(..., agents=[team_leader_agent], ...), contributions

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

Each extension owns a settings fragment class in its `config.py`, using
the same pydantic-settings style as core, with env vars prefixed by the
extension name (`ETF_GRID_*`). The fragment is instantiated inside
`register()`; core `Settings` carries nothing extension-specific.
Optional secrets (e.g. `FTSHARE_API_KEY`) never block loading — the
dependent capability fails with an explicit error at call time instead.

### 6.2 Persistence

- Same PostgreSQL database as core; **table names prefixed `<name>_`**
  (`etf_grid_trades`, `etf_grid_signals`, ...). No extension may touch
  Agno-managed tables or another extension's tables. All data access —
  Agno's own tables and extension tables alike — flows through the single
  process-wide `PostgresDb` handle (`get_postgres_db()`); extensions reach
  the underlying SQLAlchemy engine via its public `db_engine` attribute,
  so the whole Runtime shares one connection pool.
- MVP: `metadata.create_all(ctx.db.db_engine)` during `register()`. The project has
  no migration tooling yet; when it adopts Alembic, each extension keeps
  its revisions in its own directory.
- The extension's tables are the **only** source of truth for its domain
  (e.g. the trade ledger replaces quant-advisor's CSVs; a one-time import
  script migrates existing data).

### 6.3 Agent surface (tools)

- One Agno `Toolkit` subclass per extension, returned from `register()`.
- Tool function names are descriptive and stable —
  `get_grid_status`, `record_grid_trade` — giving the Client **stable
  names** to register custom card renderers against (§7). (The first
  extension ships unprefixed names; introduce a prefix convention if a
  collision ever appears.)
- Tools return structured JSON (dicts), not prose; the agent narrates, the
  Client renders. The toolkit adapts — it contains no domain logic.
- Sensitive mutations follow the shared HITL path (architecture.md §6):
  e.g. `record_grid_trade` is marked for confirmation so a wrong
  ledger entry can't slip through unnoticed.

### 6.4 HTTP surface (API)

- Routers are mounted under `/api/v1/extensions/<kebab-name>/`
  (`/api/v1/extensions/etf-grid/positions`). Versioned per the project's
  API-stability guideline; extensions never touch `/agui` or AgentOS
  internal routes.
- Read endpoints serve the Client's standalone pages; mutation endpoints
  mirror the tools (`POST .../trades` ≈ `record_grid_trade`) so the
  page and the chat can never disagree about behavior — both delegate to
  `service.py`.
- CORS is handled globally by AgentOS; auth (when it arrives, per the
  multi-tenant phases of ADR 0005) applies to extension routes the same
  as core routes.

### 6.5 Logging

Runtime logging is structured and agent-diagnosable
(`spectres/logging.py`, plan `docs/plan/v0.4.2-runtime-logging.md`): one
shared JSONL file (`logs/runtime-YYYY-MM-DD.jsonl`, daily rotation +
retention) plus stdout, with a `contextvars`-backed `trace_id` attached to
every record (one per HTTP request via middleware; tool failures without an
active request bind a fresh one). Extensions participate by convention:

- **Only `logging.getLogger(__name__)`** — extensions never configure
  handlers, formatters, or levels; core owns the sinks. The `extension`
  field on every record is derived from the logger name
  (`spectres.extensions.<name>...`), so per-extension filtering is just
  `grep '"extension": "etf_grid"'`.
- **No silent `except`.** Every swallowed or converted failure is logged at
  WARNING or above, with `exc_info` when an exception is being handled
  (e.g. `marketdata.sync_market_data` per-source ERROR, `csindex` retry
  WARNINGs).
- **Sensitive operations are structured audit events** — INFO with an
  `event` name and the business fields as extras, e.g.
  `event=trade_recorded` with symbol/side/quantity/price/net_amount.
- **Tool error contract**: toolkit functions never raise across the tool
  boundary. On failure they log ERROR (with `exc_info`) and return
  `{"ok": false, "error": {"type", "message", "trace_id", "hint"}}` where
  `hint` is a concrete shell-tool lookup (`grep <trace_id>
  logs/runtime-<today>.jsonl`); on success `{"ok": true, "data": ...}`.
  The Team Leader instructions document this contract, the log location,
  and the record shape, so the agent can self-diagnose tool failures.
- **Secrets never enter log records** (API keys, DB credentials); a
  redaction filter on the core handlers is defense in depth, not a license
  to log carelessly.

### 6.6 Schedule surface (since v0.5.0, ADR 0007)

- Extensions declare scheduled tasks as `ScheduleSpec`s in their
  contribution; core registers them with the AgentOS scheduler at startup
  (`spectres/scheduler.py`, fail-loud like the loader). Full design:
  [scheduled-tasks.md](scheduled-tasks.md).
- **The carrier is the extension's own REST route** — a schedule fires one
  HTTP call and **2xx is success**, so schedule-facing routes must map
  "nothing usable was produced" to 5xx (partial failures may stay 200 with
  a body-level `errors` field). The scheduler records only status/timings;
  domain results live in the extension's own tables.
- Scheduled endpoints must be **idempotent**: the DB lease coordinates
  workers but side effects are not exactly-once, and a schedule missed
  during downtime fires once on recovery.
- **Operational fields come from the extension's config fragment**
  (cron, timezone, enabled, retries — e.g. `ETF_GRID_SYNC_*`); structural
  fields (name, endpoint) stay in code, derived from the extension id.
  `enabled=False` converges the DB row to disabled on restart.

## 7. Reference extension: ETF Grid Trading (`etf_grid`)

The first extension ports the owner's existing quant-advisor scripts
(MA60-anchored 5%-step grid over a 3-ETF portfolio, valuation gate on one
symbol) into the Runtime. Naming: product name **ETF Grid Trading**,
extension id **`etf_grid`** — deliberately descriptive over a codename,
since the id appears in table names, tool names, env prefixes, and URLs.

- **Trigger model**: user-initiated and scheduled. Conversation-side, when
  the user asks for a refresh, `refresh_grid_data` first runs an
  incremental market-data sync (idempotent, via the FTShare MCP endpoint
  with `FTSHARE_API_KEY`), then recomputes and persists the signal
  snapshots, then returns both results; `get_grid_status` reads the
  latest persisted snapshot. Schedule-side (since v0.5.0, ADR 0007), the
  extension contributes `etf_grid_daily_sync` (`0 9 * * 1,5`,
  Asia/Shanghai) pointing at the composite `POST .../refresh` route —
  a deterministic layer-1 trigger with zero LLM calls.
- **Core** ports the proven computation (`level_of`, anchor scan, ledger
  replay with cost-protection sell pairing) decoupled from its current
  print/CSV coupling; grid parameters move from hardcoded constants into
  extension config.
- **Tools**: `get_grid_status`, `refresh_grid_data`, `record_grid_trade`,
  `list_grid_trades` — stable names per §6.3. All return the §6.5
  `{ok, data}` / `{ok, error}` envelope with bare payload shapes (no
  pagination envelope — `list_grid_trades` truncates silently at
  `limit`). HITL confirmation for `record_grid_trade` is the design
  (§6.3) but not yet adopted — the tool executes immediately today.
- **API**: `GET .../status`, `POST .../signals/compute`,
  `POST .../sync`, `POST .../refresh` (composite sync+compute for the
  scheduler, v0.5.0), `GET/POST .../trades` under
  `/api/v1/extensions/etf-grid` — the data source for a standalone Client
  page. (A `GET .../signals` history route existed in v0.4.x but was
  removed in v0.5.0: it had no consumer — the Client renders the latest
  signal embedded in `/status`; the service-layer `list_signals` remains
  available should a history page ever need it.)
- **Client contract**: chat shows the agent's markdown narration plus
  custom tool cards registered via CopilotKit `useRenderTool`
  (`@copilotkit/react-core/v2`) on the stable tool names; the standalone
  ledger page is plain React over the REST API. A2UI (LLM-composed
  declarative UI over AG-UI activity events)
  is recorded as a tracked option, to be re-evaluated when multiple
  extensions make per-tool cards repetitive — today's card components
  would then serve as its component catalog.
- **REST contract** (since v0.4.4):
  - **Pagination envelope**: `GET .../trades` returns
    `{"items": [...], "total": int, "limit": int, "offset": int}`.
    `limit` defaults to 20 (`1..200`), `offset` defaults to 0; filters
    (`symbol`, `start`, `end`) apply *before* counting, so `total` is the
    post-filter row count and clients can page through the full result
    set.
  - **Unified 422**: every 422 from the extension router — pydantic body
    validation, query-parameter validation, or domain rejection — returns
    `detail` as a list of objects carrying `loc` / `msg` / `type`. Native
    FastAPI items may additionally carry `input` / `url`; clients must
    ignore extra keys. Domain rejections use a single element with
    `loc: ["body"]` and `type: "value_error"`.
    Implementation note: domain rejections must raise
    `RequestValidationError`, **not** `HTTPException` — AgentOS installs a
    global `HTTPException` handler that renders `detail` via
    `str(exc.detail)`, which would stringify the list; the
    `RequestValidationError` path is FastAPI-native and keeps the shape.
  - **Portfolio status fields** (since v0.4.5): each `GET .../status` row
    additionally carries `unrealized` and `unrealized_percent`
    (stringified Decimals) — the floating P&L of the current position,
    derived from the ledger's existing cost-basis convention:
    `unrealized = close × shares − avg_cost × shares` and
    `unrealized_percent = unrealized / (avg_cost × shares)` (a fraction
    like `gate_percentile`: 0.12 = 12%). Both are `null` — never a
    fabricated zero — when the derivation is undefined: no position
    (`shares == 0` / no `avg_cost`), no latest close, or a zero cost
    basis (percent only).

## 8. Guardrails (anti-over-engineering)

This design is deliberately the *minimum* that achieves "one directory,
auto-loaded":

- **No abstract plugin framework.** The contract is one Protocol, one
  context dataclass, one contribution dataclass. If the second extension
  reveals the contract is wrong, it is still cheap to change.
- **No lifecycle hooks beyond `register()`** (no start/stop/reload) until
  a real need exists (e.g. the scheduler milestone).
- **No cross-extension dependencies.** If two extensions ever need to
  share logic, that logic graduates into core or a shared library package.
- **Formalization trigger**: only when a *third* capability lands do we
  extract whatever registration boilerplate has actually repeated — that
  is the earliest point where the right abstraction is knowable.

## 9. Deferred / open questions

- **Entry-point discovery** for out-of-tree extensions (needs packaging,
  versioning, trust policy).
- **Per-extension Alembic migrations** (blocked on the project adopting
  migration tooling at all).
- **Tool ACL integration**: extension tools join the Runtime-owned policy
  layer (architecture.md §2.3) once it exists; nothing extension-specific
  is built now.
- **A2UI** for generative chat cards (§7).
- **Extension-contributed member agents**: a complex extension may
  *optionally* contribute a dedicated Slave agent — own instructions,
  own (possibly cheaper/specialized) model, tools naturally isolated to
  that agent — as a member of the Master Team. The Team runs in
  **coordinate mode** (ADR 0001): the Master decides when to delegate and
  synthesizes the final answer. When this is built:
  `ExtensionContribution` gains an `agents` field, core composes the Team
  from contributed agents, and a core-provided agent factory helper keeps
  model/db conventions centralized (extensions still never touch framework
  assembly). Deliberately excluded from the first version — it depends on
  the Team milestone and its delegation-tuning work. Simple extensions
  should keep contributing plain toolkits even after this lands: one
  agent per trivial capability wastes a leader→member LLM round-trip.
- **Enable/disable gating** (`ENABLED_EXTENSIONS` allowlist): deliberately
  omitted from the first version (§5.1). Add when an extension needs to be
  parked without deleting its code, or when environments genuinely need
  different capability sets.
