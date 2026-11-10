"""Signal service: store and read computed daily signal snapshots."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.etf_grid.core.grid import SignalSnapshot
from spectres.extensions.etf_grid.models import EtfGridSignal
from spectres.extensions.etf_grid.types import OrderAdvice, normalize_symbol

from .identity import _require_user_id


class EtfGridSignalService:
    """Stores and reads computed daily signal snapshots."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Create the service with an explicitly injected session factory."""
        self._session_factory = session_factory

    def upsert_signals(self, snapshots: Sequence[SignalSnapshot], *, user_id: str) -> int:
        """Upsert one owner's signal snapshots in a single transaction."""
        user_id = _require_user_id(user_id)
        if not snapshots:
            return 0
        stmt = pg_insert(EtfGridSignal).values([_snapshot_to_row(snapshot, user_id=user_id) for snapshot in snapshots])
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "symbol", "trade_date"],
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

    def latest_signal(self, symbol: str, *, user_id: str) -> dict[str, Any] | None:
        """Return one owner's most recent signal for a symbol."""
        return self.latest_signals([symbol], user_id=user_id).get(normalize_symbol(symbol))

    def latest_signals(self, symbols: Sequence[str], *, user_id: str) -> dict[str, dict[str, Any]]:
        """Return one owner's latest signals in a single query."""
        user_id = _require_user_id(user_id)
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        if not normalized:
            return {}
        stmt = (
            select(EtfGridSignal)
            .where(EtfGridSignal.user_id == user_id, EtfGridSignal.symbol.in_(normalized))
            .distinct(EtfGridSignal.user_id, EtfGridSignal.symbol)
            .order_by(EtfGridSignal.user_id, EtfGridSignal.symbol, EtfGridSignal.trade_date.desc())
        )
        with self._session_factory() as session:
            return {signal.symbol: _signal_to_dict(signal) for signal in session.scalars(stmt)}


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


def _snapshot_to_row(snapshot: SignalSnapshot, *, user_id: str) -> dict[str, Any]:
    """Convert a computed signal snapshot into owned row values."""
    return {
        "user_id": user_id,
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
        "user_id": signal.user_id,
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
