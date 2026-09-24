"""csindex.com.cn public JSON API wrapper for the 930914 valuation series.

csindex is the only source for the 930914 dividend-yield series the
valuation gate needs (no FTShare endpoint carries dividend yield). Pure
stdlib (``http.client`` + ``json``) — a port of quant-advisor's
``backtest/update_valuation.py``. The raw fetch and the sync
orchestration are separate functions so tests can mock the network
layer without touching persistence.
"""

import http.client
import json
import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from spectres.extensions.etf_grid.service import EtfGridValuationService
from spectres.extensions.etf_grid.types import ValuationInput

HOST = "www.csindex.com.cn"
PATH = "/csindex-home/perf/index-perf?indexCode={code}&startDate=20161125&endDate=20991231"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

PRICE_INDEX_CODE = "930914"
TOTAL_RETURN_INDEX_CODE = "H20914"
TRADING_DAYS_PER_YEAR = 252
MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 3


def fetch_index_perf(code: str) -> list[dict[str, Any]]:
    """Fetch the full daily history of one index from csindex.

    Bounded retries (5 attempts, 3s backoff — same as the original
    script, which the endpoint's flakiness taught us). Returns the
    payload's ``data`` list.

    Raises:
        RuntimeError: After all attempts fail or return empty data.
    """
    for _attempt in range(MAX_ATTEMPTS):
        conn = http.client.HTTPSConnection(HOST, timeout=60)
        try:
            conn.request("GET", PATH.format(code=code), headers={"User-Agent": USER_AGENT})
            payload = json.loads(conn.getresponse().read())
            rows = payload.get("data") or []
            if rows:
                return rows
        except (http.client.HTTPException, json.JSONDecodeError, OSError):
            pass
        finally:
            conn.close()
        time.sleep(RETRY_BACKOFF_SECONDS)
    raise RuntimeError(f"fetch {code} failed after retries")


def sync_valuation(
    valuation_service: EtfGridValuationService | None = None,
    fetcher: Callable[[str], list[dict[str, Any]]] = fetch_index_perf,
) -> int:
    """Sync the 930914 valuation series into etf_grid_valuation.

    Fetches the 930914 price index (close + PE-TTM — csindex names the
    PE field ``peg``) and its H20914 total-return twin, then reconstructs
    the trailing-12m dividend yield as ``(TR 252d return / price 252d
    return) - 1`` for rows with a full trailing window (i >= 252; NULL
    otherwise). Matches the official D/P2 within ~0.1pp per
    quant-advisor. All rows are upserted.

    Args:
        valuation_service: Persistence target; defaults to the shared service.
        fetcher: Network layer; injectable for tests.

    Returns:
        The number of rows written.
    """
    px = {r["tradeDate"]: (r["close"], r["peg"]) for r in fetcher(PRICE_INDEX_CODE) if r.get("close") and r.get("peg") is not None}
    tr = {r["tradeDate"]: r["close"] for r in fetcher(TOTAL_RETURN_INDEX_CODE) if r.get("close")}
    dates = sorted(set(px) & set(tr))

    rows = []
    for i, d in enumerate(dates):
        dyr = None
        if i >= TRADING_DAYS_PER_YEAR:
            d0 = dates[i - TRADING_DAYS_PER_YEAR]
            dyr = Decimal(str((tr[d] / tr[d0]) / (px[d][0] / px[d0][0]) - 1)).quantize(Decimal("0.0001"))
        rows.append(
            ValuationInput(
                trade_date=date(int(d[:4]), int(d[4:6]), int(d[6:])),
                close=Decimal(str(px[d][0])).quantize(Decimal("0.01")),
                pe_ttm=Decimal(str(px[d][1])).quantize(Decimal("0.01")),
                dyr=dyr,
            )
        )

    service = valuation_service or EtfGridValuationService()
    service.upsert_valuation(rows)
    return len(rows)
