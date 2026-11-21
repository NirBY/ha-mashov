"""Cached sessions use an authenticated student resource, not the removed /me route."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.mashov.mashov_client import MashovClient


async def test_restore_uses_timetable_and_does_not_log_in():
    """A saved session is validated via the student timetable endpoint without a fresh login POST."""
    saved = {
        "csrf_token": "synthetic",
        "local_auth": {
            "accessToken": {
                "children": [
                    {"childGuid": "synthetic", "privateName": "Example", "familyName": "Student"},
                ]
            }
        },
    }
    client = MashovClient("123", 2027, "test", "test", saved_auth=saved)
    response = MagicMock(status=200)
    # session.get() is used as an async context manager yielding the response.
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False)
    client._session.get.return_value = context
    await client.async_init(None)
    assert client._session.get.call_args.args[0].endswith("/students/synthetic/timetable")
    client._session.post.assert_not_called()
    assert client._saved_auth is None
    assert len(client._students) == 1
    assert client.auth_data["session_year"] == 2027


async def test_relogin_after_a_restored_session_drops_the_restored_cookies():
    """Restored cookies are host-only with path /api. If a re-login kept them, a login cookie
    set with Path=/ would lose to the expired one on every /api/ request (aiohttp prefers the
    longer path), and every refresh would fail with 401 until Home Assistant restarts."""
    saved = {
        "csrf_token": "synthetic",
        "cookies": {"MashovAuthToken": "restored"},
        "local_auth": {"accessToken": {"children": [{"childGuid": "synthetic", "privateName": "Example"}]}},
    }
    client = MashovClient("123", 2027, "test", "test", saved_auth=saved)
    jar = aiohttp.CookieJar()
    response = MagicMock(status=200)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False, cookie_jar=jar)
    client._session.get.return_value = context
    await client.async_init(None)
    assert [(cookie.key, cookie.value, cookie["path"]) for cookie in jar] == [("MashovAuthToken", "restored", "/api")]

    # The restored session expires later; the re-login request must go out with an empty jar.
    def login(*_args, **_kwargs):
        assert list(jar) == []
        raise RuntimeError("stop at fresh login")

    client._session.post.side_effect = login
    with pytest.raises(RuntimeError, match="stop at fresh login"):
        await client.async_init(None)


async def test_previous_school_year_cache_is_not_restored():
    """A cached session from a previous school year is discarded and a fresh login is attempted."""
    client = MashovClient("123", 2027, "test", "test", saved_auth={"session_year": 2026, "csrf_token": "old"})
    client._session = MagicMock(closed=False)
    # Abort as soon as the login POST starts; only the decision to log in matters.
    client._session.post.side_effect = RuntimeError("stop at fresh login")
    with pytest.raises(RuntimeError, match="stop at fresh login"):
        await client.async_init(None)
    client._session.get.assert_not_called()
    client._session.post.assert_called()
    assert client._saved_auth is None
