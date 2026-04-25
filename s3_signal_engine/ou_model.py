"""
Ornstein-Uhlenbeck parameter estimation (Avellaneda-Lee methodology).

Pipeline per ticker:
  1. Rolling 60-day OLS of ticker log-return on sector ETF log-return
     → residual series (excess return relative to sector).
  2. Cumulative sum of residuals → X_t.
  3. AR(1) fit: X_t = a + b·X_{t-1} + ε
     → OU parameters:
         κ       = -ln(b) · 252        (mean-reversion speed, annualised)
         μ (m)   = a / (1 - b)         (equilibrium level)
         σ_eq    = σ_ε / sqrt(1 - b²)  (equilibrium std dev)
  4. s-score = (X_t - μ) / σ_eq        (today's deviation)

Reference: Avellaneda & Lee (2010), "Statistical Arbitrage in the
US Equities Market."
"""
import datetime
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from shared.config_loader import get_config
from shared.logger import get_logger
from shared.models import OUParam

log = get_logger(__name__)

# Minimum observations required to fit a reliable OLS + AR(1).
# Using the 60-day lookback from strategy_params but enforcing a
# floor here to avoid degenerate fits on thin history.
_MIN_OBS = 30


@dataclass
class OUResult:
    """Container for one ticker's fitted OU parameters and derived s-score."""
    ticker: str
    kappa: float
    mu: float          # equilibrium mean of cumulative residual (≡ 'm' in spec)
    sigma_eq: float    # equilibrium std dev
    beta: float        # sector ETF loading from OLS
    s_score: float     # today's (X_t - μ) / σ_eq
    valid: bool        # kappa >= min_kappa from config
    cumulative_residual: float   # X_t for today — needed by stat_arb logic


def fit_ou_params(
    returns_df: pd.DataFrame,
    etf_returns: dict[str, float],
    strategy_cfg,
    prior_ou: dict[str, dict],
) -> list[OUResult]:
    """
    Fit OU parameters for every ticker in *returns_df*.

    Requires access to the full rolling window of returns, which means
    S3 must have loaded ≥ lookback_days of history.  Today's returns
    parquet contains only the most recent row; the full window is
    assembled from the OHLCV parquet cache inside this function.

    For the rolling window requirement we load the OHLCV parquet for
    each ticker to get the last `lookback_days` of adj_close, then
    re-derive log returns on the fly.  This avoids reading multiple
    dated parquet files from disk.

    Returns a list of OUResult — one entry per ticker that has
    sufficient history.  Tickers with < _MIN_OBS valid observations are
    omitted (not written to ou_params).
    """
    cfg = _get_cfg()
    lookback = int(strategy_cfg.stat_arb.lookback_days)
    min_kappa = float(strategy_cfg.stat_arb.min_kappa)

    import pathlib
    data_dir = pathlib.Path(cfg.system.data_dir_ssd)

    results: list[OUResult] = []

    for ticker in returns_df.index:
        try:
            result = _fit_single(
                ticker=ticker,
                data_dir=data_dir,
                lookback=lookback,
                min_kappa=min_kappa,
                etf_returns=etf_returns,
                sector_etf=returns_df.loc[ticker, "sector_etf"],
                prior=prior_ou.get(ticker),
            )
            if result is not None:
                results.append(result)
        except Exception as exc:
            # One bad ticker must not abort the whole run.
            log.warning("ou_fit_failed", ticker=ticker, error=str(exc))

    log.info(
        "ou_params_fitted",
        total=len(results),
        valid=sum(r.valid for r in results),
        invalid=sum(not r.valid for r in results),
    )
    return results


def _fit_single(
    ticker: str,
    data_dir,
    lookback: int,
    min_kappa: float,
    etf_returns: dict[str, float],
    sector_etf: str,
    prior: Optional[dict],
) -> Optional[OUResult]:
    """
    Fit OU parameters for a single ticker.
    Returns None if insufficient data.
    """
    import pathlib

    ohlcv_path = pathlib.Path(data_dir) / "processed" / "ohlcv" / f"{ticker}.parquet"
    if not ohlcv_path.exists():
        log.debug("ohlcv_missing_for_ticker", ticker=ticker)
        return None

    ohlcv = pd.read_parquet(ohlcv_path)
    ohlcv.index = pd.to_datetime(ohlcv.index)
    ohlcv = ohlcv.sort_index()

    if len(ohlcv) < _MIN_OBS:
        return None

    # Use adj_close for log returns
    prices = ohlcv["adj_close"].dropna().tail(lookback + 1)
    if len(prices) < _MIN_OBS + 1:
        return None

    log_returns = np.log(prices / prices.shift(1)).dropna()

    # ── OLS: ticker_ret ~ β * etf_ret ────────────────────────────────────────
    etf_ticker = str(sector_etf) if pd.notna(sector_etf) else None
    etf_log_returns = _load_etf_log_returns(etf_ticker, data_dir, len(log_returns))

    beta, residuals = _ols_residuals(log_returns.values, etf_log_returns)

    if len(residuals) < _MIN_OBS:
        return None

    # ── AR(1) on cumulative residuals ────────────────────────────────────────
    cum_residuals = np.cumsum(residuals)
    X = cum_residuals  # X_t
    X_lag = X[:-1]
    X_curr = X[1:]

    if len(X_lag) < _MIN_OBS:
        return None

    # OLS: X_t = a + b*X_{t-1}
    A = np.column_stack([np.ones_like(X_lag), X_lag])
    try:
        coeffs, residuals_ar, _, _ = np.linalg.lstsq(A, X_curr, rcond=None)
    except np.linalg.LinAlgError:
        return None

    a_coef, b_coef = float(coeffs[0]), float(coeffs[1])

    # AR(1) requires |b| < 1 for mean reversion
    if abs(b_coef) >= 1.0 or b_coef <= 0.0:
        # b <= 0 implies anti-persistent or explosive process; not tradeable
        kappa = 0.0
        mu = 0.0
        sigma_eq = 1.0
    else:
        kappa = -math.log(b_coef) * 252  # annualised
        mu = a_coef / (1.0 - b_coef)
        ar_residuals = X_curr - (a_coef + b_coef * X_lag)
        sigma_eps = float(np.std(ar_residuals, ddof=1))
        sigma_eq = sigma_eps / math.sqrt(max(1.0 - b_coef**2, 1e-12))

    # ── s-score ───────────────────────────────────────────────────────────────
    x_today = float(cum_residuals[-1])
    s_score = (x_today - mu) / sigma_eq if sigma_eq > 1e-12 else 0.0

    valid = kappa >= min_kappa

    return OUResult(
        ticker=ticker,
        kappa=kappa,
        mu=mu,
        sigma_eq=sigma_eq,
        beta=beta,
        s_score=s_score,
        valid=valid,
        cumulative_residual=x_today,
    )


def _load_etf_log_returns(etf_ticker: Optional[str], data_dir, n_obs: int) -> np.ndarray:
    """
    Load log returns for the sector ETF aligned to n_obs length.
    Returns zeros if the ETF parquet is unavailable — OLS then yields
    zero beta and pure residuals equal to the stock's own returns.
    """
    import pathlib

    if not etf_ticker:
        return np.zeros(n_obs)

    path = pathlib.Path(data_dir) / "processed" / "ohlcv" / f"{etf_ticker}.parquet"
    if not path.exists():
        return np.zeros(n_obs)

    try:
        ohlcv = pd.read_parquet(path)
        ohlcv.index = pd.to_datetime(ohlcv.index)
        prices = ohlcv["adj_close"].dropna().tail(n_obs + 1)
        log_ret = np.log(prices / prices.shift(1)).dropna().values
        # Pad or trim to match n_obs
        if len(log_ret) < n_obs:
            return np.concatenate([np.zeros(n_obs - len(log_ret)), log_ret])
        return log_ret[-n_obs:]
    except Exception:
        return np.zeros(n_obs)


def _ols_residuals(y: np.ndarray, x: np.ndarray) -> tuple[float, np.ndarray]:
    """
    Simple OLS: y = β·x (no intercept; ETF return already has mean ~0).
    Returns (beta, residuals).
    """
    n = min(len(y), len(x))
    y, x = y[-n:], x[-n:]

    denom = float(np.dot(x, x))
    if abs(denom) < 1e-14:
        return 0.0, y.copy()

    beta = float(np.dot(x, y) / denom)
    residuals = y - beta * x
    return beta, residuals


def write_ou_params(
    session: Session,
    run_id: str,
    date: datetime.date,
    ou_results: list[OUResult],
) -> None:
    """
    Upsert OU parameters into the ou_params table.

    Uses an INSERT ... ON CONFLICT (date, ticker) DO UPDATE pattern so
    reruns are idempotent — matching the upsert pattern established in S5.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not ou_results:
        log.warning("no_ou_results_to_write", date=str(date))
        return

    rows = [
        {
            "run_id": run_id,
            "date": date,
            "ticker": r.ticker,
            "kappa": r.kappa,
            "mu": r.mu,
            "sigma_eq": r.sigma_eq,
            "beta": r.beta,
            "valid": r.valid,
        }
        for r in ou_results
    ]

    stmt = pg_insert(OUParam).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["date", "ticker"],
        set_={
            "run_id": stmt.excluded.run_id,
            "kappa": stmt.excluded.kappa,
            "mu": stmt.excluded.mu,
            "sigma_eq": stmt.excluded.sigma_eq,
            "beta": stmt.excluded.beta,
            "valid": stmt.excluded.valid,
        },
    )
    session.execute(stmt)
    log.info("ou_params_written", n=len(rows), date=str(date))


def _get_cfg():
    """Lazy config access — avoids a module-level side-effect."""
    return get_config()
