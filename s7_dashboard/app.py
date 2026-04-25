"""
s7_dashboard/app.py

Dash application instance.  Import ``app`` from here; never create a second
Dash instance elsewhere.

All page modules and callback modules must import ``app`` from this module.
``main.py`` sets ``app.layout`` after importing all page modules so that
callbacks are registered before the server starts.
"""
import dash
import dash_bootstrap_components as dbc

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="AlgoTrader Dashboard",
)
server = app.server  # expose Flask server for WSGI deployment
