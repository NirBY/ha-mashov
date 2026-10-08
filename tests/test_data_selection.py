"""User choices must bound fetching and survive upgrades without resetting entities."""

from copy import deepcopy
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_selection import (
    LEGACY_CORE_DATA,
    enabled_data,
    filter_cached_data,
    merge_selection_options,
)
from custom_components.mashov.entity import sync_selected_entities
from custom_components.mashov.mashov_client import MashovClient, MashovError

from .test_roster_change import _response
from .test_setup_resilience import DATA, _patch_cache, _patch_client


@pytest.mark.parametrize(
    "old", [{}, {"additional_data": []}, {"additional_data": ["message_board", "periodic_grades"]}]
)
def test_legacy_defaults_preserve_only_previously_enabled_data(old):
    migrated = merge_selection_options(old, {})
    assert set(migrated["enabled_data"]) == set(LEGACY_CORE_DATA) | set(old.get("additional_data", []))
    assert "mailbox" not in migrated["enabled_data"]
    assert "special_hours" not in migrated["enabled_data"]
    assert migrated["mailbox_full_content"] is False
    assert merge_selection_options(migrated, {}) == migrated


def test_explicit_empty_selection_and_legacy_service_compatibility():
    assert enabled_data({"enabled_data": [], "additional_data": ["message_board"]}) == ()
    current = {"enabled_data": ["homework", "mailbox", "message_board"], "mailbox_full_content": True}
    changed = merge_selection_options(current, {"additional_data": ["periodic_grades"]})
    assert set(changed["enabled_data"]) == {"homework", "mailbox", "periodic_grades"}
    assert changed["mailbox_full_content"] is True
    changed = merge_selection_options(changed, {"enabled_data": []})
    assert changed["mailbox_full_content"] is False
    assert not changed["additional_data"]
    changed = merge_selection_options(changed, {"enabled_data": ["mailbox"]})
    assert changed["mailbox_full_content"] is False


@pytest.mark.parametrize(
    "selected,paths",
    [
        ([], []),
        (["homework"], ["homework"]),
        (["holidays"], ["holidays"]),
        (["special_hours"], ["specialHoursLessons"]),
    ],
)
async def test_only_selected_datasets_make_network_requests(selected, paths):
    client = MashovClient("123", 2027, "test", "test", enabled_data=selected)
    client._students = [{"id": "student", "slug": "student", "name": "Student"}]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(200, [])
    result = await client.async_fetch_all()
    actual = [call.args[0].split("?")[0].rsplit("/", 1)[-1] for call in client._session.get.call_args_list]
    assert actual == paths
    assert "mailbox" not in result
    for key in LEGACY_CORE_DATA[:-1]:
        assert result["by_slug"]["student"]["source_status"][key] == ("ok" if key in selected else "disabled")
    assert result["holidays_status"] == ("ok" if "holidays" in selected else "disabled")


async def test_session_restore_does_not_probe_a_disabled_timetable():
    saved = {"csrf_token": "synthetic", "local_auth": {"accessToken": {"children": [{"childGuid": "student"}]}}}
    client = MashovClient("123", 2027, "test", "test", enabled_data=[], saved_auth=saved)
    client._session = MagicMock(closed=False)
    await client.async_init(None)
    assert client._students
    client._session.get.assert_not_called()
    client._session.post.assert_not_called()
    # A subsequent selected request that receives 401 must be allowed to reauthenticate.
    assert client._last_login_timestamp == 0


def test_cache_drops_disabled_sources_and_bodies_without_mutating_original():
    original = deepcopy(DATA)
    original["by_slug"]["test_student"]["additional_data"] = {"message_board": {"items": [{"text": "private"}]}}
    original["holidays_cached"] = True
    original["mailbox"] = {
        "full_content": True,
        "items": [{"content_status": "ok", "messages": [{"body": "private body", "subject": "header"}]}],
    }
    filtered = filter_cached_data(original, {"enabled_data": ["mailbox"]})
    assert filtered["by_slug"]["test_student"]["additional_data"] == {}
    assert filtered["holidays"] == []
    assert "holidays_cached" not in filtered
    assert "body" not in filtered["mailbox"]["items"][0]["messages"][0]
    assert filtered["mailbox"]["full_content"] is False
    assert original["mailbox"]["items"][0]["messages"][0]["body"] == "private body"
    assert "mailbox" not in filter_cached_data(original, {"enabled_data": []})


async def test_deselection_preserves_entity_ids_and_user_disabled_state(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"enabled_data": ["homework"]})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    grade = registry.async_get_or_create(
        "sensor", DOMAIN, f"mashov_{entry.entry_id}_student_grades", config_entry=entry, suggested_object_id="my_grade"
    )
    homework = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"mashov_{entry.entry_id}_student_homework",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    holiday = registry.async_get_or_create(
        "calendar", DOMAIN, f"mashov_{entry.entry_id}_holidays_calendar", config_entry=entry
    )
    sync_selected_entities(hass, entry)
    assert registry.async_get(grade.entity_id).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert registry.async_get(holiday.entity_id).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    hass.config_entries.async_update_entry(entry, options={"enabled_data": ["homework", "grades", "holidays"]})
    sync_selected_entities(hass, entry)
    assert registry.async_get(grade.entity_id).disabled_by is None
    assert registry.async_get(holiday.entity_id).disabled_by is None
    assert registry.async_get(homework.entity_id).disabled_by == er.RegistryEntryDisabler.USER


@pytest.mark.parametrize("options", [{}, {"additional_data": ["message_board", "periodic_grades"]}])
async def test_existing_hub_upgrade_preserves_selection_and_entities(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data={"school_id": "123", "username": "test", "password": "test"}, options=options
    )
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        assert set(entry.options["enabled_data"]) == set(LEGACY_CORE_DATA) | set(options.get("additional_data", []))
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert len(entities) == 8 + len(options.get("additional_data", []))
        assert all(entity.disabled_by is None for entity in entities)
        assert not any(entity.unique_id.endswith("_mailbox") for entity in entities)
        await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()


async def test_options_cannot_enable_full_content_without_mailbox(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enabled_data": ["homework"], "mailbox_full_content": True}
    )
    assert result["errors"]["data"]["mailbox_full_content"] == "mailbox_required"
    assert not mock_config_entry.options.get("mailbox_full_content")


async def test_options_deselect_mailbox_resets_checked_full_content(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["homework", "mailbox"], "mailbox_full_content": True}
    )
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enabled_data": ["homework"], "mailbox_full_content": True}
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.options["enabled_data"] == ["homework"]
    assert mock_config_entry.options["mailbox_full_content"] is False
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    await hass.config_entries.options.async_configure(flow["flow_id"], {"enabled_data": ["homework", "mailbox"]})
    assert mock_config_entry.options["mailbox_full_content"] is False


async def test_invalid_options_keep_submitted_selection(hass, mock_config_entry, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.mashov.config_flow")
    mock_config_entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "enabled_data": ["mailbox"],
            "mailbox_limit": 3,
            "schedule_time": "bad",
            "password": "never-log-this-password",
        },
    )
    assert result["errors"]["refresh"]["schedule_time"] == "invalid_time_format"
    data_section = next(value for key, value in result["data_schema"].schema.items() if str(key) == "data")
    defaults = {
        str(key): key.default() for key in data_section.schema.schema if str(key) in ("enabled_data", "mailbox_limit")
    }
    assert defaults == {"enabled_data": ["mailbox"], "mailbox_limit": 3}
    assert "never-log-this-password" not in caplog.text


async def test_initial_validation_keeps_selection(hass):
    with patch("custom_components.mashov.config_flow.ConfigFlow._load_schools_catalog", return_value=[]):
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "username": "test",
                "password": "test",
                "school_name": "123",
                "enabled_data": ["homework"],
                "mailbox_full_content": True,
            },
        )
    assert result["errors"]["data"]["mailbox_full_content"] == "mailbox_required"
    data_section = next(value for key, value in result["data_schema"].schema.items() if str(key) == "data")
    field = next(key for key in data_section.schema.schema if str(key) == "enabled_data")
    assert field.default() == ["homework"]


async def test_inflight_refresh_cannot_restore_disabled_bodies(hass, mock_config_entry):
    from custom_components.mashov import MashovCoordinator

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["mailbox"], "mailbox_full_content": True}
    )

    async def fetch():
        # Consent was revoked after the request started but before it finished.
        hass.config_entries.async_update_entry(
            mock_config_entry, options={"enabled_data": ["mailbox"], "mailbox_full_content": False}
        )
        return {
            **deepcopy(DATA),
            "mailbox": {"full_content": True, "items": [{"messages": [{"body": "revoked content"}]}]},
        }

    client = MagicMock(async_fetch_all=AsyncMock(side_effect=fetch), auth_data={})
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    with _patch_cache(None) as store_class:
        result = await coordinator._async_update_data()
        assert "revoked content" not in str(result)
        assert "revoked content" not in str(store_class.return_value.async_save.call_args)
    await coordinator.async_shutdown()


@pytest.mark.parametrize("selected", [[], ["mailbox"]])
async def test_disable_purges_disk_cache_even_when_login_fails(hass, mock_config_entry, selected):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": selected, "mailbox_full_content": False, "mailbox_limit": 1}
    )
    snapshot = deepcopy(DATA)
    snapshot.update(enabled_data=["homework", "mailbox"], mailbox_full_content=True)
    snapshot["by_slug"]["test_student"]["homework"] = [{"text": "old private homework"}]
    snapshot["mailbox"] = {
        "full_content": True,
        "items": [{"messages": [{"subject": "header", "body": "old private body"}]}] * 2,
    }
    cached = {"data": snapshot, "auth": {"csrf_token": "synthetic"}, "last_refresh_ts": 123}
    patcher, client = _patch_client(MashovError("offline"))
    try:
        with _patch_cache(cached) as store_class:

            async def assert_purged_before_login(*_):
                store_class.return_value.async_save.assert_awaited_once()
                raise MashovError("offline")

            client.async_init.side_effect = assert_purged_before_login
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
            saved = store_class.return_value.async_save.call_args.args[0]
            assert saved["auth"] == cached["auth"]
            assert saved["last_refresh_ts"] == 123
            assert "old private" not in str(saved)
            if selected:
                assert len(saved["data"]["mailbox"]["items"]) == 1
                assert saved["data"]["mailbox"]["full_content"] is False
            else:
                assert "mailbox" not in saved["data"]
            assert hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"].data == saved["data"]
            client.async_fetch_all.assert_not_awaited()
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


async def test_options_reload_disables_then_restores_existing_entity(hass, mock_config_entry):
    """Exercise HA's real options listener/reload and Store, not just selection helpers."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework"]})
    clients = []

    def make_client(**kwargs):
        client = MashovClient(**kwargs)
        client.async_init = AsyncMock()
        client.async_close = AsyncMock()
        data = filter_cached_data(DATA, mock_config_entry.options)
        data["enabled_data"] = kwargs["enabled_data"]
        client.async_fetch_all = AsyncMock(return_value=data)
        clients.append(client)
        return client

    with patch("custom_components.mashov.MashovClient", side_effect=make_client):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entity = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)[0]
        registry.async_update_entity(entity.entity_id, name="My homework")
        for selected in ([], ["homework"]):
            flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
            await hass.config_entries.options.async_configure(flow["flow_id"], {"enabled_data": selected})
            await hass.async_block_till_done()
            assert clients[-1].enabled_data == tuple(selected)
            current = registry.async_get(entity.entity_id)
            assert current.name == "My homework"
            assert current.disabled_by == (None if selected else er.RegistryEntryDisabler.INTEGRATION)
            state = hass.states.get(entity.entity_id)
            if selected:
                assert state is not None and state.state == "0"
            else:
                # HA can retain an unavailable restored placeholder for an ID.
                assert state is None or (state.state == "unavailable" and "items" not in state.attributes)
        assert len(clients) == 3
        await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_service_legacy_selection_still_updates_new_selection(hass, mock_config_entry):
    from custom_components.mashov import async_setup

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework", "message_board"]})
    await async_setup(hass, {})
    await hass.services.async_call(
        DOMAIN,
        "set_options",
        {"entry_id": mock_config_entry.entry_id, "additional_data": ["periodic_grades"]},
        blocking=True,
    )
    assert set(mock_config_entry.options["enabled_data"]) == {"homework", "periodic_grades"}
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_options", {"entry_id": mock_config_entry.entry_id, "mailbox_full_content": True}, blocking=True
        )


async def test_new_selection_forces_refresh_even_with_recent_daily_cache(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["mailbox"], "schedule_type": "daily"}
    )
    patcher, client = _patch_client()
    try:
        with _patch_cache({"last_refresh_ts": 1e20, "data": deepcopy(DATA)}):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        client.async_fetch_all.assert_awaited_once()
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
        assert len(entities) == 1
        assert entities[0].unique_id.endswith("_mailbox")
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()
