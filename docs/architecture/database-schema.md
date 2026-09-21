# Database Schema — Table Inventory

> Topic reference companion to [`../architecture.md`](../architecture.md).
> Every table that actually exists in the Runtime's PostgreSQL database,
> and its purpose. Runtime does not define core tables of its own:
> session/agent state is managed by Agno (`agno_*` defaults, uncustomized).
> Domain data will live in extension-owned tables (`<extension>_*` prefix
> convention — see [Runtime Extensions §6.2](runtime-extensions.md)); none
> exist yet, and they are registered here only once implemented.
>
> Last updated: 2026-09-21.

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

## 2. Notes

- Single PostgreSQL database (dockerized, `agnohq/pgvector` image),
  currently used only by Agno; future extensions share it under the
  `<extension>_*` prefix convention. The pgvector extension is
  pre-installed for future knowledge/RAG use.
- Table names above are Agno 3.0 defaults; if a custom name is ever passed
  to `PostgresDb`, update this document in the same change.
