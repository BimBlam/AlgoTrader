"""
Utility helpers for S5.

Centralises timezone-aware datetime construction so callers never import
datetime directly and accidentally produce naive objects.
"""

import datetime
import re
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_URL_RE = re.compile(
    r"https?://\S+|www\.\S+",
    re.IGNORECASE,
)
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]+")
_WHITESPACE_RE = re.compile(r"\s{2,}")


def utc_now() -> datetime.datetime:
    """Return the current UTC timestamp as a timezone-aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def utc_today() -> datetime.date:
    """Return today's date in UTC."""
    return utc_now().date()


def raw_news_path(data_dir_hdd: str, date: datetime.date) -> Path:
    """Canonical path that S2 writes news JSON to and S5 reads from."""
    return Path(data_dir_hdd) / "raw" / "news" / f"{date}.json"


def raw_social_path(data_dir_hdd: str, date: datetime.date) -> Path:
    """Canonical path that S2 writes social JSON to and S5 reads from."""
    return Path(data_dir_hdd) / "raw" / "social" / f"{date}.json"
