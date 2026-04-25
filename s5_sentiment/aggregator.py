"""
Per-ticker aggregation layer for S5.

Takes the flat list of (ticker, ScoredItem) pairs produced by the
preprocessor + scorer and collapses them into one row per ticker:
  - raw_mentions  — total document count mentioning the ticker
  - raw_sentiment — (Σpositive - Σnegative) / n
  - abn_attention — z-score of today's mention count vs 30-day rolling mean

Historical data needed for abn_attention is read from the
``sentiment_scores`` DB table by the caller and passed in as a plain dict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

from s5_sentiment.scorer import ScoredItem, MODEL_NONE

log = structlog.get_logger(__name__)


@dataclass
class TickerAggregate:
    """Intermediate per-ticker aggregate before residualization."""

    ticker: str
    raw_mentions: int
    raw_sentiment: float  # [-1.0, 1.0]
    abn_attention: float
    model_used: str


def aggregate_scores(
    scored_pairs: list[tuple[str, ScoredItem]],
    tickers: list[str],
    history: dict[str, list[int]],
    attention_lookback_days: int,
) -> dict[str, TickerAggregate]:
    """
    Aggregate a flat list of (ticker, ScoredItem) pairs into one row per ticker.

    Parameters
    ----------
    scored_pairs:
        Each element is (ticker, ScoredItem) produced for every document that
        mentioned *ticker*.  A single document can produce multiple pairs if
        it mentions multiple tickers.
    tickers:
        Full universe ticker list.  Every ticker must appear in the output
        even if it received zero mentions today (spec requirement).
    history:
        Mapping ticker → list of daily mention counts for the prior
        ``attention_lookback_days`` days, oldest first.  Used for z-score
        computation.  May be empty for a new ticker.
    attention_lookback_days:
        Window length for the rolling mean/std used in z-score.

    Returns
    -------
    dict mapping ticker → TickerAggregate (one entry per universe ticker).
    """
    # Build per-ticker buckets.
    buckets: dict[str, list[ScoredItem]] = {t: [] for t in tickers}
    for ticker, item in scored_pairs:
        if ticker in buckets:
            buckets[ticker].append(item)

    result: dict[str, TickerAggregate] = {}

    for ticker in tickers:
        items = buckets[ticker]
        raw_mentions = len(items)

        if raw_mentions == 0:
            raw_sentiment = 0.0
            model_used = MODEL_NONE
        else:
            total_pos = sum(i.positive for i in items)
            total_neg = sum(i.negative for i in items)
            raw_sentiment = (total_pos - total_neg) / raw_mentions
            # Use the model of the first successful (non-none) item as the
            # representative model_used for the row.  If all fell back, use none.
            model_used = next(
                (i.model_used for i in items if i.model_used != MODEL_NONE),
                MODEL_NONE,
            )

        abn_attention = _compute_abn_attention(
            ticker, raw_mentions, history.get(ticker, []), attention_lookback_days
        )

        result[ticker] = TickerAggregate(
            ticker=ticker,
            raw_mentions=raw_mentions,
            raw_sentiment=raw_sentiment,
            abn_attention=abn_attention,
            model_used=model_used,
        )

    return result


def _compute_abn_attention(
    ticker: str,
    today_count: int,
    history_counts: list[int],
    lookback_days: int,
) -> float:
    """
    Compute the z-score of *today_count* relative to the rolling 30-day history.

    Returns 0.0 when fewer than 2 historical data points are available —
    a z-score is undefined without variance.  This is a deliberate neutral
    default rather than raising, because new tickers with sparse history
    should not cause the pipeline to abort.
    """
    counts = history_counts[-lookback_days:]

    if len(counts) < 2:
        log.debug(
            "abn_attention_insufficient_history",
            ticker=ticker,
            history_len=len(counts),
        )
        return 0.0

    mean = sum(counts) / len(counts)
    variance = sum((c - mean) ** 2 for c in counts) / len(counts)
    std = math.sqrt(variance)

    if std < 1e-9:
        # All historical values were identical — z-score is technically
        # undefined; return 0.0 (no abnormal attention signal).
        return 0.0

    return (today_count - mean) / std
