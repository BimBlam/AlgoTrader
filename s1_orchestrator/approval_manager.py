"""
Approval flow for pending trading signals.

Implements the HARD / SOFT distinction from §3.2:

  HARD — write PENDING_APPROVAL state and block; the dashboard (S7) must flip
         signal.status manually.  The orchestrator only polls for the
         dashboard's decision.

  SOFT — auto-approve signals whose ``sentiment_adj`` meets the configured
         confidence threshold AND whose status is still PENDING.  Writes
         ``approved_by='AUTO'`` and ``approved_at=now()``.

In BOTH mode, the paper pipeline always uses SOFT approval and the live
pipeline uses whatever ``approval_mode`` is set in config (§3.1).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.constants import ApprovalMode, EventType, Severity, SignalStatus, SystemMode
from shared.logger import get_logger
from shared.models import Signal, SystemEvent

log = get_logger(__name__)

# The minimum sentiment_adj value a signal must have to pass SOFT auto-approval.
# Sourced from risk.yaml: there is no single "confidence_threshold" key, so we
# derive from sentiment_params.yaml threshold values.  The caller passes this
# value in from config rather than having this module reach into config directly
# (keeps this module unit-testable without a real config).
_DEFAULT_SOFT_THRESHOLD = 0.5


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _write_approval_event(
    session: Session,
    *,
    run_id: str,
    n_approved: int,
    mode: str,
) -> None:
    event = SystemEvent(
        timestamp=_utcnow(),
        event_type=EventType.APPROVAL_GRANTED.value,
        severity=Severity.INFO.value,
        subsystem="S1",
        run_id=run_id,
        message=f"Auto-approved {n_approved} signal(s) via {mode} approval",
        payload={"n_approved": n_approved, "approval_mode": mode},
    )
    session.add(event)


class ApprovalManager:
    """Evaluates and executes the approval policy for a given set of signals.

    Parameters
    ----------
    approval_mode:
        The mode read from ``system.yaml``.
    system_mode:
        The overall system mode (PAPER / LIVE / BOTH / DISABLED).
    soft_threshold:
        Minimum ``sentiment_adj`` required for SOFT auto-approval.
    """

    def __init__(
        self,
        approval_mode: ApprovalMode,
        system_mode: SystemMode,
        soft_threshold: float = _DEFAULT_SOFT_THRESHOLD,
    ) -> None:
        self.approval_mode = approval_mode
        self.system_mode = system_mode
        self.soft_threshold = soft_threshold

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process_pending_signals(
        self,
        session: Session,
        run_id: str,
        account_type: str = "PAPER",
    ) -> tuple[int, int]:
        """Attempt to approve or leave-pending all PENDING signals for this run.

        Parameters
        ----------
        session:
            Active SQLAlchemy session.  Caller commits.
        run_id:
            The job run_id whose signals we are evaluating.
        account_type:
            'PAPER' or 'LIVE' — used to enforce the stricter policy for live.

        Returns
        -------
        (n_approved, n_pending)
            How many signals were auto-approved, and how many remain PENDING
            (requiring dashboard action).
        """
        pending: list[Signal] = (
            session.query(Signal)
            .filter(
                Signal.run_id == run_id,
                Signal.status == SignalStatus.PENDING.value,
            )
            .all()
        )

        if not pending:
            log.info("approval_no_pending", run_id=run_id)
            return 0, 0

        effective_mode = self._effective_mode(account_type)

        if effective_mode == ApprovalMode.SOFT:
            return self._auto_approve(session, pending, run_id)
        else:
            # HARD: log and leave everything as PENDING for the dashboard.
            log.info(
                "approval_hard_waiting",
                run_id=run_id,
                n_pending=len(pending),
                account_type=account_type,
            )
            return 0, len(pending)

    def has_all_approved(self, session: Session, run_id: str) -> bool:
        """Return True when every signal for this run is no longer PENDING.

        Used by the orchestrator poll loop to detect when the dashboard has
        completed manual approvals so we can advance to EXECUTING.
        """
        remaining = (
            session.query(Signal)
            .filter(
                Signal.run_id == run_id,
                Signal.status == SignalStatus.PENDING.value,
            )
            .count()
        )
        return remaining == 0

    def has_any_approved(self, session: Session, run_id: str) -> bool:
        """Return True if at least one signal has been APPROVED."""
        approved = (
            session.query(Signal)
            .filter(
                Signal.run_id == run_id,
                Signal.status == SignalStatus.APPROVED.value,
            )
            .count()
        )
        return approved > 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_mode(self, account_type: str) -> ApprovalMode:
        """Determine the approval mode to apply for this account_type.

        In BOTH mode, the paper leg always uses SOFT; the live leg follows
        whatever is configured.  A LIVE account can never silently downgrade
        to SOFT unless explicitly configured (§3.2).
        """
        if self.system_mode == SystemMode.BOTH and account_type == "PAPER":
            return ApprovalMode.SOFT
        return self.approval_mode

    def _auto_approve(
        self,
        session: Session,
        signals: list[Signal],
        run_id: str,
    ) -> tuple[int, int]:
        """Apply SOFT auto-approval to qualifying signals.

        A signal qualifies when ``sentiment_adj >= soft_threshold``.
        Signals below threshold are left PENDING for manual review.
        """
        approved = 0
        pending = 0
        now = _utcnow()

        for signal in signals:
            if signal.sentiment_adj >= self.soft_threshold:
                signal.status = SignalStatus.APPROVED.value
                signal.approved_by = "AUTO"
                signal.approved_at = now
                approved += 1
                log.info(
                    "signal_auto_approved",
                    signal_id=signal.id,
                    ticker=signal.ticker,
                    sentiment_adj=signal.sentiment_adj,
                )
            else:
                pending += 1
                log.info(
                    "signal_below_threshold",
                    signal_id=signal.id,
                    ticker=signal.ticker,
                    sentiment_adj=signal.sentiment_adj,
                    threshold=self.soft_threshold,
                )

        if approved > 0:
            _write_approval_event(
                session, run_id=run_id, n_approved=approved, mode="SOFT"
            )

        log.info(
            "auto_approval_complete",
            run_id=run_id,
            approved=approved,
            pending_manual=pending,
        )
        return approved, pending
