"""
core/tz.py — Eastern Time helpers.

LENS canonical timezone is **America/New_York** (handles EDT/EST + DST automatically
via zoneinfo). All scheduling logic must use these helpers so 9 AM means 9 AM
where Steven actually lives, regardless of where the process runs or what
machine clock returns.

Rules (also in memory: feedback_timezone.md):
  • Never use `datetime.utcnow()` or naive `datetime.now()` for stored or
    compared timestamps. Always tz-aware.
  • Storage format: ISO-8601 with offset, e.g. "2026-05-07T09:00:00-04:00".
  • Comparisons: aware-vs-aware only; if a legacy naive value is read,
    interpret it as ET via `parse_et()` before any math.
  • DST: trust zoneinfo. Do not hardcode -04:00 or -05:00.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    """Current wall-clock time in ET, tz-aware."""
    return datetime.now(ET)


def at_et(d: date | str, hour: int = 0, minute: int = 0) -> datetime:
    """Build a tz-aware ET datetime for a given date + hour:minute.

    Used by the scheduler to materialize "9 AM ET on post_date" into a real
    datetime. zoneinfo handles DST cutovers correctly (the rare ambiguous
    fold uses the standard-time interpretation by default — fine for 9am/6pm
    which never land on a DST cutover).
    """
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return datetime.combine(d, time(hour=hour, minute=minute), tzinfo=ET)


def parse_et(value: str | datetime) -> datetime:
    """Parse a stored timestamp into an ET-aware datetime.

    Accepts:
      - tz-aware ISO strings ("2026-05-07T09:00:00-04:00", "...+00:00", "...Z")
      - naive ISO strings (legacy data) — interpreted as ET local time
      - datetime objects (passed through; naive ones tagged ET)
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Legacy naive — treat as ET local. After backfill this branch should
        # rarely fire; left in place as a safety net.
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def to_iso_et(dt: datetime) -> str:
    """Serialize a datetime as ET-aware ISO-8601 ('...-04:00' / '...-05:00')."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET).isoformat()


def minutes_between(a: datetime, b: datetime) -> float:
    """|a - b| in minutes, with both sides forced tz-aware ET."""
    if a.tzinfo is None:
        a = a.replace(tzinfo=ET)
    if b.tzinfo is None:
        b = b.replace(tzinfo=ET)
    return abs((a - b).total_seconds()) / 60.0
