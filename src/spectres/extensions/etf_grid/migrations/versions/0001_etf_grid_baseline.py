"""Create the ETF Grid-owned trading and market-data baseline.

Revision ID: 0001_etf_grid_baseline
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_etf_grid_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only absent ETF Grid tables and preserve all existing rows."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("etf_grid_trades"):
        op.create_table(
            "etf_grid_trades",
            sa.Column("id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.String(length=128), nullable=False, comment="Owner of this private ledger row"),
            sa.Column("trade_date", sa.Date(), nullable=False, comment="Execution date of the trade"),
            sa.Column("symbol", sa.String(length=16), nullable=False, comment="FTShare-style symbol, e.g. '513330.XSHG'"),
            sa.Column("side", sa.String(length=8), nullable=False, comment="Trade direction: buy | sell (values generated from the Side enum)"),
            sa.Column("price", sa.Numeric(10, 4), nullable=False, comment="Execution price per share"),
            sa.Column("quantity", sa.Integer(), nullable=False, comment="Number of shares (round lots of 100)"),
            sa.Column("gross_amount", sa.Numeric(12, 2), nullable=False, comment="Turnover before fees: price * quantity"),
            sa.Column("commission_rate", sa.Numeric(8, 6), nullable=False, comment="Broker commission rate applied to gross_amount, e.g. 0.001"),
            sa.Column("commission", sa.Numeric(10, 2), nullable=False, comment="Commission charged: round(gross_amount * commission_rate, 2), overridable"),
            sa.Column("net_amount", sa.Numeric(12, 2), nullable=False, comment="Cash actually paid (buy: gross + commission) or received (sell: gross - commission)"),
            sa.Column("source", sa.String(length=32), nullable=False, comment="Entry channel: manual | agent"),
            sa.Column("note", sa.Text(), nullable=True, comment="Free-form remark, e.g. backfill semantics or reconciliation notes"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="When the row was recorded (distinct from trade_date for backfills)"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_etf_grid_trades_side"),
        )
        op.create_index("ix_etf_grid_trades_user_symbol_date_id", "etf_grid_trades", ["user_id", "symbol", "trade_date", "id"])
    if not inspector.has_table("etf_grid_candles"):
        op.create_table(
            "etf_grid_candles",
            sa.Column("symbol", sa.String(length=16), nullable=False, comment="FTShare-style symbol, e.g. '513330.XSHG'"),
            sa.Column("trade_date", sa.Date(), nullable=False, comment="Trading day of the bar"),
            sa.Column("open", sa.Numeric(10, 4), nullable=False, comment="Forward-adjusted open price"),
            sa.Column("high", sa.Numeric(10, 4), nullable=False, comment="Forward-adjusted high price"),
            sa.Column("low", sa.Numeric(10, 4), nullable=False, comment="Forward-adjusted low price"),
            sa.Column("close", sa.Numeric(10, 4), nullable=False, comment="Forward-adjusted close price"),
            sa.Column("volume", sa.BigInteger(), nullable=False, comment="Volume in shares (800M+ values exist in history)"),
            sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="When this row was last refreshed by sync (data freshness marker)"),
            sa.PrimaryKeyConstraint("symbol", "trade_date"),
        )
    if not inspector.has_table("etf_grid_valuation"):
        op.create_table(
            "etf_grid_valuation",
            sa.Column("trade_date", sa.Date(), nullable=False, comment="Trading day of the valuation row"),
            sa.Column("close", sa.Numeric(10, 2), nullable=False, comment="Price index close"),
            sa.Column("pe_ttm", sa.Numeric(10, 2), nullable=False, comment="PE-TTM of the index"),
            sa.Column("dyr", sa.Numeric(8, 4), nullable=True, comment="Trailing-12m dividend yield (0.0532 = 5.32%); NULL for the first 252 trading days, where no full trailing window exists"),
            sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="When this row was last refreshed by sync (data freshness marker)"),
            sa.PrimaryKeyConstraint("trade_date"),
        )
    if not inspector.has_table("etf_grid_signals"):
        op.create_table(
            "etf_grid_signals",
            sa.Column("user_id", sa.String(length=128), nullable=False, comment="Owner of this private signal snapshot"),
            sa.Column("symbol", sa.String(length=16), nullable=False, comment="FTShare-style symbol, e.g. '513330.XSHG'"),
            sa.Column("trade_date", sa.Date(), nullable=False, comment="Trading day the signal is for"),
            sa.Column("close", sa.Numeric(10, 4), nullable=False, comment="qfq close used for the computation"),
            sa.Column("anchor_ma60", sa.Numeric(10, 4), nullable=False, comment="MA60 anchor"),
            sa.Column("level", sa.Integer(), nullable=False, comment="Grid level today (clamped to +/- max_grids)"),
            sa.Column("prev_level", sa.Integer(), nullable=False, comment="Grid level yesterday (clamped to +/- max_grids)"),
            sa.Column(
                "orders",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                comment="Advised limit orders: [{side, limit_price, grids, shares_est, kind, note}] (triggered first, then pending buy, pending sell)",
            ),
            sa.Column("block_reason", sa.String(length=32), nullable=True, comment="Why a level change was not actionable: gate_closed | max_grids_reached | cost_protection | no_position"),
            sa.Column("gate_metric_value", sa.Numeric(8, 4), nullable=True, comment="Current gate metric (e.g. dyr 0.0532)"),
            sa.Column("gate_percentile", sa.Numeric(6, 4), nullable=True, comment="Metric percentile over full history, 0-1"),
            sa.Column("gate_closed", sa.Boolean(), nullable=True, comment="Whether the gate blocks opening new grids; NULL for gateless symbols"),
            sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="When the signal was computed"),
            sa.PrimaryKeyConstraint("user_id", "symbol", "trade_date"),
        )


def downgrade() -> None:
    """Destructive downgrades are intentionally not supported during startup."""
    raise NotImplementedError("reviewed downgrade must be run explicitly")
