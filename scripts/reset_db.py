#!/usr/bin/env python3
"""Reset the development PostgreSQL database.

This script reads database credentials from `.env` (via spectres.config.settings),
drops the configured database, recreates it, and installs the pgvector extension.

Usage:
    uv run python scripts/reset_db.py
    uv run python scripts/reset_db.py --force
    SPECTRES_ENV_FILE=.env.test uv run python scripts/reset_db.py --force
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load optional local env overrides (e.g., .env.test.local) before importing settings.
_env_file = os.getenv("SPECTRES_ENV_FILE", ".env")
_local_env = Path(_env_file + ".local")
if _local_env.exists():
    load_dotenv(_local_env, override=False)

import psycopg  # noqa: E402
from psycopg.sql import SQL, Identifier  # noqa: E402

from spectres.config import settings  # noqa: E402


def _confirm(database_name: str) -> bool:
    """Prompt the user for confirmation before dropping the database."""
    prompt = f"This will DROP the development database '{database_name}'. Continue? [y/N]: "
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def reset_database(force: bool = False) -> None:
    """Drop and recreate the development database, then install pgvector."""
    database_name = settings.db_database
    admin_database = "postgres"

    if database_name in ("postgres", "template0", "template1"):
        print(f"Refusing to drop protected database: {database_name}", file=sys.stderr)
        sys.exit(1)

    if not force and not _confirm(database_name):
        print("Aborted.")
        sys.exit(0)

    admin_url = (
        f"postgresql://{settings.db_user}:{settings.db_pass}@{settings.db_host}:{settings.db_port}/{admin_database}"
    )
    target_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")

    try:
        with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
            print(f"Terminating existing connections to '{database_name}'...")
            cur.execute(
                """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                (database_name,),
            )

            print(f"Dropping database '{database_name}'...")
            cur.execute(SQL("DROP DATABASE IF EXISTS {}").format(Identifier(database_name)))

            print(f"Creating database '{database_name}'...")
            cur.execute(SQL("CREATE DATABASE {}").format(Identifier(database_name)))

        with psycopg.connect(target_url, autocommit=True) as conn, conn.cursor() as cur:
            print("Installing pgvector extension...")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        print(f"Database '{database_name}' has been reset.")
    except psycopg.OperationalError as exc:
        print(f"Failed to connect to PostgreSQL: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Parse CLI arguments and reset the database."""
    parser = argparse.ArgumentParser(description="Reset the development PostgreSQL database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt (use with caution).",
    )
    args = parser.parse_args()

    reset_database(force=args.force)


if __name__ == "__main__":
    main()
