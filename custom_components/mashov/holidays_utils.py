"""Utilities for Mashov holidays processing."""

from datetime import date, datetime

HOLIDAY_DEFAULT_NAME = "חג/חופשה"
HOLIDAY_ICON = "mdi:calendar-star"


def parse_iso_date_to_date(date_str: str) -> date | None:
    """Parse ISO date string to date object."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("T00:00:00", ""))
        return dt.date()
    except Exception:
        return None


def parse_iso_date_to_formatted(date_str: str) -> str:
    """Parse ISO date string to dd/mm/yyyy format."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("T00:00:00", ""))
        return dt.strftime("%d/%m/%Y")
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
