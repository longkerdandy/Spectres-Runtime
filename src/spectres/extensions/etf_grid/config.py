"""Settings fragment for the ETF grid extension (ETF_GRID_* env vars)."""

import json
import os
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class PortfolioItem(BaseModel):
    """One tracked symbol and its grid sizing parameters."""

    symbol: str  # FTShare full code, e.g. '513330.XSHG'
    name: str
    per_grid_amount: int
    max_grids: int


class EtfGridConfig(BaseSettings):
    """ETF grid extension settings, loaded from ETF_GRID_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ETF_GRID_",
        env_file=os.getenv("SPECTRES_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # None means "not configured"; candle sync raises a clear error at call time.
    ftshare_api_key: str | None = None

    # Tracked symbols with per-symbol grid sizing, as a JSON array env var.
    # NoDecode leaves the raw string for the validator below — without it
    # pydantic-settings JSON-decodes complex fields at the source level and
    # crashes on an empty value.
    portfolio: Annotated[list[PortfolioItem], NoDecode]

    # Trailing self-healing window for candle re-syncs; covers the MA60
    # computation window so qfq re-adjustments (dividends) propagate.
    candle_lookback_days: int

    # Start date for the first full backfill of a symbol with no local data.
    backfill_start_date: date

    # Grid step as a fraction (0.05 = 5%). Consumed by core/grid.py.
    grid_step: Decimal

    @field_validator("portfolio", mode="before")
    @classmethod
    def _parse_portfolio(cls, value: Any) -> Any:
        """Parse the portfolio value from a JSON string or leave structured input as-is."""
        if isinstance(value, str):
            return json.loads(value)
        return value
