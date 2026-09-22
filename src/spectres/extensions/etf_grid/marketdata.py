"""Market data access for the ETF grid extension (FTShare official SDK).

Only the sync orchestration lives here: computing the per-symbol fetch
window, translating provider bars into ``CandleInput``, and delegating
persistence to ``EtfGridCandleService``. SDK errors
(``FtshareHTTPError`` / ``FtshareDecodeError`` / ``FtshareAPIError``)
propagate unwrapped.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import ftshare as ft

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.service import EtfGridCandleService
from spectres.extensions.etf_grid.types import CandleInput, normalize_symbol

CST = timezone(timedelta(hours=8))
PRICE_QUANTUM = Decimal("0.0001")


def bar_to_candle(symbol: str, bar: dict[str, Any]) -> CandleInput:
    """Translate one FTShare bar row into a CandleInput.

    ``ts_millis_open`` is interpreted in CST (UTC+8, the exchange timezone);
    prices are quantized to 4 decimals (matching the historical CSV
    precision); volume is truncated to int.
    """
    trade_date = datetime.fromtimestamp(int(bar["ts_millis_open"]) / 1000, CST).date()
    return CandleInput(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(str(bar["open"])).quantize(PRICE_QUANTUM),
        high=Decimal(str(bar["high"])).quantize(PRICE_QUANTUM),
        low=Decimal(str(bar["low"])).quantize(PRICE_QUANTUM),
        close=Decimal(str(bar["close"])).quantize(PRICE_QUANTUM),
        volume=int(float(bar["volume"])),
    )


def sync_candles(
    symbols: Sequence[str] | None = None,
    *,
    client: Any | None = None,
    candle_service: EtfGridCandleService | None = None,
    config: EtfGridConfig | None = None,
) -> dict[str, int]:
    """Incrementally sync daily candles from FTShare into the local cache.

    Per symbol, the fetch window starts at ``latest_local_date -
    candle_lookback_days`` (or ``backfill_start_date`` when the symbol has
    no local data yet) and ends at now (CST). The trailing ~90-day overlap
    is deliberate self-healing: on the qfq basis a dividend recomputes ALL
    historical bars, so stale rows must be re-fetched and overwritten, not
    skipped. The original quant-advisor script's 10-day lookback only
    fixes vendor corrections — a latent flaw for dividend-paying symbols
    like 513530, deviated from deliberately.

    Args:
        symbols: Symbols to sync; ``None`` syncs the whole configured
            portfolio. Symbols are normalized and loosely validated.
        client: FTShare client; created via ``ft.market_api`` only when
            None (tests inject a mock).
        candle_service: Persistence target; defaults to the shared service.
        config: Extension settings; loaded from the environment when None.

    Returns:
        A mapping of symbol to the number of rows written.

    Raises:
        ValueError: If the API key is missing when a client must be
            created, or a symbol fails validation.
    """
    config = config or EtfGridConfig()
    candle_service = candle_service or EtfGridCandleService()
    if symbols is None:
        symbols = [item.symbol for item in config.portfolio]
    if client is None:
        if not config.ftshare_api_key:
            raise ValueError("ETF_GRID_FTSHARE_API_KEY is required for market data sync")
        client = ft.market_api(api_key=config.ftshare_api_key)

    until_ms = int(datetime.now(CST).timestamp() * 1000)
    written: dict[str, int] = {}
    for raw_symbol in symbols:
        symbol = normalize_symbol(raw_symbol)
        latest = candle_service.list_candles(symbol, descending=True, limit=1)
        since = latest[0]["trade_date"] - timedelta(days=config.candle_lookback_days) if latest else config.backfill_start_date
        since_ms = int(datetime.combine(since, datetime.min.time(), tzinfo=CST).timestamp() * 1000)
        bars = client.etf_candlesticks(
            symbol=symbol,
            interval_unit="Day",
            adjust_kind="Forward",
            since_ts_millis=since_ms,
            until_ts_millis=until_ms,
            as_dataframe=False,
        )
        candles = [bar_to_candle(symbol, bar) for bar in bars]
        written[symbol] = candle_service.upsert_candles(candles) if candles else 0
    return written
