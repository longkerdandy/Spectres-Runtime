"""ETF grid extension manifest: id, table creation, and surface construction."""

import logging

from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.etf_grid.models import EtfGridBase
from spectres.scheduler import ScheduleSpec

logger = logging.getLogger(__name__)

id = "etf_grid"
name = "ETF Grid"
description = "ETF grid trading status, trade ledger, signals, and scheduled data workflows."


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Create tables and build the extension surfaces without network calls.

    The daily sync schedule is only declared here — core registers it with
    the AgentOS scheduler after loading (spectres/scheduler.py).
    """
    EtfGridBase.metadata.create_all(ctx.db.db_engine)

    # Imported lazily so merely importing the package stays cheap and the
    # web/agent frameworks are only pulled in when surfaces are built.
    from spectres.extensions.etf_grid.api import create_router
    from spectres.extensions.etf_grid.config import load_config
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
    from spectres.extensions.etf_grid.workflows import DATA_SYNC_WORKFLOW_ID, create_workflows

    config = load_config()
    contribution = ExtensionContribution(
        toolkits=[EtfGridToolkit(config=config)],
        routers=[create_router(config=config)],
        workflows=create_workflows(config=config),
        schedules=[
            ScheduleSpec(
                name="ETF Grid Daily Sync",
                cron=config.sync_cron,
                endpoint=f"/workflows/{DATA_SYNC_WORKFLOW_ID}/runs",
                method="POST",
                payload={"message": "Run scheduled ETF Grid shared-data synchronization"},
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
            "toolkits": len(contribution.toolkits),
            "routers": len(contribution.routers),
            "workflows": len(contribution.workflows),
            "default_configs": len(contribution.default_configs),
            "schedules": len(contribution.schedules),
        },
    )
    return contribution
