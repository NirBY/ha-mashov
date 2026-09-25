"""Cached sessions use an authenticated student resource, not the removed /me route."""

from unittest.mock import AsyncMock, MagicMock

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
