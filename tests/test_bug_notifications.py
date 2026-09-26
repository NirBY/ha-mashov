"""Only internal defects offer a report; opt-in technical logs never copy private text."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import aiohttp
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.mashov import (
    MashovCoordinator,
    _async_show_auth_notification,
    _async_show_error_notification,
    _async_show_password_change_notification,
)
from custom_components.mashov.diagnostics import async_get_config_entry_diagnostics
from custom_components.mashov.mashov_client import MashovAuthError, MashovError, MashovPasswordChangeRequiredError
from custom_components.mashov.reporting import is_internal_error, issue_report_url, technical_log


@pytest.mark.parametrize(
    "error",
    [
        MashovError("HTTP 500"),
        MashovError("HTTP 403"),
        MashovError("Invalid JSON"),
        MashovAuthError("invalid credentials"),
        TimeoutError(),
        ConnectionError(),
        aiohttp.ClientConnectionError(),
        aiohttp.InvalidURL("private URL"),
        OSError("disk full"),
        None,
    ],
)
def test_operational_failures_are_not_bug_reports(error):
    assert not is_internal_error(error)


@pytest.mark.parametrize(
    "error", [TypeError("private"), KeyError("private"), AttributeError("private"), RuntimeError("private")]
)
def test_internal_failures_survive_ha_wrappers(error):
    wrapper = UpdateFailed("wrapper")
    wrapper.__cause__ = error
    assert is_internal_error(wrapper)


def test_normal_alerts_have_no_github_link(hass, mock_config_entry):
    with patch("custom_components.mashov.persistent_notification.async_create") as create:
        _async_show_auth_notification(hass, mock_config_entry, "Bad password")
        _async_show_password_change_notification(
            hass, mock_config_entry, MashovPasswordChangeRequiredError("change", "https://example.invalid")
        )
        _async_show_error_notification(hass, mock_config_entry, "Mashov refresh failed", MashovError("HTTP 500"))
    assert create.call_count == 3
    assert all("github.com" not in call.args[1] for call in create.call_args_list)


async def test_internal_error_offers_optional_logs_and_diagnostics_without_private_text(hass, mock_config_entry):
    secret = "PRIVATE-TOKEN-STUDENT-HOMEWORK"
    try:
        raise TypeError(secret)
    except TypeError as exc:
        with patch("custom_components.mashov.persistent_notification.async_create") as create:
            _async_show_error_notification(hass, mock_config_entry, "Mashov refresh failed", exc)
    message = create.call_args.args[1]
    assert "Review a bug report on GitHub" in message
    assert "Review a bug report with technical logs" in message
    assert secret not in message
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert secret not in json.dumps(result)
    assert result["technical_logs"][0]["error_type"] == "TypeError"
    assert result["technical_logs"][0]["frames"] == []  # no external test path exported
    url = issue_report_url("Mashov refresh failed", result["technical_logs"])
    report = json.loads(parse_qs(urlparse(url).query)["debug_logs"][0])
    assert report["technical_logs"][0]["error_type"] == "TypeError"
    assert len(url) < 6000


async def test_internal_errors_notify_immediately_once_and_reset_on_recovery(hass, mock_config_entry):
    client = MagicMock(async_fetch_all=AsyncMock(side_effect=TypeError("private")), auth_data={})
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = {"students": [], "by_slug": {}}
    with patch("custom_components.mashov._async_show_error_notification") as notify:
        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            assert notify.call_count == 1
        client.async_fetch_all.side_effect = None
        client.async_fetch_all.return_value = {"students": [], "by_slug": {}, "holidays": []}
        await coordinator._async_update_data()
        client.async_fetch_all.side_effect = TypeError("private")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert notify.call_count == 2
    await coordinator.async_shutdown()


async def test_technical_logs_are_bounded_and_isolated_by_hub(hass, mock_config_entry):
    with patch("custom_components.mashov.persistent_notification.async_create"):
        for _ in range(25):
            _async_show_error_notification(hass, mock_config_entry, "Mashov refresh failed", KeyError("secret"))
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert len(result["technical_logs"]) == 20
    other = await async_get_config_entry_diagnostics(hass, SimpleNamespace(entry_id="other"))
    assert "technical_logs" not in other
    assert (
        len(
            json.loads(
                parse_qs(urlparse(issue_report_url("Mashov refresh failed", result["technical_logs"])).query)[
                    "debug_logs"
                ][0]
            )["technical_logs"]
        )
        == 1
    )


def test_safe_log_never_uses_exception_message_or_custom_exception_name():
    class PRIVATESTUDENT(TypeError):
        pass

    record = technical_log(PRIVATESTUDENT("PRIVATE-TOKEN"), "unknown private title")
    assert record["error_type"] == "TypeError"
    assert "PRIVATE" not in json.dumps(record)


async def test_client_programming_error_reaches_report_with_safe_code_location(hass, mock_config_entry):
    from custom_components.mashov.mashov_client import MashovClient

    client = MashovClient("123", 2027, "u", "p")
    client._students = [{"id": "s", "slug": "s", "name": "PRIVATE STUDENT"}]
    client._headers["X-Csrf-Token"] = "PRIVATE TOKEN"
    response = MagicMock(status=200)
    response.json = AsyncMock(side_effect=TypeError("PRIVATE RECORD"))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False)
    client._session.get.return_value = context
    with pytest.raises(TypeError) as captured:
        await client.async_fetch_all()
    with patch("custom_components.mashov.persistent_notification.async_create") as create:
        _async_show_error_notification(hass, mock_config_entry, "Mashov refresh failed", captured.value)
    message = create.call_args.args[1]
    assert len(message) < 3900  # Telegram/GreenAPI forwarding does not truncate either link.
    assert "PRIVATE" not in message
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["technical_logs"][0]["frames"]
    assert all(frame["file"] == "mashov_client.py" for frame in result["technical_logs"][0]["frames"])


async def test_internal_startup_failure_with_cache_reports_only_once(hass, mock_config_entry):
    from .test_setup_resilience import DATA, _patch_cache, _patch_client

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"schedule_type": "interval"})
    patcher, client = _patch_client(TypeError("private"))
    try:
        with _patch_cache({"data": DATA, "auth": {}, "last_refresh_ts": 1}), patch(
            "custom_components.mashov._async_show_error_notification"
        ) as notify:
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
            coordinator = hass.data["mashov"][mock_config_entry.entry_id]["coordinator"]
            assert coordinator._internal_error_notified
            notify.assert_called_once()
            client.async_fetch_all.side_effect = TypeError("private")
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            notify.assert_called_once()
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()
