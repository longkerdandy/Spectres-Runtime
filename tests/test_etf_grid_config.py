"""Unit tests for the ETF grid extension settings fragment."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsError

from spectres.extensions.etf_grid.config import EtfGridConfig

pytestmark = pytest.mark.unit


class TestEtfGridConfigDefaults:
    """Defaults reproduce the current 3-ETF portfolio and sync windows."""

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All fields fall back to their defaults without env vars."""
        for var in ("ETF_GRID_FTSHARE_API_KEY", "FTSHARE_API_KEY", "ETF_GRID_PORTFOLIO"):
            monkeypatch.delenv(var, raising=False)
        config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.ftshare_api_key is None
        assert [(item.symbol, item.per_grid_amount, item.max_grids) for item in config.portfolio] == [
            ("513330.XSHG", 10000, 15),
            ("513120.XSHG", 10000, 8),
            ("513530.XSHG", 10000, 7),
        ]
        assert config.candle_lookback_days == 90
        assert config.backfill_start_date == date(2021, 1, 1)
        assert config.grid_step == Decimal("0.05")

    def test_bare_ftshare_api_key_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bare FTSHARE_API_KEY env var (also read by the SDK) is accepted."""
        monkeypatch.delenv("ETF_GRID_FTSHARE_API_KEY", raising=False)
        monkeypatch.setenv("FTSHARE_API_KEY", "bare-key")
        assert EtfGridConfig(_env_file=None).ftshare_api_key == "bare-key"  # type: ignore[call-arg]

    def test_prefixed_key_wins_over_bare(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ETF_GRID_FTSHARE_API_KEY takes precedence over the bare alias."""
        monkeypatch.setenv("ETF_GRID_FTSHARE_API_KEY", "prefixed-key")
        monkeypatch.setenv("FTSHARE_API_KEY", "bare-key")
        assert EtfGridConfig(_env_file=None).ftshare_api_key == "prefixed-key"  # type: ignore[call-arg]


class TestPortfolioParsing:
    """The portfolio field parses from a JSON env var (house settings idiom)."""

    def test_json_env_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A JSON array env var becomes typed PortfolioItem entries."""
        monkeypatch.setenv(
            "ETF_GRID_PORTFOLIO",
            '[{"symbol": "510300.XSHG", "name": "沪深300ETF", "per_grid_amount": 5000, "max_grids": 10}]',
        )
        config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
        assert len(config.portfolio) == 1
        item = config.portfolio[0]
        assert item.symbol == "510300.XSHG"
        assert item.per_grid_amount == 5000
        assert item.max_grids == 10

    def test_empty_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty env value (as shipped in .env.example) means 'use the default portfolio'."""
        monkeypatch.setenv("ETF_GRID_PORTFOLIO", "")
        config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
        assert len(config.portfolio) == 3

    def test_invalid_json_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed JSON env var fails validation."""
        monkeypatch.setenv("ETF_GRID_PORTFOLIO", "{not json")
        with pytest.raises((SettingsError, ValidationError)):
            EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
