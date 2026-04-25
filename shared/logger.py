"""
shared/logger.py

Configures structlog for JSON-formatted, levelled structured logging.
Call get_logger(__name__) in every module; never use print() or stdlib
logging directly.

Configuration (log_level, log_dir) is read from shared.config_loader on
first use so the logger is self-contained at import time but still respects
the system config at runtime.
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

_configured = False


def _configure_structlog(log_level: str, log_dir: str) -> None:
    """
    Set up structlog with a JSON renderer and route output to both stderr
    and a rotating file under log_dir. Called once per process.
    """
    global _configured
    if _configured:
        return

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Ensure log directory exists before attaching file handler.
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    if not root.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(numeric_level)

        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path / "algotrader.log",
            when="midnight",
            utc=True,
            backupCount=90,   # matches 90-day log retention policy (§4.1)
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)

        root.addHandler(stderr_handler)
        root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str) -> Any:
    """
    Return a bound structlog logger for the calling module.

    Lazily triggers structlog configuration on first call so that config
    is available before the logger is used without requiring callers to
    explicitly initialise logging.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A structlog BoundLogger instance with JSON output.
    """
    if not _configured:
        # Deferred import avoids circular dependency at module load time.
        try:
            from shared.config_loader import get_config
            cfg = get_config()
            _configure_structlog(cfg.system.log_level, cfg.system.log_dir)
        except Exception:
            # Bootstrapping fallback: config may not yet be loaded (e.g.
            # during config_loader's own initialisation). Use safe defaults.
            _configure_structlog("INFO", "logs/")

    return structlog.get_logger(name)
