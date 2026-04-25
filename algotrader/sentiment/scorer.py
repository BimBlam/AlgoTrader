"""
Model scoring layer for S5.

Implements the model fallback chain: finbert → none.
Each scorer returns a ScoredItem namedtuple so the aggregator is
model-agnostic.

FinBERT is loaded once per process (lazy singleton) to avoid repeated
GPU memory allocation across batches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Sentinel value meaning the model failed or was not attempted.
MODEL_NONE = "none"
MODEL_FINBERT = "finbert"

# Maximum tokens FinBERT can accept; truncate to avoid runtime errors.
_FINBERT_MAX_TOKENS = 512


@dataclass
class ScoredItem:
    """Holds the per-document sentiment output from any model."""

    positive: float = 0.0
    negative: float = 0.0
    neutral: float = 0.0
    model_used: str = MODEL_NONE

    @property
    def raw_contribution(self) -> float:
        """
        Per-document contribution to raw_sentiment.

        Returns (positive - negative) in [-1, 1].  The aggregator sums these
        and divides by the item count.
        """
        return self.positive - self.negative


# ---------------------------------------------------------------------------
# FinBERT singleton
# ---------------------------------------------------------------------------

_finbert_pipeline: Any = None  # transformers Pipeline or None


def _load_finbert(model_id: str, device: str) -> Any:
    """
    Load and cache the FinBERT transformers pipeline.

    Device string follows PyTorch convention: "cuda:0", "cpu", etc.
    We load once and reuse — model weights are ~440 MB on GPU.
    """
    global _finbert_pipeline
    if _finbert_pipeline is not None:
        return _finbert_pipeline

    try:
        from transformers import pipeline  # type: ignore

        # truncation=True silently truncates inputs > max_length rather than
        # raising an error, which is the correct behaviour for long articles.
        _finbert_pipeline = pipeline(
            "text-classification",
            model=model_id,
            device=device,
            truncation=True,
            max_length=_FINBERT_MAX_TOKENS,
        )
        log.info("finbert_loaded", model_id=model_id, device=device)
    except Exception as exc:  # pragma: no cover — GPU path tested in integration
        log.warning("finbert_load_failed", error=str(exc))
        _finbert_pipeline = None

    return _finbert_pipeline


def _parse_finbert_output(result: dict[str, Any]) -> ScoredItem:
    """
    Map a single FinBERT pipeline output record to a ScoredItem.

    FinBERT returns label in {"positive", "negative", "neutral"} and a
    confidence score.  We treat the confidence as the probability mass for
    that label; the remaining mass is split equally to the other two — this
    is intentionally conservative and avoids inflating extremes.
    """
    label: str = result.get("label", "neutral").lower()
    score: float = float(result.get("score", 0.0))
    remainder = (1.0 - score) / 2.0

    if label == "positive":
        return ScoredItem(
            positive=score, negative=remainder, neutral=remainder,
            model_used=MODEL_FINBERT,
        )
    elif label == "negative":
        return ScoredItem(
            positive=remainder, negative=score, neutral=remainder,
            model_used=MODEL_FINBERT,
        )
    else:
        return ScoredItem(
            positive=remainder, negative=remainder, neutral=score,
            model_used=MODEL_FINBERT,
        )


def score_batch_finbert(
    texts: list[str],
    model_id: str,
    device: str,
) -> list[ScoredItem]:
    """
    Score a batch of cleaned texts with FinBERT.

    Returns a parallel list of ScoredItems.  On any failure the entire batch
    falls back to MODEL_NONE so the caller can decide to retry or skip.
    Raises no exceptions — failures are returned as MODEL_NONE items.
    """
    pipe = _load_finbert(model_id, device)
    if pipe is None:
        log.warning("finbert_unavailable_batch", count=len(texts))
        return [ScoredItem(model_used=MODEL_NONE) for _ in texts]

    try:
        results = pipe(texts, batch_size=32)
        return [_parse_finbert_output(r) for r in results]
    except Exception as exc:
        log.warning("finbert_batch_failed", error=str(exc), count=len(texts))
        return [ScoredItem(model_used=MODEL_NONE) for _ in texts]


def score_texts(
    texts: list[str],
    primary_model: str,
    finbert_model_id: str,
    device: str,
) -> list[ScoredItem]:
    """
    Score *texts* using the configured primary model with fallback chain.

    Fallback order per spec: finbert → none.
    Each text in the input is guaranteed a corresponding ScoredItem in output.

    Parameters
    ----------
    texts:
        Cleaned text strings (empty strings will produce MODEL_NONE items).
    primary_model:
        Value of ``sentiment_params.yaml: model``.  Currently only "finbert"
        is implemented; others fall through to MODEL_NONE.
    finbert_model_id:
        Hugging Face model ID string from config.
    device:
        PyTorch device string from system config.
    """
    if not texts:
        return []

    # Filter out empty strings before passing to GPU; track original indices
    # so we can reconstruct the parallel output list.
    non_empty_indices = [i for i, t in enumerate(texts) if t]
    non_empty_texts = [texts[i] for i in non_empty_indices]

    scored: list[ScoredItem | None] = [None] * len(texts)

    # Fill empty-text slots immediately.
    for i, t in enumerate(texts):
        if not t:
            scored[i] = ScoredItem(model_used=MODEL_NONE)

    if not non_empty_texts:
        return scored  # type: ignore[return-value]

    if primary_model == MODEL_FINBERT:
        batch_results = score_batch_finbert(non_empty_texts, finbert_model_id, device)
    else:
        # Future models (openai, llama3) not yet implemented.
        log.warning(
            "unknown_model_fallback",
            model=primary_model,
            fallback=MODEL_NONE,
        )
        batch_results = [ScoredItem(model_used=MODEL_NONE) for _ in non_empty_texts]

    for result_idx, original_idx in enumerate(non_empty_indices):
        scored[original_idx] = batch_results[result_idx]

    return scored  # type: ignore[return-value]


def reset_finbert_singleton() -> None:
    """
    Unload the FinBERT pipeline and free GPU memory.

    Exposed for test teardown and graceful shutdown; not called during
    normal run execution.
    """
    global _finbert_pipeline
    _finbert_pipeline = None
