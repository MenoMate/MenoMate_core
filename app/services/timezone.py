"""User-local calendar-date semantics (Batch 2D-1 developer note).

DATE vs INSTANT (authoritative rule for this codebase):
- DATE fields represent USER CALENDAR DATES and must never be shifted by
  timezone conversion: cycles.period_start / period_end, daily_logs.log_date,
  predicted_next_period and other prediction dates, ledger predicted_at /
  basis_start / resolved_actual_start. They are stored as DATE and compared
  as dates.
- INSTANT fields represent real event moments and stay UTC timestamps:
  created_at / updated_at / last_connected_at / therapy started_at /
  ended_at. They are stored as TIMESTAMPTZ.

USER-LOCAL TODAY (single canonical rule):
- The authoritative "today" for a user is: current instant -> converted to
  that user's stored IANA timezone (profiles.timezone) -> take the local
  calendar date. See user_today() / user_today_for().
- Never use bare date.today() / datetime.now() where user-local date
  semantics are required (summaries, statuses, day counts, defaults for
  period-end and log dates, validation bounds).
- Calculations over HISTORICAL date values keep using those dates as-is;
  only the "now" anchor is timezone-resolved.

TIMEZONE STORAGE:
- profiles.timezone holds one canonical IANA identifier per user
  (e.g. "Asia/Kolkata"). No numeric offsets, no abbreviations, no second
  source. The device refreshes it; the backend only reads it here.
- Legacy NULL timezone is explicitly transitional: user_today() falls back
  to the UTC calendar date (documented, never silent), while the mobile
  client persists the device timezone on the next authenticated session.
"""

import uuid
from datetime import datetime, timezone
from datetime import date as date_cls
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile

MAX_TIMEZONE_LENGTH = 64


def _utcnow() -> datetime:
    """Current instant. Module-level seam so tests can freeze time by
    monkeypatching app.services.timezone._utcnow; production always passes
    now=None and gets the real clock."""
    return datetime.now(timezone.utc)


def user_today(
    tz_name: Optional[str],
    now: Optional[datetime] = None,
) -> date_cls:
    """Authoritative user-local calendar date for an IANA timezone name.

    Deterministic when `now` is given (tests); otherwise uses the real
    clock. NULL/blank/unknown timezone falls back to the UTC calendar
    date (legacy-transitional, see module docstring) — never raises.
    """
    instant = now if now is not None else _utcnow()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    if not tz_name or not tz_name.strip():
        return instant.date()
    try:
        return instant.astimezone(ZoneInfo(tz_name.strip())).date()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return instant.date()


def validate_timezone(value: Optional[str]) -> Optional[str]:
    """Validate an IANA timezone identifier for profile storage.

    Returns the stripped name, or None when input is None. Raises
    ValueError for blank, unknown, or over-long identifiers (callers map
    this to HTTP 422).
    """
    if value is None:
        return None
    name = value.strip()
    if not name:
        raise ValueError("timezone must be a valid IANA identifier")
    if len(name) > MAX_TIMEZONE_LENGTH:
        raise ValueError("timezone identifier too long")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA timezone: {name!r}") from exc
    return name


async def user_today_for(
    db: AsyncSession,
    user_id: uuid.UUID,
    now: Optional[datetime] = None,
) -> date_cls:
    """Resolve the authoritative user-local today for a user id.

    Single canonical resolver used by all request paths that need "today".
    Missing profile or missing timezone degrades to the documented
    UTC-date fallback (legacy-transitional).
    """
    stmt = select(Profile.timezone).where(Profile.user_id == user_id)
    res = await db.execute(stmt)
    tz_name = res.scalar_one_or_none()
    return user_today(tz_name, now=now)
