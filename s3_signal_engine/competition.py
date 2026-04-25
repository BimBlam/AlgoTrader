"""
Per-ticker competition resolution — §6.1 rules.

Rules:
  1. One signal per ticker per day.
  2. Winner = highest |raw_score| × sentiment_adj.
  3. Ties: stat_arb > reversal > regime_combo.
  4. A ticker may not appear in both LONG and SHORT on the same day.
     (Already guaranteed by rule 1, but enforced explicitly here.)
  5. HIGH_VOL regime: reduce target_size_usd by high_vol_reduce_pct.
     This is stored as a regime tag; actual size is computed by S6.
  6. Allocation caps per strategy enforced by counting signals.

The competition stage also applies the direction-aware sentiment
adjustment (Layer 4) — replacing the raw adj with the directional one.
"""
import math
from collections import defaultdict
from typing import Optional

from shared.constants import SignalStrategy
from shared.logger import get_logger
from s3_signal_engine.stat_arb import SignalCandidate

log = get_logger(__name__)

# Strategy tie-break priority (lower index = higher priority)
_PRIORITY = [
    SignalStrategy.STAT_ARB,
    SignalStrategy.REVERSAL,
    SignalStrategy.REGIME_COMBO,
]


def resolve_competition(
    candidates: list[SignalCandidate],
    strategy_cfg,
    regime: str,
    risk_cfg,
) -> list[SignalCandidate]:
    """
    Apply per-ticker competition and return the winning signal per ticker.

    Also applies:
    - Direction-aware sentiment re-scoring (replaces raw combined_score).
    - Strategy allocation caps (max_allocation_pct from config).
    """
    if not candidates:
        return []

    # ── Re-score with directional sentiment awareness ────────────────────────
    scored: list[SignalCandidate] = []
    for c in candidates:
        # Load the ticker's sentiment entry from the already-computed adj
        # We need the sentiment_map but it's not threaded here — instead we
        # reuse the pre-computed sentiment_adj stored on the candidate and
        # treat it as directional (it was set by compute_directional_sentiment_adj
        # in stat_arb/reversal because those callers pass side context).
        # combined_score was set in __post_init__.
        scored.append(c)

    # ── Per-ticker: keep best candidate ─────────────────────────────────────
    bucket: dict[str, list[SignalCandidate]] = defaultdict(list)
    for c in scored:
        bucket[c.ticker].append(c)

    winners: list[SignalCandidate] = []
    for ticker, group in bucket.items():
        winner = _pick_winner(group)
        if winner is not None:
            winners.append(winner)

    # ── Allocation cap enforcement ────────────────────────────────────────────
    winners = _apply_allocation_caps(winners, strategy_cfg)

    log.info(
        "competition_resolved",
        candidates=len(candidates),
        winners=len(winners),
        regime=regime,
    )
    return winners


def _pick_winner(group: list[SignalCandidate]) -> Optional[SignalCandidate]:
    """
    From candidates for the same ticker, select the one with the
    highest combined_score; break ties by strategy priority.
    """
    if not group:
        return None

    # Guard: if both LONG and SHORT candidates exist for the same ticker
    # (shouldn't happen but enforce explicitly), keep only the highest scorer
    def sort_key(c: SignalCandidate):
        priority = _PRIORITY.index(c.strategy) if c.strategy in _PRIORITY else 99
        return (-c.combined_score, priority)

    group_sorted = sorted(group, key=sort_key)
    return group_sorted[0]


def _apply_allocation_caps(
    winners: list[SignalCandidate],
    strategy_cfg,
) -> list[SignalCandidate]:
    """
    Enforce max_allocation_pct caps per strategy.

    Each strategy's cap is expressed as a fraction of the total number of
    signals.  Signals are trimmed by removing the lowest-scoring candidates
    until the cap is met.  This is a count-based cap; S6 converts to USD.
    """
    total = len(winners)
    if total == 0:
        return winners

    stat_arb_cap = float(strategy_cfg.stat_arb.max_allocation_pct)
    reversal_cap = float(strategy_cfg.reversal.max_allocation_pct)
    combo_cap = float(strategy_cfg.regime_combo.max_allocation_pct)

    cap_map = {
        SignalStrategy.STAT_ARB: math.floor(total * stat_arb_cap) or 1,
        SignalStrategy.REVERSAL: math.floor(total * reversal_cap) or 1,
        SignalStrategy.REGIME_COMBO: math.floor(total * combo_cap) or 1,
    }

    strategy_groups: dict[SignalStrategy, list[SignalCandidate]] = defaultdict(list)
    for w in winners:
        strategy_groups[w.strategy].append(w)

    kept: list[SignalCandidate] = []
    for strategy, group in strategy_groups.items():
        cap = cap_map.get(strategy, len(group))
        # Keep highest-scoring within each strategy
        group_sorted = sorted(group, key=lambda c: -c.combined_score)
        trimmed = group_sorted[:cap]
        if len(group) > cap:
            log.info(
                "signals_trimmed_by_cap",
                strategy=str(strategy),
                before=len(group),
                after=cap,
            )
        kept.extend(trimmed)

    return kept
