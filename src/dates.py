"""Shared date parsing for social-media posting timestamps."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


JAKARTA_TIMEZONE = ZoneInfo("Asia/Jakarta")


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
