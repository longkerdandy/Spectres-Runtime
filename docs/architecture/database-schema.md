# Database Schema

> Runtime table inventory for Agno 3.1.2 and current extensions. Last updated:
> 2026-11-06.

## 1. Storage Layout

- Agno tables use the `ai` PostgreSQL schema and default `agno_*` names.
- Extension tables use the default `public` schema and an `<extension>_` prefix.
- Logto has a separate database in the same PostgreSQL container; its internal
  tables are not listed here.
- `get_postgres_db()` supplies one process-wide `PostgresDb` and connection pool.
  Extensions create their SQLAlchemy models with `metadata.create_all()`; no
  migration tool is configured.
- Agno creates framework tables on demand. Extensions must access Agno data
  through its db APIs, never by mutating framework tables directly.

## 2. Agno-Managed Tables

“Available” means the schema exists in Agno, not that the corresponding Runtime
feature is enabled.

| Table | Purpose | Runtime usage |
|-------|---------|---------------|
| `agno_sessions` | Agent/Team/Workflow sessions and history | Team Leader and Workflow sessions |
| `agno_runs` | Run records linked to sessions | In use |
| `agno_schema_versions` | Framework schema bookkeeping | In use |
| `agno_schedules` | Schedule definitions and ownership | System and personal schedules |
| `agno_schedule_runs` | Schedule attempts and linked output | In use |
| `agno_jobs` | Durable background component jobs | Background Workflow runs |
| `agno_authz_users` | JIT user directory and disabled flag | In use with JWT user directory |
| `agno_memories` | User memories | API available; Team Leader memory not enabled |
| `agno_metrics` | Usage aggregates | Available; not enabled on Team Leader |
| `agno_eval_runs` | Evaluation runs | Available; unused |
| `agno_knowledge` | Knowledge content | Available; RAG not enabled |
| `agno_traces`, `agno_spans` | Trace and span observability | Available; tracing not enabled |
| `agno_components`, `agno_component_configs`, `agno_component_links` | Component registry/configuration | Available; unused |
| `agno_learnings` | Learning store | Available; unused |
| `agno_compactions` | Session compaction records | Available; unused |
| `agno_tool_results` | Stored tool-result content | Available; no explicit Runtime use |
| `agno_approvals` | Human approval requests | Available; no current tool requests confirmation |
| `agno_auth_tokens` | Provider/service token data | Available; unused |
| `agno_service_accounts` | AgentOS service accounts | Available; scheduler uses internal token instead |
| `agno_authz_policy`, `agno_authz_grouping`, `agno_authz_roles` | Agno-managed roles and assignments | Unused; Logto owns roles |
| `agno_authz_audit`, `agno_authz_decisions` | Authorization audit trails | Unused; Agno audit sink not configured |
| `agno_mcp_oauth_clients`, `agno_mcp_oauth_transactions`, `agno_mcp_oauth_codes`, `agno_mcp_oauth_refresh_tokens`, `agno_mcp_oauth_keys` | Built-in MCP OAuth server | Available; MCP OAuth not configured |

If custom names or a different `db_schema` are passed to `PostgresDb`, update
this inventory in the same change.

## 3. ETF Grid Tables

Models live in `src/spectres/extensions/etf_grid/models.py`.

### `etf_grid_instruments`

Shared administrator-controlled enablement for symbols already present in
`ETF_GRID_PORTFOLIO`. Startup inserts missing configured symbols without
overwriting existing selections.

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | String(16) PK | Configured FTShare full code |
| `enabled` | Boolean NOT NULL | Included in normal sync/status/compute |
| `updated_by` | String(128) NULL | Last admin subject; NULL for bootstrap |
| `created_at`, `updated_at` | DateTime(tz) NOT NULL | Creation and last selection change |

### `etf_grid_trades`

Append-only, user-owned execution ledger. Positions and cost basis derive by
replaying only the owner's rows. An opening-position backfill is a normal `buy`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | Autoincrement |
| `user_id` | String(128) NOT NULL | Owner JWT subject |
| `trade_date` | Date NOT NULL | Execution date |
| `symbol` | String(16) NOT NULL | FTShare full code |
| `side` | String(8) NOT NULL | CHECK: `buy` or `sell` |
| `price` | Numeric(10,4) NOT NULL | Execution price per share |
| `quantity` | Integer NOT NULL | Shares |
| `gross_amount` | Numeric(12,2) NOT NULL | `price × quantity` |
| `commission_rate` | Numeric(8,6) NOT NULL | Broker rate stored per trade |
| `commission` | Numeric(10,2) NOT NULL | Rounded to cents unless overridden |
| `net_amount` | Numeric(12,2) NOT NULL | Buy: gross + fee; sell: gross − fee |
| `source` | String(32) NOT NULL | `manual` or `agent`; default `manual` |
| `note` | Text NULL | Free-form note |
| `created_at` | DateTime(tz) NOT NULL | Database timestamp |

Index: `(user_id, symbol, trade_date, id)`.

### `etf_grid_candles`

Shared forward-adjusted daily candles from FTShare. Rows are upserted by symbol
and date. Incremental sync refetches the configured trailing window so historical
re-adjustments self-heal.

| Column | Type | Notes |
|--------|------|-------|
| `symbol`, `trade_date` | String(16), Date | Composite primary/upsert key |
| `open`, `high`, `low`, `close` | Numeric(10,4) NOT NULL | Forward-adjusted OHLC |
| `volume` | BigInteger NOT NULL | Shares |
| `fetched_at` | DateTime(tz) NOT NULL | Last refresh timestamp |

### `etf_grid_valuation`

Shared 930914 valuation history from the csindex public API. `dyr` is derived
from the price index and H20914 total-return series. Rows are upserted by date.

| Column | Type | Notes |
|--------|------|-------|
| `trade_date` | Date PK | Trading day |
| `close` | Numeric(10,2) NOT NULL | Price-index close |
| `pe_ttm` | Numeric(10,2) NOT NULL | PE-TTM |
| `dyr` | Numeric(8,4) NULL | Trailing dividend yield; NULL before a full window exists |
| `fetched_at` | DateTime(tz) NOT NULL | Last refresh timestamp |

### `etf_grid_signals`

Private daily grid snapshot and advised limit orders. Recomputing the same user,
symbol, and date overwrites that row; execution history remains in the ledger.

| Column | Type | Notes |
|--------|------|-------|
| `user_id`, `symbol`, `trade_date` | String(128), String(16), Date | Composite primary/upsert key |
| `close` | Numeric(10,4) NOT NULL | Adjusted close used |
| `anchor_ma60` | Numeric(10,4) NOT NULL | MA60 anchor |
| `level`, `prev_level` | Integer NOT NULL | Current/previous grid level |
| `orders` | JSONB NOT NULL | Advised limit-order list |
| `block_reason` | String(32) NULL | Reason a level change was not actionable |
| `gate_metric_value` | Numeric(8,4) NULL | Current gate metric |
| `gate_percentile` | Numeric(6,4) NULL | Historical percentile, 0–1 |
| `gate_closed` | Boolean NULL | NULL for gateless symbols |
| `computed_at` | DateTime(tz) NOT NULL | Computation timestamp |

The local Docker PostgreSQL image pre-installs pgvector for future knowledge/RAG
use; no current table above uses vectors.
