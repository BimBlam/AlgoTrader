"""Unit tests for shared/logger.py."""
import logging


from shared.logger import _configure_structlog, get_logger


def test_get_logger_returns_bound_logger(tmp_path):
    _configure_structlog("INFO", str(tmp_path))
    logger = get_logger("test.module")
    # structlog BoundLoggers expose standard log-level methods.
    assert callable(getattr(logger, "info", None))
    assert callable(getattr(logger, "error", None))


def test_get_logger_accepts_module_name(tmp_path):
    _configure_structlog("DEBUG", str(tmp_path))
    logger = get_logger(__name__)
    assert logger is not None


def test_log_dir_created(tmp_path):
    import shared.logger as logger_mod
    logger_mod._configured = False          # reset so configure runs fresh

    log_dir = tmp_path / "nested" / "logs"
    assert not log_dir.exists()
    _configure_structlog("INFO", str(log_dir))
    assert log_dir.exists()

    logger_mod._configured = False          # clean up for other tests



def test_configure_is_idempotent(tmp_path):
    """Calling _configure_structlog twice must not add duplicate handlers."""
    _configure_structlog("INFO", str(tmp_path))
    handler_count_before = len(logging.getLogger().handlers)
    _configure_structlog("INFO", str(tmp_path))
    handler_count_after = len(logging.getLogger().handlers)
    assert handler_count_after == handler_count_before
