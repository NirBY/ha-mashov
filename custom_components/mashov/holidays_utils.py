"""Utilities for Mashov holidays processing."""

from datetime import date

HOLIDAY_DEFAULT_NAME = "חג/חופשה"
HOLIDAY_ICON = "mdi:calendar-star"


def parse_iso_date_to_date(date_str: str) -> date | None:
    """Parse ISO date string to date object."""
    if not date_str:
        return None
    try:
        # Mashov sends midnight timestamps, sometimes with an offset; only the calendar date matters.
        return date.fromisoformat(str(date_str)[:10])
    except Exception:
        return None


def parse_iso_date_to_formatted(date_str: str) -> str:
    """Parse ISO date string to dd/mm/yyyy format."""
    if not date_str:
        return ""
    try:
        return date.fromisoformat(str(date_str)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return date_str.split("T")[0]


def create_holidays_device_info(domain: str, entry_id: str, manufacturer: str, model: str) -> dict:
    """Create device info for holidays entities."""
    return {
        "identifiers": {(domain, f"holidays_{entry_id}")},
        "name": "Mashov – Holidays",
        "manufacturer": manufacturer,
        "model": model,
    }
