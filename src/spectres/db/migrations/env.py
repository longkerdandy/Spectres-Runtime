"""Alembic environment for Core-owned Runtime and health schema revisions."""

from alembic import context


def run_migrations() -> None:
    """Run online migrations on the shared utility's locked connection."""
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("migrations require the shared online connection")
    context.configure(
        connection=connection,
        version_table=context.config.attributes["version_table"],
        compare_type=True,
        transaction_per_migration=False,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
