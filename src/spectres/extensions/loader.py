"""In-tree extension discovery and loading.

Convention: every package directly under ``spectres.extensions`` whose
``__init__`` exposes a module-level ``extension`` object — with a
snake_case ``id``, non-empty display ``name`` and ``description``, and a
callable ``register(ctx)`` — is an extension. In practice the object is the
package's own ``extension.py`` module re-exported as ``extension``. Presence
in the tree selects built-in code; activation is persisted separately. There
is deliberately no ``ENABLED_EXTENSIONS`` allowlist or ``entry_points``
discovery.
"""

import importlib
import pkgutil
import re
from typing import cast

from agno.db.postgres import PostgresDb

import spectres.extensions
from spectres.config import Settings
from spectres.extensions.base import Extension, ExtensionContext, LoadedExtension

_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def load_extensions(settings: Settings, db: PostgresDb) -> list[LoadedExtension]:
    """Discover in-tree extensions and retain their metadata and contributions.

    A package that fails to import, a malformed manifest, or a
    ``register()`` that raises aborts startup with a
    message naming the extension — a broken extension never fails
    silently. Extensions load in sorted package-name order so router
    mounting and toolkit concatenation order are deterministic.
    """
    extensions: list[LoadedExtension] = []
    for module_info in sorted(pkgutil.iter_modules(spectres.extensions.__path__), key=lambda m: m.name):
        if not module_info.ispkg:
            continue
        try:
            package = importlib.import_module(f"{spectres.extensions.__name__}.{module_info.name}")
        except Exception as exc:
            raise RuntimeError(f"extension package {module_info.name!r} failed to import: {exc}") from exc
        candidate = getattr(package, "extension", None)
        if candidate is None:
            continue
        extension_id = getattr(candidate, "id", None)
        if not isinstance(extension_id, str) or not _ID_PATTERN.fullmatch(extension_id):
            raise RuntimeError(f"extension package {module_info.name!r} exposes an invalid extension id {extension_id!r} (must be snake_case)")
        name = getattr(candidate, "name", None)
        description = getattr(candidate, "description", None)
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(f"extension {extension_id!r} must have a non-empty name")
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(f"extension {extension_id!r} must have a non-empty description")
        if any(extension.id == extension_id for extension in extensions):
            raise RuntimeError(f"duplicate extension id {extension_id!r}")
        register = getattr(candidate, "register", None)
        if not callable(register):
            raise RuntimeError(f"extension {extension_id!r} has no callable register()")
        ctx = ExtensionContext(settings=settings, db=db)
        try:
            contribution = cast(Extension, candidate).register(ctx)
            extensions.append(LoadedExtension(id=extension_id, name=name, description=description, contribution=contribution))
        except Exception as exc:
            raise RuntimeError(f"extension {extension_id!r} failed to register: {exc}") from exc
    return extensions
