"""Tests for s1_orchestrator.approval_manager."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock


from shared.constants import ApprovalMode, SignalStatus, SystemMode
from s1_orchestrator.approval_manager import ApprovalManager


def make_signal(sentiment_adj: float = 0.8, status: str = "PENDING"):
    sig = MagicMock()
    sig.id = 1
    sig.ticker = "AAPL"
    sig.sentiment_adj = sentiment_adj
    sig.status = status
    sig.approved_by = None
    sig.approved_at = None
    return sig


def make_session(pending_signals=None, approved_count=0, pending_count=0):
    session = MagicMock()

    filter_mock = MagicMock()
    filter_mock.all.return_value = pending_signals or []
    filter_mock.count.return_value = approved_count

    # Two separate filter chains: .all() and .count()
    session.query.return_value.filter.return_value = filter_mock
    return session


class TestSoftApproval:
    def test_auto_approves_high_confidence_signals(self):
        signals = [make_signal(sentiment_adj=0.8), make_signal(sentiment_adj=0.9)]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.SOFT,
            system_mode=SystemMode.PAPER,
            soft_threshold=0.5,
        )
        approved, pending = mgr.process_pending_signals(session, run_id=str(uuid.uuid4()))

        assert approved == 2
        assert pending == 0
        for sig in signals:
            assert sig.status == SignalStatus.APPROVED.value
            assert sig.approved_by == "AUTO"
            assert sig.approved_at is not None

    def test_leaves_low_confidence_signals_pending(self):
        signals = [make_signal(sentiment_adj=0.2), make_signal(sentiment_adj=0.3)]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.SOFT,
            system_mode=SystemMode.PAPER,
            soft_threshold=0.5,
        )
        approved, pending = mgr.process_pending_signals(session, run_id=str(uuid.uuid4()))

        assert approved == 0
        assert pending == 2

    def test_mixed_confidence_partial_approval(self):
        signals = [
            make_signal(sentiment_adj=0.7),   # approve
            make_signal(sentiment_adj=0.2),   # leave pending
        ]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.SOFT,
            system_mode=SystemMode.PAPER,
            soft_threshold=0.5,
        )
        approved, pending = mgr.process_pending_signals(session, run_id=str(uuid.uuid4()))
        assert approved == 1
        assert pending == 1

    def test_no_pending_signals_returns_zero(self):
        session = make_session(pending_signals=[])
        mgr = ApprovalManager(
            approval_mode=ApprovalMode.SOFT,
            system_mode=SystemMode.PAPER,
        )
        approved, pending = mgr.process_pending_signals(session, run_id=str(uuid.uuid4()))
        assert approved == 0
        assert pending == 0


class TestHardApproval:
    def test_hard_mode_leaves_all_pending(self):
        signals = [make_signal(sentiment_adj=0.99), make_signal(sentiment_adj=0.99)]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.HARD,
            system_mode=SystemMode.LIVE,
        )
        approved, pending = mgr.process_pending_signals(
            session, run_id=str(uuid.uuid4()), account_type="LIVE"
        )
        assert approved == 0
        assert pending == 2
        # Signals must not have been modified.
        for sig in signals:
            assert sig.status == "PENDING"


class TestBothModePaperAutoApprove:
    """In BOTH mode, paper leg always uses SOFT regardless of configured approval_mode."""

    def test_paper_leg_auto_approved_in_both_mode(self):
        signals = [make_signal(sentiment_adj=0.8)]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.HARD,  # overall config is HARD
            system_mode=SystemMode.BOTH,
            soft_threshold=0.5,
        )
        approved, pending = mgr.process_pending_signals(
            session, run_id=str(uuid.uuid4()), account_type="PAPER"
        )
        assert approved == 1
        assert pending == 0

    def test_live_leg_respects_hard_mode_in_both(self):
        signals = [make_signal(sentiment_adj=0.8)]
        session = make_session(pending_signals=signals)

        mgr = ApprovalManager(
            approval_mode=ApprovalMode.HARD,
            system_mode=SystemMode.BOTH,
        )
        approved, pending = mgr.process_pending_signals(
            session, run_id=str(uuid.uuid4()), account_type="LIVE"
        )
        assert approved == 0
        assert pending == 1


class TestHasAllApproved:
    def test_returns_true_when_no_pending(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        mgr = ApprovalManager(ApprovalMode.HARD, SystemMode.PAPER)
        assert mgr.has_all_approved(session, "run_id") is True

    def test_returns_false_when_pending_remain(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 3
        mgr = ApprovalManager(ApprovalMode.HARD, SystemMode.PAPER)
        assert mgr.has_all_approved(session, "run_id") is False


class TestHasAnyApproved:
    def test_returns_true_when_approved_exist(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 2
        mgr = ApprovalManager(ApprovalMode.SOFT, SystemMode.PAPER)
        assert mgr.has_any_approved(session, "run_id") is True

    def test_returns_false_when_none_approved(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.count.return_value = 0
        mgr = ApprovalManager(ApprovalMode.SOFT, SystemMode.PAPER)
        assert mgr.has_any_approved(session, "run_id") is False
