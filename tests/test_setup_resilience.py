"""Setup must not block the event loop, must retry transient failures and serve cached data.

Also covers entity ID preservation across upgrades/reloads, safe partial unload and the
``set_options`` service. ``DATA``, ``_patch_client`` and ``_patch_cache`` are reused by
other test modules.
"""

import builtins
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.mashov.const import DOMAIN
from custom_components.mashov.mashov_client import MashovAuthError, MashovError, MashovPasswordChangeRequiredError

DATA = {
    "students": [{"id": "student-123", "name": "Test Student", "slug": "test_student", "year": 2027}],
    "by_slug": {"test_student": {"homework": [], "timetable": []}},
    "holidays": [],
}


async def test_upgrade_and_reload_preserve_entity_ids(hass, mock_config_entry):
    """Legacy unique IDs are migrated to entry-scoped ones while existing entity IDs keep working."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old_ids = {}
    for key in ("homework", "behavior", "weekly_plan", "timetable", "lessons_history", "grades"):
        registered = registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"mashov_student-123_{key}",
            config_entry=mock_config_entry,
            suggested_object_id=f"existing_{key}",
        )
        old_ids[key] = registered.entity_id
    patcher, _client = _patch_client()
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
            assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        for key, entity_id in old_ids.items():
            assert registry.async_get(entity_id).unique_id == f"mashov_{mock_config_entry.entry_id}_student-123_{key}"
            assert hass.states.get(entity_id) is not None
            assert hass.states.get(entity_id).state not in ("unavailable", "unknown")
        registered = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
        assert len(registered) == 8  # six core sensors, holiday sensor and calendar
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


async def test_failed_platform_unload_keeps_client_and_entry(hass, mock_config_entry):
    """If platforms fail to unload, the client, timer and hass.data entry are left intact."""
    from custom_components.mashov import async_unload_entry

    client = MagicMock(async_close=AsyncMock())
    timer = MagicMock()
    stored = {"client": client, "unsub_daily": timer}
    hass.data[DOMAIN] = {mock_config_entry.entry_id: stored}
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert not await async_unload_entry(hass, mock_config_entry)
    assert hass.data[DOMAIN][mock_config_entry.entry_id] is stored
    client.async_close.assert_not_awaited()
    timer.assert_not_called()


def _patch_client(init_side_effect=None):
    """Start patching the integration's MashovClient and return ``(patcher, client_instance)``.

    The caller must call ``patcher.stop()``. ``init_side_effect`` makes ``async_init`` fail.
    """
    patcher = patch("custom_components.mashov.MashovClient")
    mock_client = patcher.start()
    client = mock_client.return_value
    client.async_init = AsyncMock(side_effect=init_side_effect)
    client.async_close = AsyncMock()
    client.async_fetch_all = AsyncMock(return_value=DATA)
    client.auth_data = {}
    client.login_page_url = "https://example.invalid/students/login"
    return patcher, client


def _patch_cache(cached):
    """Return a patch of the HA Store used for the entry cache, loading ``cached`` (None = no cache)."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=cached)
    store.async_save = AsyncMock()
    return patch("custom_components.mashov.Store", return_value=store)


async def test_setup_reads_version_without_file_io(hass: HomeAssistant, mock_config_entry, caplog):
    """Setup logs the version without opening VERSION or manifest.json inside the event loop."""
    mock_config_entry.add_to_hass(hass)
    opened = []
    real_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        """Record every opened path, then delegate to the real ``open``."""
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    patcher, _client = _patch_client()
    try:
        # Track all file opens during setup to detect blocking I/O in the event loop.
        with caplog.at_level(logging.INFO), patch.object(builtins, "open", tracking_open):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
    finally:
        patcher.stop()

    assert not [path for path in opened if path.endswith(("VERSION", "manifest.json"))]
    assert "Setting up Mashov integration v" in caplog.text
    await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_transient_startup_failure_is_retried(hass: HomeAssistant, mock_config_entry):
    """A transient login error without cache puts the entry in SETUP_RETRY and closes the client."""
    mock_config_entry.add_to_hass(hass)
    patcher, client = _patch_client(MashovError("Login timeout"))
    try:
        with _patch_cache(None):
            assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    finally:
        patcher.stop()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    client.async_close.assert_awaited()


async def test_bad_credentials_without_cache_are_not_retried(hass: HomeAssistant, mock_config_entry):
    """Invalid credentials without cache fail setup permanently (SETUP_ERROR)."""
    mock_config_entry.add_to_hass(hass)
    patcher, _client = _patch_client(MashovAuthError("Authentication failed"))
    try:
        with _patch_cache(None):
            assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    finally:
        patcher.stop()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.parametrize(
    "error",
    [
        MashovError("Login timeout"),
        MashovAuthError("Authentication failed"),
        MashovPasswordChangeRequiredError("Change password", "https://web.mashov.info/students/login"),
    ],
)
async def test_startup_failure_keeps_cached_data(hass: HomeAssistant, error):
    """With a cached snapshot, a startup login failure still loads the entry and serves the cache."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "school_id": "123456", "school_name": "Test School"},
        options={"schedule_type": "interval", "schedule_interval": 60},
        title="Test School (123456)",
    )
    entry.add_to_hass(hass)
    patcher, _client = _patch_client(error)
    try:
        # A stale timestamp forces the interval-mode startup refresh.
        with _patch_cache({"data": DATA, "last_refresh_ts": 1.0, "auth": {}}):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
    finally:
        patcher.stop()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id]["coordinator"].data == DATA
    states = [state for state in hass.states.async_all("sensor") if state.entity_id.startswith("sensor.mashov")]
    assert states
    assert all(state.attributes["data_stale"] for state in states)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_set_options_targets_requested_entry(hass: HomeAssistant):
    """set_options updates only the requested entry, normalizes days and rejects bad targets/payloads."""
    entries = []
    for school in ("111111", "222222"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"username": "u", "password": "p", "school_id": school, "school_name": "School"},
            title=f"School ({school})",
        )
        entry.add_to_hass(hass)
        entries.append(entry)

    patcher, _client = _patch_client()
    try:
        # Setting up the integration loads every configured hub.
        assert await hass.config_entries.async_setup(entries[0].entry_id)
        await hass.async_block_till_done()
        assert all(entry.state is ConfigEntryState.LOADED for entry in entries)

        await hass.services.async_call(DOMAIN, "set_options", {"schedule_time": "08:15"}, blocking=True)
        await hass.async_block_till_done()
        assert entries[0].options["schedule_time"] == "08:15"

        await hass.services.async_call(
            DOMAIN,
            "set_options",
            {"entry_id": entries[1].entry_id, "schedule_time": "07:15", "schedule_days": ["4", 2, 2]},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert entries[1].options["schedule_time"] == "07:15"
        assert entries[1].options["schedule_days"] == [2, 4]
        assert entries[0].options["schedule_time"] == "08:15"

        # The legacy single-day service field overrides a previously migrated list.
        await hass.services.async_call(
            DOMAIN, "set_options", {"entry_id": entries[1].entry_id, "schedule_day": 1}, blocking=True
        )
        await hass.async_block_till_done()
        assert entries[1].options["schedule_days"] == [1]

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "set_options", {"entry_id": "missing"}, blocking=True)

        # Invalid payloads are rejected instead of being stored and breaking the options form.
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN, "set_options", {"entry_id": entries[1].entry_id, "schedule_days": 9}, blocking=True
            )
    finally:
        patcher.stop()
    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
