"""
s7_dashboard/layout.py

Root application layout.

Structure
---------
- Navbar with page links and persistent HALT / RESUME buttons
- dcc.Location for URL routing
- dcc.Interval for global 5-second polling
- dcc.Store for session state (soft-live-approval toggle, last halt action)
- Page container (rendered by routing callback in main.py)
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

# ── Navbar ────────────────────────────────────────────────────────────────────

_NAV_LINKS = [
    dbc.NavItem(dbc.NavLink("Home",        href="/",            active="exact")),
    dbc.NavItem(dbc.NavLink("Signals",     href="/signals",     active="exact")),
    dbc.NavItem(dbc.NavLink("Backtest",    href="/backtest",    active="exact")),
    dbc.NavItem(dbc.NavLink("Calibration", href="/calibration", active="exact")),
    dbc.NavItem(dbc.NavLink("Logs",        href="/logs",        active="exact")),
]

_HALT_RESUME = dbc.ButtonGroup(
    [
        dbc.Button(
            "HALT",
            id="btn-halt",
            color="danger",
            size="sm",
            className="me-1",
            n_clicks=0,
        ),
        dbc.Button(
            "RESUME",
            id="btn-resume",
            color="success",
            size="sm",
            n_clicks=0,
        ),
    ],
    className="ms-auto",
)

navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.NavbarBrand("⚡ AlgoTrader", className="me-4"),
            dbc.Nav(_NAV_LINKS, navbar=True, className="me-auto"),
            _HALT_RESUME,
        ],
        fluid=True,
    ),
    color="dark",
    dark=True,
    sticky="top",
    className="mb-3",
)

# ── Halt/Resume confirmation modal ───────────────────────────────────────────

halt_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("Confirm HALT")),
        dbc.ModalBody("This will stop all order submission immediately. Continue?"),
        dbc.ModalFooter(
            [
                dbc.Button("Cancel", id="halt-modal-cancel", color="secondary", className="me-2"),
                dbc.Button("HALT", id="halt-modal-confirm", color="danger"),
            ]
        ),
    ],
    id="halt-modal",
    is_open=False,
)

# ── Halt/Resume action toast ──────────────────────────────────────────────────

action_toast = dbc.Toast(
    id="action-toast",
    header="Action",
    is_open=False,
    dismissable=True,
    duration=4000,
    color="info",
    style={"position": "fixed", "top": 70, "right": 20, "zIndex": 9999, "minWidth": 250},
)

# ── Root layout factory ───────────────────────────────────────────────────────

def get_layout() -> html.Div:
    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            # Global 5-second poll tick
            dcc.Interval(id="global-interval", interval=5_000, n_intervals=0),
            # Persistent stores — localStorage survives browser refresh.
            dcc.Store(id="soft-live-enabled", data=False, storage_type="local"),
            dcc.Store(id="halt-resume-store", data={"action": None}, storage_type="session"),
            # Persistent UI chrome
            navbar,
            halt_modal,
            dbc.Toast(
                id="action-toast-body",
                header="System",
                is_open=False,
                dismissable=True,
                duration=4000,
                color="info",
                style={"position": "fixed", "top": 70, "right": 20,
                       "zIndex": 9999, "minWidth": 250},
            ),
            # Page content rendered by routing callback
            html.Div(id="page-content", className="container-fluid px-4"),
        ]
    )
