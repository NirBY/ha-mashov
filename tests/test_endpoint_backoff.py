"""Core student endpoints answering HTTP 403 back off per student and per resource."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mashov import mashov_client
from custom_components.mashov.mashov_client import (
    CORE_RESOURCE_BACKOFF_STEPS,
    MashovClient,
    MashovPasswordChangeRequiredError,
)

STUDENTS = [
    {"id": "student-a", "slug": "a", "name": "Example A"},
    {"id": "student-b", "slug": "b", "name": "Example B"},
]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _response(status: int, payload=None, reason: str | None = None, text: str = ""):
    response = MagicMock(status=status, headers={"reason": reason} if reason else {})
    response.text = AsyncMock(return_value=text)
    response.json = AsyncMock(return_value=[] if payload is None else payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def _client(forbidden: dict[tuple[str, str], object]) -> MashovClient:
    """Build a client whose GETs answer 403 for (student, path-suffix) pairs in `forbidden`.

    A value of 403 means plain forbidden; a callable is invoked to build the response.
    """
    client = MashovClient("123", 2027, "test", "test")
    client._students = [dict(s) for s in STUDENTS]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._session = MagicMock(closed=False)

    def get(url, headers=None):
        for (sid, suffix), result in forbidden.items():
            if f"/students/{sid}/" in url and url.split("?")[0].endswith(suffix):
                return result() if callable(result) else _response(403)
        return _response(200, [])

    client._session.get.side_effect = get
    return client


def _calls(client: MashovClient, sid: str, suffix: str) -> int:
    return sum(
        1
        for call in client._session.get.call_args_list
        if f"/students/{sid}/" in call.args[0] and call.args[0].split("?")[0].endswith(suffix)
    )


@pytest.fixture
def clock():
    fake = FakeClock()
    with patch.object(mashov_client.time, "monotonic", fake):
        yield fake


async def test_403_escalates_1h_6h_24h_and_skips_requests(clock):
    client = _client({("student-a", "/lessons/plans"): 403})
    key = ("student-a", "weekly_plan")

    for step, delay in enumerate((*CORE_RESOURCE_BACKOFF_STEPS, CORE_RESOURCE_BACKOFF_STEPS[-1]), start=1):
        data = await client.async_fetch_all()
        assert data["by_slug"]["a"]["weekly_plan"] == []
        assert client._endpoint_cooldown[key] == (clock.now + delay, step)
        assert _calls(client, "student-a", "/lessons/plans") == step

        # Still inside the cooldown: no HTTP request for the forbidden endpoint.
        clock.now += delay - 1
        await client.async_fetch_all()
        assert _calls(client, "student-a", "/lessons/plans") == step
        clock.now += 1

    assert CORE_RESOURCE_BACKOFF_STEPS == (3600, 21600, 86400)


async def test_recovery_resets_cooldown(clock):
    forbidden = {("student-a", "/lessons/plans"): 403}
    client = _client(forbidden)
    forbidden_get = client._session.get.side_effect
    await client.async_fetch_all()
    clock.now += CORE_RESOURCE_BACKOFF_STEPS[0]
    await client.async_fetch_all()
    assert client._endpoint_cooldown[("student-a", "weekly_plan")][1] == 2

    clock.now += CORE_RESOURCE_BACKOFF_STEPS[1]
    plan = [{"groupid": 1, "lessondate": "2027-01-01", "lesson": 1, "plan": "Synthetic"}]
    client._session.get.side_effect = lambda url, headers=None: _response(
        200, plan if url.endswith("/lessons/plans") else []
    )
    data = await client.async_fetch_all()
    assert data["by_slug"]["a"]["weekly_plan"][0]["plan"] == "Synthetic"
    assert client._endpoint_cooldown == {}

    # A later 403 starts over at the first step instead of continuing the old escalation.
    client._session.get.side_effect = forbidden_get
    await client.async_fetch_all()
    assert client._endpoint_cooldown[("student-a", "weekly_plan")][1] == 1


async def test_student_and_resource_isolation(clock):
    plan = [{"groupid": 1, "lessondate": "2027-01-01", "lesson": 1, "plan": "Synthetic"}]
    client = _client({("student-a", "/lessons/plans"): 403})
    base_get = client._session.get.side_effect

    def get(url, headers=None):
        if "/students/student-b/" in url and url.endswith("/lessons/plans"):
            return _response(200, plan)
        return base_get(url, headers)

    client._session.get.side_effect = get
    await client.async_fetch_all()
    data = await client.async_fetch_all()

    assert set(client._endpoint_cooldown) == {("student-a", "weekly_plan")}
    # Student B keeps fetching weekly_plan on every refresh.
    assert _calls(client, "student-b", "/lessons/plans") == 2
    assert data["by_slug"]["b"]["weekly_plan"][0]["plan"] == "Synthetic"
    # Other resources of student A are unaffected.
    for suffix in ("/homework", "/behave", "/timetable", "/lessons/history", "/grades"):
        assert _calls(client, "student-a", suffix) == 2


@pytest.mark.parametrize(
    "reason,text",
    [("ChangePass", ""), (None, '{"message": "Please change password"}')],
)
async def test_password_change_403_is_raised_not_cooled_down(clock, reason, text):
    client = _client({("student-a", "/lessons/plans"): lambda: _response(403, reason=reason, text=text)})
    with pytest.raises(MashovPasswordChangeRequiredError):
        await client.async_fetch_all()
    assert client._endpoint_cooldown == {}
    # The next refresh probes the endpoint again and raises again.
    with pytest.raises(MashovPasswordChangeRequiredError):
        await client.async_fetch_all()
    assert _calls(client, "student-a", "/lessons/plans") == 2
