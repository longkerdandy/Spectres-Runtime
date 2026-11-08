"""Database-backed instrument definitions and administrator selection."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from spectres.extensions.etf_grid.config import GateConfig, PortfolioItem
from spectres.extensions.etf_grid.models import EtfGridInstrument
from spectres.extensions.etf_grid.types import normalize_symbol

from .base import _SessionBound


class EtfGridInstrumentService(_SessionBound):
    """Persist complete instrument configuration and its enablement state."""

    def has_existing_data(self) -> bool:
        """Return whether the instrument collection has already been initialized or managed."""
        with self._session_factory() as session:
            return session.scalars(select(EtfGridInstrument.symbol).limit(1)).first() is not None

    def initialize(self, portfolio: Sequence[PortfolioItem]) -> int:
        """Insert the complete configured collection into an empty table in one transaction."""
        with self._session_factory() as session, session.begin():
            session.add_all(
                [
                    EtfGridInstrument(
                        symbol=item.symbol,
                        name=item.name,
                        per_grid_amount=item.per_grid_amount,
                        max_grids=item.max_grids,
                        gate=item.gate.model_dump() if item.gate else None,
                        sort_order=sort_order,
                        enabled=True,
                    )
                    for sort_order, item in enumerate(portfolio)
                ]
            )
        return len(portfolio)

    def list_instruments(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return stored instrument definitions in portfolio order."""
        stmt = select(EtfGridInstrument).order_by(EtfGridInstrument.sort_order, EtfGridInstrument.symbol)
        if enabled_only:
            stmt = stmt.where(EtfGridInstrument.enabled.is_(True))
        with self._session_factory() as session:
            return [_instrument_to_dict(row) for row in session.scalars(stmt)]

    def effective_portfolio(self) -> list[PortfolioItem]:
        """Return enabled stored strategy definitions in portfolio order."""
        return [_portfolio_item(row) for row in self.list_instruments(enabled_only=True)]

    def require_enabled(self, symbol: str) -> str:
        """Validate that a new operation targets an enabled stored instrument."""
        normalized = normalize_symbol(symbol)
        with self._session_factory() as session:
            row = session.get(EtfGridInstrument, normalized)
            if row is None or not row.enabled:
                raise ValueError(f"symbol is not an enabled configured instrument: {normalized}")
        return normalized

    def set_enabled(self, symbol: str, *, enabled: bool, updated_by: str) -> dict[str, Any]:
        """Change selection for an instrument stored in the database."""
        normalized = normalize_symbol(symbol)
        with self._session_factory() as session, session.begin():
            row = session.get(EtfGridInstrument, normalized)
            if row is None:
                raise ValueError(f"instrument does not exist: {normalized}")
            previous = row.enabled
            row.enabled = enabled
            row.updated_by = updated_by
            row.updated_at = func.now()
            session.flush()
        return {"symbol": normalized, "previous_enabled": previous, "enabled": enabled, "updated_by": updated_by}


def _portfolio_item(row: dict[str, Any]) -> PortfolioItem:
    return PortfolioItem(
        symbol=row["symbol"],
        name=row["name"],
        per_grid_amount=row["per_grid_amount"],
        max_grids=row["max_grids"],
        gate=GateConfig.model_validate(row["gate"]) if row["gate"] is not None else None,
    )


def _instrument_to_dict(row: EtfGridInstrument) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "name": row.name,
        "per_grid_amount": row.per_grid_amount,
        "max_grids": row.max_grids,
        "gate": row.gate,
        "enabled": row.enabled,
        "updated_by": row.updated_by,
    }
