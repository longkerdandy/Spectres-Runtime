"""Unit tests for the csindex valuation sync (mocked network layer)."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from spectres.extensions.etf_grid.csindex import sync_valuation
from spectres.extensions.etf_grid.service import EtfGridValuationService
from spectres.extensions.etf_grid.types import ValuationInput

pytestmark = pytest.mark.unit


def _perf_rows(closes: list[float], peg: float | None = 20.0, start: str = "20240102") -> list[dict[str, Any]]:
    """Build synthetic csindex index-perf rows with consecutive dates."""
    start_date = date(int(start[:4]), int(start[4:6]), int(start[6:]))
    rows = []
    for i, close in enumerate(closes):
        d = start_date + timedelta(days=i)
        row: dict[str, Any] = {"tradeDate": d.strftime("%Y%m%d"), "close": close}
        if peg is not None:
            row["peg"] = peg
        rows.append(row)
    return rows


class FakeValuationService(EtfGridValuationService):
    """In-memory stand-in recording upsert batches (no database)."""

    def __init__(self) -> None:
        """Set up with an empty batch log."""
        self.batches: list[list[ValuationInput]] = []

    def upsert_valuation(self, rows: Sequence[ValuationInput]) -> int:
        """Record the batch and report its size."""
        self.batches.append(list(rows))
        return len(rows)


class TestSyncValuation:
    """dyr reconstruction and row translation with a mock fetcher."""

    def fetcher(self, px_rows: list[dict[str, Any]], tr_rows: list[dict[str, Any]]) -> Any:
        """Return a fetcher that serves the price index and the TR twin."""

        def fetch(code: str) -> list[dict[str, Any]]:
            return px_rows if code == "930914" else tr_rows

        return fetch

    def test_dyr_reconstruction_and_null_window(self) -> None:
        """First 252 rows have NULL dyr; row 253 reconstructs from TR/price spread."""
        px_closes = [1000.0 + i for i in range(253)]  # px: 1000 .. 1252
        tr_closes = [1000.0 + 2 * i for i in range(253)]  # tr: 1000 .. 1504
        service = FakeValuationService()
        written = sync_valuation(
            valuation_service=service,
            fetcher=self.fetcher(_perf_rows(px_closes), _perf_rows(tr_closes, peg=None)),
        )
        assert written == 253
        rows = service.batches[0]
        assert rows[0].trade_date == date(2024, 1, 2)
        assert rows[0].dyr is None
        assert rows[251].dyr is None
        # dyr = (1504/1000) / (1252/1000) - 1 = 0.201277955... -> 0.2013
        assert rows[252].dyr == Decimal("0.2013")

    def test_close_and_pe_quantized_and_peg_mapped(self) -> None:
        """The csindex 'peg' field is PE-TTM; close/PE quantize to 2 decimals."""
        service = FakeValuationService()
        sync_valuation(
            valuation_service=service,
            fetcher=self.fetcher(_perf_rows([1234.567], peg=19.876), _perf_rows([1000.0], peg=None)),
        )
        row = service.batches[0][0]
        assert row.close == Decimal("1234.57")
        assert row.pe_ttm == Decimal("19.88")

    def test_dates_intersected_and_incomplete_rows_dropped(self) -> None:
        """Dates present in only one index, or rows without close/peg, are dropped."""
        px_rows = _perf_rows([1000.0, 1001.0], peg=20.0)
        px_rows.append({"tradeDate": "20240105", "close": 1002.0})  # no peg -> dropped
        tr_rows = _perf_rows([1000.0], peg=None)  # only the first date
        service = FakeValuationService()
        written = sync_valuation(valuation_service=service, fetcher=self.fetcher(px_rows, tr_rows))
        assert written == 1
        assert service.batches[0][0].trade_date == date(2024, 1, 2)
