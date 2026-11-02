"""Normalize times and dates extracted from school pages."""

from __future__ import annotations

import re
from datetime import date


def normalize_time(value: str | None) -> str | None:
    """'8:05' / '08:05' / '8:05 AM' / '3:10 pm' -> 'HH:MM' (24h), else None."""
    if not value:
        return None
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?\s*", value.lower())
    if not m:
        return None
    h, mins, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm:
        h = h % 12 + (12 if ampm.startswith("p") else 0)
    return f"{h:02d}:{mins:02d}" if h < 24 and mins < 60 else None


def normalize_date(value: str | None) -> str | None:
    try:
        return date.fromisoformat(value.strip()).isoformat() if value else None
    except ValueError:
        return None
