"""Service-level tests for etf_grid portfolio status (unrealized P&L derivation)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from spectres.db.postgres import get_postgres_db
from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.core.ledger import Position
from spectres.extensions.etf_grid.models import EtfGridBase, EtfGridCandle, EtfGridSignal, EtfGridTrade, EtfGridValuation
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    get_portfolio_status,
)
from spectres.extensions.etf_grid.types import CandleInput, Side

Services = tuple[EtfGridLedgerService, EtfGridCandleService, EtfGridSignalService]


@pytest.fixture
def services() -> Services:
    """Ledger/candle/signal services over cleaned tables in real Postgres."""
    engine = get_postgres_db().db_engine
    EtfGridBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session, session.begin():
        for table in (EtfGridSignal, EtfGridValuation, EtfGridCandle, EtfGridTrade):
            session.execute(delete(table))
    return (
        EtfGridLedgerService(session_factory=session_factory),
        EtfGridCandleService(session_factory=session_factory),
        EtfGridSignalService(session_factory=session_factory),
    )


@pytest.fixture
def config() -> EtfGridConfig:
    """Portfolio config from .env.test (513330 / 513120 / 513530)."""
    return EtfGridConfig()  # type: ignore[call-arg]  # required fields come from .env.test


def _status_row(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    return next(row for row in rows if row["symbol"] == symbol)


@pytest.mark.integration
@pytest.mark.db
class TestGetPortfolioStatusUnrealized:
    """unrealized / unrealized_percent derivation and null branches."""

    def test_profit_and_loss(self, services: Services, config: EtfGridConfig) -> None:
        """Unrealized = close x shares - avg_cost x shares, for both signs."""
        ledger, candles, signals = services
        ledger.record_trade(
            trade_date=date(2026, 8, 19),
            symbol="513330.XSHG",
            side=Side.BUY,
            price=Decimal("0.4100"),
            quantity=24300,
            commission_rate=Decimal("0.001"),
            commission=Decimal("9.96"),
        )
        cost_basis = Decimal("9972.96") / 24300 * 24300  # avg_cost x shares (ledger precision)

        # Profit: close above cost basis.
        candles.upsert_candles(
            [CandleInput(symbol="513330.XSHG", trade_date=date(2026, 9, 1), open=Decimal("0.9000"), high=Decimal("0.9000"), low=Decimal("0.9000"), close=Decimal("0.9000"), volume=1000)]
        )
        row = _status_row(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals), "513330.XSHG")
        assert row["unrealized"] == Decimal("0.9000") * 24300 - cost_basis
        assert row["unrealized"] > 0
        assert row["unrealized_percent"] == row["unrealized"] / cost_basis

        # Loss: close below cost basis.
        candles.upsert_candles(
            [CandleInput(symbol="513330.XSHG", trade_date=date(2026, 9, 2), open=Decimal("0.3000"), high=Decimal("0.3000"), low=Decimal("0.3000"), close=Decimal("0.3000"), volume=1000)]
        )
        row = _status_row(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals), "513330.XSHG")
        assert row["unrealized"] == Decimal("0.3000") * 24300 - cost_basis
        assert row["unrealized"] < 0
        assert row["unrealized_percent"] == row["unrealized"] / cost_basis

    def test_null_without_position(self, services: Services, config: EtfGridConfig) -> None:
        """A symbol with candles but no position reports both fields as None."""
        ledger, candles, signals = services
        candles.upsert_candles(
            [CandleInput(symbol="513120.XSHG", trade_date=date(2026, 9, 1), open=Decimal("1.0000"), high=Decimal("1.0000"), low=Decimal("1.0000"), close=Decimal("1.0000"), volume=1000)]
        )
        row = _status_row(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals), "513120.XSHG")
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None

    def test_null_without_close(self, services: Services, config: EtfGridConfig) -> None:
        """A symbol with a position but no candles reports both fields as None."""
        ledger, candles, signals = services
        ledger.record_trade(
            trade_date=date(2026, 8, 19),
            symbol="513530.XSHG",
            side=Side.BUY,
            price=Decimal("1.0000"),
            quantity=1000,
            commission_rate=Decimal("0.001"),
            commission=Decimal("1.00"),
        )
        row = _status_row(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals), "513530.XSHG")
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None

    def test_null_percent_on_zero_cost_basis(self, services: Services, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """A zero cost basis yields unrealized but never a fabricated percent."""
        ledger, candles, signals = services
        monkeypatch.setattr(
            ledger,
            "get_positions",
            lambda: {"513330.XSHG": Position(shares=100, avg_cost=Decimal(0), realized=Decimal(0), lots=())},
        )
        candles.upsert_candles(
            [CandleInput(symbol="513330.XSHG", trade_date=date(2026, 9, 1), open=Decimal("1.0000"), high=Decimal("1.0000"), low=Decimal("1.0000"), close=Decimal("1.0000"), volume=1000)]
        )
        row = _status_row(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals), "513330.XSHG")
        assert row["unrealized"] == Decimal("1.0000") * 100
        assert row["unrealized_percent"] is None
