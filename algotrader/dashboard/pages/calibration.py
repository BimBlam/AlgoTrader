"""
algotrader.dashboard/pages/calibration.py

Calibration page: edit strategy_params.yaml with validation, preview, and
an explicit "Apply" gate that triggers S1's §6.2 backtest lifecycle.

Write contract
--------------
1.  User edits fields and clicks "Save & Validate".
2.  Dashboard validates against StrategyParamsConfig; shows error if invalid.
3.  On success: atomically writes strategy_params.yaml, writes CONFIG_CHANGED
    event → S1 queues a comparison backtest.
4.  Dashboard shows the two most recent backtest runs side-by-side as a diff.
5.  User reads the diff and confirms or reverts.

Mode switching (system.yaml: mode + approval_mode) is also on this page for
centralised configuration control.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
import yaml
from dash import Input, Output, State, html, no_update

from algotrader.shared.constants import ApprovalMode, SystemMode
from algotrader.shared.db import get_session
from algotrader.shared.exceptions import ConfigError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import BacktestRun

from ..app import app
from ..config_editor import (
    read_strategy_params,
    read_system_config,
    update_strategy_params,
    update_system_config,
)
from ..writer import write_config_changed_event, write_mode_changed_event

log = get_logger(__name__)

_VALID_MODES = [m.value for m in SystemMode]
_VALID_APPROVAL = [m.value for m in ApprovalMode]


# ── Layout ────────────────────────────────────────────────────────────────────

def get_layout() -> html.Div:
    # Load current values for initial display (best-effort; fallback to empty)
    try:
        strat = read_strategy_params()
        sys_cfg = read_system_config()
        strat_yaml = yaml.dump(strat, default_flow_style=False, sort_keys=False)
        current_mode = sys_cfg.get("mode", "PAPER")
        current_approval = sys_cfg.get("approval_mode", "HARD")
    except Exception:
        strat_yaml = ""
        current_mode = "PAPER"
        current_approval = "HARD"

    return html.Div(
        [
            html.H3("Calibration", className="mb-3"),

            # ── Mode switching ─────────────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader("System Mode"),
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            dbc.Label("Mode"),
                                            dbc.Select(
                                                id="cal-mode-select",
                                                options=[{"label": m, "value": m}
                                                         for m in _VALID_MODES],
                                                value=current_mode,
                                            ),
                                        ],
                                        width=3,
                                    ),
                                    dbc.Col(
                                        [
                                            dbc.Label("Approval Mode"),
                                            dbc.Select(
                                                id="cal-approval-select",
                                                options=[{"label": a, "value": a}
                                                         for a in _VALID_APPROVAL],
                                                value=current_approval,
                                            ),
                                        ],
                                        width=3,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            "Apply Mode Change",
                                            id="cal-mode-apply-btn",
                                            color="warning",
                                            className="mt-4",
                                            n_clicks=0,
                                        ),
                                        width="auto",
                                        className="align-self-end",
                                    ),
                                ],
                                className="g-3",
                            ),
                            dbc.Alert(id="cal-mode-alert", is_open=False,
                                      dismissable=True, className="mt-2"),
                        ]
                    ),
                ],
                className="mb-4",
            ),

            # ── Strategy params editor ─────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader("Strategy Parameters (strategy_params.yaml)"),
                    dbc.CardBody(
                        [
                            dbc.Textarea(
                                id="cal-params-editor",
                                value=strat_yaml,
                                style={"height": "350px", "fontFamily": "monospace",
                                       "fontSize": "13px"},
                                className="mb-2",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            "Save & Validate",
                                            id="cal-save-btn",
                                            color="primary",
                                            n_clicks=0,
                                        ),
                                        width="auto",
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            "Reload from File",
                                            id="cal-reload-btn",
                                            color="secondary",
                                            n_clicks=0,
                                        ),
                                        width="auto",
                                    ),
                                ],
                                className="g-2",
                            ),
                            dbc.Alert(id="cal-save-alert", is_open=False,
                                      dismissable=True, className="mt-2"),
                        ]
                    ),
                ],
                className="mb-4",
            ),

            # ── Backtest diff view ─────────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader("Recent Backtest Comparison (last 2 runs)"),
                    dbc.CardBody(html.Div(id="cal-backtest-diff")),
                ],
            ),
        ]
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("cal-save-alert", "children"),
    Output("cal-save-alert", "color"),
    Output("cal-save-alert", "is_open"),
    Input("cal-save-btn", "n_clicks"),
    State("cal-params-editor", "value"),
    prevent_initial_call=True,
)
def save_strategy_params(n_clicks, editor_value):
    if not n_clicks or not editor_value:
        return no_update, no_update, no_update
    try:
        new_data = yaml.safe_load(editor_value)
        if not isinstance(new_data, dict):
            return ("YAML must be a top-level mapping.", "danger", True)
        update_strategy_params(new_data)
        with get_session() as session:
            write_config_changed_event(session, payload={"source": "calibration_page"})
            session.commit()
        return (
            "Strategy parameters saved. S1 will schedule a comparison backtest.",
            "success",
            True,
        )
    except ConfigError as exc:
        return (f"Validation error: {exc}", "danger", True)
    except yaml.YAMLError as exc:
        return (f"YAML parse error: {exc}", "danger", True)
    except Exception as exc:
        log.error("cal_save_error", error=str(exc))
        return (f"Unexpected error: {exc}", "danger", True)


@app.callback(
    Output("cal-params-editor", "value"),
    Input("cal-reload-btn", "n_clicks"),
    prevent_initial_call=True,
)
def reload_params(n_clicks):
    try:
        strat = read_strategy_params()
        return yaml.dump(strat, default_flow_style=False, sort_keys=False)
    except Exception as exc:
        return f"# Error loading: {exc}"


@app.callback(
    Output("cal-mode-alert", "children"),
    Output("cal-mode-alert", "color"),
    Output("cal-mode-alert", "is_open"),
    Input("cal-mode-apply-btn", "n_clicks"),
    State("cal-mode-select", "value"),
    State("cal-approval-select", "value"),
    prevent_initial_call=True,
)
def apply_mode_change(n_clicks, new_mode, new_approval):
    if not n_clicks:
        return no_update, no_update, no_update
    try:
        data = read_system_config()
        data["mode"] = new_mode
        data["approval_mode"] = new_approval
        update_system_config(data)
        with get_session() as session:
            write_mode_changed_event(session, new_mode, new_approval)
            session.commit()
        return (
            f"Mode changed to {new_mode} (approval: {new_approval}). "
            f"S1 will reload config on next poll.",
            "success",
            True,
        )
    except ConfigError as exc:
        return (f"Validation error: {exc}", "danger", True)
    except Exception as exc:
        log.error("mode_change_error", error=str(exc))
        return (f"Unexpected error: {exc}", "danger", True)


@app.callback(
    Output("cal-backtest-diff", "children"),
    Input("global-interval", "n_intervals"),
)
def update_backtest_diff(_n):
    try:
        with get_session() as session:
            runs = (
                session.query(BacktestRun)
                .order_by(BacktestRun.created_at.desc())
                .limit(2)
                .all()
            )

        if len(runs) < 2:
            return dbc.Alert("Need at least 2 backtest runs to show a comparison.",
                             color="info")

        new_run, old_run = runs[0], runs[1]

        def _metric_row(label, old_val, new_val, higher_is_better=True):
            def fmt(v):
                return f"{v:.4f}" if v is not None else "—"
            if old_val is not None and new_val is not None:
                delta = new_val - old_val
                color = "text-success" if (delta > 0) == higher_is_better else "text-danger"
                delta_display = html.Span(f"{delta:+.4f}", className=color)
            else:
                delta_display = "—"
            return html.Tr([
                html.Td(label), html.Td(fmt(old_val)), html.Td(fmt(new_val)), html.Td(delta_display)
            ])

        return dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Metric"),
                    html.Th(f"Previous ({old_run.created_at.strftime('%m-%d %H:%M') if old_run.created_at else '—'})"),
                    html.Th(f"New ({new_run.created_at.strftime('%m-%d %H:%M') if new_run.created_at else '—'})"),
                    html.Th("Δ"),
                ])),
                html.Tbody([
                    _metric_row("Sharpe", old_run.sharpe, new_run.sharpe, higher_is_better=True),
                    _metric_row("Sortino", old_run.sortino, new_run.sortino, higher_is_better=True),
                    _metric_row("Max Drawdown", old_run.max_drawdown, new_run.max_drawdown, higher_is_better=False),
                    _metric_row("PBO", old_run.pbo, new_run.pbo, higher_is_better=False),
                    _metric_row("Deflated Sharpe", old_run.deflated_sharpe, new_run.deflated_sharpe, higher_is_better=True),
                ]),
            ],
            bordered=True, size="sm",
        )
    except Exception as exc:
        log.error("backtest_diff_error", error=str(exc))
        return dbc.Alert(f"Error: {exc}", color="danger")
