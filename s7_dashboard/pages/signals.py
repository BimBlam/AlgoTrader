"""
s7_dashboard/pages/signals.py

Signals page: display PENDING signals and allow per-signal approve / deny.

SOFT-mode LIVE guard (§3.2)
----------------------------
When system mode is LIVE or BOTH AND approval_mode=SOFT, an extra toggle
("Enable auto-approve for LIVE") is required in addition to the config setting.
Manual approve/deny buttons work unconditionally — the toggle only guards
bulk auto-approval (which is handled by S1, not S7).
"""
from __future__ import annotations

import json

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback_context, html, no_update

from shared.constants import SignalStatus
from shared.db import get_session
from shared.exceptions import DataError
from shared.logger import get_logger
from shared.models import Signal

from ..app import app
from ..writer import approve_signal, deny_signal

log = get_logger(__name__)


# ── Layout ────────────────────────────────────────────────────────────────────

def get_layout() -> html.Div:
    return html.Div(
        [
            html.H3("Pending Signals", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Switch(
                            id="soft-live-toggle",
                            label="Enable auto-approve for LIVE signals (requires approval_mode=SOFT)",
                            value=False,
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button("Refresh", id="signals-refresh-btn",
                                   color="secondary", size="sm"),
                        width="auto",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            dbc.Alert(id="signals-alert", is_open=False, dismissable=True),
            html.Div(id="signals-table"),
            # Interval for auto-refresh (10 s)
            dbc.Row(className="mt-2"),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("signals-table", "children"),
    Output("soft-live-enabled", "data"),  # update session store
    Input("global-interval", "n_intervals"),
    Input("signals-refresh-btn", "n_clicks"),
    Input("signals-alert", "is_open"),   # re-render after approval action
    State("soft-live-toggle", "value"),
)
def refresh_signals_table(_n, _refresh, _alert_open, soft_live_on):
    try:
        with get_session() as session:
            pending = (
                session.query(Signal)
                .filter(Signal.status == SignalStatus.PENDING.value)
                .order_by(Signal.created_at.desc())
                .all()
            )
            rows = [_signal_row(s) for s in pending]

        if not rows:
            return (
                dbc.Alert("No pending signals.", color="info"),
                soft_live_on or False,
            )

        table = dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("ID"), html.Th("Ticker"), html.Th("Strategy"),
                    html.Th("Side"), html.Th("Score"), html.Th("Sent. Adj"),
                    html.Th("Regime"), html.Th("Created"), html.Th("Notes"),
                    html.Th("Actions"),
                ])),
                html.Tbody(rows),
            ],
            bordered=True, hover=True, responsive=True, size="sm",
        )
        return table, soft_live_on or False
    except Exception as exc:
        log.error("signals_refresh_error", error=str(exc))
        return dbc.Alert(f"Error: {exc}", color="danger"), False


def _signal_row(signal: Signal) -> html.Tr:
    notes_input = dbc.Input(
        id={"type": "signal-notes", "index": signal.id},
        placeholder="Notes…",
        size="sm",
        style={"minWidth": "120px"},
    )
    approve_btn = dbc.Button(
        "✓ Approve",
        id={"type": "approve-btn", "index": signal.id},
        color="success",
        size="sm",
        className="me-1",
        n_clicks=0,
    )
    deny_btn = dbc.Button(
        "✗ Deny",
        id={"type": "deny-btn", "index": signal.id},
        color="danger",
        size="sm",
        n_clicks=0,
    )
    return html.Tr([
        html.Td(signal.id),
        html.Td(signal.ticker),
        html.Td(signal.strategy),
        html.Td(html.Span(signal.side,
                          className="text-success" if signal.side == "LONG" else "text-danger")),
        html.Td(f"{signal.raw_score:.3f}"),
        html.Td(f"{signal.sentiment_adj:.2f}"),
        html.Td(signal.regime),
        html.Td(signal.created_at.strftime("%m-%d %H:%M") if signal.created_at else ""),
        html.Td(notes_input),
        html.Td(html.Div([approve_btn, deny_btn], className="d-flex")),
    ])


@app.callback(
    Output("signals-alert", "children"),
    Output("signals-alert", "color"),
    Output("signals-alert", "is_open"),
    Input({"type": "approve-btn", "index": dash.ALL}, "n_clicks"),
    Input({"type": "deny-btn",    "index": dash.ALL}, "n_clicks"),
    State({"type": "signal-notes","index": dash.ALL}, "value"),
    prevent_initial_call=True,
)
def handle_approval(approve_clicks, deny_clicks, notes_values):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update

    trigger = ctx.triggered[0]
    trigger_id = json.loads(trigger["prop_id"].split(".")[0])
    action = trigger_id["type"].replace("-btn", "")   # "approve" or "deny"
    signal_id = trigger_id["index"]

    # Find matching notes value by index
    all_ids = [json.loads(s["id"])["index"] if isinstance(s["id"], str)
               else s["id"]["index"]
               for s in ctx.inputs_list[2]]
    notes = None
    if signal_id in all_ids:
        pos = all_ids.index(signal_id)
        notes = notes_values[pos] if pos < len(notes_values) else None

    try:
        with get_session() as session:
            if action == "approve":
                sig = approve_signal(session, signal_id, notes=notes)
                session.commit()
                return (f"Signal {signal_id} ({sig.ticker}) approved.", "success", True)
            else:
                sig = deny_signal(session, signal_id, notes=notes)
                session.commit()
                return (f"Signal {signal_id} ({sig.ticker}) denied.", "warning", True)
    except DataError as exc:
        return (str(exc), "danger", True)
    except Exception as exc:
        log.error("approval_callback_error", error=str(exc))
        return (f"Unexpected error: {exc}", "danger", True)


# Import dash here to avoid circular at module level (used inside callback body)
