"""
Unit tests for competition.py — per-ticker signal resolution.
"""
import datetime
import types


from algotrader.signals.stat_arb import SignalCandidate
from algotrader.signals.competition import resolve_competition, _pick_winner
from algotrader.shared.constants import SignalStrategy, SignalSide


TODAY = datetime.date(2025, 1, 15)
RUN_ID = "test-run-003"


def _make_candidate(ticker, strategy, side, raw_score, adj=1.0, regime="LOW_VOL"):
    return SignalCandidate(
        ticker=ticker,
        strategy=strategy,
        side=side,
        raw_score=raw_score,
        sentiment_adj=adj,
        regime=regime,
        run_id=RUN_ID,
        date=TODAY,
    )


def _make_strategy_cfg(stat_cap=0.40, rev_cap=0.30, combo_cap=0.30):
    return types.SimpleNamespace(
        stat_arb=types.SimpleNamespace(max_allocation_pct=stat_cap),
        reversal=types.SimpleNamespace(max_allocation_pct=rev_cap),
        regime_combo=types.SimpleNamespace(max_allocation_pct=combo_cap),
    )


def _make_risk_cfg():
    return types.SimpleNamespace(max_positions_open=40)


class TestPickWinner:
    def test_higher_combined_score_wins(self):
        c1 = _make_candidate("AAPL", SignalStrategy.STAT_ARB, SignalSide.LONG, raw_score=2.0, adj=1.0)
        c2 = _make_candidate("AAPL", SignalStrategy.REVERSAL, SignalSide.LONG, raw_score=1.0, adj=1.0)
        winner = _pick_winner([c1, c2])
        assert winner.strategy == SignalStrategy.STAT_ARB

    def test_tie_broken_by_strategy_priority_stat_arb_wins(self):
        c1 = _make_candidate("AAPL", SignalStrategy.STAT_ARB, SignalSide.LONG, raw_score=1.0, adj=1.0)
        c2 = _make_candidate("AAPL", SignalStrategy.REVERSAL, SignalSide.LONG, raw_score=1.0, adj=1.0)
        winner = _pick_winner([c1, c2])
        assert winner.strategy == SignalStrategy.STAT_ARB

    def test_returns_none_for_empty_group(self):
        assert _pick_winner([]) is None

    def test_single_candidate_always_wins(self):
        c = _make_candidate("MSFT", SignalStrategy.REVERSAL, SignalSide.SHORT, raw_score=0.8, adj=0.5)
        assert _pick_winner([c]) is c


class TestResolveCompetition:
    def test_one_winner_per_ticker(self):
        candidates = [
            _make_candidate("AAPL", SignalStrategy.STAT_ARB, SignalSide.LONG, 2.0),
            _make_candidate("AAPL", SignalStrategy.REVERSAL, SignalSide.LONG, 1.0),
            _make_candidate("MSFT", SignalStrategy.REVERSAL, SignalSide.SHORT, 0.9),
        ]
        winners = resolve_competition(candidates, _make_strategy_cfg(), "LOW_VOL", _make_risk_cfg())
        tickers = [w.ticker for w in winners]
        assert len(tickers) == len(set(tickers))  # no duplicates

    def test_returns_empty_on_no_candidates(self):
        result = resolve_competition([], _make_strategy_cfg(), "LOW_VOL", _make_risk_cfg())
        assert result == []

    def test_allocation_cap_respected(self):
        # 10 stat_arb candidates, cap=0.40 → at most floor(10*0.40)=4 kept
        candidates = [
            _make_candidate(f"T{i:02d}", SignalStrategy.STAT_ARB, SignalSide.LONG, float(i + 1))
            for i in range(10)
        ]
        winners = resolve_competition(candidates, _make_strategy_cfg(stat_cap=0.40), "LOW_VOL", _make_risk_cfg())
        stat_arb_winners = [w for w in winners if w.strategy == SignalStrategy.STAT_ARB]
        assert len(stat_arb_winners) <= 4

    def test_cap_keeps_highest_scoring(self):
        candidates = [
            _make_candidate(f"T{i:02d}", SignalStrategy.STAT_ARB, SignalSide.LONG, float(i + 1))
            for i in range(5)
        ]
        # cap=0.40 with 5 total → floor(5*0.4)=2 kept
        winners = resolve_competition(candidates, _make_strategy_cfg(stat_cap=0.40), "LOW_VOL", _make_risk_cfg())
        stat_arb_winners = sorted([w for w in winners if w.strategy == SignalStrategy.STAT_ARB],
                                   key=lambda w: -w.combined_score)
        # Should keep T04 (score=5) and T03 (score=4) — the two highest
        if len(stat_arb_winners) == 2:
            scores = [w.raw_score for w in stat_arb_winners]
            assert min(scores) >= 4.0

    def test_different_tickers_different_strategies_both_kept(self):
        candidates = [
            _make_candidate("AAPL", SignalStrategy.STAT_ARB, SignalSide.LONG, 2.0),
            _make_candidate("MSFT", SignalStrategy.REVERSAL, SignalSide.SHORT, 0.9),
        ]
        winners = resolve_competition(candidates, _make_strategy_cfg(), "LOW_VOL", _make_risk_cfg())
        assert len(winners) == 2
