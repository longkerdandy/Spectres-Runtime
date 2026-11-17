"""Create Mi Health synchronization runs.

Revision ID: 0002_mi_health_sync_runs
Revises: 0001_mi_health_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_mi_health_sync_runs"
down_revision: str | None = "0001_mi_health_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create or adopt the Extension-owned run table and concurrency invariant."""
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("mi_health_sync_runs"):
        return
    op.create_table(
        "mi_health_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("streams", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("schedule_run_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mi_health_sync_runs_user_created", "mi_health_sync_runs", ["user_id", "created_at"])
    op.create_index(
        "uq_mi_health_sync_runs_active_user",
        "mi_health_sync_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    """Destructive downgrades are intentionally not supported during startup."""
    raise NotImplementedError("reviewed downgrade must be run explicitly")
