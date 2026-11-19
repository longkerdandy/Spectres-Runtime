"""Live FTShare smoke test; requires a real FTSHARE API key."""

from datetime import datetime, timedelta

import pytest

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.marketdata import CST

pytestmark = pytest.mark.integration


def test_live_ftshare_fetch() -> None:
    """Live smoke: the real SDK fetches recent daily bars for one symbol."""
    import ftshare as ft

    config = EtfGridConfig()  # type: ignore[call-arg]  # reads SPECTRES_ENV_FILE for portfolio; real key from os.environ
    if not config.ftshare_api_key or config.ftshare_api_key.startswith("FAKE"):
        pytest.skip("no real FTSHARE API key configured")
    client = ft.market_api(api_key=config.ftshare_api_key)
    bars = client.etf_candlesticks(
        symbol="513330.XSHG",
        interval_unit="Day",
        adjust_kind="forward",
        since_ts_millis=int((datetime.now(CST) - timedelta(days=30)).timestamp() * 1000),
        until_ts_millis=int(datetime.now(CST).timestamp() * 1000),
        limit=3,
        as_dataframe=False,
    )
    assert bars, "expected at least one bar"
    assert {"ts_millis_open", "open", "high", "low", "close", "volume"} <= set(bars[-1])
