"""Valuation service: store and read the 930914 index valuation series (gate input)."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spectres.extensions.etf_grid.models import EtfGridValuation
from spectres.extensions.etf_grid.types import ValuationInput

from .base import _SessionBound


class EtfGridValuationService(_SessionBound):
    """Stores and reads the 930914 index valuation series (gate input)."""

    def upsert_valuation(self, rows: Sequence[ValuationInput]) -> int:
        """Upsert valuation rows in a single transaction.

        Upsert semantics match candles: on conflict of the ``trade_date``
        primary key the values are overwritten and ``fetched_at`` refreshed,
        so csindex history revisions self-heal.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0
        stmt = pg_insert(EtfGridValuation).values([{"trade_date": row.trade_date, "close": row.close, "pe_ttm": row.pe_ttm, "dyr": row.dyr} for row in rows])
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_date"],
            set_={"close": stmt.excluded.close, "pe_ttm": stmt.excluded.pe_ttm, "dyr": stmt.excluded.dyr, "fetched_at": func.now()},
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(rows)

    def list_valuation(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return valuation rows oldest-first (the gate needs the full series for percentiles)."""
        stmt = select(EtfGridValuation).order_by(EtfGridValuation.trade_date.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session_factory() as session:
            return [_valuation_to_dict(row) for row in session.scalars(stmt)]


def _valuation_to_dict(row: EtfGridValuation) -> dict[str, Any]:
    """Convert a valuation ORM row into a structured dict."""
    return {
        "trade_date": row.trade_date,
        "close": row.close,
        "pe_ttm": row.pe_ttm,
        "dyr": row.dyr,
        "fetched_at": row.fetched_at,
    }
