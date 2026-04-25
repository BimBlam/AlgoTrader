"""
algotrader.backtest/monte_carlo.py

GARCH(1,1) Monte Carlo validation with thread-parallel path evaluation.

Changes from audit:
  - Path evaluation is parallelised with ThreadPoolExecutor (up to 8 threads
    per spec §1.3 hardware context).
  - arch simulate() is called only in the main thread (not thread-safe).
    All GARCH paths are pre-generated sequentially, then strategy simulation
    is parallelised — that\'s where the CPU time actually sits.
  - Manual GARCH(1,1) simulation replaces arch.simulate() for two reasons:
    (a) the arch result object is not guaranteed picklable across threads,
    (b) manual simulation with an explicit RNG per path gives full determinism.
  - _wrap_as_returns_df now accepts an explicit rng parameter so every call
    is fully seeded; no unseeded rng_local calls remain.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from arch import arch_model

from algotrader.shared.logger import get_logger
from algotrader.backtest.strategy_sim import simulate_strategy
from algotrader.backtest.metrics import sharpe_ratio
from algotrader.backtest.costs import TransactionCostModel

log = get_logger(__name__)

_MAX_THREADS = 8


@dataclass
class MonteCarloResult:
    path_sharpes: List[float]
    garch_params: dict


def run_monte_carlo(
    returns_df: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
) -> MonteCarloResult:
    """
    Fit GARCH(1,1) to the equal-weight universe mean return, generate
    `n_mc_paths` synthetic return paths, and evaluate strategy Sharpe on each.

    Path generation is sequential (arch is not thread-safe) but strategy
    evaluation is parallelised across up to 8 threads.

    Parameters
    ----------
    returns_df : MultiIndex (date, ticker) DataFrame
    cfg        : AppConfig
    cost_model : TransactionCostModel

    Returns
    -------
    MonteCarloResult with Sharpe distribution and GARCH parameter dict.
    """
    n_mc_paths: int = getattr(cfg.backtest, "n_mc_paths", 1000)
    base_seed:  int = getattr(cfg.backtest, "random_seed", 42)

    mean_ret = (
        returns_df["ret1d"].groupby(level="date").mean()
        .sort_index().dropna()
    )

    if len(mean_ret) < 60:
        log.warning("monte_carlo_insufficient_data", n=len(mean_ret))
        return MonteCarloResult(path_sharpes=[], garch_params={})

    # Fit GARCH — single-threaded, deterministic
    garch_params, omega, alpha, beta, mu = _fit_garch(mean_ret)
    if garch_params is None:
        return _bootstrap_fallback(returns_df, cfg, cost_model, n_mc_paths,
                                   base_seed)

    n_obs = len(mean_ret)
    all_dates = sorted(returns_df.index.get_level_values("date").unique())
    split_date = all_dates[n_obs * 3 // 4]

    # Pre-generate all synthetic paths in the main thread using manual GARCH
    # simulation so every path has a deterministic seed and no thread contention.
    synthetic_paths: list[np.ndarray] = []
    for path_idx in range(n_mc_paths):
        rng = np.random.default_rng(seed=base_seed + path_idx)
        synthetic_paths.append(
            _simulate_garch_manual(mu, omega, alpha, beta, n_obs, rng)
        )

    # Evaluate strategy on each path in parallel
    path_sharpes: list[float] = []
    n_workers = min(_MAX_THREADS, os.cpu_count() or 1, n_mc_paths)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(
                _evaluate_path,
                synthetic_paths[i],
                returns_df,
                split_date,
                cfg,
                cost_model,
                base_seed + n_mc_paths + i,  # offset so wrap-noise seeds differ
            ): i
            for i in range(n_mc_paths)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    path_sharpes.append(result)
            except Exception as exc:
                log.debug("mc_path_failed", path=futures[future], error=str(exc))

    log.info("monte_carlo_complete", n_paths_requested=n_mc_paths,
             n_successful=len(path_sharpes))
    return MonteCarloResult(path_sharpes=path_sharpes,
                            garch_params=garch_params)


def _evaluate_path(
    synthetic_returns: np.ndarray,
    returns_df: pd.DataFrame,
    split_date,
    cfg,
    cost_model: TransactionCostModel,
    wrap_seed: int,
) -> Optional[float]:
    """
    Build a synthetic DataFrame from one GARCH path, split into IS/OOS,
    run strategy simulation, and return the OOS Sharpe.

    Designed to run in a thread pool — all state is local.
    """
    rng = np.random.default_rng(seed=wrap_seed)
    synthetic_df = _wrap_as_returns_df(returns_df, synthetic_returns, rng)
    dates_level = synthetic_df.index.get_level_values("date")
    is_df  = synthetic_df.loc[dates_level <  split_date]
    oos_df = synthetic_df.loc[dates_level >= split_date]
    if is_df.empty or oos_df.empty:
        return None
    oos_ret = simulate_strategy(is_df, oos_df, cfg, cost_model)
    if oos_ret is not None and len(oos_ret) > 1:
        return sharpe_ratio(oos_ret)
    return None


def _fit_garch(mean_ret: pd.Series):
    """
    Fit GARCH(1,1) to the mean return series.

    Returns (params_dict, omega, alpha, beta, mu) on success,
    or (None, ...) on failure so the caller can fall back gracefully.
    """
    ret_pct = mean_ret * 100.0
    try:
        garch = arch_model(ret_pct, vol="Garch", p=1, q=1,
                           dist="normal", rescale=False)
        res = garch.fit(disp="off", show_warning=False)
        mu    = float(res.params.get("mu",       0.0))
        omega = float(res.params.get("omega",    1e-6))
        alpha = float(res.params.get("alpha[1]", 0.05))
        beta  = float(res.params.get("beta[1]",  0.90))
        # Clamp to stationarity: alpha + beta must be < 1
        total = alpha + beta
        if total >= 1.0:
            scale = 0.99 / total
            alpha *= scale
            beta  *= scale
        params = {"mu": mu, "omega": omega, "alpha[1]": alpha,
                  "beta[1]": beta}
        return params, omega, alpha, beta, mu
    except Exception as exc:
        log.warning("garch_fit_failed", error=str(exc))
        return None, 0.0, 0.0, 0.0, 0.0


def _simulate_garch_manual(
    mu: float,
    omega: float,
    alpha: float,
    beta: float,
    n_obs: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Simulate one GARCH(1,1) path manually using the recurrence:
        sigma²_t = omega + alpha * e²_{t-1} + beta * sigma²_{t-1}
        e_t      = sigma_t * z_t,  z_t ~ N(0,1)
        r_t      = mu + e_t

    Returns decimal returns (divided by 100 to undo percent scaling).
    Manual simulation avoids calling arch\'s simulate() in threads.
    """
    z = rng.standard_normal(n_obs)
    sigma2 = np.empty(n_obs)
    e      = np.empty(n_obs)
    sigma2[0] = omega / max(1.0 - alpha - beta, 1e-8)  # unconditional variance
    e[0] = np.sqrt(sigma2[0]) * z[0]
    for t in range(1, n_obs):
        sigma2[t] = omega + alpha * e[t - 1] ** 2 + beta * sigma2[t - 1]
        e[t] = np.sqrt(max(sigma2[t], 1e-10)) * z[t]
    return (mu + e) / 100.0  # back to decimal returns


def _wrap_as_returns_df(
    template_df: pd.DataFrame,
    synthetic_returns: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Build a synthetic MultiIndex DataFrame matching template_df\'s date/ticker
    structure with ret1d replaced by GARCH-generated base values plus
    cross-sectional noise.

    The noise uses the caller-supplied `rng` so every call is deterministic
    given the same seed — no internal unseeded RNG creation.
    """
    dates = sorted(template_df.index.get_level_values("date").unique())
    n_dates = min(len(dates), len(synthetic_returns))
    base = synthetic_returns[:n_dates]

    cross_sec_std = float(
        template_df["ret1d"].groupby(level="date").std().median()
    )
    cross_sec_std = max(cross_sec_std, 1e-6)

    rows = []
    for i in range(n_dates):
        date = dates[i]
        try:
            day_tickers = template_df.xs(date, level="date").index.tolist()
        except KeyError:
            continue
        noise = rng.normal(0, cross_sec_std, len(day_tickers))
        for j, ticker in enumerate(day_tickers):
            rows.append({"date": date, "ticker": ticker,
                         "ret1d": base[i] + noise[j]})

    df = pd.DataFrame(rows).set_index(["date", "ticker"])
    for col in template_df.columns:
        if col not in df.columns:
            df[col] = template_df[col]
    return df


def _bootstrap_fallback(
    returns_df: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
    n_mc_paths: int,
    base_seed: int,
) -> MonteCarloResult:
    """IID resample fallback when GARCH fitting fails."""
    log.warning("monte_carlo_garch_fallback_iid")
    mean_ret = returns_df["ret1d"].groupby(level="date").mean().dropna().values
    dates = sorted(returns_df.index.get_level_values("date").unique())
    split_date = dates[len(dates) * 3 // 4]
    path_sharpes = []

    n_workers = min(_MAX_THREADS, os.cpu_count() or 1, n_mc_paths)
    all_paths = []
    for i in range(n_mc_paths):
        rng = np.random.default_rng(seed=base_seed + i)
        all_paths.append(rng.choice(mean_ret, size=len(mean_ret), replace=True))

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(_evaluate_path, all_paths[i], returns_df,
                        split_date, cfg, cost_model, base_seed + n_mc_paths + i): i
            for i in range(n_mc_paths)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    path_sharpes.append(result)
            except Exception as exc:
                log.debug("mc_fallback_path_failed", error=str(exc))

    return MonteCarloResult(path_sharpes=path_sharpes, garch_params={})