# Spectres Runtime — Architecture

> Current system design and implementation boundaries. ADRs in
> [`../adr/`](../adr/README.md) explain decision history; this document describes
> what is built now and clearly labels future design.
>
> Last updated: 2026-11-07.

## 1. System Context

Spectres Runtime is the middle layer of a personal AI assistant. The Client UI
and Edge Gateway are separate projects.

```text
Client ──AG-UI / versioned REST──> Runtime (AgentOS)
                                    ├─ Team Leader Agent → built-in/extension tools
                                    ├─ Extension routers and deterministic Workflows
                                    ├─ JWT authentication, scopes, user isolation
                                    └─ PostgreSQL / in-process scheduler
Logto ──OIDC JWT / JWKS─────────────> Runtime
Runtime ──authenticated channel─────> Edge (planned)
```

The current deployment is a local/home Runtime. Multiple authenticated users
are supported; framework data and ETF Grid private data are owner-scoped.

## 2. Current Runtime

`src/spectres/main.py` assembles the application:

1. Configure structured logging and create the process-wide `PostgresDb`.
2. Discover and register in-tree extensions.
3. Initialize configuration collections whose target tables are empty; skip every
   collection that already contains data.
4. Register missing system schedules without reconfiguring existing rows.
5. Attach extension toolkits to the Team Leader and mount extension Workflows.
6. Build AgentOS with AG-UI, optional JWT authorization, the scheduler, and
   `user_isolation=True`; mount extension routers on the FastAPI app.

The Team Leader is a single Agno `Agent`, not a Team. It supports
OpenAI-compatible or Gemini models, PostgreSQL session history, and the three
most recent history runs in context. Built-ins are calculator, shell, website,
and optional Tavily search tools.

The extension system currently hosts ETF Grid Trading: private trade ledgers
and signals, shared candles/valuation/instrument selection, REST APIs, agent
tools, and deterministic sync/recompute Workflows. Administrators can globally
enable or disable built-in Extensions; Runtime enforces the state at REST,
Toolkit, Workflow, and scheduled execution boundaries. See
[Runtime Extensions](runtime-extensions.md).

## 3. Target Agent Design

These are constraints for future work, not current behavior:

- Exactly one logical user-facing Master Agent per user. Channels and proactive
  runs must not introduce another Master.
- Master/Slave orchestration will use Agno `Team` in `coordinate` mode; no
  custom orchestration dispatcher.
- Team members will need explicit state, tool-ACL, and tenant-isolation
  handling. Top-level AgentOS isolation alone is not sufficient.
- Device control will use a local agent/tool proxy to Edge; Runtime never
  accesses hardware directly.

## 4. Sessions and Automation

- Conversation history and state are isolated by `session_id`.
- User profiles and memories aggregate by `user_id` when those features are
  enabled.
- Agent objects are shared application components; mutable run data belongs in
  PostgreSQL, not process-local state.

Automation has three layers:

| Layer | Handling | Status |
|-------|----------|--------|
| Deterministic rules | AgentOS scheduler → Workflow or authorized HTTP target, without an LLM | Implemented |
| Judgment-needed events | Master run in an isolated session with the same `user_id` | Planned |
| High-frequency events | Filter/aggregate at Edge before reaching Runtime | Planned |

Only deterministic ETF Grid Workflows currently run on schedules. Notification
delivery, cross-schedule dependencies, and judgment-based automation are not
implemented. See [Scheduled Tasks](scheduled-tasks.md).

## 5. Client Interfaces

- `AGUI(agent=team_leader_agent)` exposes `/agui` as a streaming AG-UI endpoint.
  The current stream has one assistant voice; Team delegation cards do not
  exist because Team/Slave orchestration is not implemented.
- Agent and extension tools have stable names for Client-side tool renderers.
- Extension REST routers live under `/api/v1/extensions/<kebab-name>/`.
- Future Team visibility may add member attribution and eventually native
  AG-UI subagent events; neither is current behavior.

## 6. Deployment

Clients use configurable HTTP(S) endpoints. CORS is only a browser allowlist,
not a security boundary.

The accepted remote-access design is:

```text
Client ──HTTPS──> Cloud Gateway (nginx) ──WireGuard──> Home Runtime
```

The Gateway terminates TLS and proxies/rate-limits traffic. Runtime remains
unexposed directly and owns authentication and authorization. No client VPN or
agent is required. Gateway deployment tooling is not yet implemented; current
development uses local/LAN access. A future multi-tenant Gateway may become a
registry and router for multiple home Runtimes. See ADR 0008.

## 7. Security Boundaries

- Self-hosted Logto issues JWTs; AgentOS verifies signature, issuer, and
  audience and enforces Agno-native scopes. `agent_os:admin` grants framework
  administration and cross-user access. See [Authentication](authentication.md).
- Framework isolation filters sessions, runs, memories, schedules, and related
  records by the verified JWT subject. AG-UI rejects cross-user thread writes.
- Extension tables and custom routes require explicit ownership checks; Agno
  does not isolate them automatically. See [Data Isolation](data-isolation.md).
- Sensitive operations should use Agno's shared confirmation/approval flow.
  Current ETF Grid tools do not request HITL confirmation.
- Runtime↔Edge authentication and encryption are required when Edge is added.
- Per-agent tool ACL is not implemented.

## 8. Not Implemented

Team/Slave agents, long-term agent memory, knowledge/RAG, tool ACL,
judgment-based automation, notifications, Edge proxying, and Gateway deployment
tooling remain future work.

## 9. References

- [Authentication](authentication.md)
- [Per-User Data Isolation](data-isolation.md)
- [Runtime Extensions](runtime-extensions.md)
- [Scheduled Tasks](scheduled-tasks.md)
- [Database Schema](database-schema.md)
- [ADRs 0001–0012](../adr/README.md)
- [Milestone plans](../plan/)
