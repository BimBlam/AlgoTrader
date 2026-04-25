"""
S5 Sentiment Engine — entry point.

Called by the orchestrator (S1) as:
    from s5_sentiment.main import run
    run(run_id="<uuid>")

Responsibilities (per spec):
  1. Load config and initialise DB.
  2. Read today's raw news + social JSON from HDD.
  3. Preprocess text and score with FinBERT (fallback → none).
  4. Aggregate per-ticker: raw_sentiment, abn_attention.
  5. Residualize sentiment against lagged values from DB.
  6. Write one sentiment_scores row per universe ticker.
  7. Emit SENTIMENT_READY on success, SENTIMENT_ERROR on model failure.

Failure modes:
  - Missing raw files: degrade gracefully (empty document list for that source).
  - Model failure: fall back to model_used='none'; emit SENTIMENT_ERROR WARNING.
  - DB write failure: raise SentimentError; caller (S1) handles retry.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shared.config_loader import get_config
from shared.db import get_session, init_db
from shared.exceptions import SentimentError
from shared.logger import get_logger
from shared.models import SentimentScore, SystemEvent

from s5_sentiment.aggregator import aggregate_scores
from s5_sentiment.preprocessor import build_ticker_patterns, preprocess_item
from s5_sentiment.residualizer import residualize, ResidualizedScore
from s5_sentiment.scorer import score_texts, MODEL_NONE
from s5_sentiment.utils import utc_now, utc_today, raw_news_path, raw_social_path

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants derived from spec — not hardcoded values, just symbolic names.
# ---------------------------------------------------------------------------
_SUBSYSTEM = "S5"
_HISTORY_DAYS = 30  # attention lookback; also used to bound DB query


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(run_id: str) -> None:
    """
    Execute the full sentiment scoring pipeline for today.

    Parameters
    ----------
    run_id:
        UUID string of the jobs row created by S1 for this run.
        Written to every sentiment_scores row and system_events row for
        end-to-end traceability.
    """
    cfg = get_config()
    init_db(cfg.system.db_url)

    today = utc_today()
    log.info("s5_run_start", run_id=run_id, date=str(today))

    tickers: list[str] = [t.upper() for t in cfg.universe.tickers]
    if not tickers:
        _emit_event(
            run_id=run_id,
            event_type="SENTIMENT_ERROR",
            severity="WARNING",
            message="Universe ticker list is empty; nothing to score.",
            payload={"date": str(today)},
        )
        raise SentimentError("Universe ticker list is empty.")

    # ------------------------------------------------------------------
    # Step 1 — load raw documents
    # ------------------------------------------------------------------
    news_items = _load_json_file(
        raw_news_path(cfg.system.data_dir_hdd, today), "news", run_id
    )
    social_items = _load_json_file(
        raw_social_path(cfg.system.data_dir_hdd, today), "social", run_id
    )
    all_items: list[dict[str, Any]] = news_items + social_items

    log.info(
        "s5_documents_loaded",
        run_id=run_id,
        news_count=len(news_items),
        social_count=len(social_items),
    )

    # ------------------------------------------------------------------
    # Step 2 — preprocess and identify ticker mentions
    # ------------------------------------------------------------------
    ticker_patterns = build_ticker_patterns(tickers)
    texts: list[str] = []
    ticker_mention_map: list[list[str]] = []  # parallel to texts

    for item in all_items:
        cleaned, mentioned = preprocess_item(item, ticker_patterns)
        texts.append(cleaned)
        ticker_mention_map.append(mentioned)

    # ------------------------------------------------------------------
    # Step 3 — score texts
    # ------------------------------------------------------------------
    model_failed = False
    scored_items = score_texts(
        texts=texts,
        primary_model=cfg.sentiment.model,
        finbert_model_id=cfg.sentiment.finbert_model_id,
        device=cfg.system.gpu_device,
    )

    # Detect model failure: if every non-empty text came back as MODEL_NONE,
    # the model is unavailable and we must emit SENTIMENT_ERROR.
    non_empty_count = sum(1 for t in texts if t)
    none_count = sum(
        1 for t, s in zip(texts, scored_items)
        if t and s.model_used == MODEL_NONE
    )
    if non_empty_count > 0 and none_count == non_empty_count:
        model_failed = True
        _emit_event(
            run_id=run_id,
            event_type="SENTIMENT_ERROR",
            severity="WARNING",
            message=(
                f"All {non_empty_count} non-empty texts scored as model_used='none'. "
                "Primary model unavailable; falling back to none."
            ),
            payload={"model": cfg.sentiment.model, "date": str(today)},
        )

    # ------------------------------------------------------------------
    # Step 4 — build flat (ticker, ScoredItem) list for aggregation
    # ------------------------------------------------------------------
    scored_pairs = []
    for mentions, scored_item in zip(ticker_mention_map, scored_items):
        for ticker in mentions:
            scored_pairs.append((ticker, scored_item))

    # ------------------------------------------------------------------
    # Step 5 — load DB history for attention z-score and residualization
    # ------------------------------------------------------------------
    with get_session() as session:
        attention_history = _load_attention_history(
            session, tickers, today, _HISTORY_DAYS
        )
        sentiment_history = _load_sentiment_history(
            session, tickers, today, lookback=5
        )

    # ------------------------------------------------------------------
    # Step 6 — aggregate
    # ------------------------------------------------------------------
    aggregates = aggregate_scores(
        scored_pairs=scored_pairs,
        tickers=tickers,
        history=attention_history,
        attention_lookback_days=cfg.sentiment.attention_lookback_days,
    )

    # ------------------------------------------------------------------
    # Step 7 — residualize
    # ------------------------------------------------------------------
    final_scores = residualize(
        today_aggregates=aggregates,
        history=sentiment_history,
    )

    # ------------------------------------------------------------------
    # Step 8 — write to DB (upsert; idempotent on re-run)
    # ------------------------------------------------------------------
    with get_session() as session:
        _write_scores(session, final_scores, run_id, today)
        session.commit()

    log.info(
        "s5_run_complete",
        run_id=run_id,
        date=str(today),
        ticker_count=len(final_scores),
        model_failed=model_failed,
    )

    # ------------------------------------------------------------------
    # Step 9 — emit completion event
    # ------------------------------------------------------------------
    _emit_event(
        run_id=run_id,
        event_type="SENTIMENT_READY",
        severity="INFO",
        message=f"Sentiment scoring complete for {today}. "
                f"{len(final_scores)} tickers written.",
        payload={
            "date": str(today),
            "ticker_count": len(final_scores),
            "model": cfg.sentiment.model,
            "model_failed": model_failed,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json_file(
    path: Path, source_label: str, run_id: str
) -> list[dict[str, Any]]:
    """
    Read a JSON file produced by S2 and return its contents as a list.

    Degrades gracefully: if the file is missing or malformed, logs a warning
    and returns an empty list rather than raising.  A missing news or social
    file is not fatal — the pipeline scores whatever data is available.
    """
    if not path.exists():
        log.warning(
            "s5_source_file_missing",
            source=source_label,
            path=str(path),
            run_id=run_id,
        )
        return []

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(
            "s5_source_file_unreadable",
            source=source_label,
            path=str(path),
            error=str(exc),
            run_id=run_id,
        )
        return []

    if isinstance(data, list):
        return data
    # S2 may wrap the list in a top-level object with a "items" key.
    if isinstance(data, dict):
        return data.get("items", [])

    log.warning(
        "s5_source_file_unexpected_format",
        source=source_label,
        path=str(path),
        run_id=run_id,
    )
    return []


def _load_attention_history(
    session: Session,
    tickers: list[str],
    today: datetime.date,
    lookback_days: int,
) -> dict[str, list[int]]:
    """
    Fetch daily raw_mention counts for the prior *lookback_days* days.

    Returns a dict mapping ticker → list of int, oldest first.
    Tickers with no history return an empty list (not a KeyError).
    """
    since = today - datetime.timedelta(days=lookback_days + 1)

    rows = (
        session.query(
            SentimentScore.ticker,
            SentimentScore.date,
            SentimentScore.raw_mentions,
        )
        .filter(
            SentimentScore.ticker.in_(tickers),
            SentimentScore.date >= since,
            SentimentScore.date < today,
        )
        .order_by(SentimentScore.ticker, SentimentScore.date)
        .all()
    )

    result: dict[str, list[int]] = {t: [] for t in tickers}
    for ticker, _date, raw_mentions in rows:
        result[ticker].append(int(raw_mentions))
    return result


def _load_sentiment_history(
    session: Session,
    tickers: list[str],
    today: datetime.date,
    lookback: int,
) -> dict[str, list[tuple[float, float]]]:
    """
    Fetch (raw_sentiment, abn_attention) tuples for residualization.

    Returns a dict mapping ticker → [(raw_sentiment, abn_attention), ...],
    oldest first, for the prior *lookback* days.
    """
    since = today - datetime.timedelta(days=lookback + 1)

    rows = (
        session.query(
            SentimentScore.ticker,
            SentimentScore.date,
            SentimentScore.raw_sentiment,
            SentimentScore.abn_attention,
        )
        .filter(
            SentimentScore.ticker.in_(tickers),
            SentimentScore.date >= since,
            SentimentScore.date < today,
        )
        .order_by(SentimentScore.ticker, SentimentScore.date)
        .all()
    )

    result: dict[str, list[tuple[float, float]]] = {t: [] for t in tickers}
    for ticker, _date, raw_sent, abn_att in rows:
        result[ticker].append((float(raw_sent), float(abn_att)))
    return result


def _write_scores(
    session: Session,
    scores: list[ResidualizedScore],
    run_id: str,
    date: datetime.date,
) -> None:
    """
    Upsert one sentiment_scores row per ticker.

    Uses PostgreSQL INSERT … ON CONFLICT DO UPDATE so the pipeline is
    idempotent — a re-run for the same date overwrites the previous values
    rather than raising a unique constraint error.
    """
    for score in scores:
        stmt = (
            pg_insert(SentimentScore)
            .values(
                run_id=run_id,
                date=date,
                ticker=score.ticker,
                raw_mentions=score.raw_mentions,
                abn_attention=score.abn_attention,
                raw_sentiment=score.raw_sentiment,
                sentiment_res=score.sentiment_res,
                model_used=score.model_used,
            )
            .on_conflict_do_update(
                index_elements=["date", "ticker"],
                set_={
                    "run_id": run_id,
                    "raw_mentions": score.raw_mentions,
                    "abn_attention": score.abn_attention,
                    "raw_sentiment": score.raw_sentiment,
                    "sentiment_res": score.sentiment_res,
                    "model_used": score.model_used,
                },
            )
        )
        session.execute(stmt)


def _emit_event(
    run_id: str,
    event_type: str,
    severity: str,
    message: str,
    payload: dict | None = None,
) -> None:
    """
    Write a row to system_events and log at the corresponding level.

    Never raises — a failure here must not prevent the pipeline from
    completing its primary work.
    """
    try:
        with get_session() as session:
            event = SystemEvent(
                timestamp=utc_now(),
                event_type=event_type,
                severity=severity,
                subsystem=_SUBSYSTEM,
                run_id=run_id,
                message=message,
                payload=payload or {},
            )
            session.add(event)
            session.commit()
    except Exception as exc:  # pragma: no cover
        log.error(
            "s5_emit_event_failed",
            event_type=event_type,
            error=str(exc),
        )

    # Mirror to structured log regardless of DB outcome.
    level = severity.lower()
    getattr(log, level if level in ("info", "warning", "error", "critical") else "info")(
        event_type.lower(),
        run_id=run_id,
        message=message,
    )
