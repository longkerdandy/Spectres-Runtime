"""Signal service: store and read computed daily signal snapshots."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spectres.extensions.etf_grid.core.grid import SignalSnapshot
from spectres.extensions.etf_grid.models import EtfGridSignal
from spectres.extensions.etf_grid.types import OrderAdvice, normalize_symbol

from .base import _SessionBound


class EtfGridSignalService(_SessionBound):
    """Stores and reads computed daily signal snapshots."""

    def upsert_signals(self, snapshots: Sequence[SignalSnapshot]) -> int:
        """Upsert signal snapshots in a single transaction.

        Upsert on recompute: on conflict of the ``(symbol, trade_date)``
        primary key the row is overwritten and ``computed_at`` refreshed —
        the signal is advice, not fact, and the latest computation is
        always the most accurate (e.g. after recording a trade).

        Returns:
            The number of rows written.
        """
        if not snapshots:
            return 0
        stmt = pg_insert(EtfGridSignal).values([_snapshot_to_row(snapshot) for snapshot in snapshots])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                "close": stmt.excluded.close,
                "anchor_ma60": stmt.excluded.anchor_ma60,
                "level": stmt.excluded.level,
                "prev_level": stmt.excluded.prev_level,
                "orders": stmt.excluded.orders,
                "block_reason": stmt.excluded.block_reason,
                "gate_metric_value": stmt.excluded.gate_metric_value,
                "gate_percentile": stmt.excluded.gate_percentile,
                "gate_closed": stmt.excluded.gate_closed,
                "computed_at": func.now(),
            },
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(snapshots)

    def latest_signal(self, symbol: str) -> dict[str, Any] | None:
        """Return the symbol's most recent signal snapshot, or None."""
        stmt = select(EtfGridSignal).where(EtfGridSignal.symbol == normalize_symbol(symbol)).order_by(EtfGridSignal.trade_date.desc()).limit(1)
        with self._session_factory() as session:
            row = session.scalars(stmt).first()
            return _signal_to_dict(row) if row else None


def _order_to_json(order: OrderAdvice) -> dict[str, Any]:
    """Serialize one order advice for the JSONB column (Decimals as strings)."""
    return {
        "side": order.side,
        "limit_price": str(order.limit_price),
        "grids": order.grids,
        "shares_est": order.shares_est,
        "kind": order.kind,
        "note": order.note,
    }


def _snapshot_to_row(snapshot: SignalSnapshot) -> dict[str, Any]:
    """Convert a computed signal snapshot into row values for upsert."""
    return {
        "symbol": snapshot.symbol,
        "trade_date": snapshot.trade_date,
        "close": snapshot.close,
        "anchor_ma60": snapshot.anchor_ma60,
        "level": snapshot.level,
        "prev_level": snapshot.prev_level,
        "orders": [_order_to_json(order) for order in snapshot.orders],
        "block_reason": snapshot.block_reason.value if snapshot.block_reason else None,
        "gate_metric_value": snapshot.gate_metric_value,
        "gate_percentile": snapshot.gate_percentile,
        "gate_closed": snapshot.gate_closed,
    }


def _signal_to_dict(signal: EtfGridSignal) -> dict[str, Any]:
    """Convert a signal ORM row into a structured dict."""
    return {
        "symbol": signal.symbol,
        "trade_date": signal.trade_date,
        "close": signal.close,
        "anchor_ma60": signal.anchor_ma60,
        "level": signal.level,
        "prev_level": signal.prev_level,
        "orders": signal.orders,
        "block_reason": signal.block_reason,
        "gate_metric_value": signal.gate_metric_value,
        "gate_percentile": signal.gate_percentile,
        "gate_closed": signal.gate_closed,
        "computed_at": signal.computed_at,
    }
