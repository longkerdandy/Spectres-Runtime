"""Settings fragment for the ETF grid extension (ETF_GRID_* env vars)."""

import json
import os
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class PortfolioItem(BaseModel):
    """One tracked symbol and its grid sizing parameters."""

    symbol: str  # FTShare full code, e.g. '513330.XSHG'
    name: str
    per_grid_amount: int
    max_grids: int


_DEFAULT_PORTFOLIO: list[dict[str, Any]] = [
    {"symbol": "513330.XSHG", "name": "恒生互联网ETF", "per_grid_amount": 10000, "max_grids": 15},
    {"symbol": "513120.XSHG", "name": "港股创新药ETF", "per_grid_amount": 10000, "max_grids": 8},
    {"symbol": "513530.XSHG", "name": "港股通红利ETF", "per_grid_amount": 10000, "max_grids": 7},
]


class EtfGridConfig(BaseSettings):
    """ETF grid extension settings, loaded from ETF_GRID_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ETF_GRID_",
        env_file=os.getenv("SPECTRES_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # FTShare market data API key. Also accepts the bare FTSHARE_API_KEY env
    # var (which the SDK itself reads) for operator convenience.
    ftshare_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ETF_GRID_FTSHARE_API_KEY", "FTSHARE_API_KEY"),
    )

    # Tracked symbols with per-symbol grid sizing (JSON env var, same parsing
    # idiom as TEAM_LEADER_LLM_EXTRA_HEADERS). Defaults reproduce today's
    # 3-ETF portfolio. NoDecode leaves the raw env string for the validator
    # below — without it pydantic-settings JSON-decodes complex fields at the
    # source level and crashes on an empty value.
    portfolio: Annotated[list[PortfolioItem], NoDecode] = Field(default_factory=lambda: [PortfolioItem(**item) for item in _DEFAULT_PORTFOLIO])

    # Trailing self-healing window for candle re-syncs; covers the MA60
    # computation window so qfq re-adjustments (dividends) propagate.
    candle_lookback_days: int = 90

    # Start date for the first full backfill of a symbol with no local data.
    backfill_start_date: date = date(2021, 1, 1)

    # Grid step as a fraction (0.05 = 5%). Consumed by core/grid.py.
    grid_step: Decimal = Decimal("0.05")

    @field_validator("portfolio", mode="before")
    @classmethod
    def _parse_portfolio(cls, value: Any) -> Any:
        """Parse the portfolio value from a JSON string or leave structured input as-is."""
        if value is None or value == "":
            return _DEFAULT_PORTFOLIO
        if isinstance(value, str):
            return json.loads(value)
        return value
