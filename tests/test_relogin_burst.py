"""A rejected re-login is attempted once and shared, never once per request.

If the Mashov password changes while Home Assistant runs, every request of a refresh
gets HTTP 401. Each one used to log in again with the old password (about six failed
logins per child per refresh), which can lock the Mashov account, and the requests
of other children kept running after the refresh had already failed.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mashov import mashov_client
from custom_components.mashov.mashov_client import (
    RELOGIN_FAILURE_COOLDOWN,
    MashovAuthError,
    MashovClient,
    MashovPasswordChangeRequiredError,
)

STUDENTS = [{"id": f"student-{i}", "slug": f"s{i}", "name": f"Example {i}"} for i in range(3)]


class FakeClock:
    """Controllable stand-in for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _unauthorized_response():
    response = MagicMock(status=401, headers={})
    response.text = AsyncMock(return_value="")
    return response


def _context(enter):
    context = MagicMock()
    context.__aenter__ = enter
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def _client(login_error):
    """A client whose session was invalidated server-side and whose re-login fails."""
    client = MashovClient("123", 2027, "test", "old-password")
    client._students = [dict(s) for s in STUDENTS]
    client._headers["X-Csrf-Token"] = "stale"
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = lambda url, headers=None: _context(
        AsyncMock(return_value=_unauthorized_response())
    )
    client.async_init = AsyncMock(side_effect=login_error)
    return client


async def test_parallel_401s_share_one_rejected_relogin():
    client = _client(MashovAuthError("Authentication failed."))
    results = await asyncio.gather(*(client._ensure_valid_session() for _ in range(18)), return_exceptions=True)
    assert client.async_init.await_count == 1
    assert all(isinstance(result, MashovAuthError) for result in results)
    # The next refresh starts with one lazy login instead of a 401 on every request.
    assert "X-Csrf-Token" not in client._headers


async def test_shared_password_change_error_keeps_the_login_page():
    client = _client(MashovPasswordChangeRequiredError("Please change password.", "https://web.mashov.info/login"))
    results = await asyncio.gather(*(client._ensure_valid_session() for _ in range(3)), return_exceptions=True)
    assert client.async_init.await_count == 1
    assert all(isinstance(result, MashovPasswordChangeRequiredError) for result in results)
    assert {result.login_url for result in results} == {"https://web.mashov.info/login"}


async def test_rejected_relogin_is_tried_again_after_the_cooldown():
    client = _client(MashovAuthError("Authentication failed."))
    clock = FakeClock()
    with patch.object(mashov_client.time, "monotonic", clock):
        for _ in range(2):
            with pytest.raises(MashovAuthError):
                await client._ensure_valid_session()
        assert client.async_init.await_count == 1

        clock.now += RELOGIN_FAILURE_COOLDOWN
        client.async_init.side_effect = None  # the password was fixed in the meantime
        await client._ensure_valid_session()
    assert client.async_init.await_count == 2
    assert client._login_failure is None


async def test_a_working_login_ends_a_shared_rejection():
    """After a rejected re-login, the next refresh logs in directly (no CSRF token). When that
    works, a 401 soon after must log in again instead of re-raising the old rejection."""
    client = _client(MashovAuthError("Authentication failed."))
    with pytest.raises(MashovAuthError):
        await client._ensure_valid_session()

    async def working_login(_hass):
        client._auth_data = {"accessToken": {"children": [{"childGuid": "kid", "privateName": "Kid"}]}}
        await client._extract_students()

    client.async_init.side_effect = working_login
    await client.async_init(None)  # the next refresh's lazy login
    assert client._login_failure is None
    client._last_login_timestamp = 0  # the new session expires later
    await client._ensure_valid_session()
    assert client.async_init.await_count == 3


async def test_failed_refresh_logs_in_once_and_cancels_requests_in_flight():
    client = _client(MashovAuthError("Authentication failed."))
    finished = []

    async def slow_unauthorized(*_args):
        await asyncio.sleep(0.2)
        finished.append(True)
        return _unauthorized_response()

    def get(url, headers=None):
        # The last child's requests are still on the wire when the first re-login is rejected.
        if "/students/student-2/" in url:
            return _context(AsyncMock(side_effect=slow_unauthorized))
        return _context(AsyncMock(return_value=_unauthorized_response()))

    client._session.get.side_effect = get
    with pytest.raises(MashovAuthError):
        await client.async_fetch_all()
    await asyncio.sleep(0.3)
    assert client.async_init.await_count == 1
    assert finished == []
