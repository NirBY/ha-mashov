"""Regression tests for config flow, sensor lookup, holidays parsing and school-year rollover."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mashov import mashov_client
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.holidays_utils import parse_iso_date_to_date, parse_iso_date_to_formatted
from custom_components.mashov.mashov_client import MashovAuthError, MashovClient
from custom_components.mashov.sensor import MashovListSensor, _async_migrate_list_sensor_unique_ids


def _mock_flow_client(mock_client, *, init_side_effect=None, schools=None):
    client = mock_client.return_value
    client.async_init = AsyncMock(side_effect=init_side_effect)
    client.async_close = AsyncMock()
    client.async_open_session = AsyncMock()
    client.async_fetch_schools_catalog = AsyncMock(return_value=[])
    client.async_search_schools = AsyncMock(return_value=schools or [])
    return client


async def test_picked_school_is_not_searched_again(hass: HomeAssistant):
    schools = [{"semel": 111111, "name": "Herzl"}, {"semel": 222222, "name": "Herzl Tel Aviv"}]
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client = _mock_flow_client(mock_client, schools=schools)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u", "password": "p", "school_name": "Herzl"}
        )
        assert result["step_id"] == "pick_school"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"selected_school": "111111"})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["school_id"] == 111111
    assert result["title"] == "Herzl (111111)"
    assert client.async_search_schools.await_count == 1


async def test_failed_login_closes_validation_session(hass: HomeAssistant):
    with patch("custom_components.mashov.config_flow.MashovClient") as mock_client:
        client = _mock_flow_client(mock_client, init_side_effect=MashovAuthError("bad"))
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u", "password": "p", "school_name": "123456"}
        )
    assert result["errors"] == {"base": "auth"}
    client.async_close.assert_awaited()


async def test_same_account_cannot_be_added_twice(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id="123456_user", data={}).add_to_hass(hass)
    with patch("custom_components.mashov.config_flow.MashovClient") as mock_client:
        _mock_flow_client(mock_client)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "User", "password": "p", "school_name": "123456"}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("unique_id", [None, "123456", "123456_olduser"])
async def test_legacy_or_renamed_account_cannot_be_added_twice(hass: HomeAssistant, unique_id):
    MockConfigEntry(domain=DOMAIN, unique_id=unique_id, data={"school_id": "123456", "username": "User"}).add_to_hass(
        hass
    )
    with patch("custom_components.mashov.config_flow.MashovClient") as mock_client:
        _mock_flow_client(mock_client)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "User", "password": "p", "school_name": "123456"}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_credentials_and_options_change_reloads_once(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    listener = AsyncMock()
    mock_config_entry.add_update_listener(listener)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"username": "new_user", "password": "new", "schedule_type": "daily", "schedule_time": "15:00"},
    )
    await hass.async_block_till_done()
    assert listener.await_count == 1
    assert mock_config_entry.data["password"] == "new"
    assert mock_config_entry.unique_id == "123456_new_user"
    assert mock_config_entry.options["schedule_time"] == "15:00"


def _coordinator(data):
    return SimpleNamespace(
        data=data, entry=SimpleNamespace(options={}), hass=SimpleNamespace(data={}), last_update_success=True
    )


def test_sensor_follows_student_after_class_change():
    """The slug embeds the class; a new school year renames it but the student id is stable."""
    sensor = MashovListSensor(
        _coordinator({}), "entry", "guid-1", "dana_cohen_a1", "Dana", "homework", "Homework", "homework"
    )
    sensor.coordinator.data = {
        "students": [{"id": "guid-1", "slug": "dana_cohen_b1", "name": "Dana Cohen (B1)", "year": 2027}],
        "by_slug": {"dana_cohen_b1": {"homework": [{"lesson_date": "2026-09-20", "homework": "Read"}]}},
    }
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["year"] == 2027


def test_weekly_plan_shows_subject_and_plan_text():
    data = {
        "students": [{"id": "guid-1", "slug": "dana", "name": "Dana"}],
        "by_slug": {
            "dana": {
                "weekly_plan": [
                    {"group_id": 120, "lesson_date": "2025-09-08T00:00:00", "lesson": 2, "plan": "Chapter 3"}
                ],
                "timetable": [
                    {
                        "timeTable": {"groupId": 120, "day": 2, "lesson": 2},
                        "groupDetails": {
                            "groupId": 120,
                            "subjectName": "Science",
                            "groupTeachers": [{"teacherName": "Teacher"}],
                        },
                    }
                ],
            }
        },
    }
    sensor = MashovListSensor(
        _coordinator(data), "entry", "guid-1", "dana", "Dana", "weekly_plan", "Weekly Plan", "weekly_plan"
    )
    attrs = sensor.extra_state_attributes
    assert attrs["formatted_by_date"] == {"08/09/2025": ["שיעור 2: Science – Chapter 3"]}
    assert attrs["formatted_by_subject"] == {"Science": ["08/09/2025 שיעור 2: Chapter 3"]}
    assert attrs["items"][0]["subject"] == "Science"
    # Dated plans preserve their actual dates, even when spanning multiple weeks.
    assert "2025-09-08" in attrs["formatted_table_html"]
    assert "Chapter 3" in attrs["formatted_table_html"]


async def test_legacy_list_sensor_unique_ids_are_scoped_to_entry(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor", DOMAIN, "mashov_guid-1_homework", config_entry=mock_config_entry, suggested_object_id="kid_hw"
    )
    scoped = registry.async_get_or_create(
        "sensor", DOMAIN, f"mashov_{mock_config_entry.entry_id}_holidays", config_entry=mock_config_entry
    )
    _async_migrate_list_sensor_unique_ids(hass, mock_config_entry)
    assert registry.async_get(legacy.entity_id).unique_id == f"mashov_{mock_config_entry.entry_id}_guid-1_homework"
    assert legacy.entity_id == "sensor.kid_hw"
    assert registry.async_get(scoped.entity_id).unique_id == scoped.unique_id
    _async_migrate_list_sensor_unique_ids(hass, mock_config_entry)
    assert registry.async_get(legacy.entity_id).unique_id == f"mashov_{mock_config_entry.entry_id}_guid-1_homework"


def test_holiday_dates_with_offset_are_parsed():
    assert parse_iso_date_to_date("2025-09-22T00:00:00+03:00") == date(2025, 9, 22)
    assert parse_iso_date_to_date("2025-09-22T00:00:00Z") == date(2025, 9, 22)
    assert parse_iso_date_to_formatted("2025-09-22T00:00:00+03:00") == "22/09/2025"


async def test_school_year_rollover_logs_in_again():
    client = MashovClient("123", None, "u", "p")
    with patch.object(mashov_client, "_default_mashov_year", return_value=2026):
        assert client.year == 2026
        client._session_year = 2026
    client._students = [{"id": "s", "slug": "s", "name": "S"}]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._session = SimpleNamespace(closed=False)
    client.async_init = AsyncMock(side_effect=RuntimeError("stop after login decision"))
    with patch.object(mashov_client, "_default_mashov_year", return_value=2027), pytest.raises(RuntimeError):
        await client.async_fetch_all()
    client.async_init.assert_awaited_once()
    assert MashovClient("123", 2025, "u", "p").year == 2025
