"""
Statistical arbitrage signal generation (Avellaneda-Lee).

Entry rules from strategy_params.yaml:
  Entry long  : s_score < -entry_s_score   (price below equilibrium)
  Entry short : s_score >  entry_s_score

Only tickers with valid OU params (kappa >= min_kappa) are eligible.
Sentiment adjustment is directional: a bearish sentiment on a LONG
signal reduces or kills the signal (and vice versa for SHORT).
"""
import datetime
from dataclasses import dataclass, field

from shared.constants import SignalStrategy, SignalSide
from shared.logger import get_logger
from s3_signal_engine.ou_model import OUResult
from s3_signal_engine.sentiment_adj import compute_directional_sentiment_adj

log = get_logger(__name__)


@dataclass
class SignalCandidate:
    """
    Intermediate signal representation before competition resolution.

    combined_score drives the winner-selection logic in competition.py;
    it is NOT persisted — only raw_score and sentiment_adj are written.
    """
    ticker: str
    strategy: SignalStrategy
    side: SignalSide
    raw_score: float        # |s-score| for stat arb; rank score for reversal
    sentiment_adj: float    # confidence multiplier [0.0, 1.0]
    regime: str
    run_id: str
    date: datetime.date
    combined_score: float = field(init=False)

    def __post_init__(self):
        self.combined_score = abs(self.raw_score) * self.sentiment_adj


def compute_stat_arb_signals(
    ou_results: list[OUResult],
    strategy_cfg,
    sentiment_map: dict[str, dict],
    regime: str,
    run_id: str,
    today: datetime.date,
) -> list[SignalCandidate]:
    """
    Generate stat arb entry signals for all tickers with valid OU params.

    EXTREME regime halts stat arb if extreme_vol_halt=True.
    Sentiment is applied directionally: bearish sentiment suppresses LONG
    signals; bullish sentiment suppresses SHORT signals.
    """
    params = strategy_cfg.stat_arb
    combo_params = strategy_cfg.regime_combo

    if regime == "EXTREME" and combo_params.extreme_vol_halt:
        log.info("stat_arb_halted_extreme_regime", date=str(today))
        return []

    entry_threshold = float(params.entry_s_score)
    candidates: list[SignalCandidate] = []

    for ou in ou_results:
        if not ou.valid:
            continue

        s = ou.s_score

        if s < -entry_threshold:
            side = SignalSide.LONG
        elif s > entry_threshold:
            side = SignalSide.SHORT
        else:
            continue

        adj = compute_directional_sentiment_adj(
            ticker=ou.ticker,
            side=side.value,
            sentiment_map=sentiment_map,
        )

        if adj == 0.0:
            log.info(
                "signal_filtered_zero_adj",
                ticker=ou.ticker,
                strategy="STAT_ARB",
            )
            continue


        candidates.append(
            SignalCandidate(
                ticker=ou.ticker,
                strategy=SignalStrategy.STAT_ARB,
                side=side,
                raw_score=abs(s),
                sentiment_adj=adj,
                regime=regime,
                run_id=run_id,
                date=today,
            )
        )

    log.info("stat_arb_signals_generated", n=len(candidates), date=str(today))
    return candidates
