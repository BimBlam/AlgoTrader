"""Unit tests for algotrader.sentiment.scorer."""

from unittest.mock import MagicMock, patch

import pytest

from algotrader.sentiment.scorer import (
    MODEL_FINBERT,
    MODEL_NONE,
    ScoredItem,
    _parse_finbert_output,
    reset_finbert_singleton,
    score_batch_finbert,
    score_texts,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure the FinBERT singleton is cleared between tests."""
    reset_finbert_singleton()
    yield
    reset_finbert_singleton()


class TestScoredItem:
    def test_raw_contribution_positive(self):
        item = ScoredItem(positive=0.8, negative=0.1, neutral=0.1, model_used=MODEL_FINBERT)
        assert abs(item.raw_contribution - 0.7) < 1e-9

    def test_raw_contribution_negative(self):
        item = ScoredItem(positive=0.1, negative=0.8, neutral=0.1, model_used=MODEL_FINBERT)
        assert abs(item.raw_contribution - (-0.7)) < 1e-9

    def test_default_model_none(self):
        item = ScoredItem()
        assert item.model_used == MODEL_NONE
        assert item.raw_contribution == 0.0


class TestParseFinbertOutput:
    def test_positive_label(self):
        result = _parse_finbert_output({"label": "positive", "score": 0.9})
        assert result.model_used == MODEL_FINBERT
        assert result.positive == pytest.approx(0.9)
        assert result.negative == pytest.approx(0.05)

    def test_negative_label(self):
        result = _parse_finbert_output({"label": "negative", "score": 0.8})
        assert result.negative == pytest.approx(0.8)
        assert result.positive == pytest.approx(0.1)

    def test_neutral_label(self):
        result = _parse_finbert_output({"label": "neutral", "score": 0.7})
        assert result.neutral == pytest.approx(0.7)

    def test_uppercase_label_normalised(self):
        result = _parse_finbert_output({"label": "POSITIVE", "score": 0.6})
        assert result.positive == pytest.approx(0.6)

    def test_missing_label_defaults_neutral(self):
        result = _parse_finbert_output({"score": 0.5})
        assert result.neutral == pytest.approx(0.5)


class TestScoreBatchFinbert:
    def test_returns_none_items_when_pipeline_unavailable(self):
        # _finbert_pipeline is None (reset by fixture); _load_finbert returns None
        with patch("algotrader.sentiment.scorer._load_finbert", return_value=None):
            results = score_batch_finbert(["AAPL is great"], "ProsusAI/finbert", "cpu")
        assert len(results) == 1
        assert results[0].model_used == MODEL_NONE

    def test_successful_batch(self):
        mock_pipe = MagicMock(return_value=[{"label": "positive", "score": 0.9}])
        with patch("algotrader.sentiment.scorer._load_finbert", return_value=mock_pipe):
            results = score_batch_finbert(["AAPL earnings"], "ProsusAI/finbert", "cpu")
        assert results[0].model_used == MODEL_FINBERT
        assert results[0].positive == pytest.approx(0.9)

    def test_pipeline_exception_returns_none_items(self):
        mock_pipe = MagicMock(side_effect=RuntimeError("GPU OOM"))
        with patch("algotrader.sentiment.scorer._load_finbert", return_value=mock_pipe):
            results = score_batch_finbert(["text"], "ProsusAI/finbert", "cpu")
        assert results[0].model_used == MODEL_NONE

    def test_empty_input_returns_empty(self):
        results = score_batch_finbert([], "ProsusAI/finbert", "cpu")
        assert results == []


class TestScoreTexts:
    def test_empty_strings_get_model_none(self):
        results = score_texts(["", ""], "finbert", "ProsusAI/finbert", "cpu")
        assert all(r.model_used == MODEL_NONE for r in results)

    def test_unknown_model_falls_back(self):
        results = score_texts(["some text"], "openai", "ProsusAI/finbert", "cpu")
        assert results[0].model_used == MODEL_NONE

    def test_empty_list_returns_empty(self):
        results = score_texts([], "finbert", "ProsusAI/finbert", "cpu")
        assert results == []

    def test_mixed_empty_and_nonempty(self):
        mock_pipe = MagicMock(return_value=[{"label": "positive", "score": 0.85}])
        with patch("algotrader.sentiment.scorer._load_finbert", return_value=mock_pipe):
            results = score_texts(
                ["", "AAPL is great"],
                "finbert",
                "ProsusAI/finbert",
                "cpu",
            )
        assert results[0].model_used == MODEL_NONE
        assert results[1].model_used == MODEL_FINBERT

    def test_output_length_matches_input(self):
        mock_pipe = MagicMock(
            return_value=[
                {"label": "positive", "score": 0.9},
                {"label": "negative", "score": 0.8},
            ]
        )
        with patch("algotrader.sentiment.scorer._load_finbert", return_value=mock_pipe):
            results = score_texts(
                ["text one", "text two"],
                "finbert",
                "ProsusAI/finbert",
                "cpu",
            )
        assert len(results) == 2
