"""Runtime time helpers for ZENTRA."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def now_jakarta() -> datetime:
    """Return the current time in Asia/Jakarta."""
    return datetime.now(tz=JAKARTA_TZ)


def today_jakarta() -> date:
    """Return today's date in Asia/Jakarta."""
    return now_jakarta().date()


def is_weekend_jakarta(value: date | datetime | None = None) -> bool:
    """Return True when the supplied Jakarta date falls on a weekend."""
    if value is None:
        value = today_jakarta()
    if isinstance(value, datetime):
        value = value.astimezone(JAKARTA_TZ).date()
    return value.weekday() >= 5
