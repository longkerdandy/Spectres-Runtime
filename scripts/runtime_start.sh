#!/usr/bin/env bash
# Start the Spectres-Runtime backend for local development.
#
# Assumes Postgres is already running and the recipe corpus has been ingested
# if needed. This script only *checks* those prerequisites and fails fast with
# a helpful message; it does not start Docker or run ingestion itself, because
# both are slow one-time / long-lived operations.
#
# Usage:
#   ./scripts/runtime_start.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [ ! -f "${ENV_FILE}" ]; then
  echo "⚠️  .env not found at ${ENV_FILE}"
  echo "   cp .env.example .env and fill in the required values first."
  exit 1
fi

# Load .env so we can read RUNTIME_PORT and DATABASE_URL.
# shellcheck source=/dev/null
set -a && source "${ENV_FILE}" && set +a

RUNTIME_PORT="${RUNTIME_PORT:-7777}"
DATABASE_URL="${DATABASE_URL:-}"

echo "==> Spectres-Runtime dev server"
echo "    Port: ${RUNTIME_PORT}"
echo "    Working dir: ${ROOT_DIR}"

# --- Postgres health check ---------------------------------------------------

if ! command -v pg_isready >/dev/null 2>&1; then
  echo "⚠️  pg_isready not found; skipping Postgres health check."
else
  PG_HOST="localhost"
  PG_PORT="5532"

  # If DATABASE_URL is set, try to extract host/port for a more accurate check.
  if [ -n "${DATABASE_URL}" ]; then
    # psycopg URL form: postgresql[+driver]://user:pass@host:port/db
    parsed="${DATABASE_URL#*@}"            # host:port/db
    PG_HOST="${parsed%%:*}"
    PG_PORT="${parsed#*:}"
    PG_PORT="${PG_PORT%%/*}"
  fi

  if ! pg_isready -h "${PG_HOST}" -p "${PG_PORT}" >/dev/null 2>&1; then
    echo "⚠️  Postgres not reachable at ${PG_HOST}:${PG_PORT}"
    echo "   Start it with: docker compose --env-file .env -f docker/compose.yaml up -d"
    exit 1
  fi
  echo "    Postgres: ${PG_HOST}:${PG_PORT} ✅"
fi

# --- Recipe corpus check (best-effort, warns only) ---------------------------

if [ -n "${DATABASE_URL}" ]; then
  RECIPE_COUNT=$(uv run python - <<PY 2>/dev/null || echo "unknown"
import psycopg
try:
    with psycopg.connect("${DATABASE_URL}") as conn:
        row = conn.execute("SELECT count(*) FROM recipes").fetchone()
        print(row[0] if row else 0)
except Exception:
    print("unknown")
PY
  )

  if [ "${RECIPE_COUNT}" = "0" ]; then
    echo "⚠️  recipes table is empty."
    echo "   Load the corpus with: uv run recipe-ingest"
  elif [ "${RECIPE_COUNT}" = "unknown" ]; then
    echo "    Could not check recipes table (database URL may be incomplete)."
  else
    echo "    Recipes loaded: ${RECIPE_COUNT} ✅"
  fi
fi

# --- Start backend -----------------------------------------------------------

cd "${ROOT_DIR}"
echo "==> Starting backend on http://127.0.0.1:${RUNTIME_PORT} ..."
exec uv run uvicorn spectres_runtime.app:app_factory \
  --factory \
  --reload \
  --host 127.0.0.1 \
  --port "${RUNTIME_PORT}"
