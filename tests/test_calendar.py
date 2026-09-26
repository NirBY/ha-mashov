"""Holidays calendar entity: setup, current/next event selection and robustness to bad dates.

Each test sets up the full integration with a patched MashovClient whose
``async_fetch_all`` returns one student plus the holidays under test.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .const import TEST_STUDENT


def _get_calendar_state(hass: HomeAssistant):
    """Return the Mashov holidays calendar state across HA slug variants."""
    for state in hass.states.async_all("calendar"):
        if state.entity_id.endswith("_holidays_calendar"):
            return state
    return None


async def test_holidays_calendar_setup(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """Setting up the integration creates the holidays calendar entity with a Holidays name."""
    mock_config_entry.add_to_hass(hass)

    holidays = [
        {
            "start": "2024-12-25T00:00:00",
            "end": "2024-12-26T00:00:00",
            "name": "Christmas",
        }
    ]

    # Patch the client at its import site in the package so setup never touches the network.
    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.attributes.get("friendly_name", "").endswith("Holidays Calendar")


async def test_holidays_calendar_upcoming_event(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """A future holiday leaves the calendar off and exposes it as the upcoming event."""
    mock_config_entry.add_to_hass(hass)

    future_date = (dt_util.now() + timedelta(days=10)).date()
    holidays = [
        {
            "start": future_date.isoformat(),
            "end": (future_date + timedelta(days=1)).isoformat(),
            "name": "Future Holiday",
        }
    ]

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.state == "off"
    assert state.attributes.get("message") == "Future Holiday"
    assert state.attributes.get("start_time") is not None


async def test_holidays_calendar_active_event(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """A holiday spanning today turns the calendar on with that holiday as the message."""
    mock_config_entry.add_to_hass(hass)

    today = dt_util.now().date()
    holidays = [
        {
            "start": (today - timedelta(days=1)).isoformat(),
            "end": (today + timedelta(days=1)).isoformat(),
            "name": "Active Holiday",
        }
    ]

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.state == "on"
    assert state.attributes.get("message") == "Active Holiday"


async def test_holidays_calendar_no_events(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """With no holidays the calendar entity still exists and is off."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": [],
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=[])

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.state == "off"


async def test_holidays_calendar_with_multiple_holidays(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """A list of past-only holidays (2024) is accepted and the calendar stays off."""
    mock_config_entry.add_to_hass(hass)

    base_date = datetime(2024, 6, 1).date()
    holidays = [
        {
            "start": base_date.isoformat(),
            "end": (base_date + timedelta(days=2)).isoformat(),
            "name": "Holiday 1",
        },
        {
            "start": (base_date + timedelta(days=10)).isoformat(),
            "end": (base_date + timedelta(days=12)).isoformat(),
            "name": "Holiday 2",
        },
        {
            "start": (base_date + timedelta(days=50)).isoformat(),
            "end": (base_date + timedelta(days=51)).isoformat(),
            "name": "Holiday 3",
        },
    ]

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.state == "off"


async def test_holidays_calendar_multiple_events_returns_next(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """With unsorted future holidays the calendar reports the earliest one as next."""
    mock_config_entry.add_to_hass(hass)

    future_date1 = (dt_util.now() + timedelta(days=5)).date()
    future_date2 = (dt_util.now() + timedelta(days=10)).date()
    holidays = [
        {
            "start": future_date2.isoformat(),
            "end": (future_date2 + timedelta(days=1)).isoformat(),
            "name": "Later Holiday",
        },
        {
            "start": future_date1.isoformat(),
            "end": (future_date1 + timedelta(days=1)).isoformat(),
            "name": "Earlier Holiday",
        },
    ]

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.state == "off"
    assert state.attributes.get("message") == "Earlier Holiday"


async def test_holidays_calendar_invalid_dates(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """Holidays with unparseable dates are skipped and the next valid holiday is still shown."""
    mock_config_entry.add_to_hass(hass)

    holidays = [
        {
            "start": "invalid-date",
            "end": "also-invalid",
            "name": "Invalid Holiday",
        },
        {
            "start": (dt_util.now() + timedelta(days=5)).date().isoformat(),
            "end": (dt_util.now() + timedelta(days=6)).date().isoformat(),
            "name": "Valid Holiday",
        },
    ]

    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [
                    {
                        "id": "student-123",
                        "name": "Test Student",
                        "slug": "student-123",
                        "year": "2024",
                        "school_id": "123456",
                    }
                ],
                "by_slug": {
                    "student-123": {
                        "homework": [],
                        "behavior": [],
                        "weekly_plan": [],
                        "timetable": [],
                        "lessons_history": [],
                    }
                },
                "holidays": holidays,
            }
        )
        client.async_get_students = AsyncMock(return_value=[TEST_STUDENT])
        client.async_get_holidays = AsyncMock(return_value=holidays)

        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = _get_calendar_state(hass)

    assert state is not None
    assert state.attributes.get("message") == "Valid Holiday"
