"""ETF grid extension manifest: id, table creation, and surface construction."""

import logging

from spectres.extensions.base import ExtensionContext, ExtensionContribution, ScheduleSpec
from spectres.extensions.etf_grid.models import EtfGridBase

logger = logging.getLogger(__name__)

#: Unique extension id (snake_case; every surface derives from it).
name = "etf_grid"


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Create the extension's tables (idempotent) and build its toolkit + router.

    Idempotent and side-effect-free apart from ``create_all``; performs no
    network calls at load time.
    The daily sync schedule is only declared here — core registers it with
    the AgentOS scheduler after loading (spectres/scheduler.py).
    """
    EtfGridBase.metadata.create_all(ctx.db.db_engine)

    # Imported lazily so merely importing the package stays cheap and the
    # web/agent frameworks are only pulled in when surfaces are built.
    from spectres.extensions.etf_grid.api import create_router
    from spectres.extensions.etf_grid.config import load_config
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit

    config = load_config()
    contribution = ExtensionContribution(
        toolkits=[EtfGridToolkit(config=config)],
        routers=[create_router(config=config)],
        schedules=[
            ScheduleSpec(
                name="etf_grid_daily_sync",
                cron=config.sync_cron,
                endpoint="/api/v1/extensions/etf-grid/refresh",
                method="POST",
                timezone=config.sync_timezone,
                timeout_seconds=3600,
                max_retries=config.sync_max_retries,
                retry_delay_seconds=config.sync_retry_delay_seconds,
                enabled=config.sync_schedule_enabled,
            )
        ],
    )
    logger.info(
        "extension registered",
        extra={
            "event": "extension_registered",
            "symbols": [item.symbol for item in config.portfolio],
            "toolkits": len(contribution.toolkits),
            "routers": len(contribution.routers),
            "schedules": len(contribution.schedules),
        },
    )
    return contribution
