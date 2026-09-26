"""Utilities for Mashov holidays processing.

Shared by the holidays sensor and calendar so both parse dates and describe the
per-school holidays device the same way.
"""

from datetime import date

# Fallback title ("holiday/vacation") when the portal returns an unnamed entry.
HOLIDAY_DEFAULT_NAME = "חג/חופשה"
HOLIDAY_ICON = "mdi:calendar-star"


def parse_iso_date_to_date(date_str: str) -> date | None:
    """Parse an ISO date/datetime string to a date, or None if missing or invalid.

    Only the first ten characters ("YYYY-MM-DD") are used, so any time part or
    UTC offset is ignored instead of shifting the date across a timezone boundary.
    """
    if not date_str:
        return None
    try:
        # Mashov sends midnight timestamps, sometimes with an offset; only the calendar date matters.
        return date.fromisoformat(str(date_str)[:10])
    except Exception:
        return None


def parse_iso_date_to_formatted(date_str: str) -> str:
    """Format an ISO date string as dd/mm/yyyy (the Israeli convention).

    On a parse failure the raw date part (text before "T") is returned so the
    user still sees something meaningful.
    """
    if not date_str:
        return ""
    try:
        return date.fromisoformat(str(date_str)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return date_str.split("T")[0]


def create_holidays_device_info(
    domain: str, entry_id: str, manufacturer: str, model: str, school_name: str = ""
) -> dict:
    """Create device info for the holidays entities of one config entry (school).

    The identifier includes the entry id and the name includes the school, so
    several schools/accounts get separate, distinguishable holiday devices.
    """
    return {
        "identifiers": {(domain, f"holidays_{entry_id}")},
        "name": f"Mashov – {school_name} – Holidays" if school_name else "Mashov – Holidays",
        "manufacturer": manufacturer,
        "model": model,
    }
