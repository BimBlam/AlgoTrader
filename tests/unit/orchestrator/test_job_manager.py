"""Tests for algotrader.orchestrator.job_manager."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from algotrader.shared.constants import JobStatus
from algotrader.shared.exceptions import DataError
from algotrader.orchestrator.job_manager import (
    _EXPECTED_DURATION_MINUTES,
    create_job,
    get_stale_running_jobs,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
)


@pytest.fixture()
def mock_session():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()
    return session


@pytest.fixture()
def cfg():
    return SimpleNamespace(system=SimpleNamespace(mode="PAPER", approval_mode="HARD"))


def make_job(job_type="INGEST_EOD", status=JobStatus.RUNNING.value, started_offset_minutes=-100):
    from algotrader.shared.models import Job
    job = MagicMock(spec=Job)
    job.run_id = str(uuid.uuid4())
    job.job_type = job_type
    job.status = status
    job.started_at = datetime.now(tz=timezone.utc) + timedelta(minutes=started_offset_minutes)
    job.retry_count = 0
    return job


class TestCreateJob:
    def test_creates_pending_job(self, mock_session, cfg):
        job = create_job(mock_session, "INGEST_EOD", cfg)
        assert job.status == JobStatus.PENDING.value
        assert job.job_type == "INGEST_EOD"
        mock_session.add.assert_called_once()

    def test_uses_provided_run_id(self, mock_session, cfg):
        rid = str(uuid.uuid4())
        job = create_job(mock_session, "INGEST_EOD", cfg, run_id=rid)
        assert job.run_id == rid

    def test_generates_run_id_when_not_provided(self, mock_session, cfg):
        job = create_job(mock_session, "RUN_SIGNALS", cfg)
        assert len(job.run_id) == 36  # UUID4 string length

    def test_raises_on_unknown_job_type(self, mock_session, cfg):
        with pytest.raises(DataError):
            create_job(mock_session, "INVALID_TYPE", cfg)

    def test_all_known_job_types_accepted(self, mock_session, cfg):
        for jt in _EXPECTED_DURATION_MINUTES:
            mock_session.reset_mock()
            job = create_job(mock_session, jt, cfg)
            assert job.job_type == jt


class TestMarkJobStarted:
    def test_sets_running_status(self, mock_session):
        job = make_job(status=JobStatus.PENDING.value)
        mark_job_started(mock_session, job, worker_pid=12345)
        assert job.status == JobStatus.RUNNING.value
        assert job.worker_pid == 12345
        assert job.started_at is not None
        mock_session.add.assert_called_once()  # system_event


class TestMarkJobCompleted:
    def test_sets_done_status(self, mock_session):
        job = make_job(status=JobStatus.RUNNING.value)
        mark_job_completed(mock_session, job)
        assert job.status == JobStatus.DONE.value
        assert job.completed_at is not None
        mock_session.add.assert_called_once()


class TestMarkJobFailed:
    def test_sets_failed_status(self, mock_session):
        job = make_job()
        mark_job_failed(mock_session, job, "boom")
        assert job.status == JobStatus.FAILED.value
        assert job.error_msg == "boom"

    def test_sets_retryable_failed_when_retryable(self, mock_session):
        job = make_job()
        mark_job_failed(mock_session, job, "stale", retryable=True)
        assert job.status == JobStatus.RETRYABLE_FAILED.value


class TestGetStaleRunningJobs:
    def test_returns_jobs_past_2x_timeout(self, mock_session):
        # INGEST_EOD expected = 30 min; stale at 60 min.  We set started 65 min ago.
        stale_job = make_job(job_type="INGEST_EOD", started_offset_minutes=-65)
        fresh_job = make_job(job_type="INGEST_EOD", started_offset_minutes=-10)
        mock_session.query.return_value.filter.return_value.all.return_value = [
            stale_job, fresh_job
        ]
        stale = get_stale_running_jobs(mock_session)
        assert stale_job in stale
        assert fresh_job not in stale

    def test_ignores_job_with_no_started_at(self, mock_session):
        job = make_job()
        job.started_at = None
        mock_session.query.return_value.filter.return_value.all.return_value = [job]
        stale = get_stale_running_jobs(mock_session)
        assert stale == []

    def test_returns_empty_when_no_running_jobs(self, mock_session):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        assert get_stale_running_jobs(mock_session) == []

    def test_backtest_timeout_is_240_minutes(self, mock_session):
        # RUN_BACKTEST expected = 120 min; stale at 241 min.
        job = make_job(job_type="RUN_BACKTEST", started_offset_minutes=-241)
        mock_session.query.return_value.filter.return_value.all.return_value = [job]
        stale = get_stale_running_jobs(mock_session)
        assert job in stale

    def test_backtest_not_stale_at_200_minutes(self, mock_session):
        job = make_job(job_type="RUN_BACKTEST", started_offset_minutes=-200)
        mock_session.query.return_value.filter.return_value.all.return_value = [job]
        stale = get_stale_running_jobs(mock_session)
        assert job not in stale
