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

The database will be available at `localhost:5532` by default.

## Development Commands

All quality checks and tests are run directly through `uv run` (no Makefile required):

```bash
uv run pytest                      # Run tests
uv run ruff check src tests        # Run linter
uv run ruff format src tests       # Format code
uv run ruff format --check src tests  # Check formatting without modifying files
uv run mypy src tests              # Run type checker
uv run ruff check src tests && \
  uv run ruff format --check src tests && \
  uv run mypy src tests && \
  uv run pytest                    # Run all quality checks

# Run pre-commit hooks manually against all files
uv run pre-commit run --all-files
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

`v0.2.0` is a structural skeleton. It defines the Agno/AgentOS-based runtime structure, session storage, and a small set of built-in tools, but it is not yet a runnable server. Memory and knowledge-base features are planned for later milestones.

## License

MIT
