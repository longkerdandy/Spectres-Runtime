"""Candle service: store and read the local forward-adjusted (qfq) daily candle cache."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spectres.extensions.etf_grid.models import EtfGridCandle
from spectres.extensions.etf_grid.types import CandleInput, normalize_symbol

from .base import _SessionBound


class EtfGridCandleService(_SessionBound):
    """Stores and reads the local forward-adjusted (qfq) daily candle cache."""

    def upsert_candles(self, candles: Sequence[CandleInput]) -> int:
        """Upsert a batch of daily candles in a single transaction.

        Upsert contract: on conflict of the ``(symbol, trade_date)`` primary
        key the OHLCV values are overwritten and ``fetched_at`` is refreshed.
        This overwrite-and-refresh behavior is deliberate self-healing, not
        just idempotency: on the qfq basis a dividend recomputes ALL
        historical bars, so re-syncing a trailing window must replace stale
        rows rather than skip them.

        Args:
            candles: The candles to write (provider-translated inputs).

        Returns:
            The number of rows written.

        Raises:
            ValueError: If any symbol fails validation, any price is not
                positive, or any volume negative.
        """
        rows = []
        for candle in candles:
            symbol = normalize_symbol(candle.symbol)
            if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
                raise ValueError(f"{symbol} {candle.trade_date}: candle prices must be positive, got O={candle.open} H={candle.high} L={candle.low} C={candle.close}")
            if candle.volume < 0:
                raise ValueError(f"{symbol} {candle.trade_date}: volume must be non-negative, got {candle.volume}")
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": candle.trade_date,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )
        if not rows:
            return 0
        stmt = pg_insert(EtfGridCandle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "fetched_at": func.now(),
            },
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(candles)

    def list_candles(
        self,
        symbol: str,
        *,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return one symbol's candles ordered by trade date.

        Time is the only meaningful sort dimension for candles, and the
        ``(symbol, trade_date)`` primary key already guarantees uniqueness —
        so unlike ``list_trades`` there is no ``SortSpec`` machinery and no
        stable-suffix rule here. If a genuine multi-dimensional need ever
        appears, add it following the trades template. ``limit`` is pushed
        down into SQL; combine with ``descending=True`` for the latest N
        bars.

        Args:
            symbol: The symbol whose history to read.
            descending: Newest first when True (default: chronological).
            limit: Optional maximum number of rows, pushed down into SQL.

        Returns:
            The candles as structured dicts in the requested order.
        """
        direction = EtfGridCandle.trade_date.desc() if descending else EtfGridCandle.trade_date.asc()
        stmt = select(EtfGridCandle).where(EtfGridCandle.symbol == normalize_symbol(symbol)).order_by(direction)
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session_factory() as session:
            return [_candle_to_dict(candle) for candle in session.scalars(stmt)]


def _candle_to_dict(candle: EtfGridCandle) -> dict[str, Any]:
    """Convert a candle ORM row into a structured dict."""
    return {
        "symbol": candle.symbol,
        "trade_date": candle.trade_date,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "fetched_at": candle.fetched_at,
    }
