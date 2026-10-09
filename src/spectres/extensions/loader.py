"""In-tree extension discovery and loading (runtime-extensions.md §5).

Convention: every package directly under ``spectres.extensions`` whose
``__init__`` exposes a module-level ``extension`` object — with a
snake_case ``name: str`` and a callable ``register(ctx)`` — is an
extension. In practice the object is the package's own ``extension.py``
module re-exported as ``extension``. Presence in the tree is the opt-in:
there is deliberately no enable/disable gating (§5.1); an
``ENABLED_EXTENSIONS`` allowlist and ``entry_points`` discovery stay
deferred (§9).
"""

import importlib
import logging
import pkgutil
import re
from typing import cast

from agno.db.postgres import PostgresDb

import spectres.extensions
from spectres.config import Settings
from spectres.extensions.base import Extension, ExtensionContext, ExtensionContribution

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def load_extensions(settings: Settings, db: PostgresDb) -> list[ExtensionContribution]:
    """Discover in-tree extensions, register each, and collect their contributions.

    Fail-loud (§5.2): a malformed manifest or a ``register()`` that raises
    aborts startup with a message naming the extension — a broken
    extension never fails silently.
    """
    contributions: list[ExtensionContribution] = []
    for module_info in pkgutil.iter_modules(spectres.extensions.__path__):
        if not module_info.ispkg:
            continue
        package = importlib.import_module(f"{spectres.extensions.__name__}.{module_info.name}")
        candidate = getattr(package, "extension", None)
        if candidate is None:
            continue
        ext_name = getattr(candidate, "name", None)
        if not isinstance(ext_name, str) or not _NAME_PATTERN.fullmatch(ext_name):
            raise RuntimeError(f"extension package {module_info.name!r} exposes an invalid extension name {ext_name!r} (must be snake_case)")
        register = getattr(candidate, "register", None)
        if not callable(register):
            raise RuntimeError(f"extension {ext_name!r} has no callable register()")
        ctx = ExtensionContext(settings=settings, db=db)
        try:
            contributions.append(cast(Extension, candidate).register(ctx))
        except Exception as exc:
            logger.error("extension %r failed to register", ext_name, exc_info=exc, extra={"event": "extension_register_failed"})
            raise RuntimeError(f"extension {ext_name!r} failed to register: {exc}") from exc
    return contributions
