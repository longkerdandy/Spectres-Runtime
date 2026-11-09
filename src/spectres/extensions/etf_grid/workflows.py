"""Deterministic Agno Workflows for shared sync and per-user signal recompute."""

from typing import Any

from agno.run import RunContext
from agno.workflow import Workflow
from agno.workflow.types import StepInput, StepOutput

from spectres.extensions.etf_grid.config import EtfGridConfig, load_config
from spectres.extensions.etf_grid.marketdata import sync_market_data
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
    to_jsonable,
)

DATA_SYNC_WORKFLOW_ID = "etf_grid_data_sync"
RECOMPUTE_WORKFLOW_ID = "etf_grid_recompute"


def create_workflows(
    *,
    config: EtfGridConfig | None = None,
    ledger_service: EtfGridLedgerService | None = None,
    candle_service: EtfGridCandleService | None = None,
    valuation_service: EtfGridValuationService | None = None,
    signal_service: EtfGridSignalService | None = None,
) -> list[Workflow]:
    """Build the extension's system-sync and owner-scoped recompute Workflows."""
    config = config or load_config()
    ledger = ledger_service or EtfGridLedgerService()
    candles = candle_service or EtfGridCandleService()
    valuation = valuation_service or EtfGridValuationService()
    signals = signal_service or EtfGridSignalService()

    def data_sync(step_input: StepInput, run_context: RunContext | None = None) -> StepOutput:
        del step_input, run_context
        result = sync_market_data(config=config, candle_service=candles, valuation_service=valuation)
        content = to_jsonable(result)
        if result["candles"] is None and result["valuation"] is None:
            return StepOutput(content=content, success=False, error=f"all data sources failed: {result['errors']}")
        return StepOutput(content=content)

    def recompute(step_input: StepInput, run_context: RunContext | None = None) -> StepOutput:
        del step_input
        if run_context is None or not run_context.user_id:
            return StepOutput(success=False, error="authenticated workflow user_id is required")
        result: dict[str, Any] = compute_daily_signals(
            user_id=run_context.user_id,
            config=config,
            ledger_service=ledger,
            candle_service=candles,
            valuation_service=valuation,
            signal_service=signals,
        )
        return StepOutput(content=to_jsonable(result))

    return [
        Workflow(
            id=DATA_SYNC_WORKFLOW_ID,
            name="ETF Grid Data Sync",
            description="Synchronize shared ETF market and valuation data without recomputing user signals.",
            steps=[data_sync],
        ),
        Workflow(
            id=RECOMPUTE_WORKFLOW_ID,
            name="ETF Grid Recompute",
            description="Recompute grid signals for the authenticated Workflow run owner using the latest persisted shared data.",
            steps=[recompute],
        ),
    ]
