"""
S2 Data Ingestion — entry point.

Claimed by S1 via the jobs table. Orchestrates:
  1. OHLCV download + validation per ticker
  2. Daily returns parquet computation
  3. Raw news + social scrape to HDD JSON
  4. Terminal system_events row (DATA_READY / DATA_STALE / DATA_ERROR)

Called as: python -m s2_data_ingestion.main <run_id>
S1 supplies the run_id string (UUID) as argv[1].
"""

from __future__ import annotations

import datetime
import sys

from shared.config_loader import get_config
from shared.db import get_session, init_db
from shared.logger import get_logger
from shared.constants import EventType, Severity
from shared.exceptions import DataError
from shared.models import SystemEvent

from s2_data_ingestion.downloader import download_and_persist_ohlcv
from s2_data_ingestion.validator import validate_ohlcv
from s2_data_ingestion.returns import compute_and_write_returns
from s2_data_ingestion.scraper import scrape_news, scrape_social

log = get_logger(__name__)

# Per spec: "do not halt the entire run unless >20% of universe fails"
_MAX_FAILURE_RATE: float = 0.20


def run(run_id: str) -> None:
    """
    Execute a full S2 ingest cycle for today's trading date.

    Args:
        run_id: UUID string matching the jobs.run_id created by S1.

    Raises:
        DataError: Only when the universe failure rate exceeds _MAX_FAILURE_RATE,
                   or when the returns parquet cannot be written at all.
                   Below that threshold, partial failures are recorded as
                   DATA_STALE events and the run continues.
    """
    cfg = get_config()
    # [FIX] Deviation #5: init_db called explicitly at subsystem entry point.
    init_db(cfg.system.db_url)

    logger = log.bind(run_id=run_id)
    today: datetime.date = datetime.datetime.now(datetime.timezone.utc).date()
    tickers: list[str] = [t.upper() for t in cfg.universe.tickers]

    if not tickers:
        _emit_event(
            run_id=run_id,
            event_type=EventType.DATA_ERROR,
            severity=Severity.ERROR,
            message="Universe ticker list is empty; cannot run ingestion.",
            payload={"date": str(today)},
        )
        raise DataError("Universe ticker list is empty.")

    logger.info("s2.ingest.start", ticker_count=len(tickers), date=str(today))

    failed_tickers: list[str] = []
    valid_tickers: list[str] = []

    # ── Phase 1 + 2: Download & Validate ────────────────────────────────────
    for ticker in tickers:
        try:
            df = download_and_persist_ohlcv(ticker, cfg, today)
            issues = validate_ohlcv(df, ticker)
            if issues:
                logger.warning("s2.ohlcv.validation_failed", ticker=ticker, issues=issues)
                _emit_event(
                    run_id=run_id,
                    event_type=EventType.DATA_STALE,
                    severity=Severity.WARNING,
                    message=f"OHLCV validation failed for {ticker}: {'; '.join(issues)}",
                    payload={"ticker": ticker, "date": str(today), "issues": issues},
                )
                failed_tickers.append(ticker)
            else:
                valid_tickers.append(ticker)
        except Exception as exc:
            logger.error("s2.ohlcv.download_error", ticker=ticker, error=str(exc))
            _emit_event(
                run_id=run_id,
                event_type=EventType.DATA_STALE,
                severity=Severity.WARNING,
                message=f"OHLCV download/persist error for {ticker}: {exc}",
                payload={"ticker": ticker, "date": str(today), "error": str(exc)},
            )
            failed_tickers.append(ticker)

    failure_rate = len(failed_tickers) / len(tickers)
    if failure_rate > _MAX_FAILURE_RATE:
        msg = (
            f"{len(failed_tickers)}/{len(tickers)} tickers failed "
            f"({failure_rate:.0%}), exceeding the 20% abort threshold."
        )
        logger.error("s2.ingest.abort", reason=msg)
        _emit_event(
            run_id=run_id,
            event_type=EventType.DATA_ERROR,
            severity=Severity.ERROR,
            message=msg,
            payload={
                "date": str(today),
                "failed_tickers": failed_tickers,
                "failure_rate": round(failure_rate, 4),
            },
        )
        raise DataError(msg)

    # ── Phase 3: Returns parquet ─────────────────────────────────────────────
    try:
        compute_and_write_returns(valid_tickers, cfg, today)
    except Exception as exc:
        logger.error("s2.returns.error", error=str(exc))
        _emit_event(
            run_id=run_id,
            event_type=EventType.DATA_ERROR,
            severity=Severity.ERROR,
            message=f"Returns computation failed: {exc}",
            payload={"date": str(today), "error": str(exc)},
        )
        raise DataError(f"Returns computation failed: {exc}") from exc

    # ── Phase 4: Scrape raw text (non-fatal) ─────────────────────────────────
    for scrape_fn, label in [(scrape_news, "news"), (scrape_social, "social")]:
        try:
            scrape_fn(valid_tickers, cfg, today)
        except Exception as exc:
            logger.warning(f"s2.{label}.scrape_error", error=str(exc))
            _emit_event(
                run_id=run_id,
                event_type=EventType.DATA_STALE,
                severity=Severity.WARNING,
                message=f"{label.capitalize()} scrape failed (non-fatal): {exc}",
                payload={"date": str(today), "source": label},
            )

    # ── Terminal event ────────────────────────────────────────────────────────
    if failed_tickers:
        _emit_event(
            run_id=run_id,
            event_type=EventType.DATA_STALE,
            severity=Severity.WARNING,
            message=(
                f"Ingestion complete with {len(failed_tickers)} excluded tickers. "
                f"{len(valid_tickers)} tickers written to returns parquet."
            ),
            payload={
                "date": str(today),
                "valid_count": len(valid_tickers),
                "failed_tickers": failed_tickers,
            },
        )
    else:
        _emit_event(
            run_id=run_id,
            event_type=EventType.DATA_READY,
            severity=Severity.INFO,
            message=f"Ingestion complete. {len(valid_tickers)} tickers ready.",
            payload={"date": str(today), "valid_count": len(valid_tickers)},
        )

    logger.info(
        "s2.ingest.complete",
        valid=len(valid_tickers),
        failed=len(failed_tickers),
        date=str(today),
    )


def _emit_event(
    run_id: str,
    event_type: EventType,
    severity: Severity,
    message: str,
    payload: dict | None = None,
) -> None:
    """
    Write one row to system_events.

    Deliberately isolated so that a DB failure here never masks the
    original exception that triggered the event.
    """
    try:
        with get_session() as session:
            event = SystemEvent(
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                event_type=event_type.value,
                severity=severity.value,
                subsystem="S2",
                run_id=run_id,
                message=message,
                payload=payload,
            )
            session.add(event)
            session.commit()
    except Exception as db_exc:
        get_logger(__name__).error(
            "s2.event_write_failed",
            error=str(db_exc),
            original_message=message,
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        get_logger(__name__).error("s2.main.no_run_id", detail="Pass run_id as argv[1].")
        sys.exit(1)
    run(run_id=sys.argv[1])
