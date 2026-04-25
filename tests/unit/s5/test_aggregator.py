"""Unit tests for s5_sentiment.aggregator."""

import pytest

from s5_sentiment.aggregator import aggregate_scores, _compute_abn_attention
from s5_sentiment.scorer import ScoredItem, MODEL_FINBERT, MODEL_NONE


TICKERS = ["AAPL", "MSFT", "TSLA"]


def _make_positive(score: float = 0.8) -> ScoredItem:
    remainder = (1 - score) / 2
    return ScoredItem(positive=score, negative=remainder, neutral=remainder, model_used=MODEL_FINBERT)


def _make_negative(score: float = 0.8) -> ScoredItem:
    remainder = (1 - score) / 2
    return ScoredItem(positive=remainder, negative=score, neutral=remainder, model_used=MODEL_FINBERT)


class TestAggregateScores:
    def test_all_tickers_present_in_output(self):
        result = aggregate_scores([], TICKERS, {}, 30)
        assert set(result.keys()) == set(TICKERS)

    def test_zero_mentions_ticker_gets_defaults(self):
        result = aggregate_scores([], TICKERS, {}, 30)
        agg = result["AAPL"]
        assert agg.raw_mentions == 0
        assert agg.raw_sentiment == 0.0
        assert agg.model_used == MODEL_NONE

    def test_single_positive_item(self):
        item = _make_positive(0.9)
        pairs = [("AAPL", item)]
        result = aggregate_scores(pairs, TICKERS, {}, 30)
        agg = result["AAPL"]
        assert agg.raw_mentions == 1
        # raw_sentiment = (positive - negative) / 1
        expected = item.positive - item.negative
        assert agg.raw_sentiment == pytest.approx(expected)
        assert agg.model_used == MODEL_FINBERT

    def test_mixed_positive_negative_averages(self):
        pos = _make_positive(0.8)
        neg = _make_negative(0.8)
        pairs = [("AAPL", pos), ("AAPL", neg)]
        result = aggregate_scores(pairs, TICKERS, {}, 30)
        agg = result["AAPL"]
        # Contributions cancel out approximately
        assert agg.raw_mentions == 2
        assert abs(agg.raw_sentiment) < 0.01

    def test_model_used_is_first_non_none(self):
        none_item = ScoredItem(model_used=MODEL_NONE)
        good_item = _make_positive()
        pairs = [("AAPL", none_item), ("AAPL", good_item)]
        result = aggregate_scores(pairs, TICKERS, {}, 30)
        assert result["AAPL"].model_used == MODEL_FINBERT

    def test_all_none_items_keeps_none(self):
        pairs = [("AAPL", ScoredItem(model_used=MODEL_NONE))]
        result = aggregate_scores(pairs, TICKERS, {}, 30)
        assert result["AAPL"].model_used == MODEL_NONE

    def test_unknown_ticker_in_pairs_ignored(self):
        item = _make_positive()
        pairs = [("UNKNOWN", item)]
        result = aggregate_scores(pairs, TICKERS, {}, 30)
        # UNKNOWN is not in tickers; should not appear in result
        assert "UNKNOWN" not in result

    def test_abn_attention_computed_for_mentioned_ticker(self):
        # 10 mentions today vs history mean of 5 → positive z-score
        history = {"AAPL": [5, 4, 5, 5, 5, 5, 5, 5, 5, 5]}
        pairs = [("AAPL", _make_positive())] * 10
        result = aggregate_scores(pairs, TICKERS, history, 30)
        assert result["AAPL"].abn_attention > 0


class TestComputeAbnAttention:
    def test_insufficient_history_returns_zero(self):
        assert _compute_abn_attention("AAPL", 5, [], 30) == 0.0
        assert _compute_abn_attention("AAPL", 5, [3], 30) == 0.0

    def test_constant_history_returns_zero(self):
        # std == 0; z-score is undefined → return 0.0
        assert _compute_abn_attention("AAPL", 5, [5] * 10, 30) == 0.0

    def test_positive_z_score(self):
        # today = 20, history mean = 5, std = 0
        # Use varied history so std > 0
        history = [3, 5, 4, 6, 5, 4, 6, 5, 4, 6]
        z = _compute_abn_attention("AAPL", 20, history, 30)
        assert z > 2.0

    def test_negative_z_score(self):
        history = [10, 12, 11, 13, 10, 12, 11, 13, 10, 12]
        z = _compute_abn_attention("AAPL", 0, history, 30)
        assert z < -2.0

    def test_lookback_respected(self):
        # history has 20 entries; lookback=5 should use only last 5
        history = [100] * 15 + [5, 5, 5, 5, 5]  # 20 total
        z = _compute_abn_attention("AAPL", 5, history, 5)
        # Mean of last 5 is 5; std is 0 → return 0.0
        assert z == 0.0
