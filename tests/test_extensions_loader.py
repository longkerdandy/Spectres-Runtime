"""Unit tests for the in-tree extension loader."""

import importlib
from pathlib import Path
from typing import cast

import pytest
from agno.db.postgres import PostgresDb

import spectres.extensions
from spectres.config import settings
from spectres.extensions.base import ExtensionContext, ExtensionContribution
from spectres.extensions.loader import load_extensions

pytestmark = pytest.mark.unit


@pytest.fixture
def extension_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader's package scan at a temporary directory of fake extensions."""
    monkeypatch.setattr(spectres.extensions, "__path__", [str(tmp_path)])
    return tmp_path


@pytest.fixture
def ctx() -> ExtensionContext:
    """A context whose members fake extensions never need to touch."""
    return ExtensionContext(settings=settings, db=cast(PostgresDb, None))


def _write_pkg(root: Path, name: str, init_body: str) -> None:
    """Create one fake extension package."""
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(init_body)
    importlib.invalidate_caches()


_GOOD = """
from types import SimpleNamespace
from spectres.extensions.base import ExtensionContribution

def _register(ctx):
    return ExtensionContribution()

extension = SimpleNamespace(name="good_ext", register=_register)
"""

_BROKEN = """
from types import SimpleNamespace

def _register(ctx):
    raise ValueError("boom")

extension = SimpleNamespace(name="broken_ext", register=_register)
"""

_INVALID_NAME = """
from types import SimpleNamespace

extension = SimpleNamespace(name="Not-Snake-Case", register=lambda ctx: None)
"""

_NO_REGISTER = """
from types import SimpleNamespace

extension = SimpleNamespace(name="no_register_ext")
"""


def test_scan_skips_packages_without_extension_object(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Packages without a module-level `extension` object are not extensions."""
    _write_pkg(extension_dir, "not_an_ext", '"""Just a package."""\n')
    _write_pkg(extension_dir, "good_ext", _GOOD)
    assert load_extensions(ctx.settings, ctx.db) == [ExtensionContribution()]


def test_non_package_entries_ignored(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Plain modules next to packages are ignored."""
    (extension_dir / "loose_module.py").write_text("x = 1\n")
    _write_pkg(extension_dir, "good_ext", _GOOD)
    assert len(load_extensions(ctx.settings, ctx.db)) == 1


def test_broken_register_fails_loud_naming_extension(extension_dir: Path, ctx: ExtensionContext) -> None:
    """A register() that raises aborts startup with the extension named."""
    _write_pkg(extension_dir, "broken_ext", _BROKEN)
    with pytest.raises(RuntimeError, match=r"broken_ext.*boom"):
        load_extensions(ctx.settings, ctx.db)


def test_invalid_name_fails_loud(extension_dir: Path, ctx: ExtensionContext) -> None:
    """A non-snake_case extension id is rejected before register() runs."""
    _write_pkg(extension_dir, "bad_name_pkg", _INVALID_NAME)
    with pytest.raises(RuntimeError, match="Not-Snake-Case"):
        load_extensions(ctx.settings, ctx.db)


def test_missing_register_fails_loud(extension_dir: Path, ctx: ExtensionContext) -> None:
    """An extension object without a callable register() is rejected."""
    _write_pkg(extension_dir, "no_register_ext", _NO_REGISTER)
    with pytest.raises(RuntimeError, match="no_register_ext"):
        load_extensions(ctx.settings, ctx.db)


def test_real_tree_discovers_etf_grid_manifest() -> None:
    """The real package tree exposes etf_grid's manifest with name + register."""
    import spectres.extensions.etf_grid as pkg

    extension = getattr(pkg, "extension", None)
    assert extension is not None
    assert extension.name == "etf_grid"
    assert callable(extension.register)
