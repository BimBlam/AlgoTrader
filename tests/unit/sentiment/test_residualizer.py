"""Unit tests for algotrader.sentiment.residualizer."""

import pytest
from algotrader.sentiment.residualizer import residualize, _compute_residual
from algotrader.sentiment.aggregator import TickerAggregate
from algotrader.sentiment.scorer import MODEL_FINBERT, MODEL_NONE


def _make_agg(ticker: str, raw_sentiment: float = 0.5, abn_attention: float = 1.0) -> TickerAggregate:
    return TickerAggregate(
        ticker=ticker,
        raw_mentions=10,
        raw_sentiment=raw_sentiment,
        abn_attention=abn_attention,
        model_used=MODEL_FINBERT,
    )


class TestComputeResidual:
    def test_insufficient_history_returns_raw_sentiment(self):
        result = _compute_residual("AAPL", 0.5, [])
        assert result == 0.5

    def test_single_history_item_returns_raw_sentiment(self):
        result = _compute_residual("AAPL", 0.5, [(0.4, 1.0)])
        assert result == 0.5

    def test_residual_is_float(self):
        history = [(0.1, 0.5), (0.2, 0.6), (0.3, 0.7), (0.2, 0.5), (0.1, 0.4)]
        result = _compute_residual("AAPL", 0.5, history)
        assert isinstance(result, float)

    def test_residual_near_zero_when_sentiment_matches_trend(self):
        # If today's sentiment is close to what the lagged model predicts,
        # the residual should be small in magnitude.
        history = [(0.5, 0.0), (0.5, 0.0), (0.5, 0.0), (0.5, 0.0), (0.5, 0.0)]
        result = _compute_residual("AAPL", 0.5, history)
        # OLS fit will predict ~0.5; residual should be close to 0
        assert abs(result) < 0.3

    def test_residual_large_for_surprise(self):
        # History consistently shows ~0.0 sentiment; today is strongly positive
        history = [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
        result = _compute_residual("AAPL", 0.9, history)
        # Predicted value is near 0; residual should be positive and large
        assert result > 0.5


class TestResidualize:
    def test_all_tickers_in_output(self):
        aggregates = {
            "AAPL": _make_agg("AAPL"),
            "MSFT": _make_agg("MSFT"),
        }
        result = residualize(aggregates, {})
        tickers_out = {r.ticker for r in result}
        assert tickers_out == {"AAPL", "MSFT"}

    def test_zero_mentions_ticker_preserved(self):
        aggregates = {
            "AAPL": TickerAggregate(
                ticker="AAPL",
                raw_mentions=0,
                raw_sentiment=0.0,
                abn_attention=0.0,
                model_used=MODEL_NONE,
            )
        }
        result = residualize(aggregates, {})
        assert len(result) == 1
        row = result[0]
        assert row.raw_mentions == 0
        assert row.model_used == MODEL_NONE

    def test_sentiment_res_field_populated(self):
        aggregates = {"AAPL": _make_agg("AAPL", raw_sentiment=0.7)}
        history = {
            "AAPL": [(0.1, 0.5), (0.2, 0.6), (0.3, 0.7), (0.2, 0.5), (0.1, 0.4)]
        }
        result = residualize(aggregates, history)
        assert result[0].sentiment_res is not None
        assert isinstance(result[0].sentiment_res, float)

    def test_no_history_fallback_uses_raw_sentiment(self):
        aggregates = {"AAPL": _make_agg("AAPL", raw_sentiment=0.42)}
        result = residualize(aggregates, {})
        # No history → sentiment_res == raw_sentiment
        assert result[0].sentiment_res == pytest.approx(0.42)

    def test_output_preserves_raw_fields(self):
        agg = _make_agg("AAPL", raw_sentiment=0.3, abn_attention=1.5)
        result = residualize({"AAPL": agg}, {})
        row = result[0]
        assert row.raw_mentions == 10
        assert row.raw_sentiment == pytest.approx(0.3)
        assert row.abn_attention == pytest.approx(1.5)
        assert row.model_used == MODEL_FINBERT
