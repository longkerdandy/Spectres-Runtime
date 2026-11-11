"""Mi Health Extension registration and composition root."""

import logging

from sqlalchemy.orm import sessionmaker

from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.mi_health.credentials import CredentialCipher
from spectres.extensions.mi_health.models import MiHealthBase

logger = logging.getLogger(__name__)

id = "mi_health"
name = "Mi Health"
description = "Xiaomi Mi Fitness QR account binding and secure health-session lifecycle."


def register(ctx: ExtensionContext) -> ExtensionContribution:
    """Create Mi Health tables and inject one service set into the REST adapter."""
    from spectres.extensions.mi_health.api import create_router
    from spectres.extensions.mi_health.config import load_config
    from spectres.extensions.mi_health.service import MiHealthBindingService, MiHealthSessionService
    from spectres.extensions.mi_health.xiaomi import XiaomiClient

    config = load_config()
    session_factory = sessionmaker(bind=ctx.db.db_engine)
    cipher = CredentialCipher(config.credential_key)
    xiaomi = XiaomiClient(config)
    bindings = MiHealthBindingService(config=config, session_factory=session_factory, cipher=cipher, xiaomi=xiaomi)
    sessions = MiHealthSessionService(bindings=bindings, xiaomi=xiaomi)
    MiHealthBase.metadata.create_all(ctx.db.db_engine)
    contribution = ExtensionContribution(routers=[create_router(bindings=bindings, sessions=sessions)])
    logger.info("Mi Health Extension registered", extra={"event": "extension_registered", "extension": id, "routers": 1})
    return contribution
