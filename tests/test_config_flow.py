"""Test Mashov config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mashov.const import DOMAIN

from .const import TEST_PASSWORD, TEST_SCHOOL_ID, TEST_STUDENT, TEST_USERNAME


async def test_user_flow_success(hass: HomeAssistant):
    """Test successful user flow."""
    # Prevent actual setup and network calls - patch BEFORE async_init
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
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

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
                "school_name": TEST_SCHOOL_ID,  # Can be school ID or name
            },
        )

        assert result2["type"] == FlowResultType.CREATE_ENTRY
        # Title is formatted as "school_name (school_id)" or "school_id (school_id)" if name not available
        assert TEST_SCHOOL_ID in result2["title"]
        assert result2["data"]["username"] == TEST_USERNAME
        assert result2["data"]["password"] == TEST_PASSWORD
        assert result2["data"]["school_id"] == int(TEST_SCHOOL_ID)


async def test_user_flow_auth_failed(hass: HomeAssistant):
    """Test user flow with authentication failure."""
    # Prevent actual setup and network calls - patch BEFORE async_init
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(return_value=False)
        client.async_fetch_all = AsyncMock(
            return_value={
                "students": [],
                "by_slug": {},
                "holidays": [],
            }
        )

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
                "school_name": TEST_SCHOOL_ID,  # Can be school ID or name
            },
        )

        # Config flow succeeds - authentication is checked during setup, not in config flow
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert TEST_SCHOOL_ID in result2["title"]


async def test_user_flow_cannot_connect(hass: HomeAssistant):
    """Test user flow with connection failure.

    Note: Config flow creates the entry successfully. Connection is validated
    during setup, not during config flow.
    """
    # Prevent actual setup and network calls - patch BEFORE async_init
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client = mock_client.return_value
        client.async_init = AsyncMock(return_value=None)
        client.async_close = AsyncMock(return_value=None)
        client.async_open_session = AsyncMock(return_value=None)
        client.async_close_session = AsyncMock(return_value=None)
        client.async_authenticate = AsyncMock(side_effect=Exception("Connection error"))
        client.async_fetch_all = AsyncMock(side_effect=Exception("Connection error"))

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
                "school_name": TEST_SCHOOL_ID,  # Can be school ID or name
            },
        )

        # Config flow succeeds - connection is checked during setup, not in config flow
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert TEST_SCHOOL_ID in result2["title"]


async def test_options_flow(hass: HomeAssistant, mock_config_entry):
    """Test options flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "username": "updated_user",
            "password": "updated_password",
            "schedule_type": "daily",
            "schedule_time": "14:00",
        },
    )

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["data"]["schedule_time"] == "14:00"
    assert "password" not in result2["data"]

    updated_entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data["username"] == "updated_user"
    assert updated_entry.data["password"] == "updated_password"
