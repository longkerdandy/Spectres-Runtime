"""ETF grid extension manifest: id, table creation, and surface construction."""

import logging

from spectres.extensions.base import ExtensionContext, ExtensionContribution, ScheduleSpec
from spectres.extensions.etf_grid.models import EtfGridBase

logger = logging.getLogger(__name__)

#: Unique extension id (snake_case; every surface derives from it).
name = "etf_grid"


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Create tables, bootstrap instrument selection, and build the surfaces.

    Table creation and selection bootstrap are idempotent; no network calls
    happen at load time.
    The daily sync schedule is only declared here — core registers it with
    the AgentOS scheduler after loading (spectres/scheduler.py).
    """
    EtfGridBase.metadata.create_all(ctx.db.db_engine)

    # Imported lazily so merely importing the package stays cheap and the
    # web/agent frameworks are only pulled in when surfaces are built.
    from spectres.extensions.etf_grid.api import create_router
    from spectres.extensions.etf_grid.config import load_config
    from spectres.extensions.etf_grid.service import EtfGridInstrumentService
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
    from spectres.extensions.etf_grid.workflows import DATA_SYNC_WORKFLOW_ID, create_workflows

    config = load_config()
    instruments = EtfGridInstrumentService()
    instruments.bootstrap([item.symbol for item in config.portfolio])
    contribution = ExtensionContribution(
        toolkits=[EtfGridToolkit(config=config, instrument_service=instruments)],
        routers=[create_router(config=config, instrument_service=instruments)],
        workflows=create_workflows(config=config, instrument_service=instruments),
        schedules=[
            ScheduleSpec(
                name="ETF Grid Daily Sync",
                previous_names=("etf_grid_daily_sync",),
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
            "symbols": [item.symbol for item in config.portfolio],
            "toolkits": len(contribution.toolkits),
            "routers": len(contribution.routers),
            "workflows": len(contribution.workflows),
            "schedules": len(contribution.schedules),
        },
    )
    return contribution
