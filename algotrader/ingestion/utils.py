"""
Shared utility helpers for S2.

Only module-internal utilities live here. Nothing that belongs in shared/.
"""

from __future__ import annotations

import datetime


def utc_now() -> datetime.datetime:
    """Return timezone-aware UTC datetime. Central point so tests can freeze time."""
    return datetime.datetime.now(datetime.timezone.utc)


def utc_today() -> datetime.date:
    """Return today's UTC date."""
    return utc_now().date()
