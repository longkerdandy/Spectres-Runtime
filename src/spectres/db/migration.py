"""Schema-agnostic Alembic execution with per-namespace PostgreSQL locking."""

import hashlib
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


def migrate_schema(engine: Engine, *, script_location: str | Path, version_table: str, lock_namespace: str) -> None:
    """Upgrade one independent migration namespace to its reviewed head."""
    if not _IDENTIFIER.fullmatch(version_table):
        raise ValueError("migration version table must be a snake_case identifier")
    if not lock_namespace:
        raise ValueError("migration lock namespace is required")
    location = Path(script_location).resolve()
    if not (location / "env.py").is_file() or not (location / "versions").is_dir():
        raise ValueError("migration script location must contain env.py and versions")
    config = Config()
    config.set_main_option("script_location", str(location))
    config.set_main_option("version_table", version_table)
    config.attributes["version_table"] = version_table
    lock_key = int.from_bytes(hashlib.sha256(lock_namespace.encode("utf-8")).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def migrate_core_schema(engine: Engine) -> None:
    """Migrate only Runtime Core state and Core-owned health tables."""
    migrate_schema(
        engine,
        script_location=Path(__file__).parent / "migrations",
        version_table="runtime_schema_version",
        lock_namespace="spectres.runtime.core",
    )
