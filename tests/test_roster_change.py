"""A re-login during a refresh must not mix up students' data.

A 401 mid-refresh triggers a re-login that replaces the client's roster. The refresh
must keep pairing each result with the student it was fetched for: reordering must not
swap children's data, an added child must not crash the refresh, and a removed child
must not lose its data for this refresh. The new roster applies on the next refresh.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.mashov_client import MashovClient

A = {"id": "student-a", "slug": "a", "name": "Example A"}
B = {"id": "student-b", "slug": "b", "name": "Example B"}
C = {"id": "student-c", "slug": "c", "name": "Example C"}


def _response(status: int, payload=None):
    """Async-context-manager mock yielding a response with ``status`` and JSON ``payload``."""
    response = MagicMock(status=status, headers={})
    response.text = AsyncMock(return_value="")
    response.json = AsyncMock(return_value=payload if payload is not None else [])
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def _client(new_roster: list[dict]) -> MashovClient:
    """Client whose first homework request returns 401; the re-login installs ``new_roster``.

    Each student's homework response names that student, so a mix-up is detectable.
    """
    client = MashovClient("123", 2027, "test", "test")
    client._students = [dict(A), dict(B)]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._session = MagicMock(closed=False)
    state = {"unauthorized_sent": False}

    def get(url, headers=None):
        path = url.split("?")[0]
        if path.endswith("/homework"):
            if not state["unauthorized_sent"]:
                state["unauthorized_sent"] = True
                return _response(401)
            sid = path.split("/students/")[1].split("/")[0]
            return _response(200, [{"homework": f"for {sid}", "lessonDate": "2026-10-01T00:00:00"}])
        return _response(200, [])

    async def relogin():
        # What async_init -> _extract_students does: replace the roster with a new list.
        client._students = [dict(s) for s in new_roster]

    client._session.get.side_effect = get
    client._ensure_valid_session = AsyncMock(side_effect=relogin)
    return client


@pytest.mark.parametrize(
    "new_roster",
    [[B, A], [A, B, C], [B]],
    ids=["reordered", "child_added", "child_removed"],
)
async def test_relogin_mid_refresh_keeps_each_child_with_its_own_data(new_roster):
    """Every returned student keeps their own homework, and the result matches the refresh's roster."""
    client = _client(new_roster)

    data = await client.async_fetch_all()

    client._ensure_valid_session.assert_awaited()
    assert [s["id"] for s in data["students"]] == ["student-a", "student-b"]
    assert set(data["by_slug"]) == {"a", "b"}
    for slug, sid in (("a", "student-a"), ("b", "student-b")):
        assert data["by_slug"][slug]["homework"][0]["homework"] == f"for {sid}"
    # The new roster is kept for the next refresh.
    assert [s["id"] for s in client._students] == [s["id"] for s in new_roster]
    # The next refresh must actually use the changed roster, including additions/removals.
    next_data = await client.async_fetch_all()
    assert [s["id"] for s in next_data["students"]] == [s["id"] for s in new_roster]
    for student in new_roster:
        assert next_data["by_slug"][student["slug"]]["homework"][0]["homework"] == f"for {student['id']}"
