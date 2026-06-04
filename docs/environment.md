# Development Environment

How to set up Spectres-Runtime locally — from a clean machine to a running server
with its database. For daily Git workflow and commit/branching conventions see
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Prerequisites

- Linux, macOS, or WSL2 (native Windows untested).
- Git ≥ 2.30.
- [`uv`](https://docs.astral.sh/uv/) ≥ 0.11.17 — manages Python, dependencies, and
  the venv. No system Python required; `uv` fetches its own.
- Docker Engine + Docker Compose v2 (the `docker compose` subcommand) — runs the
  Postgres + pgvector database.

Python is pinned to **3.12** (`requires-python = ">=3.12,<3.13"`); the upper bound
is locked until 3.13 wheel coverage matures for native deps.

## 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # or: brew install uv
uv --version          # expect ≥ 0.11.17
```

## 2. Clone and install dependencies

```bash
git clone https://github.com/longkerdandy/Spectres-Runtime.git
cd Spectres-Runtime
uv python install 3.12                             # fetch the pinned interpreter
uv sync                                            # runtime + dev tools (lint, test, mypy, pre-commit)
uv run pre-commit install                          # pre-commit stage
uv run pre-commit install --hook-type commit-msg   # commit-msg stage (separate, required)
```

Use `uv sync --frozen` in CI/scripts to forbid silent lockfile regeneration.

## 3. Configure environment

The app and the database both read a git-ignored `.env` at the repo root. Create it
from the committed template and fill in real values:

```bash
cp .env.example .env
```

At minimum, set:

- `DATABASE_USERNAME` / `DATABASE_PASSWORD` — credentials for the local Postgres
  role. `DATABASE_URL` references them via `${...}`, so you set them in one place.
- `EMBEDDER_API_KEY` — your SiliconFlow (`.cn`) key; required for any live embedding
  call (ingestion / search).

Every key is documented inline in `.env.example`.

## 4. Start the database (Docker)

A single Postgres + pgvector container backs all persistent state. Compose reads the
credentials from `.env`, so pass it explicitly with `--env-file` — otherwise Compose
looks for `.env` next to the compose file (in `docker/`), not the repo root:

```bash
docker compose --env-file .env -f docker/compose.yaml up -d
docker compose --env-file .env -f docker/compose.yaml ps   # STATUS should be "healthy"
```

On first boot (empty volume) the container creates the `spectres_runtime` database,
the role from your `.env`, and enables the `vector` extension
(`docker/postgres/init.sql`). It listens on host port **5532** (mapped to container
5432, avoiding a clash with a standard local Postgres on 5432).

Stop it (data is preserved in the named `pgdata` volume):

```bash
docker compose --env-file .env -f docker/compose.yaml down
```

> The username, password, and database name only take effect on the **first** boot.
> If you change them later, recreate the volume: `down -v` (wipes **all** data),
> then `up -d`.

## 5. Verify

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatter dry-run
uv run mypy                    # strict type check
uv run pytest                  # tests + coverage gate (≥ 80%)

uv run uvicorn spectres_runtime.app:app --reload
curl -s http://127.0.0.1:8000/health   # → {"status":"ok",...}
```

OpenAPI: `/openapi.json`; Swagger UI: `/docs`. (`/health` needs no database; storage
features do.)

## Reset

Rebuild the toolchain and database from scratch:

```bash
rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov
uv sync --frozen
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg
docker compose --env-file .env -f docker/compose.yaml down -v
docker compose --env-file .env -f docker/compose.yaml up -d
uv run pytest
```
