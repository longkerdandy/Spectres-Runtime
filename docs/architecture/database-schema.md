# Database Schema — Table Inventory

> Topic reference companion to [`../architecture.md`](../architecture.md).
> Every table that actually exists in the Runtime's PostgreSQL database,
> and its purpose. Runtime does not define core tables of its own:
> session/agent state is managed by Agno (`agno_*` defaults, uncustomized).
> Domain data lives in extension-owned tables (`<extension>_*` prefix
> convention — see [Runtime Extensions §6.2](runtime-extensions.md)),
> registered here once implemented.
>
> Last updated: 2026-09-22.

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
| `symbol` | String(6) NOT NULL | six-digit ETF code |
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

## 3. Notes

- Single PostgreSQL database (dockerized, `agnohq/pgvector` image),
  currently used only by Agno; future extensions share it under the
  `<extension>_*` prefix convention. The pgvector extension is
  pre-installed for future knowledge/RAG use.
- Table names above are Agno 3.0 defaults; if a custom name is ever passed
  to `PostgresDb`, update this document in the same change.
