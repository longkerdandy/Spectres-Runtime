# Spectres Runtime

The Runtime layer is the core of the Spectres personal assistant system. Built on the Agno framework, it is responsible for agent orchestration, memory management, and user profile maintenance.

## Positioning

- The system follows a three-tier architecture: UI / Gateway / Runtime. This layer is the lowest tier.
- The business is stateful (persisted in databases), but Runtime instances themselves remain stateless to enable horizontal scaling.
- Within Runtime, `user_id` is trusted; authentication is handled by the Gateway.

## Agent Model

- Each agent is defined as a Python class in code, **not relying on pure prompts**.
- Agents are peers; they can be orchestrated via Teams or registered as tools for one another to achieve lateral invocation.
- The user-to-agent relationship is 1:N; a single user can converse with multiple agents simultaneously.
- When instantiated, an agent is injected with the Memory and Profile context corresponding to the current `user_id`.

## Multi-User Isolation

- All Session / Memory / Profile data is isolated by `user_id`.
- All interfaces of Memory Service and Profile Service mandatorily require a `user_id` parameter.
- An agent instance operates only within the context of a single user.

## Storage

| Storage | Purpose |
|---|---|
| Postgres + pgvector | Users, sessions, messages, long-term memory vectors, user profiles |
| Redis | Session window cache, future asynchronous queues |
| Object Store | Attachments and media files |

## Agno Documentation References

The Runtime is built on the [Agno](https://agno.com) framework. Two resources are wired in for use by both humans and coding agents working on this repository:

- **MCP server (preferred for AI coding agents)**: `https://docs.agno.com/mcp`
  Pre-configured for opencode in `.opencode/opencode.json` under the `agno-docs` server. Restart opencode after cloning so the MCP tools become available.
- **Docs index (`llms.txt`)**: `https://docs.agno.com/llms.txt`
  A compact, link-rich table of contents listing every documentation page with a one-line description. Useful for targeted lookups when MCP is unavailable.
- **Full docs (`llms-full.txt`)**: `https://docs.agno.com/llms-full.txt`
  Concatenated full content of every page (~10 MB). Avoid loading wholesale into an LLM context; prefer the MCP server or per-page `.md` URLs derived from the index.

