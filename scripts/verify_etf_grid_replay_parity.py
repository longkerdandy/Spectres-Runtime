#!/usr/bin/env python3
"""Verify replay parity between quant-advisor's replay_ledger and the Runtime port.

Feeds the real ``trades_*.csv`` ledgers through both implementations:
the original float-based ``replay_ledger`` (run in quant-advisor's own
virtualenv via subprocess) and the new Decimal-based
``spectres.extensions.etf_grid.core.ledger.replay_ledger``. Shares must match
exactly; monetary values are compared with a small tolerance (float vs
Decimal representation noise).

Usage:
    uv run python scripts/verify_etf_grid_replay_parity.py
    uv run python scripts/verify_etf_grid_replay_parity.py --data-dir /path/to/data
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

from spectres.extensions.etf_grid.core.ledger import LedgerTrade, replay_ledger
from spectres.extensions.etf_grid.types import Side

QUANT_ADVISOR_DIR = Path("/home/dgue12306/projects/quant-advisor")
DEFAULT_DATA_DIR = QUANT_ADVISOR_DIR / "data"
TOLERANCE = Decimal("0.000001")

ORIGINAL_RUNNER = """
import csv, json, sys
sys.path.insert(0, {backtest_dir!r})
from bt_position import replay_ledger
out = {{}}
for csv_path in sys.argv[1:]:
    with open(csv_path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["action"]]
    shares, avg_cost, realized, lots = replay_ledger(rows)
    out[csv_path] = {{
        "shares": shares,
        "avg_cost": avg_cost,
        "realized": realized,
        "lots": lots,
    }}
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


def run_original(python: Path, csv_paths: list[Path]) -> dict[str, Any]:
    """Run the original replay_ledger in quant-advisor's venv and return its results."""
    runner = ORIGINAL_RUNNER.format(backtest_dir=str(QUANT_ADVISOR_DIR / "backtest"))
    proc = subprocess.run(
        [str(python), "-c", runner, *(str(p) for p in csv_paths)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"error: original replay failed:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)
    return cast(dict[str, Any], json.loads(proc.stdout))


def run_new(csv_path: Path) -> dict[str, Any]:
    """Replay one CSV ledger with the new Decimal-based implementation."""
    trades = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row["action"]:
                continue
            price = Decimal(row["price"])
            shares = int(row["shares"])
            fee = Decimal(row["fee"] or "0")
            gross = price * shares
            # Historical `init` rows (opening-position backfill) replay as buys.
            side = Side.BUY if row["action"] == "init" else Side(row["action"])
            net = gross - fee if side is Side.SELL else gross + fee
            trades.append(LedgerTrade(trade_date=_parse_date(row["date"]), side=side, quantity=shares, net_amount=net))
    position = replay_ledger(trades)
    return {
        "shares": position.shares,
        "avg_cost": position.avg_cost,
        "realized": position.realized,
        "lots": [[lot.entry_price, lot.shares] for lot in position.lots],
    }


def close(decimal_value: Decimal | None, float_value: Any) -> bool:
    """Compare a Decimal result against a float result within tolerance."""
    if decimal_value is None or float_value is None:
        return decimal_value is None and float_value is None
    return abs(decimal_value - Decimal(str(float_value))) < TOLERANCE


def main() -> None:
    """Run both replays over the real CSVs and report per-symbol parity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    csv_paths = sorted(args.data_dir.glob("trades_*.csv"))
    if not csv_paths:
        print(f"error: no trades_*.csv files in {args.data_dir}", file=sys.stderr)
        sys.exit(1)
    python = QUANT_ADVISOR_DIR / ".venv" / "bin" / "python"

    original = run_original(python, csv_paths)
    failures = 0
    for csv_path in csv_paths:
        sym = csv_path.stem.removeprefix("trades_")
        old = original[str(csv_path)]
        new = run_new(csv_path)
        old_lots: list[list[Any]] = old["lots"]
        new_lots: list[list[Any]] = new["lots"]
        ok = (
            old["shares"] == new["shares"]
            and close(new["avg_cost"], old["avg_cost"])
            and close(new["realized"], old["realized"])
            and len(old_lots) == len(new_lots)
            and all(close(nl[0], ol[0]) and ol[1] == nl[1] for ol, nl in zip(old_lots, new_lots, strict=True))
        )
        print(f"== {sym} ({csv_path.name}) ==")
        print(f"  old: shares={old['shares']} avg_cost={old['avg_cost']} realized={old['realized']:.6f}")
        print(f"  old lots: {old_lots}")
        print(f"  new: shares={new['shares']} avg_cost={new['avg_cost']} realized={new['realized']:.6f}")
        print(f"  new lots: {new_lots}")
        print(f"  -> {'OK' if ok else 'MISMATCH'}")
        failures += 0 if ok else 1
    if failures:
        print(f"\n{failures} symbol(s) diverged", file=sys.stderr)
        sys.exit(1)
    print(f"\nAll {len(csv_paths)} symbol(s) match")


if __name__ == "__main__":
    main()
