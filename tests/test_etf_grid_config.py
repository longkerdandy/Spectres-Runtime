"""Unit tests for the ETF grid extension settings fragment."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from spectres.extensions.etf_grid.config import EtfGridConfig

pytestmark = pytest.mark.unit

_PORTFOLIO_JSON = '[{"symbol": "510300.XSHG", "name": "沪深300ETF", "per_grid_amount": 5000, "max_grids": 10}]'
_REQUIRED_ENV = {
    "ETF_GRID_PORTFOLIO": _PORTFOLIO_JSON,
    "ETF_GRID_CANDLE_LOOKBACK_DAYS": "90",
    "ETF_GRID_BACKFILL_START_DATE": "2021-01-01",
    "ETF_GRID_GRID_STEP": "0.05",
}


@pytest.fixture
def required_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Provide every required ETF_GRID_* env var; return the monkeypatch for per-test tweaks."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


class TestRequiredFields:
    """All fields except the API key are required env vars; nothing is hardcoded."""

    def test_missing_required_fields_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Construction without the required env vars fails validation."""
        for var in (*_REQUIRED_ENV, "ETF_GRID_FTSHARE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValidationError):
            EtfGridConfig(_env_file=None)  # type: ignore[call-arg]

    def test_env_vars_provide_values(self, required_env: pytest.MonkeyPatch) -> None:
        """Required env vars become typed settings fields."""
        config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
        assert config.portfolio[0].symbol == "510300.XSHG"
        assert config.portfolio[0].per_grid_amount == 5000
        assert config.portfolio[0].max_grids == 10
        assert config.candle_lookback_days == 90
        assert config.backfill_start_date == date(2021, 1, 1)
        assert config.grid_step == Decimal("0.05")

    def test_api_key_optional(self, required_env: pytest.MonkeyPatch) -> None:
        """The API key stays optional so Runtime startup never depends on it."""
        required_env.delenv("ETF_GRID_FTSHARE_API_KEY", raising=False)
        assert EtfGridConfig(_env_file=None).ftshare_api_key is None  # type: ignore[call-arg]

    def test_bare_ftshare_api_key_not_read(self, required_env: pytest.MonkeyPatch) -> None:
        """Only the prefixed ETF_GRID_FTSHARE_API_KEY var is read (no alias)."""
        required_env.delenv("ETF_GRID_FTSHARE_API_KEY", raising=False)
        required_env.setenv("FTSHARE_API_KEY", "bare-key")
        assert EtfGridConfig(_env_file=None).ftshare_api_key is None  # type: ignore[call-arg]


class TestPortfolioParsing:
    """The portfolio field parses from a JSON env var (house settings idiom)."""

    def test_invalid_json_rejected(self, required_env: pytest.MonkeyPatch) -> None:
        """A malformed JSON env var fails validation."""
        required_env.setenv("ETF_GRID_PORTFOLIO", "{not json")
        with pytest.raises(ValidationError):
            EtfGridConfig(_env_file=None)  # type: ignore[call-arg]

    def test_empty_env_rejected(self, required_env: pytest.MonkeyPatch) -> None:
        """An empty portfolio env var fails validation instead of silently defaulting."""
        required_env.setenv("ETF_GRID_PORTFOLIO", "")
        with pytest.raises(ValidationError):
            EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
