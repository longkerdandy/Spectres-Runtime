# Development Environment

Setup, daily commands, and troubleshooting for working on Spectres-Runtime
locally. For commit / branching conventions see
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Prerequisites

- Linux, macOS, or WSL2 (native Windows untested).
- Git ≥ 2.30.
- [`uv`](https://docs.astral.sh/uv/) ≥ 0.11.17 — manages Python, deps, and venv.
- No system Python required; `uv` fetches its own.

Python is pinned to **3.12** (`requires-python = ">=3.12,<3.13"`) — upper bound
locked until 3.13 wheel coverage matures for native deps.

## Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # or: brew install uv
uv --version          # expect ≥ 0.11.17
uv self update        # upgrade later
```

## First-time setup

```bash
git clone https://github.com/longkerdandy/Spectres-Runtime.git
cd Spectres-Runtime
uv python install 3.12                             # fetch pinned interpreter
uv sync                                            # runtime + dev (lint + test + mypy + pre-commit)
uv run pre-commit install                          # pre-commit stage
uv run pre-commit install --hook-type commit-msg   # commit-msg stage (separate, required)
```

Use `uv sync --frozen` in CI/scripts to forbid silent lockfile regeneration.

## Smoke verification

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatter dry-run
uv run mypy                    # strict type check
uv run pytest                  # tests + coverage gate (≥ 80%)

uv run uvicorn spectres_runtime.app:app --reload
curl -s http://127.0.0.1:8000/healthz   # → {"status":"ok"}
```

OpenAPI: `/openapi.json`; Swagger UI: `/docs`.

## Daily commands

| Task | Command |
|---|---|
| Lint (with auto-fix) | `uv run ruff check --fix .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy` |
| Run tests | `uv run pytest` |
| Run a single test | `uv run pytest tests/test_healthz.py::test_healthz_ok` |
| Coverage HTML | `uv run pytest --cov-report=html` → `htmlcov/index.html` |
| Run all hooks | `uv run pre-commit run --all-files` |
| Update hook versions | `uv run pre-commit autoupdate` |
| Bypass hooks (rare) | `git commit --no-verify` |
| Add dependency | `uv add <pkg>` (or `--group dev` / `lint` / `test`) |
| Remove dependency | `uv remove <pkg>` |
| Upgrade one / all | `uv lock --upgrade-package <pkg>` / `uv lock --upgrade` |
| Dependency tree | `uv tree` |
| Dev server | `uv run uvicorn spectres_runtime.app:app --reload` |

Every dependency change must commit the updated `uv.lock`.

## Pre-commit ↔ CI

Both run the same checks; intentionally redundant. Pre-commit uses isolated
per-hook venvs and runs on staged files (fast feedback); CI uses the project
`.venv` on the full tree and is the authoritative gate.

The Mypy hook lives in its own venv and cannot see `.venv`, so third-party
packages it needs are listed under `additional_dependencies` in
`.pre-commit-config.yaml`. **When you bump a runtime dep, mirror the bump
there.**

## Troubleshooting

- **`uv sync` says lockfile is out of date** — `pyproject.toml` changed without
  relocking. Run `uv lock`, review the diff, commit.
- **Pre-commit Ruff result differs from `uv run ruff`** — version drift between
  `.pre-commit-config.yaml` `rev:` and the `ruff>=` lower bound in
  `pyproject.toml`. Bump both together.
- **Pre-commit Mypy: "module not found"** — add it to `additional_dependencies`
  under the `mypy` hook.
- **`uvicorn: command not found`** — always prefix with `uv run`.
- **`commit-msg` hook does not fire** — install the second stage:
  `uv run pre-commit install --hook-type commit-msg`.

## Reset

```bash
rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov
uv sync --frozen
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg
uv run pytest
```
