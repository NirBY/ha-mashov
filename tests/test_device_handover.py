"""HA is a private device: a hub logs in once, keeps that login, and saves new passes at once.

Every Mashov password login registers a device and emails the parent, so the login made
by the add-hub or Configure check is handed over to the hub instead of being repeated.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.mashov as mashov
from custom_components.mashov.const import DEFAULT_API_BASE, DOMAIN
from custom_components.mashov.pending_auth import PENDING_AUTH, hand_over_auth, take_pending_auth

from .test_setup_resilience import DATA, _patch_client

AUTH = {
    "local_auth": {"accessToken": {"children": [{"childGuid": "student-123"}]}},
    "session_year": 2027,
    "csrf_token": "check-csrf",
    "cookies": {"MashovAuthToken": "check-session"},
    "device_auth": {"pass": {"appName": "com.mashov.main"}, "uniquId": "device-cookie", "binding": "binding"},
}


def _entry(**options):
    return MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "old", "school_id": "123456", "school_name": "Test School"},
        options={"schedule_type": "daily", "schedule_time": "14:00", "enabled_data": ["homework"], **options},
        title="Test School (123456)",
    )


def _patch_store(cached):
    """Patch the entry cache Store; return (patcher, store) so saves can be inspected."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=cached)
    store.async_save = AsyncMock()
    return patch("custom_components.mashov.Store", return_value=store), store


def _client_matching(client, entry):
    """Give the mocked client the attributes the options listener compares."""
    client.username = entry.data["username"]
    client.password = entry.data["password"]
    client._api_base = DEFAULT_API_BASE


async def test_handed_over_login_is_used_once_and_only_by_the_same_account(hass: HomeAssistant):
    hand_over_auth(hass, 123456, "u", AUTH)
    assert take_pending_auth(hass, "123456", "someone-else") is None
    assert take_pending_auth(hass, "123456", "u") == AUTH
    assert take_pending_auth(hass, "123456", "u") is None


async def test_abandoned_or_failed_checks_hand_nothing_over(hass: HomeAssistant):
    hand_over_auth(hass, 123456, "u", None)  # the check failed
    hand_over_auth(hass, 123456, "u", MagicMock())  # never a dict
    hand_over_auth(hass, 123456, "u", {"cookies": {}, "device_auth": {}})  # nothing usable
    assert not hass.data.get(DOMAIN, {}).get(PENDING_AUTH)
    hand_over_auth(hass, 123456, "u", AUTH)
    with patch("custom_components.mashov.pending_auth.time.monotonic", return_value=time.monotonic() + 3601):
        assert take_pending_auth(hass, 123456, "u") is None


async def test_new_hub_starts_from_the_check_login_and_remembers_the_device(hass: HomeAssistant):
    entry = _entry()
    entry.add_to_hass(hass)
    hand_over_auth(hass, "123456", "u", AUTH)
    patcher, _client = _patch_client()
    store_patch, store = _patch_store(None)
    try:
        with store_patch:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            kwargs = mashov.MashovClient.call_args.kwargs
            assert kwargs["saved_auth"] == AUTH
            assert kwargs["remember_device"] is True
            assert take_pending_auth(hass, "123456", "u") is None

            # A pass issued or revoked by a login is saved at once, before the data
            # fetch that follows it, and the cached data stays untouched.
            store.async_load.return_value = {"data": DATA, "last_refresh_ts": 1.0, "auth": {}}
            await kwargs["auth_updated"]({"device_auth": {"uniquId": "new"}})
            saved = store.async_save.call_args.args[0]
            assert saved == {"data": DATA, "last_refresh_ts": 1.0, "auth": {"device_auth": {"uniquId": "new"}}}
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()


async def test_cached_login_wins_over_a_stale_hand_over(hass: HomeAssistant):
    entry = _entry()
    entry.add_to_hass(hass)
    cached_auth = {"csrf_token": "cached", "cookies": {"MashovAuthToken": "cached"}, "session_year": 2027}
    hand_over_auth(hass, "123456", "u", AUTH)
    patcher, _client = _patch_client()
    store_patch, _store = _patch_store({"data": DATA, "last_refresh_ts": time.time(), "auth": cached_auth})
    try:
        with store_patch:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            assert mashov.MashovClient.call_args.kwargs["saved_auth"] == cached_auth
            # Taken either way, so a check's session never lingers in memory.
            assert take_pending_auth(hass, "123456", "u") is None
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()


async def test_configure_check_logs_in_as_private_device_and_hands_over(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.mashov.config_flow.MashovClient") as client_class:
        client_class.return_value.async_init = AsyncMock()
        client_class.return_value.async_close = AsyncMock()
        client_class.return_value.auth_data = AUTH
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"password": "new-password"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert client_class.call_args.kwargs["remember_device"] is True
    assert take_pending_auth(hass, "123456", "test_user") == AUTH


async def test_rejected_configure_check_hands_nothing_over(hass: HomeAssistant, mock_config_entry):
    from custom_components.mashov.mashov_client import MashovAuthError

    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.mashov.config_flow.MashovClient") as client_class:
        client_class.return_value.async_init = AsyncMock(side_effect=MashovAuthError("rejected"))
        client_class.return_value.async_close = AsyncMock()
        client_class.return_value.auth_data = AUTH
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        await hass.config_entries.options.async_configure(result["flow_id"], user_input={"password": "wrong"})
    assert take_pending_auth(hass, "123456", "test_user") is None


async def test_credential_change_reuses_the_configure_login(hass: HomeAssistant):
    entry = _entry()
    entry.add_to_hass(hass)
    cache = {
        "data": {**DATA, "enabled_data": ["homework"]},
        "last_refresh_ts": time.time(),
        "auth": {"csrf_token": "x"},
    }
    patcher, client = _patch_client()
    _client_matching(client, entry)
    store_patch, store = _patch_store(cache)
    try:
        with store_patch:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            hand_over_auth(hass, "123456", "u", AUTH)  # what the Configure check leaves
            hass.config_entries.async_update_entry(entry, data={**entry.data, "password": "fixed"})
            await hass.async_block_till_done(wait_background_tasks=True)
            assert cache["auth"] == AUTH
            assert mashov.MashovClient.call_args.kwargs["saved_auth"] == AUTH
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()


async def test_api_address_change_clears_the_saved_login(hass: HomeAssistant):
    """A session or pass for one API address must never be sent to another."""
    entry = _entry()
    entry.add_to_hass(hass)
    cache = {"data": {**DATA, "enabled_data": ["homework"]}, "last_refresh_ts": time.time(), "auth": AUTH}
    patcher, client = _patch_client()
    _client_matching(client, entry)
    store_patch, _store = _patch_store(cache)
    try:
        with store_patch:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, "api_base": "https://example.invalid/api/"}
            )
            await hass.async_block_till_done(wait_background_tasks=True)
            assert cache["auth"] == {}
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()
