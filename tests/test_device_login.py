"""Remembered devices renew sessions without changing student data or retry policy."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from multidict import CIMultiDict
import pytest
from yarl import URL

from custom_components.mashov.mashov_client import MashovClient, MashovError, MashovPasswordChangeRequiredError

PASS = {
    "appName": "com.mashov.main",
    "deviceUuid": "test-device",
    "pass": "secret",
    "semel": 123,
    "userId": "test-user",
    "year": 2027,
}
DATA = {"accessToken": {"children": [{"childGuid": "child", "privateName": "Example"}]}}


def client_with_pass():
    client = MashovClient("123", 2027, "test", "password", remember_device=True, auth_updated=AsyncMock())
    client._device_auth = {"pass": dict(PASS), "uniquId": "device-cookie", "binding": client._device_binding()}
    client._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())
    return client


def response(status=200, headers=None, data=None):
    resp = MagicMock(status=status, headers=CIMultiDict(headers or {"X-Csrf-Token": "fresh"}))
    resp.json = AsyncMock(return_value=DATA if data is None else data)
    resp.text = AsyncMock(return_value="")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=resp)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


async def test_expired_session_uses_only_device_credentials_and_refreshes_roster():
    client = client_with_pass()
    client._session.cookie_jar.update_cookies({"MashovAuthToken": "stale"}, response_url=URL(client._api_base))

    def post(url, **kwargs):
        assert url.endswith("/loginDevice")
        assert "password" not in kwargs["json"]
        assert "pass" not in kwargs["json"]
        assert kwargs["json"]["devicePlatform"] == "chrome"
        assert kwargs["json"] == client._login_device_fields() | {"deviceUuid": PASS["deviceUuid"]}
        assert kwargs["json"]["apiVersion"] == "4.20250101"
        assert json.loads(kwargs["headers"]["devicePass"]) == PASS
        assert {c.key for c in client._session.cookie_jar} == {"uniquId"}
        assert kwargs["allow_redirects"] is False
        return response()

    client._session.post.side_effect = post
    await client.async_init(None)
    assert client._session.post.call_count == 1
    assert client._students[0]["id"] == "child"
    assert client.roster_refreshed
    assert client._headers["X-Csrf-Token"] == "fresh"
    client._auth_updated.assert_awaited_once()


async def test_restart_restores_device_pass_independently_of_session():
    first = client_with_pass()
    saved = first.auth_data
    second = MashovClient("123", 2027, "test", "password", remember_device=True, saved_auth=saved)
    second._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())
    second._session.post.return_value = response()
    await second.async_init(None)
    assert second._session.post.call_args.args[0].endswith("/loginDevice")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
async def test_definite_rejection_falls_back_once_and_clears_cookie(status, caplog):
    """Revoked passes and a changed loginDevice contract (Mashov answers 400 for a
    missing field) must not block the password login on every refresh."""
    client = client_with_pass()

    def post(url, **kwargs):
        if url.endswith("loginDevice"):
            return response(status)
        assert list(client._session.cookie_jar) == []
        assert kwargs["json"]["isPrivateDevice"] is True
        assert kwargs["json"]["appName"] == "com.mashov.main"
        return response()

    client._session.post.side_effect = post
    await client.async_init(None)
    assert client._session.post.call_count == 2
    assert client._device_auth == {}
    assert client._auth_updated.await_count == 2
    assert f"rejected the remembered device (HTTP {status})" in caplog.text


async def test_reply_without_session_falls_back_to_password():
    client = client_with_pass()

    def post(url, **kwargs):
        if url.endswith("loginDevice"):
            return response(headers={"Content-Type": "application/json"})  # no CSRF token
        return response()

    client._session.post.side_effect = post
    await client.async_init(None)
    assert [call.args[0].rsplit("/", 1)[1] for call in client._session.post.call_args_list] == ["loginDevice", "login"]
    assert client._device_auth == {}


async def test_non_json_reply_is_a_temporary_failure_not_a_code_error():
    """A proxy or maintenance page must not raise a raw ValueError (reported as a bug)."""
    client = client_with_pass()
    reply = response()
    reply.__aenter__.return_value.json.side_effect = json.JSONDecodeError("Expecting value", "<html>", 0)
    client._session.post.return_value = reply
    with pytest.raises(MashovError):
        await client.async_init(None)
    assert client._session.post.call_count == 1
    assert client._device_auth["pass"] == PASS


@pytest.mark.parametrize("status", [408, 429, 500, 503, 302])
async def test_server_failure_retains_pass_without_password_login(status):
    client = client_with_pass()
    client._session.post.return_value = response(status)
    with pytest.raises(MashovError):
        await client.async_init(None)
    assert client._session.post.call_count == 1
    assert client._device_auth["pass"] == PASS


@pytest.mark.parametrize("change", ["year", "cookie", "account", "origin"])
async def test_invalid_binding_or_missing_cookie_uses_password(change):
    first = client_with_pass()
    saved = first.auth_data
    if change == "cookie":
        saved["device_auth"].pop("uniquId")
    client = MashovClient(
        "123",
        2028 if change == "year" else 2027,
        "another" if change == "account" else "test",
        "password",
        api_base="https://example.invalid/api/" if change == "origin" else None,
        remember_device=True,
        saved_auth=saved,
    )
    client._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())
    client._session.post.return_value = response()
    await client.async_init(None)
    assert client._session.post.call_args.args[0].endswith("/login")


async def test_password_login_captures_device_pass_and_cookie():
    client = client_with_pass()
    client._device_auth = {}

    def post(*args, **kwargs):
        client._session.cookie_jar.update_cookies({"uniquId": "issued-cookie"}, response_url=URL(client._api_base))
        return response(headers={"X-Csrf-Token": "fresh", "devicePass": json.dumps(PASS)})

    client._session.post.side_effect = post
    await client.async_init(None)
    assert client.auth_data["device_auth"]["uniquId"] == "issued-cookie"
    assert client.auth_data["device_auth"]["pass"] == PASS


async def test_every_login_identifies_as_the_app_but_only_remembering_clients_keep_a_pass():
    client = MashovClient("123", 2027, "test", "password")
    client._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())

    def post(url, **kwargs):
        client._session.cookie_jar.update_cookies({"uniquId": "issued-cookie"}, response_url=URL(client._api_base))
        return response(headers={"X-Csrf-Token": "fresh", "devicePass": json.dumps(PASS)})

    client._session.post.side_effect = post
    await client.async_init(None)
    payload = client._session.post.call_args.kwargs["json"]
    assert payload["appName"] == "com.mashov.main"
    # Unticked "private device" box, as in the Mashov app's default login form.
    assert "isPrivateDevice" not in payload
    assert client.auth_data["device_auth"] == {}


async def test_school_stored_by_name_keeps_its_pass_across_restarts():
    saved = client_with_pass().auth_data  # bound to school 123 after an earlier login
    client = MashovClient("Example School", 2027, "test", "password", remember_device=True, saved_auth=saved)
    client._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())
    client._session.post.return_value = response()
    client.async_search_schools = AsyncMock(return_value=[{"semel": 123, "name": "Example School"}])
    await client.async_init(None)
    assert client._session.post.call_args.args[0].endswith("/loginDevice")


async def test_school_stored_by_name_still_checks_the_account():
    saved = client_with_pass().auth_data
    client = MashovClient("Example School", 2027, "another", "password", remember_device=True, saved_auth=saved)
    client._session = MagicMock(closed=False, cookie_jar=aiohttp.CookieJar())
    client._session.post.return_value = response()
    client.async_search_schools = AsyncMock(return_value=[{"semel": 123, "name": "Example School"}])
    await client.async_init(None)
    assert client._session.post.call_args.args[0].endswith("/login")
    assert client._device_auth == {}


async def test_parallel_expirations_share_one_device_login():
    client = client_with_pass()
    client._session.post.return_value = response()
    await asyncio.gather(*(client._ensure_valid_session() for _ in range(12)))
    assert client._session.post.call_count == 1


async def test_password_change_is_not_hidden_by_fallback():
    client = client_with_pass()
    client._session.post.return_value = response(403, headers={"reason": "changepass"})
    with pytest.raises(MashovPasswordChangeRequiredError):
        await client.async_init(None)
    assert client._session.post.call_count == 1
    assert not client._device_auth


async def test_working_cached_session_does_not_register_or_renew_device():
    client = client_with_pass()
    client._saved_auth = {"csrf_token": "cached", "local_auth": DATA, "session_year": 2027}
    client._session.get.return_value = response()
    await client.async_init(None)
    client._session.post.assert_not_called()
    assert client._device_auth["pass"] == PASS


async def test_transient_network_failure_does_not_use_password():
    client = client_with_pass()
    client._session.post.side_effect = aiohttp.ClientConnectionError()
    from unittest.mock import patch

    with (
        patch("custom_components.mashov.mashov_client.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(MashovError),
    ):
        await client.async_init(None)
    assert client._session.post.call_count == 3
    assert all(call.args[0].endswith("/loginDevice") for call in client._session.post.call_args_list)
    assert client._device_auth["pass"] == PASS
