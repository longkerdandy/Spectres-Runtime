"""Real-PostgreSQL tests for built-in Extension activation state."""

import logging

import pytest

from spectres.db.postgres import get_postgres_db
from spectres.extensions.state import ExtensionStateService

pytestmark = pytest.mark.db


def _service(*names: str) -> ExtensionStateService:
    return ExtensionStateService(get_postgres_db(), names)


def test_new_extensions_default_to_enabled() -> None:
    """Newly discovered Extensions receive enabled bootstrap rows."""
    service = _service("alpha", "beta")
    service.initialize()

    states = service.list_states()

    assert [(state.id, state.enabled) for state in states] == [("alpha", True), ("beta", True)]
    assert service.is_enabled("alpha") is True


def test_restart_preserves_administrator_choice() -> None:
    """Additive initialization never overwrites a stored disabled state."""
    _service("alpha").initialize()
    _service("alpha").set_enabled("alpha", enabled=False, updated_by="operator")

    restarted = _service("alpha")
    restarted.initialize()

    assert restarted.is_enabled("alpha") is False
    state = restarted.list_states()[0]
    assert state.enabled is False


def test_unknown_or_missing_extension_fails_closed() -> None:
    """Unknown ids cannot execute or receive administrator updates."""
    service = _service("alpha")
    service.initialize()

    assert service.is_enabled("missing") is False
    with pytest.raises(KeyError):
        service.set_enabled("missing", enabled=False, updated_by="operator")


def test_removed_extension_is_not_in_current_catalog() -> None:
    """State for code no longer discovered is retained but not listed."""
    _service("removed", "current").initialize()

    current = _service("current")
    current.initialize()

    assert [state.id for state in current.list_states()] == ["current"]
    assert current.is_enabled("removed") is False


def test_state_change_emits_audit_event(caplog: pytest.LogCaptureFixture) -> None:
    """An administrator state change records its identity and before/after state."""
    service = _service("alpha")
    service.initialize()

    with caplog.at_level(logging.INFO, logger="spectres.extensions.state"):
        result = service.set_enabled("alpha", enabled=False, updated_by="operator")

    assert result.enabled is False
    record = next(record for record in caplog.records if record.__dict__["event"] == "extension_activation_updated")
    assert record.__dict__["extension_name"] == "alpha"
    assert record.__dict__["updated_by"] == "operator"
    assert record.__dict__["previous_enabled"] is True
    assert record.__dict__["enabled"] is False
