"""ETF grid extension manifest: id, table creation, and surface construction."""

from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.etf_grid.models import EtfGridBase

#: Unique extension id (snake_case; every surface derives from it).
name = "etf_grid"


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Create the extension's tables (idempotent) and build its toolkit + router.

    Idempotent and side-effect-free apart from ``create_all``
    (runtime-extensions.md §6.2); performs no network calls at load time.
    """
    EtfGridBase.metadata.create_all(ctx.db.db_engine)

    # Imported lazily so merely importing the package stays cheap and the
    # web/agent frameworks are only pulled in when surfaces are built.
    from spectres.extensions.etf_grid.api import create_router
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit

    return ExtensionContribution(toolkits=[EtfGridToolkit()], routers=[create_router()])
