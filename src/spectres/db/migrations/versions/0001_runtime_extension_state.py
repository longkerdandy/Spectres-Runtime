"""Create the Core-owned Runtime extension activation state baseline.

Revision ID: 0001_runtime_state
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_runtime_state"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the state table only when adopting an empty or legacy schema."""
    if sa.inspect(op.get_bind()).has_table("runtime_extension_states"):
        return
    op.create_table(
        "runtime_extension_states",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    """Destructive downgrades are intentionally not supported during startup."""
    raise NotImplementedError("reviewed downgrade must be run explicitly")
