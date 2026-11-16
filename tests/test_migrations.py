"""Unit tests for migration boundaries and startup failure behavior."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from spectres.db.migration import migrate_schema
from spectres.db.postgres import get_postgres_db
from spectres.extensions.etf_grid import extension as etf_grid_extension
from spectres.extensions.mi_health import extension as mi_health_extension

pytestmark = pytest.mark.unit
_CORE_MIGRATIONS = Path(__file__).parents[1] / "src" / "spectres" / "db" / "migrations" / "versions"


def test_migration_utility_rejects_unsafe_or_incomplete_namespaces(tmp_path: Path) -> None:
    """Version identifiers and script locations are validated before database work."""
    with pytest.raises(ValueError, match="snake_case"):
        migrate_schema(MagicMock(), script_location=tmp_path, version_table="bad-name", lock_namespace="test")
    with pytest.raises(ValueError, match=r"env\.py"):
        migrate_schema(MagicMock(), script_location=tmp_path, version_table="safe_version", lock_namespace="test")
    with pytest.raises(ValueError, match="namespace"):
        migrate_schema(MagicMock(), script_location=tmp_path, version_table="safe_version", lock_namespace="")


def test_core_migrations_have_no_extension_schema_or_imports() -> None:
    """Core migration history never defines or imports Extension-owned schema."""
    source = "\n".join(path.read_text() for path in _CORE_MIGRATIONS.glob("*.py"))
    assert "etf_grid" not in source
    assert "mi_health" not in source
    assert "spectres.extensions" not in source


def test_runtime_and_extensions_no_longer_call_create_all() -> None:
    """Registration relies exclusively on reviewed local migrations."""
    paths = [
        Path(__file__).parents[1] / "src" / "spectres" / "extensions" / "state.py",
        Path(etf_grid_extension.__file__),
        Path(mi_health_extension.__file__),
    ]
    assert all("create_all(" not in path.read_text() for path in paths)


@pytest.mark.parametrize("extension", [etf_grid_extension, mi_health_extension])
def test_extension_migration_failure_aborts_registration(extension: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed local migration cannot produce a registered contribution."""
    monkeypatch.setattr(extension, "migrate_schema", MagicMock(side_effect=RuntimeError("synthetic migration failure")))
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        extension.register(MagicMock())  # type: ignore[attr-defined]


def test_core_migration_failure_prevents_database_and_extension_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core migration failures propagate before an adapter can be used for loading."""
    import spectres.db.postgres as postgres

    monkeypatch.setattr(postgres, "_db", None)
    monkeypatch.setattr(postgres, "PostgresDb", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(postgres, "migrate_core_schema", MagicMock(side_effect=RuntimeError("synthetic core migration failure")))
    with pytest.raises(RuntimeError, match="synthetic core migration failure"):
        get_postgres_db()
