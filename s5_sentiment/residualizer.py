"""
Residualization layer for S5.

Regresses today's raw_sentiment for each ticker against:
  1. lagged raw_sentiment (mean of the prior 5 trading days)
  2. lagged abn_attention (mean of the prior 5 trading days)

The OLS residual is stored as ``sentiment_res``.  This removes the
autocorrelation component from the sentiment signal so that S3 receives
only the *surprise* component, which has stronger predictive power.

We use numpy's lstsq for clarity and minimal dependencies; no sklearn needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

from s5_sentiment.aggregator import TickerAggregate

log = structlog.get_logger(__name__)

_LAGGED_LOOKBACK = 5  # days; wired to spec ("lagged sentiment (5-day)")


@dataclass
class ResidualizedScore:
    """Final output row for a single ticker, ready to write to DB."""

    ticker: str
    raw_mentions: int
    abn_attention: float
    raw_sentiment: float
    sentiment_res: float
    model_used: str


def residualize(
    today_aggregates: dict[str, TickerAggregate],
    history: dict[str, list[tuple[float, float]]],
) -> list[ResidualizedScore]:
    """
    Produce one ResidualizedScore per ticker in *today_aggregates*.

    Parameters
    ----------
    today_aggregates:
        Output of aggregator.aggregate_scores — one TickerAggregate per ticker.
    history:
        Mapping ticker → list of (raw_sentiment, abn_attention) tuples for
        the prior N days, oldest first.  Provided by the DB reader in main.py.

    Returns
    -------
    List of ResidualizedScore objects, one per universe ticker.

    Residualization model
    ---------------------
    y  = raw_sentiment_today
    X  = [1, mean(raw_sentiment[-5:]), mean(abn_attention[-5:])]
    ŷ  = X @ β   (OLS fit)
    sentiment_res = y - ŷ

    When insufficient history exists (< 2 data points) we fall back to
    sentiment_res = raw_sentiment_today.  This preserves signal rather than
    zeroing it, and is clearly distinguishable in the model_used column.
    """
    results: list[ResidualizedScore] = []

    for ticker, agg in today_aggregates.items():
        past = history.get(ticker, [])
        past_trimmed = past[-_LAGGED_LOOKBACK:]

        sentiment_res = _compute_residual(ticker, agg.raw_sentiment, past_trimmed)

        results.append(
            ResidualizedScore(
                ticker=ticker,
                raw_mentions=agg.raw_mentions,
                abn_attention=agg.abn_attention,
                raw_sentiment=agg.raw_sentiment,
                sentiment_res=sentiment_res,
                model_used=agg.model_used,
            )
        )

    return results


def _compute_residual(
    ticker: str,
    raw_sentiment_today: float,
    past: list[tuple[float, float]],
) -> float:
    """
    OLS residual of raw_sentiment_today against lagged predictors.

    Falls back to raw_sentiment_today when there are fewer than 2 historical
    data points (OLS is undefined with a single observation).
    """
    if len(past) < 2:
        log.debug(
            "residual_insufficient_history",
            ticker=ticker,
            history_len=len(past),
        )
        return raw_sentiment_today

    sentiments = [s for s, _ in past]
    attentions = [a for _, a in past]

    lag_sentiment = float(np.mean(sentiments))
    lag_attention = float(np.mean(attentions))

    # Design matrix: intercept + two predictors.
    # We fit a cross-sectional model for *this ticker* using its own history.
    # With only a few data points the OLS will be nearly exact, but the
    # residual still removes the most recent directional trend.
    X = np.array([[1.0, s, a] for s, a in past], dtype=np.float64)
    y = np.array([s for s, _ in past], dtype=np.float64)

    # Guard against degenerate X (all predictors constant across history).
    try:
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        log.warning("residual_lstsq_failed", ticker=ticker)
        return raw_sentiment_today

    # Apply the fitted coefficients to today's lagged values to get ŷ.
    x_today = np.array([1.0, lag_sentiment, lag_attention], dtype=np.float64)
    y_hat = float(x_today @ beta)

    residual = raw_sentiment_today - y_hat
    return residual
