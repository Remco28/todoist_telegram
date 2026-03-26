from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_RECURRENCE_ALIASES = {
    "daily": "daily",
    "every day": "daily",
    "weekly": "weekly",
    "every week": "weekly",
    "monthly": "monthly",
    "every month": "monthly",
    "weekdays": "weekdays",
    "weekday": "weekdays",
    "every weekday": "weekdays",
}

_SNOOZE_PRESET_ALIASES = {
    "1h": "1h",
    "hour": "1h",
    "one hour": "1h",
    "tomorrow": "tomorrow_morning",
    "tomorrow morning": "tomorrow_morning",
    "tomorrow_morning": "tomorrow_morning",
    "next week": "next_week",
    "next_week": "next_week",
}


def normalize_recurrence_rule(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    return _RECURRENCE_ALIASES.get(raw)


def supported_recurrence_rules() -> list[str]:
    return ["daily", "weekly", "weekdays", "monthly"]


def normalize_snooze_preset(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    return _SNOOZE_PRESET_ALIASES.get(raw)


def supported_snooze_presets() -> list[str]:
    return ["1h", "tomorrow_morning", "next_week"]


def _reminder_timezone(timezone_name: Optional[str]):
    raw = str(timezone_name or "").strip() or "UTC"
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return timezone.utc


def next_recurrence_time(remind_at: datetime, rule: str) -> Optional[datetime]:
    normalized = normalize_recurrence_rule(rule)
    if normalized is None or not isinstance(remind_at, datetime):
        return None
    current = remind_at if remind_at.tzinfo is not None else remind_at.replace(tzinfo=timezone.utc)
    if normalized == "daily":
        return current + timedelta(days=1)
    if normalized == "weekly":
        return current + timedelta(days=7)
    if normalized == "weekdays":
        candidate = current + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if normalized == "monthly":
        year = current.year
        month = current.month + 1
        if month > 12:
            year += 1
            month = 1
        day = min(current.day, monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    return None


def compute_snooze_remind_at(
    preset: Optional[str],
    *,
    now: Optional[datetime] = None,
    current_remind_at: Optional[datetime] = None,
    timezone_name: Optional[str] = None,
) -> Optional[datetime]:
    normalized = normalize_snooze_preset(preset)
    if normalized is None:
        return None

    current_now = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if current_now.tzinfo is None:
        current_now = current_now.replace(tzinfo=timezone.utc)
    else:
        current_now = current_now.astimezone(timezone.utc)

    tz = _reminder_timezone(timezone_name)
    local_now = current_now.astimezone(tz)

    if normalized == "1h":
        return current_now + timedelta(hours=1)

    if normalized == "tomorrow_morning":
        target_local = (local_now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return target_local.astimezone(timezone.utc)

    if normalized == "next_week":
        anchor = current_remind_at if isinstance(current_remind_at, datetime) else current_now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        target_local = anchor.astimezone(tz) + timedelta(days=7)
        return target_local.astimezone(timezone.utc)

    return None
