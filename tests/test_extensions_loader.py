"""Unit tests for the in-tree extension loader."""

import importlib
from pathlib import Path
from typing import cast

import pytest
from agno.db.postgres import PostgresDb

import spectres.extensions
from spectres.config import settings
from spectres.extensions.base import ExtensionContext, ExtensionContribution, LoadedExtension
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

extension = SimpleNamespace(id="good_ext", name="Good Extension", description="Good extension", register=_register)
"""

_BROKEN = """
from types import SimpleNamespace

def _register(ctx):
    raise ValueError("boom")

extension = SimpleNamespace(id="broken_ext", name="Broken Extension", description="Broken extension", register=_register)
"""

_INVALID_ID = """
from types import SimpleNamespace

extension = SimpleNamespace(id="Not-Snake-Case", name="Invalid", description="Invalid extension", register=lambda ctx: None)
"""

_NO_REGISTER = """
from types import SimpleNamespace

extension = SimpleNamespace(id="no_register_ext", name="No Register", description="No register extension")
"""

_ORDER_PROBE = """
from types import SimpleNamespace
from agno.tools.toolkit import Toolkit
from spectres.extensions.base import ExtensionContribution

extension = SimpleNamespace(id={name!r}, name={name!r}, description="Ordered extension", register=lambda ctx: ExtensionContribution(toolkits=[Toolkit(name={name!r})]))
"""


def test_scan_skips_packages_without_extension_object(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Packages without a module-level `extension` object are not extensions."""
    _write_pkg(extension_dir, "not_an_ext", '"""Just a package."""\n')
    _write_pkg(extension_dir, "good_ext", _GOOD)
    assert load_extensions(ctx.settings, ctx.db) == [LoadedExtension(id="good_ext", name="Good Extension", description="Good extension", contribution=ExtensionContribution())]


def test_non_package_entries_ignored(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Plain modules next to packages are ignored."""
    (extension_dir / "loose_module.py").write_text("x = 1\n")
    _write_pkg(extension_dir, "good_ext", _GOOD)
    assert len(load_extensions(ctx.settings, ctx.db)) == 1


def test_broken_register_fails_loud_naming_extension(extension_dir: Path, ctx: ExtensionContext, caplog: pytest.LogCaptureFixture) -> None:
    """A register() failure propagates with its cause and is not logged a second time."""
    _write_pkg(extension_dir, "broken_ext", _BROKEN)
    with pytest.raises(RuntimeError, match=r"broken_ext.*boom") as exc_info:
        load_extensions(ctx.settings, ctx.db)
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert not caplog.records


def test_broken_import_fails_loud_naming_extension(extension_dir: Path, ctx: ExtensionContext, caplog: pytest.LogCaptureFixture) -> None:
    """An import failure propagates with its cause and is not logged a second time."""
    _write_pkg(extension_dir, "import_broken_ext", 'raise ValueError("import boom")\n')
    with pytest.raises(RuntimeError, match=r"import_broken_ext.*import boom") as exc_info:
        load_extensions(ctx.settings, ctx.db)
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert not caplog.records


def test_extensions_load_in_sorted_order(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Discovery order is alphabetical by package name, independent of filesystem order."""
    _write_pkg(extension_dir, "zeta_ext", _ORDER_PROBE.format(name="zeta_ext"))
    _write_pkg(extension_dir, "alpha_ext", _ORDER_PROBE.format(name="alpha_ext"))
    extensions = load_extensions(ctx.settings, ctx.db)
    assert [extension.id for extension in extensions] == ["alpha_ext", "zeta_ext"]
    assert [extension.contribution.toolkits[0].name for extension in extensions] == ["alpha_ext", "zeta_ext"]


def test_invalid_id_fails_loud(extension_dir: Path, ctx: ExtensionContext) -> None:
    """A non-snake_case extension id is rejected before register() runs."""
    _write_pkg(extension_dir, "bad_id_pkg", _INVALID_ID)
    with pytest.raises(RuntimeError, match="Not-Snake-Case"):
        load_extensions(ctx.settings, ctx.db)


@pytest.mark.parametrize(
    "metadata",
    [
        'name="Metadata"',
        'description="Metadata extension"',
        'name=" ", description="Metadata extension"',
        'name="Metadata", description=" "',
    ],
)
def test_display_metadata_is_required(extension_dir: Path, ctx: ExtensionContext, metadata: str) -> None:
    """Display name and description must be present and non-empty."""
    body = f"""
from types import SimpleNamespace
extension = SimpleNamespace(id="metadata_ext", {metadata}, register=lambda ctx: None)
"""
    _write_pkg(extension_dir, "metadata_ext", body)
    with pytest.raises(RuntimeError, match="non-empty"):
        load_extensions(ctx.settings, ctx.db)


def test_duplicate_id_fails_loud(extension_dir: Path, ctx: ExtensionContext) -> None:
    """Two packages cannot claim the same stable Extension id."""
    _write_pkg(extension_dir, "duplicate_alpha_ext", _ORDER_PROBE.format(name="duplicate"))
    _write_pkg(extension_dir, "duplicate_zeta_ext", _ORDER_PROBE.format(name="duplicate"))
    with pytest.raises(RuntimeError, match="duplicate extension id 'duplicate'"):
        load_extensions(ctx.settings, ctx.db)


def test_missing_register_fails_loud(extension_dir: Path, ctx: ExtensionContext) -> None:
    """An extension object without a callable register() is rejected."""
    _write_pkg(extension_dir, "no_register_ext", _NO_REGISTER)
    with pytest.raises(RuntimeError, match="no_register_ext"):
        load_extensions(ctx.settings, ctx.db)


def test_real_tree_discovers_etf_grid_manifest() -> None:
    """The real package tree exposes etf_grid's metadata and register hook."""
    import spectres.extensions.etf_grid as pkg

    extension = getattr(pkg, "extension", None)
    assert extension is not None
    assert extension.id == "etf_grid"
    assert extension.name == "ETF Grid"
    assert extension.description
    assert callable(extension.register)
