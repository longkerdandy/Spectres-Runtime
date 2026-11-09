# AGENTS.md — Spectres Runtime

> Guidance for coding agents. Last updated: 2026-11-09.

## 1. Project Context

Spectres Runtime is the middle layer of a personal AI assistant: it hosts agents, tools, memory, scheduled work, and extension APIs. The Client and Edge are separate projects.

- **Stack**: Python 3.13, Agno AgentOS, FastAPI, PostgreSQL, pydantic-settings, and `uv`.
- **Implemented**: one Team Leader agent exposed through AG-UI, built-in tools, JWT authentication and authorization, per-user isolation, structured logging, static extension loading with administrator-controlled global enablement, Agno Workflows, and native scheduled tasks. The first extension is ETF Grid Trading.
- **Not implemented**: Team/Slave orchestration, long-term memory, knowledge/RAG, tool ACL, judgment-based automation, notification delivery, and Edge proxying. Do not describe these as existing behavior.
- **Source of truth**: [`docs/architecture/`](docs/architecture/README.md) describes current behavior; [`docs/adr/`](docs/adr/README.md) records decisions; [`docs/plan/`](docs/plan/) tracks milestones. Update affected documentation when behavior changes.

## 2. Architectural Constraints

- Exactly one logical user-facing Master Agent per user. Channels and proactive runs must not create another Master. Proactive behavior uses isolated sessions or Workflows.
- Future Master/Slave orchestration uses Agno `Team` in `coordinate` mode. Do not add a custom orchestration dispatcher.
- Prefer Agno primitives over custom equivalents. In particular, use the AgentOS scheduler, native `/schedules` API, and extension Workflows; do not add a custom scheduler, Action abstraction, dispatch registry, or parallel schedule API.
- Conversation state is isolated by `session_id`; user-level data aggregates by `user_id`.
- Runtime never controls hardware directly. Device operations must go through the authenticated, encrypted Edge channel. Client UI rendering and model training are out of scope.
- Keep APIs versioned and preserve existing public contracts unless a breaking change is explicitly requested.

## 3. Security and Ownership

- Logto owns users, roles, and role assignments. JWT `sub` is the Runtime `user_id`; Agno-native JWT scopes authorize framework routes. `agent_os:admin` is the cross-user break-glass scope.
- `AgentOS(user_isolation=True)` does **not** isolate extension tables or custom business logic. Explicitly scope every private read and write.
- Derive ownership from verified request/run context (`request.state.user_id` or `RunContext.user_id`), never from LLM arguments, request payloads, or query parameters. Missing required identity must fail closed.
- Unowned schedules are system tasks, not user-shared schedules. Personal schedules are created through native CRUD, never seeded at startup.
- Sensitive operations require the shared human-confirmation path. Never commit secrets or log credentials/tokens.

## 4. Extension Rules

- Keep each capability under `src/spectres/extensions/<name>/`; core code must not import extension code.
- Implement the contract in `src/spectres/extensions/base.py`: each manifest has a stable snake_case `id`, a non-empty display `name` and `description`, and an idempotent `register()` that may contribute toolkits, routers, Workflows, and declarative system Schedules.
- Keep `toolkit.py`, `api.py`, and `workflows.py` as thin adapters. Put business logic in services and pure domain code in `core/`; `core/` must not import Agno, FastAPI, or SQLAlchemy.
- Extensions share the core PostgreSQL connection pool, use table names prefixed with the extension id, and must not access Agno-managed or other extensions' tables.
- Use snake_case for Python identifiers and UPPER_SNAKE for environment prefixes; use kebab-case under `/api/v1/extensions/`.
- Extension configuration belongs in the extension's settings fragment, not core `Settings`. Scheduled work must be idempotent. Startup must preserve existing stored Schedule configuration.
- Use `logging.getLogger(__name__)`; do not configure logging sinks in extensions. Log handled failures and sensitive-operation audit events without secrets.

## 5. Development Conventions

- Write code, comments, documentation, and commit messages in English. Respond to the project owner in Chinese.
- Follow existing naming and structural patterns. Add type annotations and use existing dependencies; confirm availability before introducing a library.
- New required configuration uses explicit environment variables without defaults unless truly necessary. Development loads `.env` then `.env.local`; tests load `.env.test` then `.env.test.local`. Local override files and credentials stay untracked.
- `.env.example` contains two complete, independent configuration sets with explicit start/end markers: the development set is copied verbatim to `.env`, and the test set to `.env.test`. Whenever configuration changes, update both complete sets rather than supplying only changed keys or partial snippets. Do not edit `.env`, `.env.test`, `.env.local`, or `.env.test.local`; the project owner copies the example sections and manages local overrides.
- Do not reference ADRs, plans, or other documents in code comments or docstrings.
- Add unit tests for new functionality and integration tests for agent-orchestration changes. Preserve authentication, ownership, and schedule-isolation coverage for related changes.
- Check for nested `AGENTS.md` files before working in subdirectories.
- Do not run Git mutations without explicit user permission; ask each time. When authorized, use English Conventional Commits with an imperative, lowercase subject.

## 6. Commands

Use `uv run` (or `.venv/bin/python` for direct Python invocation), not a global Python interpreter.

```bash
uv sync --extra dev
uv run pytest                       # Fast unit tests; integration tests are deselected
uv run pytest -m integration        # External-service integration tests
uv run pytest -m db                 # Real-PostgreSQL tests
uv run pytest -m llm                # Real-LLM tests
uv run pytest -m ''                 # All tests
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src tests scripts
uv run pre-commit run --all-files
```

Before finishing a code change, run the relevant tests and the standard quality checks: Ruff lint, Ruff format check, strict Mypy, and pytest. Exercise the affected API or runtime path when practical; do not claim unverified behavior works.

## 7. Key Files

- `src/spectres/main.py` — AgentOS assembly, authentication, AG-UI, extension mounting
- `src/spectres/config.py` — core typed settings
- `src/spectres/extensions/base.py` — extension contract
- `src/spectres/extensions/loader.py` — in-tree extension discovery and loading
- `src/spectres/extensions/state.py` — persistent global extension activation
- `src/spectres/extensions/activation.py` — REST, Toolkit, and Workflow activation guards
- `src/spectres/scheduler.py` — system-schedule registration
- `src/spectres/extensions/etf_grid/` — reference vertical-slice extension
- `tests/` — unit and integration coverage

## 8. Reference Projects
- Spectres Web Client — ..\Spectres-Web-Client
