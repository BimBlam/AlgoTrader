"""
Unit tests for sentiment_adj.py — Layer 4 confidence multiplier.
"""
import types
from unittest.mock import patch


from s3_signal_engine.sentiment_adj import compute_directional_sentiment_adj


def _make_s_cfg(pos=0.30, neg=-0.30, attn=2.0):
    return types.SimpleNamespace(
        sentiment_threshold_positive=pos,
        sentiment_threshold_negative=neg,
        attention_z_threshold=attn,
        attention_lookback_days=30,
        model="finbert",
    )


def _patch_cfg(s_cfg):
    cfg = types.SimpleNamespace(sentiment_params=s_cfg)
    return patch("s3_signal_engine.sentiment_adj.get_config", return_value=cfg)


class TestDirectionalSentimentAdj:
    def test_no_entry_returns_neutral(self):
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("AAPL", "LONG", {})
        assert result == 1.0

    def test_model_none_returns_neutral(self):
        sentiment_map = {"AAPL": {"sentiment_res": 0.5, "abn_attention": 3.0, "model_used": "none"}}
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("AAPL", "LONG", sentiment_map)
        assert result == 1.0

    def test_neutral_band_returns_full(self):
        sentiment_map = {"AAPL": {"sentiment_res": 0.10, "abn_attention": 0.5, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("AAPL", "LONG", sentiment_map)
        assert result == 1.0

    def test_confirming_bullish_long_returns_full(self):
        sentiment_map = {"AAPL": {"sentiment_res": 0.50, "abn_attention": 0.5, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("AAPL", "LONG", sentiment_map)
        assert result == 1.0

    def test_confirming_bearish_short_returns_full(self):
        sentiment_map = {"AAPL": {"sentiment_res": -0.50, "abn_attention": 0.5, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("AAPL", "SHORT", sentiment_map)
        assert result == 1.0

    def test_counter_bullish_short_low_attention_returns_half(self):
        # Bullish sentiment vs SHORT signal, low abnormal attention → 0.5
        sentiment_map = {"AAPL": {"sentiment_res": 0.50, "abn_attention": 1.0, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg(attn=2.0)):
            result = compute_directional_sentiment_adj("AAPL", "SHORT", sentiment_map)
        assert result == 0.5

    def test_counter_bearish_long_high_attention_returns_zero(self):
        # Bearish sentiment vs LONG signal with high attention → 0.0 (skip)
        sentiment_map = {"MSFT": {"sentiment_res": -0.50, "abn_attention": 3.0, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg(attn=2.0)):
            result = compute_directional_sentiment_adj("MSFT", "LONG", sentiment_map)
        assert result == 0.0

    def test_counter_bullish_short_high_attention_returns_zero(self):
        sentiment_map = {"TSLA": {"sentiment_res": 0.80, "abn_attention": 2.5, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg(attn=2.0)):
            result = compute_directional_sentiment_adj("TSLA", "SHORT", sentiment_map)
        assert result == 0.0

    def test_exactly_at_attention_threshold_returns_zero(self):
        # Boundary: abn_attention == threshold with counter direction → 0.0
        sentiment_map = {"X": {"sentiment_res": 0.50, "abn_attention": 2.0, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg(attn=2.0)):
            result = compute_directional_sentiment_adj("X", "SHORT", sentiment_map)
        assert result == 0.0

    def test_buy_side_string_treated_as_long(self):
        sentiment_map = {"X": {"sentiment_res": 0.50, "abn_attention": 0.5, "model_used": "finbert"}}
        with _patch_cfg(_make_s_cfg()):
            result = compute_directional_sentiment_adj("X", "BUY", sentiment_map)
        assert result == 1.0
