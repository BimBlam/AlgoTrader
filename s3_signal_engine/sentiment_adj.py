"""
Layer 4 — Sentiment confidence adjustment.

Rules per §6.1:
  - sentiment_adj = 1.0 (full size)   : neutral or no data
  - sentiment_adj = 0.5 (half size)   : moderate signal (ambiguous or low conviction)
  - sentiment_adj = 0.0 (skip signal) : strong counter-signal

The confidence multiplier is derived from the residualized sentiment score
(sentiment_res) and abnormal attention (abn_attention) stored in
sentiment_scores.  Thresholds are read from config/sentiment_params.yaml.

Logic:
  1. If model_used='none', return 1.0 — treat absence of data as neutral.
  2. If |sentiment_res| < positive_threshold → neutral → 1.0.
  3. If sentiment aligns with signal direction → 1.0 (confirming).
  4. If sentiment is mildly counter (abn_attention < attention_z_threshold) → 0.5.
  5. If sentiment is strongly counter (abn_attention >= attention_z_threshold) → 0.0.
"""
from shared.config_loader import get_config
from shared.logger import get_logger

log = get_logger(__name__)


def compute_sentiment_adj(
    ticker: str,
    sentiment_map: dict[str, dict],
) -> float:
    """
    Return the sentiment confidence multiplier for *ticker*.

    Reads thresholds from config/sentiment_params.yaml at call time.
    Returns 1.0 if the ticker has no entry in sentiment_map (neutral).
    """
    cfg = get_config()
    s_cfg = cfg.sentiment_params

    pos_threshold = float(s_cfg.sentiment_threshold_positive)
    neg_threshold = float(s_cfg.sentiment_threshold_negative)
    attn_threshold = float(s_cfg.attention_z_threshold)

    entry = sentiment_map.get(ticker)
    if not entry or entry.get("model_used") == "none":
        return 1.0

    sentiment_res: float = float(entry.get("sentiment_res", 0.0))
    abn_attention: float = float(entry.get("abn_attention", 0.0))

    # Sentiment is within neutral band → no adjustment
    if neg_threshold <= sentiment_res <= pos_threshold:
        return 1.0

    # Sentiment is bullish (positive)
    if sentiment_res > pos_threshold:
        # Confirming for LONG, counter for SHORT — but caller doesn't pass
        # direction here; caller should use the returned multiplier
        # directionally.  We return raw multiplier; direction-awareness is
        # applied in stat_arb.py and reversal.py where side is known.
        return _direction_adj(sentiment_is_positive=True, abn_attention=abn_attention, attn_threshold=attn_threshold)

    # Sentiment is bearish (negative)
    return _direction_adj(sentiment_is_positive=False, abn_attention=abn_attention, attn_threshold=attn_threshold)


def compute_directional_sentiment_adj(
    ticker: str,
    side: str,
    sentiment_map: dict[str, dict],
) -> float:
    """
    Direction-aware sentiment multiplier.

    Returns:
      1.0 when sentiment confirms signal direction or is neutral.
      0.5 when sentiment is mildly counter-directional.
      0.0 when sentiment is strongly counter-directional (high attention).
    """
    cfg = get_config()
    s_cfg = cfg.sentiment_params

    pos_threshold = float(s_cfg.sentiment_threshold_positive)
    neg_threshold = float(s_cfg.sentiment_threshold_negative)
    attn_threshold = float(s_cfg.attention_z_threshold)

    entry = sentiment_map.get(ticker)
    if not entry or entry.get("model_used") == "none":
        return 1.0

    sentiment_res: float = float(entry.get("sentiment_res", 0.0))
    abn_attention: float = float(entry.get("abn_attention", 0.0))

    if neg_threshold <= sentiment_res <= pos_threshold:
        return 1.0

    sentiment_bullish = sentiment_res > pos_threshold
    signal_long = side in ("LONG", "BUY")

    if sentiment_bullish == signal_long:
        # Confirming direction → full size
        return 1.0

    # Counter-directional: apply attention gate
    if abn_attention >= attn_threshold:
        log.info(
            "sentiment_counter_signal_strong",
            ticker=ticker,
            side=side,
            sentiment_res=round(sentiment_res, 4),
            abn_attention=round(abn_attention, 4),
        )
        return 0.0


    return 0.5


def _direction_adj(sentiment_is_positive: bool, abn_attention: float, attn_threshold: float) -> float:
    """
    Returns 1.0 for confirming sentiment (called without direction context),
    0.5 for ambiguous, 0.0 for high-attention counter signal.

    Without direction context, all non-neutral sentiment is treated as
    potentially counter — callers with direction context should use
    compute_directional_sentiment_adj instead.
    """
    if abn_attention >= attn_threshold:
        return 0.0
    return 0.5
