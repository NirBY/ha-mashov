"""Opt-in student profile pictures (#19): GET-only, in-memory, bounded, shown as image entities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yarl

from custom_components.mashov import _fetch_settings_changed, image as image_module
from custom_components.mashov.const import DOMAIN, PLATFORMS
from custom_components.mashov.data_schedule import SHARED_DATA
from custom_components.mashov.data_selection import DATA_KEYS, LEGACY_CORE_DATA, filter_cached_data
from custom_components.mashov.image import MashovStudentPicture
from custom_components.mashov.mashov_client import (
    PICTURE_MAX_BYTES,
    MashovClient,
    MashovPasswordChangeRequiredError,
)
from custom_components.mashov.reporting import _account_statuses

JPEG = b"\xff\xd8\xff" + b"0" * 64


@pytest.fixture
def enable_custom_integrations():
    """Override the autouse HA fixture: these tests exercise the client and entity directly."""
    yield


def make_context(
    status=200,
    content_type="image/jpeg",
    body=JPEG,
    content_length=None,
    headers=None,
    text="",
    url=None,
    chunks=None,
):
    response = MagicMock(status=status, headers={"Content-Type": content_type, **(headers or {})})
    response.content_length = content_length
    response.content = MagicMock()

    async def iter_any():
        # Like aiohttp: the body arrives in pieces, never as one guaranteed read.
        for chunk in (body,) if chunks is None else chunks:
            yield chunk

    response.content.iter_any = iter_any
    response.text = AsyncMock(return_value=text)
    response.url = yarl.URL(url or "https://web.mashov.info/api/user/student/picture")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def make_client(**kwargs):
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock()
    client._session.get.return_value = make_context(**kwargs)
    client._headers = {"X-Csrf-Token": "test"}
    return client


def fetch_picture(client, sid="student"):
    return asyncio.run(client._fetch_student_picture(sid))


def test_picture_is_opt_in_and_shared_per_hub():
    assert "picture" in DATA_KEYS
    assert "picture" not in LEGACY_CORE_DATA
    assert "picture" in SHARED_DATA
    assert "image" in PLATFORMS


def test_picture_download_is_get_and_kept_in_memory():
    client = make_client()
    assert fetch_picture(client) == "ok"
    url = client._session.get.call_args.args[0]
    assert url.endswith("user/student/picture")
    assert {call[0].split("(")[0] for call in client._session.mock_calls} == {"get"}
    body, content_type, fetched_at = client.pictures["student"]
    assert body == JPEG and content_type == "image/jpeg" and fetched_at > 0


def test_picture_request_asks_for_images_and_never_follows_redirects_blindly():
    client = make_client()
    fetch_picture(client)
    kwargs = client._session.get.call_args.kwargs
    assert kwargs["headers"]["Accept"].startswith("image/")
    assert kwargs["headers"]["X-Csrf-Token"] == "test"
    assert kwargs["allow_redirects"] is False


def test_student_id_is_url_encoded():
    client = make_client()
    fetch_picture(client, "a/b?c")
    assert client._session.get.call_args.args[0].endswith("user/a%2Fb%3Fc/picture")


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"status": 404}, "unsupported"),
        ({"status": 403}, "forbidden"),
        ({"status": 500}, "http_500"),
        ({"content_type": "application/json", "body": b"{}"}, "invalid_response"),
        ({"content_type": "image/svg+xml", "body": b"<svg onload='x()'/>"}, "invalid_response"),
        ({"content_type": "text/html", "body": b"<html>"}, "invalid_response"),
        ({"body": b""}, "invalid_response"),
        ({"content_length": PICTURE_MAX_BYTES + 1}, "too_large"),
        ({"body": b"x" * (PICTURE_MAX_BYTES + 1)}, "too_large"),
    ],
)
def test_bad_picture_responses_are_reported_not_stored(kwargs, expected):
    client = make_client(**kwargs)
    assert fetch_picture(client) == expected
    assert "student" not in client.pictures


def test_picture_arriving_in_pieces_is_stored_whole():
    # A real network delivers a photo in many reads; storing the first one cut it off.
    picture = b"\xff\xd8\xff" + bytes(range(256)) * 800
    pieces = [picture[i : i + 8192] for i in range(0, len(picture), 8192)]
    client = make_client(body=None, chunks=pieces)
    assert fetch_picture(client) == "ok"
    assert client.pictures["student"][0] == picture


def test_chunked_picture_without_length_is_capped():
    piece = b"x" * (1024 * 1024)
    client = make_client(body=None, chunks=[b"\xff\xd8\xff", piece, piece, piece])
    assert fetch_picture(client) == "too_large"
    assert "student" not in client.pictures


@pytest.mark.parametrize("content_type", ["image/jpeg", "image/png", "image/webp", "image/gif", "IMAGE/PNG; charset=x"])
def test_raster_types_are_accepted(content_type):
    client = make_client(content_type=content_type)
    assert fetch_picture(client) == "ok"
    assert client.pictures["student"][1] == content_type.split(";")[0].lower()


def test_image_jpg_is_normalised_to_jpeg():
    client = make_client(content_type="image/jpg")
    assert fetch_picture(client) == "ok"
    assert client.pictures["student"][1] == "image/jpeg"


def test_same_host_redirect_keeps_session_headers():
    client = make_client()
    base = client._api_base
    client._session.get.side_effect = [
        make_context(status=302, headers={"Location": "/api/user/student/picture2"}, url=base + "user/student/picture"),
        make_context(),
    ]
    assert fetch_picture(client) == "ok"
    second = client._session.get.call_args_list[1]
    assert second.args[0].endswith("/api/user/student/picture2")
    assert second.kwargs["headers"]["X-Csrf-Token"] == "test"


def test_cross_host_redirect_drops_session_headers():
    client = make_client()
    client._session.get.side_effect = [
        make_context(status=302, headers={"Location": "https://cdn.example.com/p.jpg"}),
        make_context(),
    ]
    assert fetch_picture(client) == "ok"
    second = client._session.get.call_args_list[1]
    assert second.args[0] == "https://cdn.example.com/p.jpg"
    assert "X-Csrf-Token" not in second.kwargs["headers"]
    assert second.kwargs["headers"]["Accept"].startswith("image/")


def test_off_host_401_never_relogs_or_resends_session_headers():
    client = make_client()
    client._ensure_valid_session = AsyncMock()
    client._session.get.side_effect = [
        make_context(status=302, headers={"Location": "https://cdn.example.com/p.jpg"}),
        make_context(status=401, url="https://cdn.example.com/p.jpg"),
        make_context(),
    ]
    assert fetch_picture(client) == "unauthorized"
    client._ensure_valid_session.assert_not_awaited()
    assert client._session.get.call_count == 2
    assert all("X-Csrf-Token" not in call.kwargs["headers"] for call in client._session.get.call_args_list[1:])


def test_mashov_401_relogs_once_with_fresh_headers():
    client = make_client()

    async def relogin():
        client._headers = {"X-Csrf-Token": "fresh"}

    client._ensure_valid_session = AsyncMock(side_effect=relogin)
    client._session.get.side_effect = [make_context(status=401), make_context()]
    assert fetch_picture(client) == "ok"
    assert client._session.get.call_args_list[1].kwargs["headers"]["X-Csrf-Token"] == "fresh"


def test_https_to_http_redirect_is_refused():
    client = make_client()
    client._session.get.side_effect = [make_context(status=302, headers={"Location": "http://cdn.example.com/p.jpg"})]
    assert fetch_picture(client) == "invalid_response"
    assert client._session.get.call_count == 1


def test_redirect_loop_is_bounded():
    client = make_client()
    client._session.get.side_effect = lambda *a, **k: make_context(status=302, headers={"Location": "/again"})
    assert fetch_picture(client) == "invalid_response"
    assert client._session.get.call_count <= 5


def test_password_change_required_is_not_a_missing_picture():
    client = make_client(status=403, headers={"reason": "changePass"})
    with pytest.raises(MashovPasswordChangeRequiredError):
        fetch_picture(client)
    client = make_client(status=403, text="Please change password")
    with pytest.raises(MashovPasswordChangeRequiredError):
        fetch_picture(client)


def test_closed_session_is_a_failed_fetch_not_a_crash():
    client = make_client()
    client._session.get.side_effect = RuntimeError("Session is closed")
    client._session.closed = True
    assert fetch_picture(client) == "fetch_failed"
    client._session.closed = False
    with pytest.raises(RuntimeError):
        fetch_picture(client)


def test_missing_picture_is_not_requested_again_for_a_day():
    client = make_client(status=404)
    assert fetch_picture(client) == "unsupported"
    assert fetch_picture(client) == "unsupported"
    assert client._session.get.call_count == 1
    client._resource_retry_after[("student", "picture")] = (0, "unsupported")
    client._session.get.return_value = make_context()
    assert fetch_picture(client) == "ok"
    assert ("student", "picture") not in client._resource_retry_after
    assert fetch_picture(client) == "ok"
    assert client._session.get.call_count == 3


def test_transient_failure_is_retried_next_refresh():
    client = make_client(status=500)
    assert fetch_picture(client) == "http_500"
    assert fetch_picture(client) == "http_500"
    assert client._session.get.call_count == 2


def test_refresh_reports_per_student_status_and_drops_departed_students():
    client = make_client()
    client.pictures["gone"] = (JPEG, "image/jpeg", 1.0)
    result = asyncio.run(client._fetch_pictures([{"id": "student"}]))
    assert result == {"status": "ok", "by_student": {"student": "ok"}}
    assert "gone" not in client.pictures and "student" in client.pictures


def test_mixed_outcomes_mark_the_dataset_partial():
    client = make_client()
    client._session.get.side_effect = [make_context(status=404), make_context()]
    result = asyncio.run(client._fetch_pictures([{"id": "a"}, {"id": "b"}]))
    assert result["status"] == "partial_failure"
    assert result["by_student"] == {"a": "unsupported", "b": "ok"}


@pytest.mark.parametrize("status_code,expected", [(500, "http_500"), (403, "forbidden")])
def test_uniform_failure_reports_the_shared_status(status_code, expected):
    """Every child failing the same way keeps that status (so a transient one can retain the last pictures)."""
    client = make_client(status=status_code)
    result = asyncio.run(client._fetch_pictures([{"id": "a"}, {"id": "b"}]))
    assert result["status"] == expected


def make_entity(stored=None, status="ok", student_id="student"):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.entry = SimpleNamespace(options={}, title="School")
    coordinator.last_update_success = True
    coordinator.data_stale = False
    coordinator.failed_datasets = set()
    coordinator.client = SimpleNamespace(pictures={} if stored is None else {student_id: stored})
    coordinator.data = {
        "students": [{"id": student_id, "name": "Student", "slug": "student"}],
        "picture": {"status": status, "by_student": {student_id: status}},
    }
    return MashovStudentPicture(coordinator, student_id, "student", "Student", "entry")


def test_entity_serves_stored_bytes_and_timestamp():
    entity = make_entity((JPEG, "image/png", 1700000000.0))
    assert asyncio.run(entity.async_image()) == JPEG
    assert entity.content_type == "image/png"
    assert entity.image_last_updated.timestamp() == 1700000000.0
    assert entity.unique_id == "mashov_entry_student_picture"
    attributes = entity.extra_state_attributes
    assert attributes["source_status"] == "ok"
    assert attributes["data_stale"] is False
    assert attributes["schedule_type"]
    assert entity.available is True


def test_entity_without_picture_is_unavailable():
    entity = make_entity()
    assert asyncio.run(entity.async_image()) is None
    assert entity.image_last_updated is None
    assert entity.available is False


def test_after_restart_an_ok_status_without_bytes_is_not_reported_as_ok():
    """The cache never holds pictures; a stale status must not claim one is available."""
    attributes = make_entity(None, status="ok").extra_state_attributes
    assert attributes["source_status"] == "not_fetched"
    assert attributes["data_stale"] is True


def test_non_text_student_ids_are_matched_in_roster_and_memory():
    entity = make_entity((JPEG, "image/jpeg", 1.0), student_id=7)
    assert entity.available is True
    assert entity.student_name == "Student"
    assert entity.unique_id == "mashov_entry_7_picture"
    assert entity.device_info["identifiers"] == {(DOMAIN, "7")}
    assert entity.extra_state_attributes["source_status"] == "ok"


def test_disabling_picture_removes_cached_copy():
    data = {"picture": {"status": "ok", "by_student": {"student": "ok"}}}
    assert "picture" not in filter_cached_data(data, {"enabled_data": ["homework"]})
    assert "picture" in filter_cached_data(data, {"enabled_data": ["picture"]})


def test_missing_pictures_alone_do_not_force_a_full_startup_refresh():
    """A cached restart fetches pictures on their own (see test_setup_resilience), not the whole hub."""
    cached = {"enabled_data": ["picture"], "students": []}
    assert _fetch_settings_changed(cached, {"enabled_data": ["picture"]}) is False
    assert _fetch_settings_changed(cached, {"enabled_data": ["picture", "homework"]}) is True


def test_diagnostics_report_picture_outcomes_without_student_ids():
    data = {"picture": {"status": "partial_failure", "by_student": {"secret-id": "ok", "other-secret": "too_large"}}}
    result = _account_statuses(data)
    assert result["picture_status"] == {"status": "partial_failure"}
    assert result["picture_student_status_counts"] == {"ok": 1, "too_large": 1}
    assert "secret" not in str(result)


def make_setup(students, roster_refreshed=True, stale=False, success=True):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.data = {"students": students}
    coordinator.data_stale = stale
    coordinator.last_update_success = success
    coordinator.client = SimpleNamespace(roster_refreshed=roster_refreshed, pictures={})
    listeners = []
    coordinator.async_add_listener.side_effect = lambda listener: listeners.append(listener) or (lambda: None)
    hass = SimpleNamespace(data={DOMAIN: {"entry": {"coordinator": coordinator}}})
    entry = SimpleNamespace(entry_id="entry", options={"enabled_data": ["picture"]}, async_on_unload=MagicMock())
    return hass, entry, coordinator, listeners


def student(sid):
    return {"id": sid, "name": sid, "slug": sid}


async def test_setup_syncs_registry_and_adds_one_entity_per_student():
    hass, entry, coordinator, listeners = make_setup([student("a"), student("b")])
    added = []
    with patch.object(image_module, "sync_selected_entities") as sync:
        await image_module.async_setup_entry(hass, entry, added.extend)
    sync.assert_called_once_with(hass, entry)
    assert sorted(entity.unique_id for entity in added) == ["mashov_entry_a_picture", "mashov_entry_b_picture"]
    listeners[0]()
    assert len(added) == 2


async def test_setup_does_nothing_when_picture_is_not_selected():
    hass, entry, coordinator, listeners = make_setup([student("a")])
    entry.options = {"enabled_data": ["homework"]}
    added = []
    with patch.object(image_module, "sync_selected_entities") as sync:
        await image_module.async_setup_entry(hass, entry, added.extend)
    sync.assert_called_once()
    assert added == [] and listeners == []


async def test_returning_student_gets_an_entity_again_after_a_verified_departure():
    hass, entry, coordinator, listeners = make_setup([student("a"), student("b")])
    added = []
    with patch.object(image_module, "sync_selected_entities"):
        await image_module.async_setup_entry(hass, entry, added.extend)
    coordinator.data = {"students": [student("a")]}
    listeners[0]()
    coordinator.data = {"students": [student("a"), student("b")]}
    listeners[0]()
    assert [entity.unique_id for entity in added].count("mashov_entry_b_picture") == 2


async def test_unverified_roster_does_not_forget_students():
    hass, entry, coordinator, listeners = make_setup([student("a"), student("b")])
    added = []
    with patch.object(image_module, "sync_selected_entities"):
        await image_module.async_setup_entry(hass, entry, added.extend)
    coordinator.client.roster_refreshed = False
    coordinator.data = {"students": [student("a")]}
    listeners[0]()
    coordinator.client.roster_refreshed = True
    coordinator.data_stale = True
    listeners[0]()
    coordinator.data_stale = False
    coordinator.data = {"students": [student("a"), student("b")]}
    listeners[0]()
    assert len(added) == 2
