# Spectres Runtime

[![CI](https://github.com/longkerdandy/Spectres-Runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/longkerdandy/Spectres-Runtime/actions/workflows/ci.yml)
[![CodeQL](https://github.com/longkerdandy/Spectres-Runtime/actions/workflows/codeql.yml/badge.svg)](https://github.com/longkerdandy/Spectres-Runtime/actions/workflows/codeql.yml)

Agent core runtime for the Spectres AI personal assistant system.

## Overview

Spectres Runtime is the middle layer that hosts AI agents, orchestrates tasks, manages memory and knowledge, and proxies device commands to the Edge layer. This repository focuses on the runtime only; the Client UI and Edge Gateway are separate subprojects.

## Prerequisites

- Python 3.13.x
- [uv](https://docs.astral.sh/uv/) package manager
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for local PostgreSQL)
- VSCode (recommended, settings are provided)

## Local Setup

Install the project with development dependencies:

```bash
uv sync --extra dev
```

Install Git hooks so quality checks run automatically on every commit:

```bash
uv run pre-commit install
```

### Start the local database

Spectres Runtime uses PostgreSQL with the pgvector extension for session and chat-history storage. Start it in Docker Desktop:

```bash
cp .env.example .env
# Optionally edit .env to change database credentials.
docker compose up -d
```

The PostgreSQL server will be available at `localhost:5532` by default, with both `spectres_runtime` and `spectres_runtime_test` databases created and the `pgvector` extension installed.

### Reset the local database

To drop and recreate the development database (configured in `.env`) and reinstall the pgvector extension:

```bash
uv run python scripts/reset_db.py
```

Use `--force` to skip the confirmation prompt:

```bash
uv run python scripts/reset_db.py --force
```

## Run AgentOS

`v0.2.1` exposes the Team Leader Agent through the AG-UI protocol. Start the server with:

```bash
docker compose up -d              # Start PostgreSQL if you need persistent sessions
uv run python -m spectres.main    # Or: uv run python src/spectres/main.py
```

By default AgentOS listens on `http://localhost:7777`. Override the bind address or port with `AGENT_OS_HOST` and `AGENT_OS_PORT` in `.env`.

### Manual AG-UI test

With the server running, verify the endpoints with `curl`:

```bash
# Health / status check
curl http://localhost:7777/status

# AG-UI streaming run (requires a configured LLM in .env)
curl -N -X POST http://localhost:7777/agui \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "test-thread",
    "run_id": "test-run",
    "state": {},
    "messages": [{"id": "msg-1", "role": "user", "content": "你好"}],
    "tools": [],
    "context": [],
    "forwarded_props": {}
  }'
```

The `/agui` endpoint returns a streaming `text/event-stream` response containing AG-UI events such as `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, and `RUN_FINISHED`.

## Development Commands

All quality checks and tests are run directly through `uv run` (no Makefile required):

```bash
uv run pytest                      # Run tests
uv run ruff check src tests scripts        # Run linter
uv run ruff format src tests scripts       # Format code
uv run ruff format --check src tests scripts  # Check formatting without modifying files
uv run mypy src tests scripts              # Run type checker
uv run ruff check src tests scripts && \
  uv run ruff format --check src tests scripts && \
  uv run mypy src tests scripts && \
  uv run pytest                    # Run all quality checks

# Run pre-commit hooks manually against all files
uv run pre-commit run --all-files
```

### Test environment

Tests use the committed `.env.test` file instead of your local `.env`. This keeps CI stable and configures the test suite to use GitHub Models rather than your production LLM.

By default, `uv run pytest` runs only fast unit tests. Integration tests that require external services are excluded unless explicitly selected:

```bash
uv run pytest                       # Run unit tests only
uv run pytest -m integration        # Run integration tests only
uv run pytest -m ''                 # Run all tests
uv run pytest -m db                 # Run database integration tests
uv run pytest -m llm                # Run real-LLM integration tests
```

The committed `.env.test` contains only non-sensitive configuration. Sensitive credentials for integration tests are provided differently in local development and CI:

**Local development**

Create the gitignored `.env.test.local` file next to `.env.test`:

```bash
# .env.test.local (do not commit)
DB_USER=ai
DB_PASS=ai
TEAM_LEADER_LLM_API_KEY=ghp_xxxxxxxxxxxxxxxxxxxx
```

`tests/conftest.py` loads `.env.test.local` automatically when pytest runs.

**GitHub Actions**

The `.github/workflows/integration.yml` workflow reads sensitive values from repository secrets:

- `DB_USER`
- `DB_PASS`
- `TEAM_LEADER_LLM_API_KEY`

Set these under Settings → Secrets and variables → Actions.

If you need to point tests at a different environment file:

```bash
SPECTRES_ENV_FILE=.env.custom uv run pytest
```

## VSCode

Open the project in VSCode. The repository includes recommended extensions and workspace settings. When prompted, install the recommended extensions for Python, Ruff, and MyPy.

## Security

- CodeQL analysis runs on every push and pull request to `main`.
- Dependency Review scans pull requests for vulnerable dependencies.
- Dependabot monitors Python and GitHub Actions dependencies.

## Project Structure

```
.
├── .github/            # GitHub Actions, Dependabot, and security workflows
├── .vscode/            # VSCode settings and recommended extensions
├── .editorconfig       # Editor configuration for consistent coding style
├── docs/               # Plans and documentation
├── src/spectres/       # Application source code
│   ├── agents/         # Agent definitions
│   ├── db/             # Database adapters
│   ├── sessions/       # Session management
│   ├── tools/          # Tool registrations
│   ├── config.py       # Typed application settings
│   └── main.py         # AgentOS entry point stub
├── tests/              # Test suite
├── docker-compose.yml  # Local PostgreSQL service (Docker Desktop)
├── pyproject.toml      # Project metadata and tool configuration
├── uv.lock             # Locked dependency versions
├── LICENSE             # MIT license
└── README.md           # This file
```

## Current Status

`v0.2.1` adds AG-UI protocol support to the `v0.2.0` skeleton, exposing the Team Leader Agent through a streaming `/agui` endpoint. Memory and knowledge-base features are planned for later milestones.

## License

MIT
