# Database Schema — Table Inventory

> Topic reference companion to [`../architecture.md`](../architecture.md).
> Every table that actually exists in the Runtime's PostgreSQL database,
> and its purpose. Runtime does not define core tables of its own:
> session/agent state is managed by Agno (`agno_*` defaults, uncustomized).
> Domain data lives in extension-owned tables (`<extension>_*` prefix
> convention — see [Runtime Extensions §6.2](runtime-extensions.md)),
> registered here once implemented.
>
> Last updated: 2026-09-24.

---

## 1. Agno-managed tables (`agno_*`)

Created and owned by the framework; **lazy** — a table appears only when
the corresponding feature is first used. Never query or mutate these from
extension code; access goes through Agno's db handle.

| Table | Purpose | Status |
|-------|---------|--------|
| `agno_sessions` | Agent/team sessions: state and conversation history, isolated by `session_id` | In use (Team Leader) |
| `agno_runs` | Individual run records, FK to `agno_sessions` | In use |
| `agno_schema_versions` | Framework schema migration bookkeeping | In use |
| `agno_memories` | Long-term user memories, aggregated by `user_id` | Unused (no MemoryManager yet) |
| `agno_metrics` | Token/usage metrics per run | Unused |
| `agno_eval_runs` | Evaluation runs | Unused |
| `agno_knowledge` | Knowledge base documents/chunks (RAG) | Unused |
| `agno_traces` | Observability traces | Unused |
| `agno_spans` | Observability spans (child of traces) | Unused |
| `agno_components` | AgentOS component registry (agents/teams/workflows) | Unused |
| `agno_component_configs` | Registry component configurations | Unused |
| `agno_component_links` | Registry component relationships | Unused |
| `agno_learnings` | Learning-machine store | Unused |
| `agno_schedules` | Scheduler definitions | Unused |
| `agno_schedule_runs` | Scheduler execution records | Unused |
| `agno_jobs` | Background jobs | Unused |
| `agno_tool_results` | Tool call results (paused/HITL runs) | Unused |
| `agno_approvals` | HITL approval requests | Unused |
| `agno_auth_tokens` | AgentOS RBAC auth tokens | Unused |
| `agno_service_accounts` | AgentOS service accounts | Unused |
| `agno_mcp_oauth_clients` | MCP OAuth client registrations | Unused |
| `agno_mcp_oauth_transactions` | MCP OAuth in-flight transactions | Unused |
| `agno_mcp_oauth_codes` | MCP OAuth authorization codes | Unused |
| `agno_mcp_oauth_refresh_tokens` | MCP OAuth refresh tokens | Unused |
| `agno_mcp_oauth_keys` | MCP OAuth signing keys | Unused |

## 2. Extension tables

Owned by Runtime extensions under the `<extension>_*` prefix convention.
Created by the owning extension (SQLAlchemy `create_all`), never by Agno.

### `etf_grid_trades` (ETF Grid Trading extension)

Append-only trades ledger: every executed buy/sell of the ETF grid
portfolio. An opening-position backfill is recorded as a plain `buy`
(it replays identically; the backfill semantics go in `note`). The
ledger is the single source of truth for positions; holdings and
average cost are derived by replaying it
(`spectres.extensions.etf_grid.core.ledger.replay_ledger`). Model:
`src/spectres/extensions/etf_grid/models.py`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | autoincrement |
| `trade_date` | Date NOT NULL | execution date |
| `symbol` | String(16) NOT NULL | FTShare full code, e.g. `513330.XSHG` |
| `side` | String(8) NOT NULL | CHECK in (`buy`, `sell`), generated from the `Side` enum |
| `price` | Numeric(10,4) NOT NULL | execution price per share |
| `quantity` | Integer NOT NULL | shares |
| `gross_amount` | Numeric(12,2) NOT NULL | `price x quantity` |
| `commission_rate` | Numeric(8,6) NOT NULL | broker commission rate |
| `commission` | Numeric(10,2) NOT NULL | `ROUND_HALF_UP(gross_amount x commission_rate, 2)` unless overridden |
| `net_amount` | Numeric(12,2) NOT NULL | buy: `gross + commission`; sell: `gross - commission` |
| `source` | String(32) NOT NULL | `manual` / `agent`, default `manual` |
| `note` | Text NULL | free-form note |
| `created_at` | DateTime(tz) NOT NULL | `server_default=func.now()` |

Index: `(symbol, trade_date)`. No CSV migration: the quant-advisor
history is considered potentially inaccurate and will be re-entered
manually (owner decision).

### `etf_grid_candles` (ETF Grid Trading extension)

Forward-adjusted (qfq) daily-K cache, sourced solely from FTShare
`ft_v1_etf_candlesticks` (`adjust_kind=Forward`). A dividend recomputes
all historical bars, so rows are **upserted, never append-only** — sync
refetches a trailing ~90-day window (covering the MA60 window) so
re-adjustments self-heal. Model:
`src/spectres/extensions/etf_grid/models.py`.

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | String(16) PK | FTShare full code, e.g. `513330.XSHG` (composite PK, part 1) |
| `trade_date` | Date PK | trading day (composite PK, part 2) |
| `open`/`high`/`low`/`close` | Numeric(10,4) NOT NULL | forward-adjusted OHLC |
| `volume` | BigInteger NOT NULL | shares (800M+ values exist in history) |
| `fetched_at` | DateTime(tz) NOT NULL | `server_default=func.now()`, refreshed on every upsert |

The composite PK is the upsert key and covers the only access pattern
(history per symbol, date-ordered); no surrogate id, no extra indexes.

### `etf_grid_valuation` (ETF Grid Trading extension)

Valuation series of the 930914 index — the input of the valuation gate
(pause opening new grids when the index is expensive). Sourced solely
from the csindex.com.cn public JSON API (`csindex.py`); `dyr` is
reconstructed locally from the price index and its H20914 total-return
twin. Model: `src/spectres/extensions/etf_grid/models.py`.

| Column | Type | Notes |
|--------|------|-------|
| `trade_date` | Date PK | trading day |
| `close` | Numeric(10,2) NOT NULL | price index close |
| `pe_ttm` | Numeric(10,2) NOT NULL | PE-TTM |
| `dyr` | Numeric(8,4) NULL | trailing-12m dividend yield (0.0532 = 5.32%); NULL for the first 252 trading days |
| `fetched_at` | DateTime(tz) NOT NULL | `server_default=func.now()`, refreshed on every upsert |

Single-index table (930914 only). Upsert semantics like candles so
csindex history revisions self-heal.

### `etf_grid_signals` (ETF Grid Trading extension)

Computed daily grid signal snapshot per symbol, persisted by
`compute_daily_signals()`. Makes "why buy / not buy that day" auditable
and UI-renderable. Model: `src/spectres/extensions/etf_grid/models.py`.

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | String(16) PK | FTShare full code (composite PK, part 1) |
| `trade_date` | Date PK | trading day the signal is for (composite PK, part 2) |
| `close` | Numeric(10,4) NOT NULL | qfq close used for the computation |
| `anchor_ma60` | Numeric(10,4) NOT NULL | MA60 anchor |
| `level` / `prev_level` | Integer NOT NULL | grid level today / yesterday (clamped to ±max_grids) |
| `action` | String(8) NOT NULL | `none` / `buy` / `sell` (next-day-open operation) |
| `grids` | Integer NOT NULL | grid units to trade (0 when action=`none`) |
| `block_reason` | String(32) NULL | `gate_closed` / `max_grids_reached` / `cost_protection` / `no_position` |
| `next_buy_trigger` | Numeric(10,4) NULL | close below → buy 1 grid at next open |
| `next_sell_trigger` | Numeric(10,4) NULL | max(grid boundary, cheapest lot cost × (1+step)) |
| `gate_metric_value` | Numeric(8,4) NULL | current gate metric |
| `gate_percentile` | Numeric(6,4) NULL | metric percentile over full history, 0~1 |
| `gate_closed` | Boolean NULL | NULL for gateless symbols |
| `computed_at` | DateTime(tz) NOT NULL | `server_default=func.now()` |

Upsert on recompute: a same-day recomputation overwrites the row (the
signal is advice, not fact; the audit trail lives in `etf_grid_trades`).
No position columns — holdings derive from the ledger on demand.

## 3. Notes

- Single PostgreSQL database (dockerized, `agnohq/pgvector` image),
  currently used only by Agno; future extensions share it under the
  `<extension>_*` prefix convention. The pgvector extension is
  pre-installed for future knowledge/RAG use.
- Table names above are Agno 3.0 defaults; if a custom name is ever passed
  to `PostgresDb`, update this document in the same change.
