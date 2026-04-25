"""
Cross-sectional reversal signal generation.

Methodology:
  1. Rank all tickers by ret_1d (ascending).
  2. Bottom decile (worst performers) → LONG (mean-reversion up).
  3. Top decile (best performers)    → SHORT.
  4. If turnover_split=True: rank within high- and low-turnover buckets
     separately (Lehmann 1990 enhancement to reduce crowding).

raw_score is a normalised rank-distance from the extreme:
  LONG:  1.0 at rank=0 (worst), 0.0 at long_decile boundary
  SHORT: 0.0 at short_decile boundary, 1.0 at rank=1 (best)
"""
import datetime

import pandas as pd

from algotrader.shared.constants import SignalStrategy, SignalSide
from algotrader.shared.logger import get_logger
from algotrader.signals.stat_arb import SignalCandidate
from algotrader.signals.sentiment_adj import compute_directional_sentiment_adj

log = get_logger(__name__)


def compute_reversal_signals(
    returns_df: pd.DataFrame,
    strategy_cfg,
    sentiment_map: dict[str, dict],
    regime: str,
    run_id: str,
    today: datetime.date,
    extreme_vol_halt: bool = True,
) -> list[SignalCandidate]:
    """
    Generate cross-sectional reversal signals.

    Tickers with avg_vol_30 <= 0 are excluded (insufficient liquidity).
    EXTREME regime halts all reversals if extreme_vol_halt=True.
    """
    params = strategy_cfg.reversal

    if regime == "EXTREME" and extreme_vol_halt:
        log.info("reversal_halted_extreme_regime", date=str(today))
        return []

    long_decile = float(params.long_decile)
    short_decile = float(params.short_decile)
    turnover_split = bool(params.turnover_split)

    eligible = returns_df[returns_df["avg_vol_30"] > 0].copy()
    if eligible.empty:
        log.warning("reversal_no_eligible_tickers", date=str(today))
        return []

    candidates: list[SignalCandidate] = []

    if turnover_split:
        median_turnover = eligible["turnover"].median()
        high_bucket = eligible[eligible["turnover"] >= median_turnover]
        low_bucket = eligible[eligible["turnover"] < median_turnover]
        for bucket in (high_bucket, low_bucket):
            if not bucket.empty:
                candidates.extend(
                    _rank_and_select(
                        bucket, long_decile, short_decile,
                        sentiment_map, regime, run_id, today,
                    )
                )
    else:
        candidates.extend(
            _rank_and_select(
                eligible, long_decile, short_decile,
                sentiment_map, regime, run_id, today,
            )
        )

    log.info("reversal_signals_generated", n=len(candidates), date=str(today))
    return candidates


def _rank_and_select(
    df: pd.DataFrame,
    long_decile: float,
    short_decile: float,
    sentiment_map: dict[str, dict],
    regime: str,
    run_id: str,
    today: datetime.date,
) -> list[SignalCandidate]:
    """
    Rank df by ret_1d, select extreme deciles, apply directional sentiment.
    """
    ranked = df["ret_1d"].rank(pct=True, ascending=True)
    candidates = []

    for ticker, pct_rank in ranked.items():
        ticker = str(ticker).upper()

        if pct_rank <= long_decile:
            side = SignalSide.LONG
            raw_score = 1.0 - (pct_rank / long_decile) if long_decile > 0 else 1.0
        elif pct_rank >= short_decile:
            side = SignalSide.SHORT
            raw_score = (pct_rank - short_decile) / (1.0 - short_decile) if short_decile < 1.0 else 1.0
        else:
            continue

        adj = compute_directional_sentiment_adj(
            ticker=ticker,
            side=side.value,
            sentiment_map=sentiment_map,
        )
        if adj == 0.0:
            log.info(
                "signal_filtered_zero_adj",
                ticker=ticker,
                strategy="REVERSAL",
            )
            continue


        candidates.append(
            SignalCandidate(
                ticker=ticker,
                strategy=SignalStrategy.REVERSAL,
                side=side,
                raw_score=raw_score,
                sentiment_adj=adj,
                regime=regime,
                run_id=run_id,
                date=today,
            )
        )

    return candidates
