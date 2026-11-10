"""Unit tests for ETF Grid deterministic Workflow steps."""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from agno.run import RunContext
from agno.workflow import Workflow
from agno.workflow.types import StepInput, StepOutput

from spectres.extensions.etf_grid.service import EtfGridCandleService, EtfGridLedgerService, EtfGridSignalService, EtfGridValuationService
from spectres.extensions.etf_grid.workflows import create_workflows

pytestmark = pytest.mark.unit


def _create_workflows() -> list[Workflow]:
    return create_workflows(
        ledger_service=MagicMock(spec=EtfGridLedgerService),
        candle_service=MagicMock(spec=EtfGridCandleService),
        valuation_service=MagicMock(spec=EtfGridValuationService),
        signal_service=MagicMock(spec=EtfGridSignalService),
    )


def _execute(workflow: Workflow, *, user_id: str | None = None, step_input: StepInput | None = None) -> StepOutput:
    assert isinstance(workflow.steps, list)
    executor = cast(Any, workflow.steps[0])
    context = RunContext(run_id="run-1", session_id="session-1", user_id=user_id) if user_id is not None else None
    return cast(StepOutput, executor(step_input or StepInput(), run_context=context))


def test_sync_workflow_only_synchronizes_shared_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """The system Workflow has no per-user signal fan-out."""
    sync = MagicMock(return_value={"candles": {"513330.XSHG": 2}, "valuation": 3, "errors": {}})
    recompute = MagicMock()
    monkeypatch.setattr("spectres.extensions.etf_grid.workflows.sync_market_data", sync)
    monkeypatch.setattr("spectres.extensions.etf_grid.workflows.compute_daily_signals", recompute)
    sync_workflow, _ = _create_workflows()

    result = _execute(sync_workflow)

    assert result.success is True
    assert result.content == {"candles": {"513330.XSHG": 2}, "valuation": 3, "errors": {}}
    sync.assert_called_once()
    recompute.assert_not_called()


def test_sync_workflow_accepts_partial_source_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """One available source keeps the scheduled sync successful and exposes errors."""
    monkeypatch.setattr(
        "spectres.extensions.etf_grid.workflows.sync_market_data",
        lambda **kwargs: {"candles": None, "valuation": 3, "errors": {"candles": "boom"}},
    )
    sync_workflow, _ = _create_workflows()

    result = _execute(sync_workflow)

    assert result.success is True
    assert result.content == {"candles": None, "valuation": 3, "errors": {"candles": "boom"}}


def test_sync_workflow_fails_when_all_sources_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Total source failure is visible to Agno as a failed step."""
    monkeypatch.setattr(
        "spectres.extensions.etf_grid.workflows.sync_market_data",
        lambda **kwargs: {"candles": None, "valuation": None, "errors": {"candles": "boom", "valuation": "boom"}},
    )
    sync_workflow, _ = _create_workflows()

    result = _execute(sync_workflow)

    assert result.success is False
    assert "all data sources failed" in (result.error or "")


def test_recompute_workflow_requires_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unowned run cannot recompute private signals."""
    recompute = MagicMock()
    monkeypatch.setattr("spectres.extensions.etf_grid.workflows.compute_daily_signals", recompute)
    _, recompute_workflow = _create_workflows()

    result = _execute(recompute_workflow)

    assert result.success is False
    assert "user_id is required" in (result.error or "")
    recompute.assert_not_called()


def test_recompute_workflow_uses_run_context_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Input cannot impersonate another user; only RunContext selects the ledger."""
    recompute = MagicMock(return_value={"signals": {}, "skipped": {}})
    monkeypatch.setattr("spectres.extensions.etf_grid.workflows.compute_daily_signals", recompute)
    _, recompute_workflow = _create_workflows()

    result = _execute(recompute_workflow, user_id="alice", step_input=StepInput(input={"user_id": "bob"}))

    assert result.success is True
    assert recompute.call_args.kwargs["user_id"] == "alice"
