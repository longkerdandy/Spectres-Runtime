"""Mi Health Extension registration and composition root."""

import logging
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from spectres.db.migration import migrate_schema
from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.mi_health.credentials import CredentialCipher
from spectres.health.ingestion import HealthIngestionService

logger = logging.getLogger(__name__)

id = "mi_health"
name = "Mi Health"
description = "Xiaomi Mi Fitness account binding and owner-triggered personal health synchronization."


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Run local migrations and inject binding, session, and sync services."""
    from spectres.extensions.mi_health.api import create_router
    from spectres.extensions.mi_health.config import load_config
    from spectres.extensions.mi_health.service import MiHealthBindingService, MiHealthSessionService, MiHealthSyncService
    from spectres.extensions.mi_health.xiaomi import XiaomiClient

    migrate_schema(
        ctx.db.db_engine,
        script_location=Path(__file__).parent / "migrations",
        version_table="mi_health_schema_version",
        lock_namespace="spectres.runtime.extension.mi_health",
    )
    config = load_config()
    session_factory = sessionmaker(bind=ctx.db.db_engine)
    cipher = CredentialCipher(config.credential_key)
    xiaomi = XiaomiClient(config)
    ingestion = HealthIngestionService(session_factory)
    bindings = MiHealthBindingService(config=config, session_factory=session_factory, cipher=cipher, xiaomi=xiaomi, ingestion=ingestion)
    sessions = MiHealthSessionService(bindings=bindings, xiaomi=xiaomi)
    sync = MiHealthSyncService(bindings=bindings, sessions=sessions, xiaomi=xiaomi, ingestion=ingestion)
    contribution = ExtensionContribution(routers=[create_router(bindings=bindings, sessions=sessions, sync=sync)])
    logger.info("Mi Health Extension registered", extra={"event": "extension_registered", "extension": id, "routers": 1})
    return contribution
