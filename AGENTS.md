# AGENTS.md — Spectres Runtime

> This document is for coding agents working on the project. It defines the project background, high-level architecture, module boundaries, and the scope of the current subproject: Runtime.
>
> Last updated: 2026-06-17

---

## 1. Project Background

**Spectres** is an AI personal assistant system. Users interact with one or more AI agents through natural language to complete daily tasks, retrieve information, control devices, and automate routines.

- **Core concept**: A **Master Agent** serves as the user-facing entry point. It understands user intent, decomposes tasks, delegates to **Slave Agents** (specialists), and returns a unified result to the user.
- **Long-term user profiles**: A key goal is to build rich, persistent user profiles that evolve over time. Runtime integrates third-party memory systems to capture preferences, habits, and personal context beyond a single session.
- **Foundation**: Built on the [Agno](https://docs.agno.com/) platform. Agno provides the agent lifecycle, tool invocation, memory, knowledge, multi-agent teams, and monitoring primitives. Runtime is expected to run on **Agno AgentOS**.
- **Product surface**: Users interact through the **Client** layer (Web / Mobile App). The Runtime delegates physical-device control to the **Edge** layer.

---

## 2. High-Level Architecture

The system is split into three layers:

```
┌─────────────────────────────────────────────────────────────┐
│                         Client Layer                        │
│   User-facing UI: Web App, Mobile App, mini-program, etc.   │
│   Responsibilities: conversation UI, user input, status     │
│   display, voice/text interaction.                          │
└─────────────────────────┬───────────────────────────────────┘
                          │  AG-UI protocol
┌─────────────────────────▼───────────────────────────────────┐
│                        Runtime Layer                        │
│   Agent core runtime (this repository: Spectres-Runtime)    │
│   Responsibilities: agent orchestration, tool dispatch,     │
│   memory management, context handling, security policy.     │
└─────────────────────────┬───────────────────────────────────┘
                          │  secure channel to Edge Gateway
┌─────────────────────────▼───────────────────────────────────┐
│                          Edge Layer                         │
│   Home LAN gateway / service connecting to physical devices │
│   Responsibilities: protocol translation, device discovery, │
│   command forwarding, state reporting, local execution.     │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Layer Responsibilities

| Layer | Main Responsibilities | Deployment Target |
|-------|----------------------|-------------------|
| **Client** | User interface, front-end authentication, conversation rendering, message display. | Browser / mobile / desktop. |
| **Runtime** | Agent orchestration, tool invocation, memory persistence, context management, access control. | Cloud or local server / edge host. |
| **Edge** | LAN device discovery, protocol adaptation for smart-home devices, command delivery, offline caching. | Home gateway / edge device. |

### 2.2 Master-Slave Agent Model

- **Master Agent**: The entry point for every user session. It interprets intent, decides whether to handle a request itself, and selects Slave Agents when needed.
- **Slave Agents (Specialists)**: Focused agents for specific domains. Examples:
  - `home-device-agent`: controls lights, AC, curtains, and other home devices.
  - `calendar-agent`: schedules and queries events.
  - `weather-agent`: weather lookup and travel advice.
  - `knowledge-agent`: answers questions based on the knowledge base.
- Slave Agents are invoked by the Master Agent through Agno's built-in mechanisms or a thin custom dispatcher.

---

## 3. Runtime Scope

This repository implements the Runtime layer.

### 3.1 Core Capabilities

1. **Agent Runtime**
   - Create, load, and destroy Agno agent instances.
   - Manage the lifecycle of the Master Agent and registered Slave Agents.
   - Support streaming and non-streaming responses.
   - Remain model-agnostic: switch between online model providers without changing core agent logic.

2. **Task Orchestration**
   - Route user requests to the Master Agent.
   - Let the Master Agent decide whether to respond directly, call one Slave Agent, or call multiple agents in parallel.
   - Leverage Agno's multi-agent team and workflow primitives where they fit; keep a thin custom dispatcher only when needed.
   - Support synchronous, asynchronous, parallel, and fallback invocation patterns as the project evolves.

3. **Tool Registry**
   - Maintain a central registry of tools available to agents.
   - Provide common built-in tools such as HTTP calls, time utilities, and structured data access.
   - Use Agno's tool integration patterns and standard connection mechanisms where appropriate.
   - Device-control tools proxy commands to the Edge layer. Runtime never manipulates hardware directly.

4. **Memory and Context**
   - Short-term memory: current-session context window management.
   - Long-term memory: user preferences, conversation summaries, and entity memory.
   - Integrate third-party memory systems such as **Mem0** or **Hindsight** to build complex, long-term user profiles.
   - Use Agno's Memory / Storage abstractions; allow the backing store to be swapped for pluggable storage backends to avoid vendor lock-in.

5. **Knowledge Base**
   - Document ingestion, embedding, and retrieval (RAG).
   - Per-agent knowledge isolation where applicable.

6. **Security and Permissions**
   - Tool-level permissions: restrict which agents can invoke which tools.
   - User-level isolation: a user can access only their own memory and data.
   - Sensitive operations (e.g., unlocking doors) require explicit human-in-the-loop confirmation.
   - All calls to the Edge layer must be authenticated and use an encrypted channel.

7. **Client API**
   - Expose endpoints for the Client layer using the **AG-UI protocol**.
   - Session management: create, continue, list, and archive sessions.
   - Unified message format supporting text, images, voice, and structured action cards.

8. **Edge Gateway Proxy**
   - Forward device commands to the Edge Gateway instead of directly accessing LAN devices.
   - Use a unified device description model to hide brand/protocol differences.
   - Receive device-state updates from Edge and keep relevant agents in sync.

### 3.2 Explicitly Out of Scope

The following belong to other subprojects or services. Runtime uses them through well-defined interfaces only:

- **Client UI rendering**: handled by the Client layer.
- **Device protocol translation**: handled by the Edge layer.
- **Model training / fine-tuning**: Runtime consumes LLM APIs, but does not train models.

---

## 4. Development Guidelines

- **Language**: Python; use type annotations wherever practical.
- **Framework**: Prefer Agno's Agent, Tool, Memory, Storage, Team, and Workflow abstractions rather than rebuilding equivalent primitives.
- **Configuration**: Manage configuration through environment variables and a typed configuration library. Secrets must not be committed.
- **Testing**: New functionality requires unit tests; changes to agent orchestration require integration tests.
- **Monitoring**: Use Agno's monitoring and evaluation hooks where available to track agent performance and quality.
- **Logging**: Use structured logging. Tool invocations, Edge commands, and permission checks must be auditable.
- **API Stability**: Expose versioned APIs to the Client and Edge layers.

---

## 5. Confirmed Decisions

The following decisions are confirmed by the project owner:

1. **Deployment**: Runtime must support both **local** and **cloud** deployment.
2. **Multi-tenancy**: The architecture must support **multi-tenant** usage, but the first implementation targets a **single-user** scenario.
3. **LLM**: Use **online model APIs** rather than local inference or self-hosted models.
4. **Long-term memory**: Integrate third-party memory systems (e.g., **Mem0**, **Hindsight**) to support complex and persistent user profiles.

---

## 6. Agent Conventions

Behavior expectations for coding agents working on this project:

- **Language for code and docs**: Write all code comments, documentation, and commit messages in **English**.
- **Language for user conversation**: When interacting with the project owner, respond in **Chinese**.
- **Version control**: Do **not** run `git commit`, `git push`, `git reset`, `git rebase`, or any other git mutation without explicit user permission. Ask for confirmation each time.
- **Commit messages**: See Section 7 for detailed conventions.

---

## 7. Commit Message Conventions

All commit messages must be written in **English** and follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.

### 7.1 Format

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### 7.2 Common Types

| Type | Use when |
|------|----------|
| `feat` | Adding a new feature |
| `fix` | Fixing a bug |
| `docs` | Changing documentation only |
| `style` | Formatting, semicolons, etc.; no code logic change |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Improving performance |
| `test` | Adding or correcting tests |
| `chore` | Build process, tooling, dependency updates, etc. |
| `ci` | CI/CD configuration changes |

### 7.3 Description Rules

- Use the imperative mood and present tense (e.g., `add`, `fix`, `update`).
- Start with a lowercase letter.
- Do not end with a period.
- Keep the subject line within 50 characters when possible.

### 7.4 Body and Footer

- **Body** (optional): explain the **why** and **what**, wrapped at 72 characters.
- **Footer** (optional): reference issues (`Fixes #123`) or describe breaking changes (`BREAKING CHANGE: ...`).

### 7.5 Examples

```text
feat(ci): add GitHub Actions workflow for lint and test

Run ruff, mypy, and pytest on every push and pull request to main.
```

```text
docs(readme): update setup instructions for python 3.13
```

---

## 8. References

- Agno documentation: https://docs.agno.com/
- Agno LLMs reference: https://www.agno.com/llms.txt
- Repository: current directory `Spectres-Runtime`
