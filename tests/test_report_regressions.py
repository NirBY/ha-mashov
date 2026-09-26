"""Regressions from the live-installation review, exercised through HA where possible.

Covers schedule seconds, automatic school year, the set_options schema, cached-auth
restore, holiday/refresh failure handling with cached data, translated entity names,
orphan-entity cleanup, options-flow unique IDs, entry removal and translation coverage.
Setup-based tests reuse the client/cache patch helpers from ``test_setup_resilience``.
"""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.mashov import SET_OPTIONS_SCHEMA, MashovCoordinator, async_remove_entry
from custom_components.mashov.config_flow import OptionsFlowHandler
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.mashov_client import MashovClient, MashovError
from custom_components.mashov.sensor import MashovListSensor

from .test_setup_resilience import DATA, _patch_cache, _patch_client


async def test_schedule_seconds_are_used_by_timer_and_next_refresh(hass, mock_config_entry):
    """A daily time with seconds is passed to the time-change tracker and shown in the next-refresh info."""
    from custom_components.mashov import _async_setup_scheduler

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"schedule_type": "daily", "schedule_time": "07:00:15"}
    )
    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    hass.data[DOMAIN] = {mock_config_entry.entry_id: {"coordinator": coordinator, "unsub_daily": None}}
    with patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()) as track:
        await _async_setup_scheduler(hass, mock_config_entry)
        assert track.call_args.kwargs == {"hour": 7, "minute": 0, "second": 15}
    sensor = MashovListSensor(
        coordinator, mock_config_entry.entry_id, "s", "s", "Student", "homework", "Homework", "homework"
    )
    assert "T07:00:15" in sensor._compute_schedule_info()["next"]
    await coordinator.async_shutdown()


async def test_auto_year_option_overrides_legacy_pinned_year(hass, mock_config_entry):
    """The automatic school year option makes setup create the client with ``year=None``."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"automatic_school_year": True})
    patcher, _client = _patch_client()
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        from custom_components.mashov import MashovClient as client_mock

        assert client_mock.call_args.kwargs["year"] is None
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


def test_service_accepts_legacy_time_and_all_options_but_discards_unknowns():
    """set_options accepts HH:MM:SS and every option, drops unknown keys and rejects invalid values."""
    result = SET_OPTIONS_SCHEMA(
        {
            "schedule_time": "07:00:15",
            "additional_data": ["periodic_grades"],
            "max_items_in_attributes": 20,
            "automatic_school_year": True,
            "obsolete": "ignored",
        }
    )
    assert "obsolete" not in result
    assert result["schedule_time"] == "07:00:15"
    for invalid in ({"schedule_time": "24:10:00"}, {"additional_data": ["bad"]}, {"max_items_in_attributes": 501}):
        with pytest.raises(vol.Invalid):
            SET_OPTIONS_SCHEMA(invalid)


@pytest.mark.parametrize("saved", [{}, {"session_year": 2027}])
def test_metadata_only_auth_is_not_restored(saved):
    """Saved auth containing only metadata (no session) is not treated as restorable."""
    assert MashovClient("123", 2027, "u", "p", saved_auth=saved)._saved_auth is None


@pytest.mark.parametrize("holiday_status", [401, 404, 500])
async def test_holiday_failure_retains_fresh_student_data(holiday_status):
    """A failing holidays endpoint is reported in ``holidays_status`` without losing student data."""
    client = MashovClient("123", 2027, "u", "p")
    client._students = [{"id": "s", "slug": "s", "name": "Student"}]
    client._headers["X-Csrf-Token"] = "test"
    client._ensure_valid_session = AsyncMock()
    client._session = MagicMock(closed=False)

    def get(url, **kwargs):
        """Answer the holidays endpoint with ``holiday_status`` and every other endpoint with 200."""
        holidays = url == client._endpoints["holidays"]
        response = MagicMock(status=holiday_status if holidays else 200, headers={})
        response.json = AsyncMock(return_value=[{"homework": "Read"}] if "homework" in url else [])
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    client._session.get.side_effect = get
    data = await client.async_fetch_all()
    assert data["holidays_status"] == f"http_{holiday_status}"
    assert data["by_slug"]["s"]["source_status"]["homework"] == "ok"
    if holiday_status == 401:
        client._ensure_valid_session.assert_awaited_once()


async def test_cache_and_notification_threshold_then_recovery(hass, mock_config_entry):
    """Failures keep cached data marked stale and notify from the 3rd failure; recovery reuses cached holidays."""
    client = MagicMock(async_fetch_all=AsyncMock(side_effect=MashovError("offline")))
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = deepcopy(DATA)
    with patch("custom_components.mashov._async_show_error_notification") as notify:
        for attempt in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            assert coordinator.data_stale
            assert notify.call_count == (1 if attempt >= 2 else 0)
        client.async_fetch_all.side_effect = None
        client.async_fetch_all.return_value = {**deepcopy(DATA), "holidays_status": "http_500"}
        # Recovery with a failing holidays endpoint must keep the previously cached holidays.
        coordinator.data["holidays"] = [{"name": "Cached holiday"}]
        result = await coordinator._async_update_data()
        assert result["holidays"] == [{"name": "Cached holiday"}]
        assert result["holidays_cached"]
        assert not coordinator.data_stale
        assert coordinator._consecutive_failures == 0
    await coordinator.async_shutdown()


async def test_failed_holidays_never_become_a_successful_empty_cache(hass, mock_config_entry):
    """Holidays are cached only after a successful fetch, and a later failure keeps its timestamp."""
    client = MagicMock(auth_data={}, async_fetch_all=AsyncMock())
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    for _ in range(2):
        client.async_fetch_all.return_value = {**deepcopy(DATA), "holidays_status": "http_500"}
        coordinator.data = await coordinator._async_update_data()
        assert not coordinator.data.get("holidays_cached")
    client.async_fetch_all.return_value = {**deepcopy(DATA), "holidays_status": "ok"}
    coordinator.data = await coordinator._async_update_data()
    timestamp = coordinator.data["holidays_last_update"]
    client.async_fetch_all.return_value = {**deepcopy(DATA), "holidays_status": "http_500"}
    result = await coordinator._async_update_data()
    assert result["holidays_cached"]
    assert result["holidays_last_update"] == timestamp
    await coordinator.async_shutdown()


async def test_failed_first_coordinator_refresh_exposes_stale_cache_in_ha(hass, mock_config_entry):
    """When the first refresh fails, entities show the cached snapshot flagged ``data_stale``."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"schedule_type": "interval"})
    patcher, client = _patch_client()
    client.async_fetch_all.side_effect = MashovError("offline")
    try:
        # Seed the Store cache with a snapshot refreshed at epoch second 1 (hence 1970 below).
        with _patch_cache({"data": deepcopy(DATA), "auth": {}, "last_refresh_ts": 1}):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
        assert not coordinator.last_update_success
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"mashov_{mock_config_entry.entry_id}_student-123_homework"
        )
        state = hass.states.get(entity_id)
        assert state.state == "0"
        assert state.attributes["data_stale"] is True
        # last_update is the cached refresh time (epoch second 1) shown in HA's local timezone.
        last_update = datetime.fromisoformat(state.attributes["last_update"])
        assert last_update.timestamp() == 1
        assert last_update.utcoffset() == dt_util.as_local(last_update).utcoffset()
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


@pytest.mark.parametrize(
    "language,label", [("ar", "الواجبات المنزلية"), ("ru", "Домашние задания"), ("uk", "Домашні завдання")]
)
async def test_translated_names_and_blocked_status_visible_in_ha(hass, mock_config_entry, language, label):
    """Entity names are translated, the student name appears once, and blocked sources are unknown."""
    hass.config.language = language
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"additional_data": ["periodic_grades"]})
    patcher, client = _patch_client()
    data = deepcopy(DATA)
    data["by_slug"]["test_student"].update(
        {
            "source_status": {"homework": "forbidden"},
            "additional_data": {"periodic_grades": {"items": [], "status": "unsupported"}},
        }
    )
    client.async_fetch_all.return_value = data
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        registry = er.async_get(hass)
        for key, status in [("homework", "forbidden"), ("periodic_grades", "unsupported")]:
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"mashov_{mock_config_entry.entry_id}_student-123_{key}"
            )
            state = hass.states.get(entity_id)
            assert state.state == "unknown"
            assert state.attributes["source_status"] == status
            assert state.attributes["friendly_name"].count("Test Student") == 1
            if key == "homework":
                assert label in state.attributes["friendly_name"]
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


@pytest.mark.parametrize("authoritative", [False, True])
async def test_orphan_cleanup_requires_live_roster_and_keeps_active_optional_sensors(
    hass, mock_config_entry, authoritative
):
    """Departed-student entities are removed only after a live roster refresh; renames update the device."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"mashov_{mock_config_entry.entry_id}_departed_homework", config_entry=mock_config_entry
    )
    # outside_behavior is an enabled optional resource, so its sensor must survive cleanup;
    # message_board is not enabled, so a live roster refresh removes its leftover sensor.
    hass.config_entries.async_update_entry(mock_config_entry, options={"additional_data": ["outside_behavior"]})
    retained = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"mashov_{mock_config_entry.entry_id}_student-123_outside_behavior",
        config_entry=mock_config_entry,
    )
    disabled = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"mashov_{mock_config_entry.entry_id}_student-123_message_board",
        config_entry=mock_config_entry,
    )
    patcher, client = _patch_client()
    # Only a freshly fetched roster may be trusted to delete departed students.
    client.roster_refreshed = authoritative
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        assert (registry.async_get(old.entity_id) is None) == authoritative
        assert (registry.async_get(disabled.entity_id) is None) == authoritative
        assert registry.async_get(retained.entity_id) is not None
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
        updated = deepcopy(DATA)
        updated["students"][0]["name"] = "Test Student (B2)"
        coordinator.async_set_updated_data(updated)
        await hass.async_block_till_done()
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"mashov_{mock_config_entry.entry_id}_student-123_homework"
        )
        device = dr.async_get(hass).async_get(registry.async_get(entity_id).device_id)
        assert device.name == "Mashov – Test Student (B2)"
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


async def test_password_edit_on_legacy_duplicate_does_not_claim_other_unique_id(hass, mock_config_entry):
    """Changing the password does not move the entry onto a unique ID owned by another entry."""
    mock_config_entry.add_to_hass(hass)
    # A legacy duplicate entry already owns the username-suffixed unique ID.
    other = MockConfigEntry(domain=DOMAIN, data=dict(mock_config_entry.data), unique_id="123456_test_user")
    other.add_to_hass(hass)
    handler = OptionsFlowHandler(mock_config_entry)
    handler.hass = hass
    await handler.async_step_init({"password": "changed"})
    assert mock_config_entry.data["password"] == "changed"
    assert mock_config_entry.unique_id == "123456"


async def test_remove_entry_deletes_only_its_cache_and_notification(hass, mock_config_entry):
    """Removing an entry deletes only its own Store cache file and clears its notification."""
    with (
        # Patch the HA Store class so no real .storage file is touched.
        patch("custom_components.mashov.Store") as store,
        patch("custom_components.mashov._async_clear_issue_notification") as clear,
    ):
        store.return_value.async_remove = AsyncMock()
        await async_remove_entry(hass, mock_config_entry)
        store.assert_called_once_with(hass, 1, f"mashov.{mock_config_entry.entry_id}.cache")
        store.return_value.async_remove.assert_awaited_once()
        clear.assert_called_once_with(hass, mock_config_entry)


def test_all_languages_cover_same_translation_keys():
    """Every translation file defines exactly the same set of keys as ``en.json``."""
    root = Path(__file__).parents[1] / "custom_components/mashov/translations"

    def paths(value, prefix=""):
        """Return the flattened dotted key paths of a nested translation dict."""
        return {
            path
            for key, child in value.items()
            for path in (paths(child, f"{prefix}.{key}") if isinstance(child, dict) else [f"{prefix}.{key}"])
        }

    expected = paths(json.loads((root / "en.json").read_text(encoding="utf-8")))
    for language in ("he", "ar", "ru", "uk"):
        assert paths(json.loads((root / f"{language}.json").read_text(encoding="utf-8"))) == expected


async def test_disabling_automatic_year_persists_year_across_rollover(hass, mock_config_entry):
    from custom_components.mashov import _frozen_school_year

    mock_config_entry.add_to_hass(hass)
    data = dict(mock_config_entry.data)
    data.pop("year", None)
    hass.config_entries.async_update_entry(mock_config_entry, data=data, options={"automatic_school_year": False})
    with patch("custom_components.mashov.mashov_client._default_mashov_year", return_value=2027):
        assert _frozen_school_year(hass, mock_config_entry) == 2027
    with patch("custom_components.mashov.mashov_client._default_mashov_year", return_value=2028):
        assert _frozen_school_year(hass, mock_config_entry) == 2027
    assert mock_config_entry.data["year"] == 2027
