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
- `RUNTIME_PORT` — port the local uvicorn dev server binds to (default `7777`).
- `EMBEDDER_API_KEY` — your embedder-provider key; required for any live embedding
  call (recipe ingestion and knowledge search).
- `CHAT_API_KEY` — your chat-provider key; required for the recipe agent to generate
  replies.

Every key is documented inline in `.env.example`, including the recipe agent's own
`RECIPE_AGENT_*` settings.

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

## 5. Populate the recipe knowledge base (optional)

The recipe agent answers from a pgvector knowledge base, which starts empty. Run the
one-shot `recipe-ingest` batch command to load the bundled corpus. It needs the
database **up** (step 4) and a valid `EMBEDDER_API_KEY` (step 3) to compute vectors:

```bash
uv run recipe-ingest
```

The run is idempotent — it re-ingests the full corpus each time, so re-running it is
safe. Skip this step if you only want to exercise `/health` or non-knowledge paths.

## 6. Start the dev server

Once Postgres is up and the corpus is loaded, use the helper script to start the
backend with hot reload:

```bash
./scripts/runtime_start.sh
```

The script checks that Postgres is reachable and warns if the `recipes` table is
empty, then starts uvicorn on `127.0.0.1:${RUNTIME_PORT:-7777}`.

If you prefer to start uvicorn directly:

```bash
uv run uvicorn spectres_runtime.app:app_factory --factory --reload --port "${RUNTIME_PORT:-7777}"
```

Then verify liveness:

```bash
curl -s "http://127.0.0.1:${RUNTIME_PORT:-7777}/health"   # → {"status":"ok",...}
```

OpenAPI: `/openapi.json`; Swagger UI: `/docs`. (`/health` needs no database; storage
features do.)

## 7. Verify

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatter dry-run
uv run mypy                    # strict type check
uv run pytest                  # tests + coverage gate (≥ 80%)
```

## Reset

Rebuild the toolchain and database from scratch:

```bash
rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov
uv sync --frozen
uv run pre-commit install && uv run pre-commit install --hook-type commit-msg
docker compose --env-file .env -f docker/compose.yaml down -v
docker compose --env-file .env -f docker/compose.yaml up -d
uv run recipe-ingest   # down -v wiped the volume; re-load the knowledge corpus
uv run pytest
```
