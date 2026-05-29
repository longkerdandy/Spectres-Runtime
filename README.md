# Spectres Runtime

The Runtime tier of the Spectres personal assistant — agent orchestration,
memory, knowledge, and capability exposure built on Agno's AgentOS.

Architectural overview lives in [`Agents.md`](./Agents.md).
Contribution conventions (commit-message format, hook setup, branching)
live in [`CONTRIBUTING.md`](./CONTRIBUTING.md) — read it before opening
a PR.

> **Status: pre-alpha.** v0.1 ships only the engineering baseline; no agents,
> no database, no auth wiring yet.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) (≥ 0.11).

```bash
# 1. interpreter — uv will fetch a managed CPython 3.12 if needed
uv python install 3.12

# 2. install runtime + dev dependencies (lint, test, mypy, pre-commit)
uv sync

# 3. install git hooks (one-time per clone)
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg

# 4. smoke check
uv run pytest
uv run uvicorn spectres_runtime.app:app --reload
# → http://127.0.0.1:8000/healthz
```

## Common commands

```bash
uv run ruff check .                 # lint
uv run ruff format .                # format
uv run mypy                         # strict type check
uv run pytest                       # tests + coverage gate
uv run pre-commit run --all-files   # run every hook over the whole repo
```

## Layout

```
src/spectres_runtime/   application code (FastAPI app, agents — TBD)
tests/                  pytest suite
docs/                   project documentation
.github/                CI workflows, dependabot, codeql (TBD)
```
