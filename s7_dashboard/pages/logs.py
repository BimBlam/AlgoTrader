"""
s7_dashboard/pages/logs.py

Logs page: tail of system_events with severity and subsystem filters.

Polling every 5 seconds via the global interval.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import Input, Output, html

from shared.constants import Severity
from shared.db import get_session
from shared.logger import get_logger
from shared.models import SystemEvent

from ..app import app

log = get_logger(__name__)

_SEVERITIES = ["ALL"] + [s.value for s in Severity]
_SUBSYSTEMS = ["ALL", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "SYSTEM"]
_SEVERITY_COLOR = {
    "INFO":     "table-light",
    "WARNING":  "table-warning",
    "ERROR":    "table-danger",
    "CRITICAL": "table-danger fw-bold",
}


# ── Layout ────────────────────────────────────────────────────────────────────

def get_layout() -> html.Div:
    return html.Div(
        [
            html.H3("System Logs", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Severity"),
                            dbc.Select(
                                id="log-severity-filter",
                                options=[{"label": s, "value": s} for s in _SEVERITIES],
                                value="ALL",
                            ),
                        ],
                        width=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Subsystem"),
                            dbc.Select(
                                id="log-subsystem-filter",
                                options=[{"label": s, "value": s} for s in _SUBSYSTEMS],
                                value="ALL",
                            ),
                        ],
                        width=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("Max rows"),
                            dbc.Select(
                                id="log-limit-select",
                                options=[{"label": str(n), "value": n}
                                         for n in [50, 100, 200, 500]],
                                value=100,
                            ),
                        ],
                        width=2,
                    ),
                ],
                className="mb-3 g-3",
            ),
            html.Div(id="logs-table"),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("logs-table", "children"),
    Input("global-interval", "n_intervals"),
    Input("log-severity-filter", "value"),
    Input("log-subsystem-filter", "value"),
    Input("log-limit-select", "value"),
)
def update_logs(_n, severity_filter, subsystem_filter, limit):
    try:
        with get_session() as session:
            query = session.query(SystemEvent).order_by(SystemEvent.timestamp.desc())
            if severity_filter and severity_filter != "ALL":
                query = query.filter(SystemEvent.severity == severity_filter)
            if subsystem_filter and subsystem_filter != "ALL":
                query = query.filter(SystemEvent.subsystem == subsystem_filter)
            events = query.limit(int(limit) if limit else 100).all()

        if not events:
            return dbc.Alert("No log entries match the current filter.", color="info")

        rows = [
            html.Tr(
                [
                    html.Td(e.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                            if e.timestamp else ""),
                    html.Td(e.subsystem or ""),
                    html.Td(e.event_type or ""),
                    html.Td(e.severity or ""),
                    html.Td(e.message or "",
                            style={"maxWidth": "600px", "wordBreak": "break-word"}),
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
            bordered=True, hover=True, responsive=True, size="sm",
        )
    except Exception as exc:
        log.error("logs_update_error", error=str(exc))
        return dbc.Alert(f"Error loading logs: {exc}", color="danger")
