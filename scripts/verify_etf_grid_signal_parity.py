#!/usr/bin/env python3
"""Verify signal parity between quant-advisor's bt_position report and the Runtime port.

For the real 513330/513120 data (trades CSVs + daily-K CSVs in
quant-advisor's ``data/``), runs the original ``report_symbol`` (in
quant-advisor's own virtualenv via subprocess, stdout parsed) and the
Runtime ``core.grid.compute_signal`` on the same inputs, then compares
close/anchor/levels/action/grids/triggers and the replayed position.

Levels, actions, grids, and share counts must match exactly; prices are
compared with a tolerance covering the original's 4-decimal print
rounding plus float-vs-Decimal representation noise.

Usage:
    uv run python scripts/verify_etf_grid_signal_parity.py
    uv run python scripts/verify_etf_grid_signal_parity.py --data-dir /path/to/data
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from spectres.extensions.etf_grid.core.grid import GridSignalInput, compute_signal, moving_average
from spectres.extensions.etf_grid.core.ledger import LedgerTrade, replay_ledger
from spectres.extensions.etf_grid.types import Side

QUANT_ADVISOR_DIR = Path("/home/dgue12306/projects/quant-advisor")
DEFAULT_DATA_DIR = QUANT_ADVISOR_DIR / "data"

# Mirrors the PORTFOLIO sizing in quant-advisor's bt_position.py for the
# two gateless symbols checked here (513530's gate needs the valuation
# series and is out of scope for this script).
SYMBOLS: dict[str, dict[str, Any]] = {
    "513330": {"full_code": "513330.XSHG", "per_grid_amount": 10000, "max_grids": 15},
    "513120": {"full_code": "513120.XSHG", "per_grid_amount": 10000, "max_grids": 8},
}
GRID_STEP = Decimal("0.05")
PRICE_TOLERANCE = Decimal("0.001")

ORIGINAL_RUNNER = """
import io, json, re, sys
from contextlib import redirect_stdout
sys.path.insert(0, {backtest_dir!r})
import bt_position as bp

def parse(sym, text):
    rec = {{"symbol": sym, "text": text}}
    m = re.search(r"\\((\\d{{4}}-\\d{{2}}-\\d{{2}}) 收盘 ([\\d.]+)\\)", text)
    rec["date"], rec["close"] = m.group(1), float(m.group(2))
    m = re.search(r"锚点\\(MA60\\) ([\\d.]+) \\| 档位 ([+-]?\\d+) \\(昨日 ([+-]?\\d+)\\) \\| 持仓折算 ([\\d.]+) 格", text)
    rec["anchor"], rec["level"], rec["prev_level"], rec["n_lots"] = float(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4))
    m = re.search(r"持有 (\\d+) 股, 平均成本 ([\\d.]+)", text)
    rec["shares"] = int(m.group(1)) if m else 0
    rec["avg_cost"] = float(m.group(2)) if m else None
    m = re.search(r"明日开盘操作: (买入|卖出) (\\d+) 格", text)
    rec["action"] = m.group(1) if m else "无"
    rec["grids"] = int(m.group(2)) if m else 0
    m = re.search(r"下一买点: 收盘跌破 ([\\d.]+)", text)
    rec["next_buy_trigger"] = float(m.group(1)) if m else None
    m = re.search(r"下一卖点: 收盘涨破 ([\\d.]+)", text)
    rec["next_sell_trigger"] = float(m.group(1)) if m else None
    return rec

out = {{}}
for sym, name, lot_value, max_levels in bp.PORTFOLIO:
    if sym not in {symbols!r}:
        continue
    buf = io.StringIO()
    with redirect_stdout(buf):
        bp.report_symbol(sym, name, lot_value, max_levels)
    out[sym] = parse(sym, buf.getvalue())
print(json.dumps(out))
"""


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def run_original(python: Path) -> dict[str, Any]:
    """Run the original report in quant-advisor's venv and return parsed values."""
    runner = ORIGINAL_RUNNER.format(backtest_dir=str(QUANT_ADVISOR_DIR / "backtest"), symbols=sorted(SYMBOLS))
    proc = subprocess.run([str(python), "-c", runner], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"error: original report failed:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)
    return cast(dict[str, Any], json.loads(proc.stdout))


def run_new(short: str, data_dir: Path) -> dict[str, Any]:
    """Compute the same day's signal with the Runtime port from the CSV data."""
    cfg = SYMBOLS[short]
    closes: list[Decimal] = []
    dates: list[date] = []
    with (data_dir / f"{short}_daily.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dates.append(_parse_date(row["date"]))
            closes.append(Decimal(row["close"]))

    trades = []
    with (data_dir / f"trades_{short}.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row["action"]:
                continue
            price = Decimal(row["price"])
            shares = int(row["shares"])
            fee = Decimal(row["fee"] or "0")
            gross = price * shares
            side = Side.BUY if row["action"] == "init" else Side(row["action"])
            net = gross - fee if side is Side.SELL else gross + fee
            trades.append(LedgerTrade(trade_date=_parse_date(row["date"]), side=side, quantity=shares, net_amount=net))
    position = replay_ledger(trades)

    anchor = moving_average(closes)
    prev_anchor = moving_average(closes[:-1])
    assert anchor is not None and prev_anchor is not None
    snapshot = compute_signal(
        GridSignalInput(
            symbol=cfg["full_code"],
            trade_date=dates[-1],
            close=closes[-1],
            prev_close=closes[-2],
            anchor=anchor,
            prev_anchor=prev_anchor,
            shares=position.shares,
            lots=position.lots,
            per_grid_amount=cfg["per_grid_amount"],
            max_grids=cfg["max_grids"],
            gate=None,
        ),
        GRID_STEP,
    )
    return {
        "date": str(dates[-1]),
        "close": closes[-1],
        "anchor": anchor,
        "level": snapshot.level,
        "prev_level": snapshot.prev_level,
        "shares": position.shares,
        "avg_cost": position.avg_cost,
        "action": snapshot.action.value,
        "grids": snapshot.grids,
        "next_buy_trigger": snapshot.next_buy_trigger,
        "next_sell_trigger": snapshot.next_sell_trigger,
    }


_ACTION_MAP = {"买入": "buy", "卖出": "sell", "无": "none"}


def close_enough(decimal_value: Decimal | None, float_value: Any) -> bool:
    """Compare a Decimal result against a float result within tolerance."""
    if decimal_value is None or float_value is None:
        return decimal_value is None and float_value is None
    return abs(decimal_value - Decimal(str(float_value))) < PRICE_TOLERANCE


def main() -> None:
    """Run both computations over the real CSVs and report per-symbol parity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    python = QUANT_ADVISOR_DIR / ".venv" / "bin" / "python"

    original = run_original(python)
    failures = 0
    for short in sorted(SYMBOLS):
        old = original[short]
        new = run_new(short, args.data_dir)
        checks = {
            "date": old["date"] == new["date"],
            "close": close_enough(new["close"], old["close"]),
            "anchor": close_enough(new["anchor"], old["anchor"]),
            "level": old["level"] == new["level"],
            "prev_level": old["prev_level"] == new["prev_level"],
            "shares": old["shares"] == new["shares"],
            "avg_cost": close_enough(new["avg_cost"], old["avg_cost"]),
            "action": _ACTION_MAP[old["action"]] == new["action"],
            "grids": old["grids"] == new["grids"],
            "next_buy_trigger": close_enough(new["next_buy_trigger"], old["next_buy_trigger"]),
            "next_sell_trigger": close_enough(new["next_sell_trigger"], old["next_sell_trigger"]),
        }
        ok = all(checks.values())
        print(f"== {SYMBOLS[short]['full_code']} ({old['date']}) ==")
        print(
            f"  old: close={old['close']} anchor={old['anchor']} level={old['level']} prev={old['prev_level']} "
            f"action={old['action']}x{old['grids']} buy_trig={old['next_buy_trigger']} sell_trig={old['next_sell_trigger']}"
        )
        print(
            f"  new: close={new['close']} anchor={new['anchor']:.6f} level={new['level']} prev={new['prev_level']} "
            f"action={new['action']}x{new['grids']} buy_trig={new['next_buy_trigger']} sell_trig={new['next_sell_trigger']}"
        )
        print(f"  position: old shares={old['shares']} avg={old['avg_cost']} | new shares={new['shares']} avg={new['avg_cost']}")
        print(f"  -> {'OK' if ok else 'MISMATCH: ' + json.dumps(checks)}")
        failures += 0 if ok else 1
    if failures:
        print(f"\n{failures} symbol(s) diverged", file=sys.stderr)
        sys.exit(1)
    print(f"\nAll {len(SYMBOLS)} symbol(s) match")


if __name__ == "__main__":
    main()
