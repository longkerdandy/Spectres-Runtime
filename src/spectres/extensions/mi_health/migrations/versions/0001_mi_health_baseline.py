"""Create the Mi Health account-binding and QR-attempt baseline.

Revision ID: 0001_mi_health_baseline
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_mi_health_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only Mi Health-owned tables when they are absent."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("mi_health_bindings"):
        op.create_table(
            "mi_health_bindings",
            sa.Column("user_id", sa.String(length=128), nullable=False),
            sa.Column("region", sa.String(length=8), nullable=False),
            sa.Column("device_id", sa.String(length=64), nullable=False),
            sa.Column("xiaomi_user_id", sa.Text(), nullable=False),
            sa.Column("c_user_id", sa.Text(), nullable=False),
            sa.Column("pass_token", sa.Text(), nullable=False),
            sa.Column("service_token", sa.Text(), nullable=False),
            sa.Column("ssecurity", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("bound_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_renewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("user_id"),
        )
    if not inspector.has_table("mi_health_qr_attempts"):
        op.create_table(
            "mi_health_qr_attempts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=128), nullable=False),
            sa.Column("device_id", sa.String(length=64), nullable=False),
            sa.Column("lp_ciphertext", sa.Text(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("server_timeout_seconds", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_mi_health_qr_attempts_user_id", "mi_health_qr_attempts", ["user_id"])


def downgrade() -> None:
    """Destructive downgrades are intentionally not supported during startup."""
    raise NotImplementedError("reviewed downgrade must be run explicitly")
