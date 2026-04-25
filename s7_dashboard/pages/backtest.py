"""
s7_dashboard/pages/backtest.py

Backtest page: display results from the backtest_runs table.

Shows the most recent 20 runs ordered by created_at desc.
Polling every 30 seconds (backtest results change slowly).
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Input, Output, dcc, html

from shared.db import get_session
from shared.logger import get_logger
from shared.models import BacktestRun

from ..app import app

log = get_logger(__name__)

# ── Layout ────────────────────────────────────────────────────────────────────

def get_layout() -> html.Div:
    return html.Div(
        [
            html.H3("Backtest Results", className="mb-3"),
            dcc.Interval(id="backtest-interval", interval=30_000, n_intervals=0),
            html.Div(id="backtest-table"),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("backtest-table", "children"),
    Input("backtest-interval", "n_intervals"),
    Input("global-interval", "n_intervals"),
)
def update_backtest(_bt, _global):
    try:
        with get_session() as session:
            runs = (
                session.query(BacktestRun)
                .order_by(BacktestRun.created_at.desc())
                .limit(20)
                .all()
            )

        if not runs:
            return dbc.Alert("No backtest runs yet.", color="info")

        rows = [
            html.Tr([
                html.Td(r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""),
                html.Td(r.strategy or ""),
                html.Td(f"{r.sharpe:.3f}" if r.sharpe is not None else "—"),
                html.Td(f"{r.sortino:.3f}" if r.sortino is not None else "—"),
                html.Td(f"{r.max_drawdown:.3f}" if r.max_drawdown is not None else "—"),
                html.Td(f"{r.pbo:.3f}" if r.pbo is not None else "—"),
                html.Td(f"{r.deflated_sharpe:.3f}" if r.deflated_sharpe is not None else "—"),
                html.Td(r.date_range_start.isoformat() if r.date_range_start else ""),
                html.Td(r.date_range_end.isoformat() if r.date_range_end else ""),
                html.Td(r.code_version[:8] if r.code_version else ""),
            ])
            for r in runs
        ]

        return dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Run At"), html.Th("Strategy"),
                    html.Th("Sharpe"), html.Th("Sortino"), html.Th("Max DD"),
                    html.Th("PBO"), html.Th("DSR"),
                    html.Th("From"), html.Th("To"), html.Th("Code"),
                ])),
                html.Tbody(rows),
            ],
            bordered=True, hover=True, responsive=True, size="sm",
        )
    except Exception as exc:
        log.error("backtest_update_error", error=str(exc))
        return dbc.Alert(f"Error loading backtest results: {exc}", color="danger")
