"""New credentials are checked when they are entered and used as soon as the hub reloads.

Before, the Configure form saved a new username or password without logging in, and in
daily or weekly mode the reload did not log in either, so a mistyped password (or the
fix for a rejected one) went unnoticed until the next scheduled refresh, up to a week.
"""

import time
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mashov.const import DOMAIN
from custom_components.mashov.mashov_client import MashovAuthError, MashovError

from .test_setup_resilience import DATA, _patch_cache, _patch_client


async def _submit(hass, entry, user_input, login_error=None):
    """Submit the Configure form with a mocked login; return (result, mocked client class)."""
    with patch("custom_components.mashov.config_flow.MashovClient") as client_class:
        client_class.return_value.async_init = AsyncMock(side_effect=login_error)
        client_class.return_value.async_close = AsyncMock()
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=user_input)
    return result, client_class


async def test_new_password_is_checked_before_it_is_saved(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result, client_class = await _submit(hass, mock_config_entry, {"password": "new-password"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.data["password"] == "new-password"
    kwargs = client_class.call_args.kwargs
    assert (kwargs["school_id"], kwargs["username"], kwargs["password"]) == ("123456", "test_user", "new-password")
    client_class.return_value.async_init.assert_awaited_once()
    client_class.return_value.async_close.assert_awaited_once()


async def test_rejected_password_is_reported_and_not_saved(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result, client_class = await _submit(
        hass,
        mock_config_entry,
        {"username": "typo_user", "password": "wrong"},
        MashovAuthError("Authentication failed."),
    )
    assert result["type"] == FlowResultType.FORM
    # Shown on the password field, which also opens the account section.
    assert result["errors"] == {"account": {"password": "auth"}}
    assert (mock_config_entry.data["username"], mock_config_entry.data["password"]) == ("test_user", "test_password")
    client_class.return_value.async_close.assert_awaited_once()
    # The form keeps what was typed, so only the password needs to be entered again.
    account = next(key for key in result["data_schema"].schema if str(key) == "account")
    assert account.default()["username"] == "typo_user"


async def test_unreachable_mashov_is_reported_and_nothing_is_saved(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result, _ = await _submit(hass, mock_config_entry, {"password": "new-password"}, MashovError("offline"))
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data["password"] == "test_password"


async def test_unchanged_credentials_are_not_checked(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result, client_class = await _submit(hass, mock_config_entry, {"schedule_type": "daily", "schedule_time": "15:00"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    client_class.assert_not_called()


async def test_reload_after_a_credential_change_logs_in_at_once_in_daily_mode(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "old", "school_id": "123456", "school_name": "Test School"},
        options={"schedule_type": "daily", "schedule_time": "14:00", "enabled_data": ["homework"]},
        title="Test School (123456)",
    )
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    cache = {"data": {**DATA, "enabled_data": ["homework"]}, "last_refresh_ts": time.time(), "auth": {}}
    try:
        with _patch_cache(cache):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            client.async_init.assert_not_awaited()  # a cached daily start does not log in

            hass.config_entries.async_update_entry(entry, data={**entry.data, "password": "fixed"})
            await hass.async_block_till_done(wait_background_tasks=True)
            client.async_init.assert_awaited_once()
            client.async_fetch_all.assert_awaited_once()
            assert entry.entry_id not in hass.data[DOMAIN].get("credentials_changed", set())

            # A later reload without a credential change is a normal cached start again.
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            client.async_init.assert_awaited_once()
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()
