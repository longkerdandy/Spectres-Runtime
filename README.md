# Spectres Runtime

[![CI](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/codeql.yml/badge.svg)](https://github.com/Spectres-Runtime/Spectres-Runtime/actions/workflows/codeql.yml)

Agent core runtime for the Spectres AI personal assistant system.

## Overview

Spectres Runtime is the middle layer that hosts AI agents, orchestrates tasks, manages memory and knowledge, and proxies device commands to the Edge layer. This repository focuses on the runtime only; the Client UI and Edge Gateway are separate subprojects.

## Prerequisites

- Python 3.13.x
- `make` (optional, for convenience commands)
- VSCode (recommended, settings are provided)

## Local Setup

Create and activate a Python 3.13 virtual environment, then install the package with development dependencies:

```bash
make install-dev
```

Or manually:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

## Development Commands

```bash
make test          # Run tests
make lint          # Run linter
make format        # Format code
make format-check  # Check formatting without modifying files
make typecheck     # Run type checker
make check         # Run lint, format-check, typecheck, and tests
make clean         # Remove build artifacts and virtual environment
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
├── docs/               # Plans and documentation
├── src/spectres/       # Application source code (to be implemented)
├── tests/              # Test suite
├── Makefile            # Development commands
├── pyproject.toml      # Project metadata and tool configuration
└── README.md           # This file
```

## License

MIT
