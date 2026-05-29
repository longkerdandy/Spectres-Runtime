# Spectres Runtime

The Runtime layer is the core of the Spectres personal assistant system. It is built on top of [Agno](https://agno.com) and is responsible for agent orchestration, conversation state, long-term memory, knowledge, and the secure exposure of agent capabilities to client applications.

**Status:** design stage. High-level architecture is settled; concrete schemas, protocols, and deployment specifics are deferred to implementation.

**Scope:** this repository contains **only the Runtime tier**. The Client and Edge tiers live in separate repositories and are described below only to give Runtime design choices their context.

## System Overview

Spectres is a personal assistant for a single household with multiple users. The system is logically structured into three tiers:

| Tier | Responsibility | Where it runs |
|---|---|---|
| **Client** | Human-facing interfaces (web, mobile, CLI). Initiates conversations; some clients (e.g. a phone) also expose capabilities back to the Runtime (location, push, sensors). | User devices |
| **Runtime** | Agents, conversation state, memory, profile, knowledge, authentication, tool orchestration. All user data is persisted here. | Cloud |
| **Edge** | Bridges the Runtime to physical-world resources unreachable from the public internet (Home Assistant, NAS, LAN-only services, IoT). Split into `edge-cloud` (cloud-side companion to the Runtime) and `edge-local` (runs in the household). | Cloud + household |

All client traffic flows through the Runtime; clients never bypass it to talk directly to the Edge.

## Runtime Architecture

The Runtime is realized as a single **[AgentOS](https://docs.agno.com/agent-os/introduction) instance** — Agno's open-source (Apache-2.0) FastAPI container that provides the HTTP/SSE surface, JWT auth + RBAC, session/memory/knowledge/tracing persistence, per-request agent factories, hooks, and human-in-the-loop flows out of the box. Spectres extends it via custom routes, middleware, hooks, and factories.

### Runtime characteristics

- **Stateless processes, stateful data.** Business state lives in the database; the Runtime process is replicable. The one documented exception is background-run resume (`/resume`), which requires sticky routing by `run_id`.
- **Cloud-resident user data.** All session / memory / profile / knowledge / tracing data lives in the Runtime's database. Clients and Edge hold no authoritative copies.
- **Network layer is out of scope.** TLS termination, WAF, DDoS protection, and reverse proxying belong to the deployment edge (CDN / load balancer / reverse proxy), not the Runtime process.

## Agent Model

- Each agent is a **structured, declarative object** with explicit fields: `model`, `tools`, `instructions`, `db`, `knowledge`, etc. Agents are **not defined by free-form prompting alone** — every agent has a typed surface that can be inspected, versioned, and reasoned about.
- **Construction style is open.** Agno supports several and Spectres can mix them:
  - **Static construction in Python** — `Agent(...)` at module load, passed to `AgentOS(agents=[...])`. Simplest; suitable for built-in system agents.
  - **AgentFactory / TeamFactory / WorkflowFactory** — a callable invoked per request with `RequestContext`, producing a fresh agent whose tools / instructions / model / db can depend on the caller. Suitable when the agent must vary by user or context.
  - **Directory- or config-driven** — `from_agent_directory`, the Registry, or AgentOS Studio for composing agents from registered components without a code deploy. Suitable for user-customizable assistants.
  - The produced object is the same structured `Agent` in all cases; only the construction path differs.
- Agents are peers. They compose through:
  - **Team** for runtime collaboration. Agno provides `TeamMode` values: `route`, `coordinate`, `collaborate`, `broadcast`, `tasks`.
  - **Tool registration**: any agent (or sub-team) can be exposed as a tool to another agent for lateral invocation.
  - **Workflow** for deterministic, step-based pipelines.
- A single user can hold multiple concurrent conversations with different agents.

## Multi-User, Single-Household

Spectres targets one household with multiple users. There is **no multi-tenant / multi-household isolation**; the data model only distinguishes users and their permissions.

- All session / memory / profile data is scoped by `user_id`.
- Authentication is **self-hosted**: Spectres issues its own accounts and signs its own JWTs.
- `user_id` (and `session_id`) are extracted from the JWT by AgentOS's JWT middleware and injected automatically into endpoints and agent runs. Verified middleware values take precedence over request-body values.
- Past the middleware boundary, `user_id` is treated as trusted.
- An agent run operates within the context of a single `user_id` for its duration.
- RBAC differentiates user permissions within the household; concrete roles deferred.

## Client Integration

Clients (web, mobile, CLI) talk to the Runtime over its authenticated HTTP/SSE surface.

- **No bypass.** All client interactions go through the Runtime, even on the local network. This keeps conversation, memory, and audit trail consistent across paths.
- **Multi-device sessions.** A user can be active on multiple clients simultaneously; continuity comes from the Runtime's session store.
- **Clients may expose capabilities back to the Runtime.** A mobile client can offer location, push, sensors, or on-device actions as tools the Runtime's agents can invoke — the phone then behaves as a "client-side Edge". Protocol deferred (candidates: AG-UI, MCP, webhook + push).

## Edge Integration

The Edge tier exists because the cloud Runtime cannot directly reach household-local resources behind residential NAT. It splits into:

- **edge-cloud** — Spectres-owned process in the cloud, separate from the Runtime, acting as the cloud-side endpoint the Runtime calls whenever an agent needs household resources.
- **edge-local** — Spectres-owned process inside the household, with LAN access to Home Assistant, NAS, and other on-premise services.

**Settled:**

- **edge-local can push events to the Runtime**, not just respond to requests. Physical-world signals (door unlock, sensor threshold, package arrival) must be able to trigger Runtime agents and workflows. Exact event surface deferred (webhook / MQTT / AgentOS Hook / Workflow trigger).
- **edge-cloud and Runtime are separate processes.** Different release cadences, failure domains, scaling characteristics. Coupling them is rejected.

**Deferred:**

- Protocol between edge-cloud and edge-local (MQTT / WebSocket reverse tunnel / managed overlay).
- edge-cloud thickness: thin reverse-tunnel termination vs. richer device-abstraction layer. Default leaning is **thin**, delegating device abstraction to Home Assistant.
- Tool surface shape: single generic device tool vs. per-domain tools (`home_assistant.*`, `nas.*`).

## Memory & Profile

Agno splits long-term per-user state into two stores; Spectres adopts both:

| Store | Shape | Purpose |
|---|---|---|
| **User Profile Store** | Structured (name, preferred name, custom dataclass fields) | Stable identity and preferences. Maintained in `always` or `agentic` mode. |
| **User Memory Store** | Unstructured observations | Preferences, behaviors, context that don't fit a fixed schema. Long-lived, optionally curated. |
| **Session history** | Per `session_id` message log | "What did we just discuss?" — distinct from memory. |

## Knowledge / RAG

- Knowledge bases are first-class in Agno: `Knowledge(vector_db=...)` attached to an agent via `knowledge=...`.
- Postgres + `pgvector` is the default target.
- RAG style (traditional auto-injection vs. agentic search-as-tool) is per-agent and deferred.

## Storage

| Storage | Purpose |
|---|---|
| Postgres + pgvector | Sessions, messages, user profile, user memory, knowledge vectors, traces — single source of truth for all persistent Runtime state. |
| Object Store | Attachments and media. Required once media flows are implemented; provider deferred (S3-compatible). |

Additional infrastructure (cache, message broker, task queue) is not adopted up-front; introduced only when a concrete need appears.

## Models

- The Runtime is **model-agnostic**. Agents declare their model in code; swapping providers is configuration, not architecture.
- Current leaning: **domestic (China-based) providers** — DeepSeek / Zhipu / Qwen / Moonshot — to keep inference in-region with the Runtime, reduce cost, and avoid cross-border reliability issues.
- Mixing providers per agent (stronger model for reasoning, cheaper one for simple tasks) is expected.

## Observability and Governance

- **Tracing** is provided by AgentOS and stored in the same database (no third-party egress).
- **Hooks** (pre/post, per-hook or global) extend cross-cutting concerns: auditing, redaction, custom event publication. Inline or as FastAPI background tasks.
- **Approvals / Human-in-the-loop** are built into AgentOS for tool calls and team runs.
- **Agno Control Plane (`os.agno.com`)** may be used in development (free); not used in production (paid + cross-border).

## Deployment

The Runtime is containerized and intended for deployment to a Chinese public cloud, with cost as the primary selection criterion. Specific provider deferred. During development the Runtime may run on a local PC, exposed via a tunnel (Cloudflare Tunnel, ngrok, etc.) when multi-device testing is needed.

## Open Questions

To be resolved during implementation.

**Runtime**
- Concrete user-profile schema (custom dataclass fields).
- Memory maintenance mode: `always` extraction vs. `agentic` updates vs. hybrid.
- Default RAG strategy per agent (traditional auto-injection vs. agentic search-as-tool).
- Agent construction split: static Python / `AgentFactory` / directory-driven — likely a mix.
- Event surface for Edge-originated and other asynchronous triggers: AgentOS Hooks, an external event bus, or both.
- Whether to expose the Runtime over MCP (`enable_mcp_server=True`).
- AgentOS anonymous telemetry: keep on or disable (`AGNO_TELEMETRY=false`).

**Edge**
- Protocol between edge-cloud and edge-local.
- edge-cloud thickness (thin vs. device abstraction).
- Tool surface shape exposed to agents.

**Client**
- Protocol for clients registering capabilities back to the Runtime.

**Deployment**
- Specific cloud provider, chosen after price comparison.
- How `/resume` sticky routing is handled in a replicated deployment.
- ICP registration when a public domain becomes required.
- Whether any auxiliary workloads (e.g. scheduled jobs) run on serverless.

## Agno Documentation References

For both humans and coding agents working on this repository:

- **MCP server** (preferred for AI coding agents): `https://docs.agno.com/mcp` — pre-configured for opencode in `.opencode/opencode.json` under the `agno-docs` server. Restart opencode after cloning.
- **Docs index** (`https://docs.agno.com/llms.txt`) — compact table of contents for targeted lookups when MCP is unavailable.
- **Full docs** (`https://docs.agno.com/llms-full.txt`, ~10 MB) — full content of every page. Do not load wholesale into an LLM context; prefer the MCP server or per-page `.md` URLs.

## Repository Conventions

Working conventions for anyone making changes to this repository —
commit-message format, branching, code style, and similar **how-to-work**
rules — live in [`CONTRIBUTING.md`](./CONTRIBUTING.md). **Coding
assistants (Claude Code, opencode, Cursor, etc.) working in this
repository must read `CONTRIBUTING.md` before making changes.**

The sections above this one describe *what the system builds* (Agno
agents, the Runtime services). `CONTRIBUTING.md` describes *how to work
on the codebase*. The word "agent" in this file refers to the former;
"contributor" or "coding assistant" refers to the latter.
