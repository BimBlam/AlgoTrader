"""
s7_dashboard/pages/home.py

Home page: system state, today's P&L, open positions, recent events.

Polling: refreshed on every global-interval tick (5 s).
"""
from __future__ import annotations

from datetime import datetime, timezone

import dash_bootstrap_components as dbc
from dash import Input, Output, html

from shared.constants import PositionStatus
from shared.db import get_session
from shared.logger import get_logger
from shared.models import Position, SystemEvent

from ..app import app

log = get_logger(__name__)

# ── Layout ────────────────────────────────────────────────────────────────────

def get_layout() -> html.Div:
    return html.Div(
        [
            html.H3("System Overview", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(dbc.Card([dbc.CardHeader("System State"),
                                      dbc.CardBody(html.H4(id="home-state", children="—"))]),
                            width=3),
                    dbc.Col(dbc.Card([dbc.CardHeader("Today's Realised P&L"),
                                      dbc.CardBody(html.H4(id="home-pnl", children="—"))]),
                            width=3),
                    dbc.Col(dbc.Card([dbc.CardHeader("Open Positions"),
                                      dbc.CardBody(html.H4(id="home-open-positions", children="—"))]),
                            width=3),
                    dbc.Col(dbc.Card([dbc.CardHeader("Pending Signals"),
                                      dbc.CardBody(html.H4(id="home-pending-signals", children="—"))]),
                            width=3),
                ],
                className="mb-4",
            ),
            html.H5("Recent System Events", className="mb-2"),
            html.Div(id="home-events-table"),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("home-state", "children"),
    Output("home-pnl", "children"),
    Output("home-open-positions", "children"),
    Output("home-pending-signals", "children"),
    Output("home-events-table", "children"),
    Input("global-interval", "n_intervals"),
)
def update_home(_n):
    try:
        with get_session() as session:
            # Latest system state from events
            latest_event = (
                session.query(SystemEvent)
                .order_by(SystemEvent.timestamp.desc())
                .first()
            )
            state_display = latest_event.subsystem if latest_event else "—"

            # Today's P&L
            today_start = datetime.now(tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            closed_today = (
                session.query(Position)
                .filter(
                    Position.status == PositionStatus.CLOSED.value,
                    Position.exit_time >= today_start,
                )
                .all()
            )
            pnl = sum(p.realised_pnl or 0.0 for p in closed_today)
            pnl_color = "text-success" if pnl >= 0 else "text-danger"
            pnl_display = html.Span(f"${pnl:,.2f}", className=pnl_color)

            # Open positions count
            open_count = (
                session.query(Position)
                .filter(Position.status == PositionStatus.OPEN.value)
                .count()
            )

            # Pending signals count
            from shared.constants import SignalStatus
            from shared.models import Signal
            pending_count = (
                session.query(Signal)
                .filter(Signal.status == SignalStatus.PENDING.value)
                .count()
            )

            # Recent 25 events
            events = (
                session.query(SystemEvent)
                .order_by(SystemEvent.timestamp.desc())
                .limit(25)
                .all()
            )
            events_table = _build_events_table(events)

        return (
            state_display,
            pnl_display,
            str(open_count),
            str(pending_count),
            events_table,
        )
    except Exception as exc:
        log.error("home_update_error", error=str(exc))
        err = html.Span(f"Error: {exc}", className="text-danger")
        return "—", "—", "—", "—", err


def _build_events_table(events: list) -> dbc.Table:
    _SEVERITY_COLOR = {
        "INFO": "table-light",
        "WARNING": "table-warning",
        "ERROR": "table-danger",
        "CRITICAL": "table-danger fw-bold",
    }
    rows = [
        html.Tr(
            [
                html.Td(e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else ""),
                html.Td(e.subsystem or ""),
                html.Td(e.event_type or ""),
                html.Td(e.severity or ""),
                html.Td(e.message or "", style={"maxWidth": "500px", "wordBreak": "break-word"}),
            ],
            className=_SEVERITY_COLOR.get(e.severity or "", ""),
        )
        for e in events
    ]
    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("Timestamp"), html.Th("Subsystem"),
                html.Th("Event"), html.Th("Severity"), html.Th("Message"),
            ])),
            html.Tbody(rows),
        ],
        bordered=True,
        hover=True,
        responsive=True,
        size="sm",
        className="mt-2",
    )
