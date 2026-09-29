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
from spectres.extensions.etf_grid.csindex import fetch_index_perf, sync_valuation
from spectres.extensions.etf_grid.service import EtfGridCandleService, EtfGridValuationService
from spectres.extensions.etf_grid.types import CandleInput, normalize_symbol

CST = timezone(timedelta(hours=8))
PRICE_QUANTUM = Decimal("0.0001")

# FTShare rejects daily-K queries spanning more than 12 calendar months;
# stay safely below that when chunking long backfills.
MAX_WINDOW_DAYS = 360


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
        A mapping of symbol to the number of distinct trading days written.

    Raises:
        ValueError: If the API key is missing when a client must be
            created, or a symbol fails validation.
    """
    config = config or EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
    candle_service = candle_service or EtfGridCandleService()
    if symbols is None:
        symbols = [item.symbol for item in config.portfolio]
    if client is None:
        if not config.ftshare_api_key:
            raise ValueError("ETF_GRID_FTSHARE_API_KEY is required for market data sync")
        client = ft.market_api(api_key=config.ftshare_api_key)

    until_dt = datetime.now(CST)
    written: dict[str, int] = {}
    for raw_symbol in symbols:
        symbol = normalize_symbol(raw_symbol)
        latest = candle_service.list_candles(symbol, descending=True, limit=1)
        since = latest[0]["trade_date"] - timedelta(days=config.candle_lookback_days) if latest else config.backfill_start_date

        # Chunk long ranges: FTShare caps daily-K queries at 12 calendar
        # months. Chunks may overlap by one boundary day; dedupe below.
        bars: list[dict[str, Any]] = []
        window_start = datetime.combine(since, datetime.min.time(), tzinfo=CST)
        while window_start < until_dt:
            window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), until_dt)
            bars.extend(
                client.etf_candlesticks(
                    symbol=symbol,
                    interval_unit="Day",
                    adjust_kind="forward",
                    since_ts_millis=int(window_start.timestamp() * 1000),
                    until_ts_millis=int(window_end.timestamp() * 1000),
                    as_dataframe=False,
                )
            )
            window_start = window_end

        candles = {c.trade_date: c for c in (bar_to_candle(symbol, bar) for bar in bars)}
        written[symbol] = candle_service.upsert_candles(list(candles.values())) if candles else 0
    return written


def sync_market_data(
    *,
    config: EtfGridConfig | None = None,
    candle_service: EtfGridCandleService | None = None,
    valuation_service: EtfGridValuationService | None = None,
    client: Any | None = None,
    fetcher: Any = fetch_index_perf,
) -> dict[str, Any]:
    """Run the network refresh pipeline: candles from FTShare, valuation from csindex.

    Per-source failure is captured in the response instead of raised —
    a provider outage must not abort the other source (the API returns
    this body without a 500; the toolkit echoes it in chat). Signal
    recomputation is deliberately NOT part of this pipeline: it is a
    local-only step triggered separately (``compute_daily_signals``).

    Args:
        config: Extension settings; loaded from the environment when None.
        candle_service: Candle persistence target.
        valuation_service: Valuation persistence target.
        client: FTShare client; created from the configured key when None.
        fetcher: csindex fetch function; injectable for tests.

    Returns:
        ``{"candles": {symbol: rows} | None, "valuation": rows | None,
        "errors": {source: message}}`` — a source is None when it failed.
    """
    result: dict[str, Any] = {"candles": None, "valuation": None, "errors": {}}
    try:
        result["candles"] = sync_candles(config=config, candle_service=candle_service, client=client)
    except Exception as exc:  # provider/network failure must not abort the pipeline
        result["errors"]["candles"] = str(exc)
    try:
        result["valuation"] = sync_valuation(valuation_service=valuation_service, fetcher=fetcher)
    except Exception as exc:  # provider/network failure must not abort the pipeline
        result["errors"]["valuation"] = str(exc)
    return result
