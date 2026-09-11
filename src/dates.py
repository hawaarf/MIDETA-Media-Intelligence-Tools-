"""Shared date parsing for social-media posting timestamps."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


JAKARTA_TIMEZONE = ZoneInfo("Asia/Jakarta")

_RELATIVE_UNITS = {
    "s": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "detik": "seconds",
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "menit": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "jam": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "hari": "days",
    "w": "weeks",
    "wk": "weeks",
    "wks": "weeks",
    "week": "weeks",
    "weeks": "weeks",
    "minggu": "weeks",
}


def parse_social_datetime(value) -> datetime | None:
    """Parse a platform date and normalize timestamp values to Jakarta time."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=JAKARTA_TIMEZONE)
    else:
        text_value = str(value).strip()
        if re.fullmatch(r"-?\d{10,19}(?:\.\d+)?", text_value):
            try:
                timestamp = float(text_value)
                while abs(timestamp) > 20_000_000_000:
                    timestamp /= 1_000
                parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        else:
            try:
                parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
            except ValueError:
                return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JAKARTA_TIMEZONE)
    return parsed.astimezone(JAKARTA_TIMEZONE)


def social_date_iso(value) -> str | None:
    parsed = parse_social_datetime(value)
    return parsed.date().isoformat() if parsed else None


def social_datetime_iso(value) -> str | None:
    parsed = parse_social_datetime(value)
    return parsed.isoformat() if parsed else None


def parse_relative_social_datetime(value, *, now: datetime | None = None) -> datetime | None:
    """Convert labels such as ``2d ago`` or ``3 hr`` to Jakarta time."""
    if value in (None, ""):
        return None
    text_value = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip().casefold()
    reference = now or datetime.now(JAKARTA_TIMEZONE)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=JAKARTA_TIMEZONE)
    else:
        reference = reference.astimezone(JAKARTA_TIMEZONE)

    if re.search(r"\b(?:just now|now|baru saja)\b", text_value):
        return reference
    if re.search(r"\b(?:yesterday|kemarin)\b", text_value):
        return reference - timedelta(days=1)

    units = "|".join(sorted((re.escape(unit) for unit in _RELATIVE_UNITS), key=len, reverse=True))
    match = re.search(rf"(?<![\w.])(\d+)\s*({units})(?![\w.])(?:\s+(?:ago|lalu))?", text_value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = _RELATIVE_UNITS[match.group(2)]
    return reference - timedelta(**{unit: amount})


def relative_social_date_iso(value, *, now: datetime | None = None) -> str | None:
    parsed = parse_relative_social_datetime(value, now=now)
    return parsed.date().isoformat() if parsed else None
