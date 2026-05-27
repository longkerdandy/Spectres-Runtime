# Spectres Runtime

The Runtime layer is the core of the Spectres personal assistant system. Built on the Agno framework, it is responsible for agent orchestration, memory management, and user profile maintenance.

## Positioning

- The system follows a three-tier architecture: UI / Gateway / Runtime. This layer is the lowest tier.
- The business is stateful (persisted in databases), but Runtime instances themselves remain stateless to enable horizontal scaling.
- Within Runtime, `user_id` is trusted; authentication is handled by the Gateway.

## Submodules

| Submodule | Responsibility |
|---|---|
| Session Manager | Manages sessions scoped by `(user_id, conversation_id)` |
| Agent Registry | Maintains all agents defined as Python classes |
| AgentFactory | Instantiates agents on demand, injecting user context |
| Team Orchestrator | Orchestrates multi-agent collaboration via Agno `Team` (route / coordinate / collaborate) |
| Tool Registry | Registers built-in tools and MCP tools |
| Memory Service | Short-term conversational memory + long-term semantic memory; all reads/writes require `user_id` |
| Profile Service | Incremental maintenance of user profiles |
| LLM Provider Pool | Unified LLM invocation with multi-provider routing and retries |
| Event Publisher | Publishes events to the Event Bus interface at key checkpoints |

## Agent Model

- Each agent is defined as a Python class in code, **not relying on pure prompts**.
- Agents are peers; they can be orchestrated via Teams or registered as tools for one another to achieve lateral invocation.
- The user-to-agent relationship is 1:N; a single user can converse with multiple agents simultaneously.
- When instantiated, an agent is injected with the Memory and Profile context corresponding to the current `user_id`.

## Multi-User Isolation

- All Session / Memory / Profile data is isolated by `user_id`.
- All interfaces of Memory Service and Profile Service mandatorily require a `user_id` parameter.
- An agent instance operates only within the context of a single user.

## Communication Contracts

### Interfaces Exposed to the Gateway (Python abstractions; in-process initially)

```
class RuntimeAPI:
    async def chat_stream(user_id, conversation_id, message, agent_hint=None)
        -> AsyncIterator[Event]
    async def list_agents(user_id) -> List[AgentMeta]
    async def list_sessions(user_id) -> List[SessionMeta]
    async def get_memory(user_id, query=None) -> List[MemoryItem]
    async def get_profile(user_id) -> UserProfile
```

### Events Published to the Event Bus

```
conversation.started    {user_id, conversation_id, agent_id}
conversation.message    {user_id, conversation_id, role, content}
conversation.ended      {user_id, conversation_id}
agent.tool_called       {user_id, tool, args, result}
agent.proactive_msg     {user_id, content}
```

During the MVP phase, subscribers may be no-op implementations; the event interface is reserved in advance.

## Storage

| Storage | Purpose |
|---|---|
| Postgres + pgvector | Users, sessions, messages, long-term memory vectors, user profiles |
| Redis | Session window cache, future asynchronous queues |
| Object Store | Attachments and media files |

## Extension Points (Reserved in Architecture, Not Implemented in MVP)

- **Evolution Worker**: Subscribes to events such as `conversation.ended` to perform memory extraction, profile updates, and skill consolidation.
- **Memory Service write interface** reserves a `source` field (`manual` / `auto`) for future automated writes.
- **Profile Service** reserves the incremental interface `merge_profile(user_id, partial_traits)`.
