# Spectres System Architecture

> Current implementation contracts and the accepted Edge target design for coding
> agents. Current behavior and future design are labeled separately.
> Last updated: 2026-11-09.

## 1. System Boundaries

- **Spectres Runtime**: agents, tools, built-in Extensions, deterministic
  Workflows, scheduled work, persistence, and APIs.
- **Spectres Web Client**: a separate static React/Vite SPA for chat and views.
- **Logto**: the sole authority for users, roles, role assignments, and tokens.
- **PostgreSQL**: Runtime, Logto, and future Edge persistence under separate
  ownership boundaries.
- **Edges**: independently deployed vertical services for external clouds,
  software intermediaries, or devices. Xiaomi Health is the first accepted Edge
  design, but no Edge service is currently implemented.

The **Target** sections below come from ADR 0012 and are not implementation
claims.

## 2. Current System Context

```text
Web Client ──AG-UI / Bearer JWT / REST──▶ Runtime / AgentOS
Web Client ◀──authorization code + PKCE── Logto
Logto ──Runtime API JWT─────────────────▶ Runtime
Runtime ──LLM / Tavily / FTShare / csindex / web pages
Runtime ──Agno + custom tables──────────▶ PostgreSQL
Logto ──separate database───────────────▶ PostgreSQL
```

Current deployment is local/LAN. CORS is an explicit browser allowlist, not an
authentication boundary. Runtime verifies Logto tokens locally rather than
calling Logto per request.

## 3. Current Runtime

### 3.1 Agent, Conversation, and Tools

- One user-facing **Team Leader Agent** is exposed through AG-UI at `/agui`. It
  is an Agno `Agent`, not a Team or custom orchestration dispatcher.
- OpenAI-compatible and Gemini models are supported through typed configuration.
  PostgreSQL stores sessions/runs; the latest three history runs enter context.
- AG-UI maps `thread_id` to session id, pins the verified owner, and rejects
  cross-user thread writes. `forwarded_props.user_id` is not authoritative.
- Built-in tools are Calculator, Shell, Website/page reading, and optional
  Tavily search when `TAVILY_API_KEY` is configured.
- Stable tool names support Client renderers. Extension tools share the same
  Team Leader and return structured success/error envelopes.

### 3.2 Built-in Extensions

Extensions are trusted in-process capabilities discovered statically at startup.
Each can contribute Toolkits, REST routers, Agno Workflows, and declarative
system Schedules. They are not independent deployments, third-party sandboxes,
or Edges.

Implementation contracts:

- Registration is idempotent; invalid built-in code fails startup.
- `runtime_extension_states` persists global activation. Catalog reads require
  authentication; changes require `agent_os:admin`.
- Activation guards cover REST, Toolkit, Workflow, and scheduled execution
  without rebuilding AgentOS or restarting Runtime.
- Disabling preserves code, domain data, and native Schedule configuration.

See [Runtime Extensions](runtime-extensions.md) for layering and adapter rules.

### 3.3 ETF Grid Extension

ETF Grid is the reference vertical slice:

- Private append-only trade ledgers drive positions, cost basis, and P&L through
  owner-scoped replay.
- Shared forward-adjusted candles and index valuation support private daily grid
  signals and advised limit orders.
- `ETF_GRID_PORTFOLIO` supplies in-memory strategy definitions, not database
  configuration rows.
- REST and Team Leader tools cover status, trade recording/listing, shared sync,
  and current-owner recomputation.
- Deterministic Workflows separate shared-data sync from private recomputation.
  One unowned system Schedule handles sync; personal recompute Schedules use
  native CRUD and are never seeded.

### 3.4 Workflows and Scheduled Tasks

AgentOS polls `agno_schedules`, claims due rows with a PostgreSQL lease, and
fires one HTTP request per Schedule inside the Runtime process.

- Component targets run Agents/Teams/Workflows in the background and retain
  linked output. Ordinary HTTP targets succeed on 2xx and are admin-only.
- `agno_schedules`, `agno_schedule_runs`, and `agno_jobs` own framework state;
  domain results remain in Extension tables.
- Leases do not make side effects exactly-once, so scheduled work must be
  idempotent. Retries are per Schedule; downtime recovery fires once rather
  than replaying every missed interval. Cron uses the stored IANA timezone.
- Owned Schedules and runs retain their owner. Unowned rows are system tasks,
  not user-shared Schedules. Only the verified internal scheduler may forward
  an owner; payloads cannot override it.

Native Schedule authorization contracts:

| Operation | Required permission |
|-----------|---------------------|
| List/detail/history reads | `schedules:read` |
| Create | `schedules:write` + target run permission |
| Update, enable, trigger | `schedules:write` + required target run permission |
| Disable | `schedules:write` |
| Delete | `schedules:delete` |

`agent_os:admin` can perform all operations. Cross-user/nonexistent detail
operations return 404, and run detail validates the Schedule/run relationship.
The ordinary role currently has global `workflows:run`, including shared ETF
Grid sync; catalog visibility alone grants no run permission.

System Schedule registration looks up an unowned row by current name. Existing
rows remain unchanged; missing rows are created from `ScheduleSpec`, with
`enabled=False` applied only to a new row when requested. Registration failures
abort startup. Stored configuration survives restarts without legacy-name or
format migration.

A disabled Extension Workflow returns `{status: disabled, extension: <id>}` with
`stop=True` before business work. This deliberate skip is not retried and does
not rewrite Schedule configuration.

For ETF Grid, `etf_grid_data_sync` changes shared data without enumerating
ledger owners; `etf_grid_recompute` requires `RunContext.user_id`. Total source
failure is retryable, partial failure returns an `errors` field, and sync and
recompute have no ordering guarantee.

Do not add a custom scheduler, Action abstraction, dispatch registry, parallel
Schedule API, or cross-Schedule dependency layer.

### 3.5 Authentication, Authorization, and Data Isolation

Logto owns users and `user`/`admin` roles. AgentOS verifies JWT signature,
issuer, audience, and expiry, enforces Agno-native scopes, and provides the JIT
user directory and disabled-user enforcement. `agent_os:admin` is the framework
cross-user break-glass scope. Open no-auth mode is local development only.

Runtime always sets `user_isolation=True`. Framework isolation is route/query
filtering, not PostgreSQL RLS, and does not automatically cover custom services
or Extension tables.

| Framework data | Owner behavior | `user_id IS NULL` |
|----------------|----------------|-------------------|
| Sessions, runs, memories | Owner and framework admins | Hidden from regular users |
| Traces | Caller-filtered | Hidden from regular users |
| Metrics | Per-user buckets; admin aggregate access | Excluded from owned views |
| Knowledge | Private to uploader | Shared under Agno's current schema |
| Schedules and runs | Private to owner | System tasks |

Long-term memory, knowledge/RAG, and tracing are not enabled on Team Leader.
Knowledge's shared-NULL rule is an Agno behavior, not a default to copy into
Extensions.

For custom code:

1. Derive identity from `request.state.user_id` or `RunContext.user_id`; client,
   payload, Schedule, and LLM owner fields are never authoritative. Missing
   required identity fails closed.
2. Administrator scope does not automatically make Extension routes cross-user;
   ETF Grid self-scopes administrators too.
3. Classify every Extension data set as shared or private. Scope every private
   read, write, count, replay, and upsert; do not add accidental owner filters
   to shared data.
4. Keep mutable run state in owner-scoped persistence, not process-local user
   state.

Preserve `tests/test_user_isolation.py`, Schedule API ownership tests, and
relevant Extension isolation tests when changing these boundaries. See
[Authentication and Authorization](authentication-and-authorization.md) for token
and scope details.

### 3.6 Persistence and Custom Tables

- Agno owns `ai.agno_*` tables; access them only through Agno APIs. Logto owns a
  separate database and must not be queried as Runtime application storage.
- Runtime/Extension tables use `public`; Extension names use `<extension>_` and
  must not access another Extension's tables.
- `get_postgres_db()` shares one engine/connection pool, not table ownership.
- Custom tables use `metadata.create_all()` with no migration tool. It does not
  alter existing tables, so schema changes require an explicit migration design.
- SQLAlchemy models are authoritative for columns, types, checks, and indexes.

| Table | Ownership | Purpose and write contract |
|-------|-----------|----------------------------|
| `runtime_extension_states` | Global | One row per discovered Extension keyed by `name`; additive startup reconciliation preserves admin choices |
| `etf_grid_trades` | Private | Append-only ledger; replay `(symbol, trade_date, id)` per owner and correct mistakes with reversal rows |
| `etf_grid_candles` | Shared | Forward-adjusted candles keyed by `(symbol, trade_date)`; sync upserts refreshed history |
| `etf_grid_valuation` | Shared | Index 930914 history keyed by `trade_date`; sync upserts revisions |
| `etf_grid_signals` | Private | Latest advice keyed by `(user_id, symbol, trade_date)`; recompute upserts only the owner's row |

Runtime state models live in `src/spectres/extensions/state.py`; ETF Grid models
live in `src/spectres/extensions/etf_grid/models.py`. Preserve ledger replay
order and composite upsert keys, and do not create a second canonical position,
session, or Schedule store.

### 3.7 Configuration and Observability

Typed pydantic-settings uses explicit environment variables and separate
development/test base files with untracked local overrides. Structured logs go
to stdout and daily JSONL files with trace correlation. Log failures and
sensitive-operation audits without credentials, tokens, or health data.

## 4. Runtime Assembly and Execution Paths

```text
PostgreSQL adapter
→ static Extension discovery/registration
→ Extension-state reconciliation
→ system-Schedule registration
→ Toolkit and Workflow activation guards
→ Team Leader with built-in + Extension tools
→ AgentOS with AG-UI, JWT/RBAC, isolation, Workflows, and scheduler
→ core and Extension REST routers
```

Business execution uses three paths:

1. **Conversation**: AG-UI → Team Leader → built-in/Extension tool.
2. **Direct API**: authenticated REST router → domain service.
3. **Automation**: scheduler → Workflow or authorized HTTP target → service.

Private operations in every path use the same verified owner and domain services.
Keep REST, tool, and Workflow adapters thin and core code independent of
Extension imports.

## 5. Target: Extensions versus Edges

| Concern | Built-in Extension | Edge |
|---------|--------------------|------|
| Code/deployment | Released with Runtime/Web Client | Independent project and deployment |
| Loading | Static startup/build-time discovery | Independently released UI remote |
| Administration | Runtime global enable/disable | Independent deployment and availability |
| Data | Runtime-owned custom tables | Edge-owned schemas and tables |
| Example | ETF Grid and Runtime AI integration | Xiaomi Health service and UI |

A Runtime Extension may expose selected Edge operations as tools or event
handlers. Disabling it affects only Runtime integration, not Edge sync or UI.

## 6. Target: Xiaomi Health Edge

### 6.1 Independent Vertical Service

Xiaomi Health Edge owns account binding, credential refresh, device/sync state,
manual and scheduled synchronization, health schemas/migrations/persistence, and
configuration/status/query APIs. Runtime neither manages its sync lifecycle nor
keeps a second canonical health-data copy. A shared PostgreSQL deployment does
not permit cross-owned table access.

Runtime-to-Edge calls are specific operations implemented by a corresponding
Runtime Extension. Optional Edge-to-Runtime notifications must be authenticated
and idempotent; Runtime correctness must not depend on delivery. No generic
Connector, Edge registry/control plane, ingestion protocol, or custom scheduler
is introduced. Runtime never controls hardware directly.

### 6.2 Browser Identity

The SPA uses Logto authorization-code flow with PKCE and obtains a token for the
service it calls:

```text
Runtime token: sub = user-123, aud = Runtime API resource
Edge token:    sub = user-123, aud = Edge API resource
```

Each service independently verifies signature, issuer, audience, expiry, and
permissions. Verified `sub` is the common `user_id`; Edge must reject
Runtime-audience tokens. No Runtime/Edge BFF session, shared auth cookie, or
service-to-service browser authentication call is introduced.

### 6.3 Edge UI

`@module-federation/vite` loads independently released Edge pages:

- Web Client is the host; a managed catalog supplies manifest/API URLs, approved
  Logto resource, and navigation metadata.
- Pages load lazily with a narrow contract: API base URL, restricted token
  getter, locale, theme, and cancellation support.
- React/React DOM are compatible singletons; Edge libraries remain private.
  Manifest/page failures are isolated from chat and other capabilities.
- Only reviewed first-party remotes from approved origins are allowed. Module
  Federation is code loading, not a security sandbox; iframes and custom loaders
  are excluded.

An Edge outage or disabled Runtime integration must not disable unrelated
Runtime capabilities, and Runtime outage must not inherently stop Edge sync.

## 7. Explicitly Not Implemented

- Team/Slave orchestration or another user-facing Master Agent.
- Long-term memory, knowledge/RAG, per-agent tool ACL, judgment-based automation,
  notifications, and cross-Schedule dependencies.
- Xiaomi Health Edge backend, account binding, health persistence, or sync.
- Runtime-to-Edge proxying, Edge event handling, or a generic Edge control plane.
- Module Federation Edge UI remotes and independent Edge UI releases.
- Cloud Gateway deployment tooling and production public exposure.

Agno framework APIs or tables alone do not make a Spectres product feature
enabled.

## 8. Related Contracts

- [Authentication and Authorization](authentication-and-authorization.md)
- [Runtime Extensions](runtime-extensions.md)
