"""Real-PostgreSQL migration adoption, isolation, locking, and rollback tests."""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import Engine, MetaData, create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from spectres.config import settings
from spectres.db.migration import migrate_core_schema, migrate_schema
from spectres.db.postgres import get_postgres_db
from spectres.extensions.etf_grid.models import EtfGridBase, EtfGridCandle
from spectres.extensions.mi_health.models import MiHealthBase, MiHealthBinding
from spectres.extensions.state import ExtensionStateBase, RuntimeExtensionState
from spectres.health.models import HealthBase

pytestmark = [pytest.mark.integration, pytest.mark.db]
_ROOT = Path(__file__).parents[1] / "src" / "spectres"
_ETF_MIGRATIONS = _ROOT / "extensions" / "etf_grid" / "migrations"
_MI_MIGRATIONS = _ROOT / "extensions" / "mi_health" / "migrations"


@pytest.fixture
def isolated_engine() -> Iterator[Engine]:
    """Use a disposable PostgreSQL schema without touching Runtime tables."""
    schema = f"migration_test_{uuid.uuid4().hex}"
    base = get_postgres_db().db_engine
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema}"}, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def _etf(engine: Engine) -> None:
    migrate_schema(engine, script_location=_ETF_MIGRATIONS, version_table="etf_grid_schema_version", lock_namespace="test.etf_grid")


def _mi(engine: Engine) -> None:
    migrate_schema(engine, script_location=_MI_MIGRATIONS, version_table="mi_health_schema_version", lock_namespace="test.mi_health")


def _assert_model_shape(engine: Engine, metadata: MetaData) -> None:
    inspector = inspect(engine)
    for table in metadata.tables.values():
        assert inspector.has_table(table.name)
        actual = {column["name"]: column for column in inspector.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys())
        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable
            assert actual[column.name]["type"].compile(engine.dialect) == column.type.compile(engine.dialect)
        assert set(inspector.get_pk_constraint(table.name)["constrained_columns"]) == set(table.primary_key.columns.keys())
        assert {index["name"] for index in inspector.get_indexes(table.name)} == {index.name for index in table.indexes}


def test_empty_schema_reaches_independent_heads_repeatedly_with_matching_models(isolated_engine: Engine) -> None:
    """All three namespaces migrate independently and are idempotent at head."""
    for migration in (_etf, _mi):
        migrate_core_schema(isolated_engine)
        migration(isolated_engine)
    migrate_core_schema(isolated_engine)
    _etf(isolated_engine)
    _mi(isolated_engine)

    inspector = inspect(isolated_engine)
    tables = set(inspector.get_table_names())
    assert {name for name in tables if name.startswith("health_")} == set(HealthBase.metadata.tables)
    assert len([name for name in tables if name.startswith("health_")]) == 6
    assert {"runtime_schema_version", "etf_grid_schema_version", "mi_health_schema_version"} <= tables
    with Session(isolated_engine) as session:
        assert session.scalar(text("SELECT version_num FROM runtime_schema_version")) == "0002_personal_health"
        assert session.scalar(text("SELECT version_num FROM etf_grid_schema_version")) == "0001_etf_grid_baseline"
        assert session.scalar(text("SELECT version_num FROM mi_health_schema_version")) == "0001_mi_health_baseline"
    _assert_model_shape(isolated_engine, ExtensionStateBase.metadata)
    _assert_model_shape(isolated_engine, HealthBase.metadata)
    _assert_model_shape(isolated_engine, EtfGridBase.metadata)
    _assert_model_shape(isolated_engine, MiHealthBase.metadata)
    assert not any(name.startswith("agno_") for name in tables)
    assert not any(name.startswith("logto") for name in tables)


def test_existing_baseline_rows_survive_adoption(isolated_engine: Engine) -> None:
    """Pre-migration Core and Extension tables adopt histories without data loss."""
    ExtensionStateBase.metadata.create_all(isolated_engine)
    EtfGridBase.metadata.create_all(isolated_engine)
    MiHealthBase.metadata.create_all(isolated_engine)
    with Session(isolated_engine) as session, session.begin():
        session.add(RuntimeExtensionState(name="existing", enabled=False))
        session.add(
            MiHealthBinding(
                user_id="alice",
                region="cn",
                device_id="synthetic-device",
                xiaomi_user_id="synthetic-account",
                c_user_id="synthetic-c-user",
                pass_token="synthetic-ciphertext",
                service_token="synthetic-ciphertext",
                ssecurity="synthetic-ciphertext",
                status="authenticated",
                revision=0,
            )
        )
        session.add(
            EtfGridCandle(
                symbol="000000.XSHG",
                trade_date=__import__("datetime").date(2026, 1, 1),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=100,
            )
        )

    migrate_core_schema(isolated_engine)
    _etf(isolated_engine)
    _mi(isolated_engine)

    with Session(isolated_engine) as session:
        state = session.get(RuntimeExtensionState, "existing")
        assert state is not None and state.enabled is False
        assert session.get(MiHealthBinding, "alice") is not None
        assert session.scalar(select(func.count()).select_from(EtfGridCandle)) == 1


def test_concurrent_migration_execution_is_serialized_per_namespace(isolated_engine: Engine) -> None:
    """Concurrent adopters share one lock and converge on one version history."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: migrate_core_schema(isolated_engine), range(4)))
        list(executor.map(lambda _: _etf(isolated_engine), range(4)))
        list(executor.map(lambda _: _mi(isolated_engine), range(4)))

    with Session(isolated_engine) as session:
        assert session.scalar(text("SELECT count(*) FROM runtime_schema_version")) == 1
        assert session.scalar(text("SELECT count(*) FROM etf_grid_schema_version")) == 1
        assert session.scalar(text("SELECT count(*) FROM mi_health_schema_version")) == 1


def test_failed_revision_rolls_back_schema_and_version(isolated_engine: Engine, tmp_path: Path) -> None:
    """A failed revision cannot leave a successful version or partial table."""
    (tmp_path / "versions").mkdir()
    (tmp_path / "env.py").write_text(
        "from alembic import context\n"
        "connection = context.config.attributes['connection']\n"
        "context.configure(connection=connection, version_table=context.config.attributes['version_table'])\n"
        "with context.begin_transaction():\n"
        "    context.run_migrations()\n"
    )
    (tmp_path / "versions" / "0001_failure.py").write_text(
        "import sqlalchemy as sa\n"
        "from alembic import op\n"
        "revision = '0001_failure'\n"
        "down_revision = None\n"
        "def upgrade():\n"
        "    op.create_table('synthetic_partial', sa.Column('id', sa.Integer(), primary_key=True))\n"
        "    raise RuntimeError('synthetic revision failure')\n"
    )

    with pytest.raises(RuntimeError, match="synthetic revision failure"):
        migrate_schema(isolated_engine, script_location=tmp_path, version_table="failure_schema_version", lock_namespace="test.failure")

    inspector = inspect(isolated_engine)
    assert not inspector.has_table("synthetic_partial")
    assert not inspector.has_table("failure_schema_version")
