"""
algotrader.dashboard/main.py

Dashboard entry point.

Start with:
    python -m algotrader.dashboard.main

or (from project root, venv active):
    python algotrader.dashboard/main.py

S7 is a standalone long-running web server.  It is NOT launched by S1's
process_manager — run it separately as a systemd unit or manually.

Startup sequence
----------------
1.  Load config and init DB so all page queries work immediately.
2.  Import all page modules (registers Dash callbacks as a side effect).
3.  Register the root routing callback.
4.  Attach root layout.
5.  Start the Dash/Flask development server (or hand off to gunicorn/wsgi).
"""
from __future__ import annotations


from dash import Input, Output

from algotrader.shared.config_loader import get_config
from algotrader.shared.db import init_db
from algotrader.shared.logger import get_logger

from .app import app

# Import pages — this registers all their callbacks with `app`
from .pages import backtest, calibration, home, logs, signals  # noqa: F401
from .layout import get_layout

log = get_logger(__name__)


def _register_routing_callback() -> None:
    """Map URL → page layout via a single routing callback."""
    _PAGE_MAP = {
        "/":            home.get_layout,
        "/signals":     signals.get_layout,
        "/backtest":    backtest.get_layout,
        "/calibration": calibration.get_layout,
        "/logs":        logs.get_layout,
    }

    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
    )
    def route(pathname):
        page_fn = _PAGE_MAP.get(pathname or "/", home.get_layout)
        return page_fn()

    # ── Halt/Resume button callbacks ──────────────────────────────────────────
    from dash import callback_context, no_update
    from .writer import write_halt_event, write_resume_event
    from algotrader.shared.db import get_session

    @app.callback(
        Output("halt-modal", "is_open"),
        Input("btn-halt", "n_clicks"),
        Input("halt-modal-cancel", "n_clicks"),
        Input("halt-modal-confirm", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_halt_modal(halt_clicks, cancel_clicks, confirm_clicks):
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger == "btn-halt":
            return True
        return False  # cancel or confirm both close the modal

    @app.callback(
        Output("action-toast-body", "children"),
        Output("action-toast-body", "is_open"),
        Output("action-toast-body", "color"),
        Input("halt-modal-confirm", "n_clicks"),
        Input("btn-resume", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_halt_resume(halt_confirm, resume_clicks):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            with get_session() as session:
                if trigger == "halt-modal-confirm":
                    write_halt_event(session)
                    session.commit()
                    return "HALT requested — S1 will stop order submission.", True, "danger"
                elif trigger == "btn-resume":
                    write_resume_event(session)
                    session.commit()
                    return "RESUME requested — S1 will return to IDLE.", True, "success"
        except Exception as exc:
            log.error("halt_resume_error", error=str(exc))
            return f"Error: {exc}", True, "danger"
        return no_update, no_update, no_update


def main() -> None:
    cfg = get_config()
    init_db(cfg.system.db_url)
    log.info("dashboard_startup", db_url=cfg.system.db_url[:30] + "…")

    _register_routing_callback()
    app.layout = get_layout()

    app.run(
        host="127.0.0.1",
        port=8050,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
