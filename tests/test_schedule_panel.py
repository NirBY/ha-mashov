import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import Unauthorized
import pytest
import voluptuous as vol

from custom_components.mashov.mashov_client import MashovAuthError
from custom_components.mashov.schedule_panel import (
    HubRegistrationView,
    create_hub,
    revision,
    save_schedules,
    websocket_get,
    websocket_save,
)


async def test_save_all_schedule_edits_is_atomic_and_preserves_other_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={"enabled_data": ["homework", "grades"], "mailbox_full_content": False, "max_items_in_attributes": 27},
    )
    before = dict(mock_config_entry.data)
    general = {"schedule_type": "interval", "schedule_interval": 45}
    overrides = {
        "homework": {"schedule_type": "daily", "schedule_time": "18:00"},
        "grades": {"schedule_type": "weekly", "schedule_days": [4], "schedule_time": "19:00"},
    }
    token = save_schedules(hass, mock_config_entry.entry_id, revision(mock_config_entry), general, overrides)
    assert token == revision(mock_config_entry)
    assert mock_config_entry.options["schedule_interval"] == 45
    assert mock_config_entry.options["data_schedules"]["homework"]["schedule_time"] == "18:00"
    assert mock_config_entry.options["data_schedules"]["grades"]["schedule_days"] == [4]
    assert mock_config_entry.options["enabled_data"] == ["homework", "grades"]
    assert mock_config_entry.options["max_items_in_attributes"] == 27
    assert dict(mock_config_entry.data) == before
    snapshot = dict(mock_config_entry.options)
    with pytest.raises(vol.Invalid):
        save_schedules(
            hass,
            mock_config_entry.entry_id,
            token,
            general,
            {**overrides, "grades": {"schedule_type": "weekly", "schedule_days": []}},
        )
    assert dict(mock_config_entry.options) == snapshot
    with pytest.raises(ValueError, match="settings_changed"):
        save_schedules(hass, mock_config_entry.entry_id, "old-revision", general, {})
    assert dict(mock_config_entry.options) == snapshot
    save_schedules(hass, mock_config_entry.entry_id, token, general, {})
    assert mock_config_entry.options["data_schedules"] == {}


@pytest.mark.parametrize("command", [websocket_get, websocket_save])
async def test_schedule_editor_commands_require_admin(hass, command):
    connection = Mock(user=Mock(is_admin=False))
    with pytest.raises(Unauthorized):
        command(hass, connection, {"id": 1, "type": "mashov/schedules/get"})
    connection.send_result.assert_not_called()


@pytest.mark.parametrize("user", [None, Mock(is_admin=False)])
async def test_registration_http_requires_admin_before_reading_credentials(hass, user):
    request = Mock()
    request.get.return_value = user
    request.json = AsyncMock()
    response = await HubRegistrationView(hass).post(request)
    assert response.status == 403
    request.json.assert_not_awaited()
    assert HubRegistrationView.requires_auth is True


async def test_registration_http_passes_valid_draft_and_rejects_invalid_schedule(hass):
    payload = {
        "username": "demo",
        "password": "demo",
        "school_name": "123456",
        "enabled_data": ["homework"],
        "general": {"schedule_type": "interval", "schedule_interval": 45},
        "overrides": {},
    }
    request = Mock()
    request.get.return_value = Mock(is_admin=True)
    request.json = AsyncMock(return_value=payload)
    with patch("custom_components.mashov.schedule_panel.create_hub", new_callable=AsyncMock) as create:
        create.return_value = {"created": True, "entry_id": "demo", "revision": "saved"}
        response = await HubRegistrationView(hass).post(request)
        assert json.loads(response.text) == create.return_value
        create.assert_awaited_once_with(hass, payload)
        create.side_effect = vol.Invalid("Invalid schedule")
        response = await HubRegistrationView(hass).post(request)
        assert json.loads(response.text) == {"created": False, "errors": ["invalid_data_schedule"]}


@pytest.mark.parametrize("failure", [None, "auth", "duplicate"])
async def test_interactive_registration_commits_general_and_overrides_together(hass, mock_config_entry, failure):
    if failure == "duplicate":
        mock_config_entry.add_to_hass(hass)
    payload = {
        "username": "test_user",
        "password": "test_password",
        "school_name": "123456",
        "enabled_data": ["homework", "grades"],
        "general": {"schedule_type": "interval", "schedule_interval": 45},
        "overrides": {
            "homework": {"schedule_type": "daily", "schedule_time": "18:00"},
            "grades": {"schedule_type": "weekly", "schedule_days": [4], "schedule_time": "19:00"},
        },
    }
    with (
        patch("custom_components.mashov.config_flow.ConfigFlow._load_schools_catalog", return_value=[]),
        patch("custom_components.mashov.config_flow.MashovClient") as client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client.return_value.async_init = AsyncMock(side_effect=MashovAuthError("auth") if failure == "auth" else None)
        client.return_value.async_close = AsyncMock()
        result = await create_hub(hass, payload)
        await hass.async_block_till_done()
    assert not hass.config_entries.flow.async_progress()
    if failure:
        assert result["created"] is False
        assert result["errors"] == ["auth" if failure == "auth" else "already_configured"]
        assert len(hass.config_entries.async_entries("mashov")) == (1 if failure == "duplicate" else 0)
        return
    entry = hass.config_entries.async_get_entry(result["entry_id"])
    assert entry.options["schedule_interval"] == 45
    assert entry.options["data_schedules"]["homework"]["schedule_time"] == "18:00"
    assert entry.options["data_schedules"]["grades"]["schedule_days"] == [4]
    assert entry.options["enabled_data"] == ["homework", "grades"]
    assert entry.data["password"] == "test_password"
    assert "password" not in entry.options


async def test_invalid_registration_draft_never_starts_authentication(hass):
    with patch("custom_components.mashov.config_flow.MashovClient") as client:
        with pytest.raises(vol.Invalid):
            await create_hub(hass, {"general": {"schedule_type": "weekly", "schedule_days": []}, "overrides": {}})
        client.assert_not_called()
    assert not hass.config_entries.async_entries("mashov")


@pytest.mark.parametrize("language", ["en", "he", "ar", "ru", "uk"])
async def test_registration_and_editor_share_complete_translations(hass, mock_config_entry, language):
    mock_config_entry.add_to_hass(hass)
    connection = Mock()
    await websocket_get.__wrapped__.__wrapped__(hass, connection, {"id": 1, "language": language})
    payload = connection.send_result.call_args.args[1]
    source = json.loads(
        (Path("custom_components/mashov/translations") / f"{language}.json").read_text(encoding="utf-8")
    )
    expected = source["selector"]["schedule_editor"]["options"]
    english = json.loads(Path("custom_components/mashov/translations/en.json").read_text(encoding="utf-8"))["selector"][
        "schedule_editor"
    ]["options"]
    assert set(expected) == set(english)
    assert payload["ui"] == expected
    assert payload["ui"]["username"] == source["config"]["step"]["user"]["data"]["username"]
    assert payload["ui"]["password"] == source["config"]["step"]["user"]["data"]["password"]
    assert len(payload["datasets"]) == 18
    assert "test_password" not in json.dumps(payload)


async def test_student_schedules_save_together_and_invalid_draft_is_atomic(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    general = {"schedule_type": "daily", "schedule_time": "14:00"}
    students = {
        "a": {"general": {"schedule_type": "interval", "schedule_interval": 45}, "overrides": {}},
        "b": {"overrides": {"homework": {"schedule_type": "daily", "schedule_time": "18:00"}}},
    }
    token = save_schedules(hass, mock_config_entry.entry_id, revision(mock_config_entry), general, {}, students)
    assert mock_config_entry.options["student_schedules"]["a"]["general"]["schedule_interval"] == 45
    assert mock_config_entry.options["student_schedules"]["b"]["overrides"]["homework"]["schedule_time"] == "18:00"
    snapshot = dict(mock_config_entry.options)
    with pytest.raises(vol.Invalid):
        save_schedules(
            hass,
            mock_config_entry.entry_id,
            token,
            general,
            {},
            {"a": {"overrides": {"grades": {"schedule_type": "weekly", "schedule_days": []}}}},
        )
    assert dict(mock_config_entry.options) == snapshot
