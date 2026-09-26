"""Cached sessions use an authenticated student resource, not the removed /me route."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.mashov_client import MashovClient


async def test_restore_uses_timetable_and_does_not_log_in():
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


async def test_previous_school_year_cache_is_not_restored():
    client = MashovClient("123", 2027, "test", "test", saved_auth={"session_year": 2026, "csrf_token": "old"})
    client._session = MagicMock(closed=False)
    client._session.post.side_effect = RuntimeError("stop at fresh login")
    with pytest.raises(RuntimeError, match="stop at fresh login"):
        await client.async_init(None)
    client._session.get.assert_not_called()
    client._session.post.assert_called()
    assert client._saved_auth is None
