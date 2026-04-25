"""Initial schema — all tables from shared/models.py

Revision ID: 0001
Revises:
Create Date: 2026-03-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_pid", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("config_hash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("sentiment_adj", sa.Float(), nullable=False),
        sa.Column("regime", sa.Text(), nullable=False),
        sa.Column("target_size_usd", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["jobs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("ibkr_order_id", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("realised_pnl", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ou_params",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("kappa", sa.Float(), nullable=False),
        sa.Column("mu", sa.Float(), nullable=False),
        sa.Column("sigma_eq", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["jobs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "ticker", name="uq_ou_date_ticker"),
    )

    op.create_table(
        "sentiment_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("raw_mentions", sa.Integer(), nullable=False),
        sa.Column("abn_attention", sa.Float(), nullable=False),
        sa.Column("raw_sentiment", sa.Float(), nullable=False),
        sa.Column("sentiment_res", sa.Float(), nullable=False),
        sa.Column("model_used", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["jobs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "ticker", name="uq_sentiment_date_ticker"),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_range_start", sa.Date(), nullable=False),
        sa.Column("date_range_end", sa.Date(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("universe_hash", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("n_mc_paths", sa.Integer(), nullable=False),
        sa.Column("include_costs", sa.Boolean(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=True),
        sa.Column("sortino", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("pbo", sa.Float(), nullable=True),
        sa.Column("deflated_sharpe", sa.Float(), nullable=True),
        sa.Column("result_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["jobs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )

    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("subsystem", sa.Text(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_events")
    op.drop_table("backtest_runs")
    op.drop_table("sentiment_scores")
    op.drop_table("ou_params")
    op.drop_table("positions")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("jobs")
