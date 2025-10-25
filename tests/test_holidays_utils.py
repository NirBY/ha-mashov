"""Test Mashov holidays utilities."""

from datetime import date

from custom_components.mashov.holidays_utils import (
    HOLIDAY_DEFAULT_NAME,
    HOLIDAY_ICON,
    create_holidays_device_info,
    parse_iso_date_to_date,
    parse_iso_date_to_formatted,
)


def test_parse_iso_date_to_date_valid():
    """Test parsing valid ISO date to date object."""
    result = parse_iso_date_to_date("2024-01-15T00:00:00")
    assert result == date(2024, 1, 15)


def test_parse_iso_date_to_date_valid_without_time():
    """Test parsing ISO date without time component."""
    result = parse_iso_date_to_date("2024-01-15")
    assert result == date(2024, 1, 15)


def test_parse_iso_date_to_date_empty():
    """Test parsing empty date string."""
    result = parse_iso_date_to_date("")
    assert result is None


def test_parse_iso_date_to_date_invalid():
    """Test parsing invalid date string."""
    result = parse_iso_date_to_date("invalid-date")
    assert result is None


def test_parse_iso_date_to_formatted_valid():
    """Test formatting valid ISO date to dd/mm/yyyy."""
    result = parse_iso_date_to_formatted("2024-01-15T00:00:00")
    assert result == "15/01/2024"


def test_parse_iso_date_to_formatted_valid_without_time():
    """Test formatting ISO date without time component."""
    result = parse_iso_date_to_formatted("2024-12-25")
    assert result == "25/12/2024"


def test_parse_iso_date_to_formatted_empty():
    """Test formatting empty date string."""
    result = parse_iso_date_to_formatted("")
    assert result == ""


def test_parse_iso_date_to_formatted_with_timestamp():
    """Test formatting date with timestamp."""
    result = parse_iso_date_to_formatted("2024-01-15T12:30:45")
    assert result == "15/01/2024"


def test_parse_iso_date_to_formatted_invalid_fallback():
    """Test formatting truly invalid date string falls back to split."""
    result = parse_iso_date_to_formatted("invalid-dateT00:00:00")
    assert result == "invalid-date"


def test_create_holidays_device_info():
    """Test creating device info for holidays entities."""
    result = create_holidays_device_info("test_domain", "entry123", "Test Manufacturer", "Test Model")

    assert result["identifiers"] == {("test_domain", "holidays_entry123")}
    assert result["name"] == "Mashov – Holidays"
    assert result["manufacturer"] == "Test Manufacturer"
    assert result["model"] == "Test Model"


def test_holiday_constants():
    """Test holiday constants are defined correctly."""
    assert HOLIDAY_DEFAULT_NAME == "חג/חופשה"
    assert HOLIDAY_ICON == "mdi:calendar-star"
