"""
Integration-style unit tests for the main.run() orchestration function.

All external I/O (yfinance, DB, config) is mocked. These tests verify
the event-emission logic and abort thresholds without a real database.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch
import types

import pandas as pd
import pytest

from s2_data_ingestion import main
from shared.exceptions import DataError


@pytest.fixture()
def patched_env(mock_cfg):
    """Patch all external calls that main.run() depends on."""
    with (
        patch("s2_data_ingestion.main.get_config", return_value=mock_cfg),
        patch("s2_data_ingestion.main.init_db"),
        patch("s2_data_ingestion.main.get_session"),
        patch("s2_data_ingestion.main.SystemEvent"),
    ):
        yield


class TestRunSuccess:
    def test_data_ready_emitted_on_full_success(self, patched_env, mock_cfg, today):
        with (
            patch("s2_data_ingestion.main.download_and_persist_ohlcv", return_value=pd.DataFrame()),
            patch("s2_data_ingestion.main.validate_ohlcv", return_value=[]),
            patch("s2_data_ingestion.main.compute_and_write_returns"),
            patch("s2_data_ingestion.main.scrape_news"),
            patch("s2_data_ingestion.main.scrape_social"),
            patch("s2_data_ingestion.main._emit_event") as mock_emit,
            patch("s2_data_ingestion.main.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value.date.return_value = today
            mock_dt.datetime.now.return_value = datetime.datetime(2024, 3, 15, tzinfo=datetime.timezone.utc)
            mock_dt.timezone = datetime.timezone

            main.run("test-run-id-001")

        event_types = [c.kwargs["event_type"] for c in mock_emit.call_args_list]
        from shared.constants import EventType
        assert EventType.DATA_READY in event_types

    def test_data_stale_emitted_when_one_ticker_fails(self, patched_env, today):
      """1/5 = 20% failure rate — below threshold, run continues with DATA_STALE."""
      import types as _types
      cfg_5 = _types.SimpleNamespace(
          system=_types.SimpleNamespace(
              db_url="x", data_dir_ssd="/tmp", data_dir_hdd="/tmp", log_level="DEBUG"
          ),
          universe=_types.SimpleNamespace(
              tickers=["A", "B", "C", "D", "E"],
              sector_etf_map={},
          ),
          sentiment=_types.SimpleNamespace(
              sources={
                  "news":    {"enabled": False},
                  "reddit":  {"enabled": False},
                  "twitter": {"enabled": False},
              }
          ),
      )
      call_count = [0]

      def fail_first_ticker(ticker, cfg, date):
          call_count[0] += 1
          if call_count[0] == 1:
              raise RuntimeError("Simulated download failure")
          return pd.DataFrame()

      with (
          patch("s2_data_ingestion.main.get_config", return_value=cfg_5),
          patch("s2_data_ingestion.main.init_db"),
          patch("s2_data_ingestion.main.get_session"),
          patch("s2_data_ingestion.main.SystemEvent"),
          patch("s2_data_ingestion.main.download_and_persist_ohlcv", side_effect=fail_first_ticker),
          patch("s2_data_ingestion.main.validate_ohlcv", return_value=[]),
          patch("s2_data_ingestion.main.compute_and_write_returns"),
          patch("s2_data_ingestion.main.scrape_news"),
          patch("s2_data_ingestion.main.scrape_social"),
          patch("s2_data_ingestion.main._emit_event") as mock_emit,
          patch("s2_data_ingestion.main.datetime") as mock_dt,
      ):
          mock_dt.datetime.now.return_value.date.return_value = today
          mock_dt.datetime.now.return_value = datetime.datetime(2024, 3, 15, tzinfo=datetime.timezone.utc)
          mock_dt.timezone = datetime.timezone

          main.run("test-run-id-002")  # Must NOT raise

      from shared.constants import EventType
      event_types = [c.kwargs["event_type"] for c in mock_emit.call_args_list]
      assert EventType.DATA_STALE in event_types
      assert EventType.DATA_ERROR not in event_types



class TestAbortThreshold:
    def test_data_error_and_raises_when_over_20pct(self, patched_env, mock_cfg, today):
        """Both tickers in mock_cfg fail → 100% failure rate → DataError."""
        with (
            patch("s2_data_ingestion.main.download_and_persist_ohlcv",
                  side_effect=RuntimeError("all fail")),
            patch("s2_data_ingestion.main._emit_event"),
            patch("s2_data_ingestion.main.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value.date.return_value = today
            mock_dt.timezone = datetime.timezone

            with pytest.raises(DataError, match="20%"):
                main.run("test-run-id-003")

    def test_does_not_raise_when_one_of_five_fails(self, patched_env, today):
        """1/5 = 20% — exactly at the threshold, should NOT raise (rule is >20%)."""
        cfg_5 = types.SimpleNamespace(
            system=types.SimpleNamespace(
                db_url="x", data_dir_ssd="/tmp", data_dir_hdd="/tmp", log_level="DEBUG"
            ),
            universe=types.SimpleNamespace(
                tickers=["A", "B", "C", "D", "E"],
                sector_etf_map={},
            ),
            sentiment=types.SimpleNamespace(sources={"news": {"enabled": False},
                                                       "reddit": {"enabled": False},
                                                       "twitter": {"enabled": False}}),
        )
        call_count = [0]

        def partial_fail(ticker, cfg, date):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("one fail")
            return pd.DataFrame()

        with (
            patch("s2_data_ingestion.main.get_config", return_value=cfg_5),
            patch("s2_data_ingestion.main.init_db"),
            patch("s2_data_ingestion.main.get_session"),
            patch("s2_data_ingestion.main.SystemEvent"),
            patch("s2_data_ingestion.main.download_and_persist_ohlcv", side_effect=partial_fail),
            patch("s2_data_ingestion.main.validate_ohlcv", return_value=[]),
            patch("s2_data_ingestion.main.compute_and_write_returns"),
            patch("s2_data_ingestion.main.scrape_news"),
            patch("s2_data_ingestion.main.scrape_social"),
            patch("s2_data_ingestion.main._emit_event"),
            patch("s2_data_ingestion.main.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value.date.return_value = today
            mock_dt.timezone = datetime.timezone
            # Should not raise.
            main.run("test-run-id-004")


class TestEmptyUniverse:
    def test_raises_data_error_on_empty_ticker_list(self, patched_env, mock_cfg, today):
        mock_cfg.universe.tickers = []
        with (
            patch("s2_data_ingestion.main._emit_event"),
            patch("s2_data_ingestion.main.datetime") as mock_dt,
        ):
            mock_dt.datetime.now.return_value.date.return_value = today
            mock_dt.timezone = datetime.timezone
            with pytest.raises(DataError, match="empty"):
                main.run("test-run-id-005")
