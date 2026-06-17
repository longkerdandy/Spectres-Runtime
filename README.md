# Spectres Runtime

[![CI](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/codeql.yml/badge.svg)](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/codeql.yml)

Agent core runtime for the Spectres AI personal assistant system.

## Overview

Spectres Runtime is the middle layer that hosts AI agents, orchestrates tasks, manages memory and knowledge, and proxies device commands to the Edge layer. This repository focuses on the runtime only; the Client UI and Edge Gateway are separate subprojects.

## Prerequisites

- Python 3.13.x
- [uv](https://docs.astral.sh/uv/) package manager
- VSCode (recommended, settings are provided)

## Local Setup

Install the project with development dependencies:

```bash
uv sync
```

Install Git hooks so quality checks run automatically on every commit:

```bash
uv run pre-commit install
```

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
├── src/spectres/       # Application source code (to be implemented)
├── tests/              # Test suite
├── pyproject.toml      # Project metadata and tool configuration
├── uv.lock             # Locked dependency versions
├── LICENSE             # MIT license
└── README.md           # This file
```

## License

MIT
