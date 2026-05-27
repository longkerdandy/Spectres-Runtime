# Spectres Runtime

The Runtime layer is the core of the Spectres personal assistant system. It is built on top of [Agno](https://agno.com) and is responsible for agent orchestration, memory, and user profile management.

> **Status: design stage.** Architectural direction below is settled. Technical specifics (concrete classes, table schemas, deployment topology, etc.) are intentionally left open and will be decided during implementation.

## Positioning

- Logically a three-tier system: **UI / Gateway / Runtime**. The Runtime is the lowest tier.
- In practice, the Runtime is realized as an **[AgentOS](https://docs.agno.com/agent-os/introduction) instance**. AgentOS is a FastAPI service that already provides:
  - REST + SSE endpoints for running agents, teams, and workflows
  - Session, memory, knowledge, and tracing persistence
  - JWT-based authentication and RBAC
  - Built-in interfaces (Slack / Telegram / WhatsApp / A2A / AG-UI)
  - Multi-framework support (native Agno SDK plus Claude Agent SDK, LangGraph, DSPy)
- The Gateway tier may collapse into AgentOS middleware (JWT validation + parameter injection) unless a separate API gateway becomes necessary for cross-cutting concerns (rate limiting, multi-tenant routing, non-Agno endpoints).
- Business state is persistent (in databases). Runtime processes themselves stay stateless so they can be replicated. The one documented exception is background-run resume (`/resume`), which currently requires sticky routing by `run_id`.
- Inside the Runtime, `user_id` is treated as trusted; authentication happens at the AgentOS middleware boundary.

## Agent Model

- Each agent is defined as a Python class / construction in code (`Agent(model=..., tools=..., instructions=..., db=..., knowledge=...)`), **not by free-form prompting alone**.
- Agents are peers. They compose through:
  - **Team** for runtime collaboration. Agno provides explicit `TeamMode` values: `route`, `coordinate`, `collaborate`, `broadcast`, `tasks`.
  - **Tool registration**: any agent (or sub-team) can be exposed as a tool to another agent for lateral invocation.
  - **Workflow** for deterministic, step-based pipelines where the same sequence must run every time.
- The user-to-agent relationship is 1:N. A single user can hold multiple concurrent conversations with different agents.
- Per-request agent construction (when membership, instructions, or model must depend on the caller) goes through Agno's `AgentFactory` / `TeamFactory` / `WorkflowFactory` rather than a hand-rolled registry.

## Multi-User Isolation

- All session / memory / profile data is scoped by `user_id`.
- `user_id` (and `session_id`) are extracted from the JWT `sub` claim (and a configured session claim) by Agno's JWT middleware and injected automatically into endpoints and agent runs. Verified middleware values take precedence over any value sent in the request body.
- An agent run operates only within the context of a single `user_id` for the duration of the run.

## Memory & Profile

Agno splits long-term per-user state into two stores; Spectres adopts both:

| Store | Shape | Purpose |
|---|---|---|
| **User Profile Store** | Structured (name, preferred name, custom dataclass fields) | Stable identity and preferences. Maintained in `always` or `agentic` mode. |
| **User Memory Store** | Unstructured observations | Preferences, behaviors, and context that don't fit a fixed schema. Long-lived, optionally curated. |
| **Session history** | Per `session_id` message log | "What did we just discuss?" — distinct from memory. |

Additional stores Agno exposes (Session Context, Entity Memory, Learned Knowledge, Decision Log) are candidates for later phases; they are not adopted yet.

## Knowledge / RAG

- Knowledge bases are first-class in Agno: `Knowledge(vector_db=...)` attached to an agent via `knowledge=...`.
- Postgres + `pgvector` is the default target. Hybrid (vector + lexical) search is supported.
- RAG style (traditional auto-injection vs. agentic search-as-tool) is per-agent and undecided at this stage.

## Storage

| Storage | Purpose | Status |
|---|---|---|
| Postgres + pgvector | Sessions, messages, user profile, user memory, knowledge vectors, traces | Default direction |
| Redis | Short-term caches, future async queues | Optional, may be deferred |
| Object Store | Attachments and media | Required only when media flows are implemented |

Agno also supports SQLite / MySQL / MongoDB / DynamoDB / Firestore / SurrealDB / Singlestore / Supabase / Neon / GCS-JSON / in-memory backends. Provider choice can be revisited per environment without changing agent code.

## Observability and Governance

- **Tracing** is provided by AgentOS and stored in the same database (no third-party egress).
- **Hooks** (pre / post, per-hook or global) provide the extension point previously labeled "Event Publisher". They can run inline or as FastAPI background tasks.
- **Approvals / Human-in-the-loop** are built into AgentOS (including over Slack), available for tool calls and team runs.

## Open Questions (to resolve during implementation)

- Whether to keep a separate Gateway process or rely solely on AgentOS middleware.
- Concrete user-profile schema (custom dataclass fields).
- Memory maintenance mode: `always` extraction vs. `agentic` updates vs. a hybrid policy.
- Default RAG strategy per agent (traditional vs. agentic).
- Event surface: does Spectres need an external event bus, or are Agno hooks + tracing sufficient?
- Deployment target (Docker / Railway / AWS ECS / other) and how `/resume` sticky routing is handled.
- How agents are registered (static list passed to `AgentOS(agents=[...])` vs. per-request `AgentFactory`).
- Whether to expose the runtime over MCP (`enable_mcp_server=True`) for third-party agent clients.

## Agno Documentation References

Three resources are wired in for use by both humans and coding agents working on this repository:

- **MCP server (preferred for AI coding agents)**: `https://docs.agno.com/mcp`
  Pre-configured for opencode in `.opencode/opencode.json` under the `agno-docs` server. Restart opencode after cloning so the MCP tools become available.
- **Docs index (`llms.txt`)**: `https://docs.agno.com/llms.txt`
  A compact, link-rich table of contents listing every documentation page with a one-line description. Useful for targeted lookups when MCP is unavailable.
- **Full docs (`llms-full.txt`)**: `https://docs.agno.com/llms-full.txt`
  Concatenated full content of every page (~10 MB). Avoid loading wholesale into an LLM context; prefer the MCP server or per-page `.md` URLs derived from the index.
