"""Administrator selection and effective-portfolio resolution."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spectres.extensions.etf_grid.config import EtfGridConfig, PortfolioItem
from spectres.extensions.etf_grid.models import EtfGridInstrument
from spectres.extensions.etf_grid.types import normalize_symbol

from .base import _SessionBound


class EtfGridInstrumentService(_SessionBound):
    """Persist symbol selection while configuration owns strategy parameters."""

    def bootstrap(self, symbols: Sequence[str]) -> None:
        """Insert missing configured symbols without changing existing choices."""
        normalized = sorted({normalize_symbol(symbol) for symbol in symbols})
        if not normalized:
            return
        stmt = pg_insert(EtfGridInstrument).values([{"symbol": symbol, "enabled": True} for symbol in normalized])
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol"])
        with self._session_factory() as session, session.begin():
            session.execute(stmt)

    def list_instruments(self, *, config: EtfGridConfig, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return configured strategy definitions joined to their selection state."""
        with self._session_factory() as session:
            rows = {row.symbol: row for row in session.scalars(select(EtfGridInstrument))}
        instruments: list[dict[str, Any]] = []
        for item in config.portfolio:
            row = rows.get(item.symbol)
            if row is None or (enabled_only and not row.enabled):
                continue
            instruments.append({**item.model_dump(), "enabled": row.enabled, "updated_by": row.updated_by})
        return instruments

    def effective_portfolio(self, *, config: EtfGridConfig) -> list[PortfolioItem]:
        """Return enabled configured items in their configuration order."""
        enabled = {row["symbol"] for row in self.list_instruments(config=config, enabled_only=True)}
        return [item for item in config.portfolio if item.symbol in enabled]

    def require_enabled(self, symbol: str, *, config: EtfGridConfig) -> str:
        """Validate that a new operation targets an enabled configured symbol."""
        normalized = normalize_symbol(symbol)
        if normalized not in {item.symbol for item in self.effective_portfolio(config=config)}:
            raise ValueError(f"symbol is not an enabled configured instrument: {normalized}")
        return normalized

    def set_enabled(self, symbol: str, *, enabled: bool, updated_by: str, config: EtfGridConfig) -> dict[str, Any]:
        """Change selection for a symbol that exists in configuration."""
        normalized = normalize_symbol(symbol)
        if normalized not in {item.symbol for item in config.portfolio}:
            raise ValueError(f"symbol is not present in ETF_GRID_PORTFOLIO: {normalized}")
        with self._session_factory() as session, session.begin():
            row = session.get(EtfGridInstrument, normalized)
            if row is None:
                raise ValueError(f"instrument selection has not been bootstrapped: {normalized}")
            previous = row.enabled
            row.enabled = enabled
            row.updated_by = updated_by
            row.updated_at = func.now()
            session.flush()
        return {"symbol": normalized, "previous_enabled": previous, "enabled": enabled, "updated_by": updated_by}
