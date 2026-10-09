"""ETF grid extension manifest: id, table creation, and surface construction."""

import logging

from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.etf_grid.models import EtfGridBase

logger = logging.getLogger(__name__)

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
    from spectres.extensions.etf_grid.config import EtfGridConfig
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit

    config = EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
    contribution = ExtensionContribution(toolkits=[EtfGridToolkit(config=config)], routers=[create_router(config=config)])
    logger.info(
        "extension registered",
        extra={
            "event": "extension_registered",
            "symbols": [item.symbol for item in config.portfolio],
            "toolkits": len(contribution.toolkits),
            "routers": len(contribution.routers),
        },
    )
    return contribution
