# Spectres Runtime — Architecture

> The living description of the system's current design. This document is
> updated in place as the architecture evolves. Decisions and their rationale
> are frozen in [`adr/`](adr/README.md); this document explains *what is*,
> ADRs explain *why*.
>
> For project background, layer responsibilities, and the full Runtime scope,
> see [`AGENTS.md`](../AGENTS.md). Last updated: 2026-09-20.

---

## 1. System Overview

Spectres is a personal AI assistant. Three physical layers:

```
┌────────────────────────────────────────────────────────────┐
│  Clients: Web App · Mobile App · Mini-program (roadmap)    │
└──────────────────────────┬─────────────────────────────────┘
                           │  AG-UI over HTTP(S), configurable endpoint
┌──────────────────────────▼─────────────────────────────────┐
│  Runtime (this repository)                                 │
│  Master Agent (Agno Team) → Slave Agents → Tools           │
│  PostgreSQL: sessions, history, memory, knowledge (later)  │
└──────────────────────────┬─────────────────────────────────┘
                           │  authenticated channel to Edge Gateway
┌──────────────────────────▼─────────────────────────────────┐
│  Edge: home-LAN gateway, device protocols, state truth     │
└────────────────────────────────────────────────────────────┘
```

Current phase: single user, full stack deployed at home (ADR 0005).

## 2. Agent Architecture

### 2.1 Single Master (red line — ADR 0002)

Exactly one logical Master Agent per user. It owns the *user relationship*:
the single conversational persona, the unified long-term profile, and the
authoritative interpretation of intent. Any proposal for another user-facing
agent is re-examined as a Slave or Workflow in disguise.

- "One" is **role uniqueness**, not a process singleton: instances are
  created/restored per user and scale horizontally.
- Channels (web, app, voice) are interfaces to the same Master, never
  separate Masters.

### 2.2 Master/Slave on Agno Team (ADR 0001)

The Master is the leader of an Agno `Team` in `coordinate` mode; Slave Agents
are members, each with its own model, tools, knowledge, and memory. Nested
Teams model sub-domains. Delegation (`delegate_task_to_member`), session
persistence, streaming member events, and HITL pause propagation are
framework-provided.

- **Request classification is a standing concern**: trivial requests get a
  direct Master answer or `route`-mode forwarding; only genuine multi-step
  work pays for full coordination.
- **Master model must be strong** (delegation decisions depend on it); Slaves
  may use cheaper/specialized models.

### 2.3 Runtime-owned gaps (not provided by Agno)

| Gap | Approach |
|-----|----------|
| No per-member `session_state` isolation | Namespacing convention for per-slave state |
| No per-member tool ACL | Policy layer in Toolkit wrappers / `tool_hooks` / guardrails ("which agent may invoke which tool") |
| No per-member tenant isolation | Single-user phase: none needed. Multi-tenant: `TeamFactory` + db filtering + `user_isolation`; verify member-memory leakage separately |
| Remote agents cannot be team members | Device control = local Slave Agent + custom Toolkit proxying to the Edge Gateway; Runtime never touches hardware |

## 3. Sessions, Memory, and Automation

### 3.1 Isolation model (ADR 0003)

- Memory and user profile aggregate by **`user_id`** — shared across sessions.
- Conversation history and state are isolated by **`session_id`**.
- Team instances are stateless; concurrent runs on different sessions are safe.

### 3.2 Automation triggers — three layers

| Layer | Examples | Handling |
|-------|----------|----------|
| Deterministic rules | "Lights off at 23:00" | Scheduler → tools/Workflow directly, zero LLM calls, audit log only |
| Judgment-needed | "Air quality dropped — ventilate?" | Master run in an **isolated session**, same `user_id` |
| High-frequency events | Per-second sensor reports | Filtered/aggregated at Edge; only semantic events reach Runtime |

Automation outcomes enrich the user profile but never pollute the live
conversation. Proactive results are delivered via a notification channel (a
separate "updates" stream in the Client), not injected into the chat thread.
Logical conflicts (automation vs. live intent) are resolved by querying Edge
device state before acting and by routing sensitive actions through one shared
HITL approval path.

Open question: scheduler/event entry point location (Agno `scheduler` module
vs. external component) — to be settled in the automation milestone.

## 4. Client Interface (AG-UI)

Runtime exposes the Master Team through Agno's AG-UI interface
(`AGUI(team=master)`); clients are AG-UI/CopilotKit compatible.

Visibility strategy (ADR 0004):

1. **Phase 1 (current)**: accept the framework's flattened stream — one
   assistant voice. Custom renderer for the `delegate_task_to_member` tool
   call surfaces "dispatched to <slave>" cards; HITL confirmation cards work
   out of the box.
2. **Phase 2**: custom AG-UI event mapping for per-Slave attribution (message
   `name`, `{member}:{tool}` prefixes, `CUSTOM` member-boundary events)
   enabling an expandable subtask UI.
3. **Phase 3**: migrate to protocol-native Subagent Events when
   `ag-ui-protocol` ships them and Agno adopts them.

## 5. Deployment Topology (ADR 0005)

**Principle: deployment location is a variable, not an architecture
decision.** Clients talk to Runtime only via AG-UI over HTTP(S) against a
configurable endpoint; the Web UI's proxy layer is separable from its static
frontend.

### MVP — single PC (current milestone)

Runtime (`localhost:7777`) and the independently served Web Client
(`localhost:3000`) run on the same home PC; the browser is on that PC too.
Cross-origin calls are handled by the Runtime's `CORS_ALLOWED_ORIGINS`
allowlist (a browser convenience, not a security boundary). No tunneling,
no remote access.

### Phase 1 — full home stack (remote access)

```
Owner devices (laptop, phone — Tailscale installed)
        │  tailnet (100.x addresses)
        ▼
Home Windows host:
  Web UI · Runtime (AgentOS) · PostgreSQL (Docker) · Edge
```

No cloud server, no public exposure, no port mapping. Privacy is maximal and
cost is zero.

### Phase 2 — cloud entry (when mini-program / public access / multi-user)

```
Any client ──HTTPS──> Cloud VPS: Web UI + auth + AG-UI proxy
                             │  overlay (Tailscale) or frp tunnel (outbound from home)
                             ▼
                      Home Runtime (never publicly exposed)
```

### Phase 3 — multi-tenant

Cloud backend becomes a registry + router: each home Runtime registers its
tunnel address on startup; the proxy routes by `user_id`.

### Client access paths

| Client | Phase 1 | Later |
|--------|---------|-------|
| Web | Tailscale to home | Cloud entry |
| Mobile app | Official Tailscale app (one-VPN-slot caveat) → embedded `tsnet` | Cloud entry |
| Mini-program | Not possible on tailnet | Cloud entry (requires public HTTPS + ICP filing) |

Operational notes (Windows host, Clash/Tailscale coexistence, service
auto-start, power settings) are recorded in ADR 0005.

## 6. Security Cross-Cutting

- **Sensitive operations** (e.g., door unlock) share one HITL path regardless
  of trigger (user or automation): member tool marked for confirmation → pause
  propagates to the team run → AgentOS `/approvals` or AG-UI resume →
  `continue_run`.
- **Runtime ↔ Edge** traffic is authenticated and encrypted; Runtime never
  manipulates hardware directly.
- **Runtime exposure**: Phase 1 binds to the tailnet only; Phase 2 adds
  service credentials between the cloud proxy and Runtime (AgentOS RBAC).
- **Tool-level permissions** ("which agent may invoke which tool") are a
  Runtime-owned policy layer (see 2.3) — a pending implementation item.

## 7. Current Implementation State

Implemented (v0.2.0–v0.2.1): single Team Leader agent stub, `OpenAILike` model
configuration (verified against Kimi Code API), PostgreSQL session/history
persistence, `CalculatorTools` + `ShellTools`, AgentOS with AG-UI interface,
dockerized dev database.

Not yet implemented: Slave Agents, long-term memory (Mem0/Hindsight),
knowledge base/RAG, tool ACL, automation/scheduler, Edge proxy, notification
channel, deployment tooling.

## 8. References

- [`AGENTS.md`](../AGENTS.md) — project background, scope, conventions
- [`adr/`](adr/README.md) — decision records 0001–0005
- [`plan/`](plan/) — milestone plans
- Agno docs: https://docs.agno.com/ · AG-UI: https://docs.ag-ui.com/
