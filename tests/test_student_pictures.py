"""Opt-in student profile pictures (#19): GET-only, in-memory, bounded, shown as image entities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.const import PLATFORMS
from custom_components.mashov.data_schedule import SHARED_DATA
from custom_components.mashov.data_selection import DATA_KEYS, LEGACY_CORE_DATA, filter_cached_data
from custom_components.mashov.image import MashovStudentPicture
from custom_components.mashov.mashov_client import PICTURE_MAX_BYTES, MashovClient

JPEG = b"\xff\xd8\xff" + b"0" * 64


@pytest.fixture
def enable_custom_integrations():
    """Override the autouse HA fixture: these tests exercise the client and entity directly."""
    yield


def make_client(status=200, content_type="image/jpeg", body=JPEG, content_length=None):
    client = MashovClient("123", 2027, "test", "test")
    response = MagicMock(status=status, headers={"Content-Type": content_type})
    response.content_length = content_length
    response.content = MagicMock()
    response.content.read = AsyncMock(return_value=body)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock()
    client._session.get.return_value = context
    client._headers = {"X-Csrf-Token": "test"}
    return client


def test_picture_is_opt_in_and_shared_per_hub():
    assert "picture" in DATA_KEYS
    assert "picture" not in LEGACY_CORE_DATA
    assert "picture" in SHARED_DATA
    assert "image" in PLATFORMS


def test_picture_download_is_get_and_kept_in_memory():
    client = make_client()
    assert asyncio.run(client._fetch_student_picture("student")) == "ok"
    url = client._session.get.call_args.args[0]
    assert url.endswith("user/student/picture")
    assert {call[0].split("(")[0] for call in client._session.mock_calls} == {"get"}
    body, content_type, fetched_at = client.pictures["student"]
    assert body == JPEG and content_type == "image/jpeg" and fetched_at > 0


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"status": 404}, "unsupported"),
        ({"status": 403}, "forbidden"),
        ({"status": 500}, "http_500"),
        ({"content_type": "application/json", "body": b"{}"}, "invalid_response"),
        ({"body": b""}, "invalid_response"),
        ({"content_length": PICTURE_MAX_BYTES + 1}, "too_large"),
        ({"body": b"x" * (PICTURE_MAX_BYTES + 1)}, "too_large"),
    ],
)
def test_bad_picture_responses_are_reported_not_stored(kwargs, expected):
    client = make_client(**kwargs)
    assert asyncio.run(client._fetch_student_picture("student")) == expected
    assert "student" not in client.pictures


def test_refresh_reports_per_student_status_and_drops_departed_students():
    client = make_client()
    client.pictures["gone"] = (JPEG, "image/jpeg", 1.0)
    result = asyncio.run(client._fetch_pictures([{"id": "student"}]))
    assert result == {"status": "ok", "by_student": {"student": "ok"}}
    assert "gone" not in client.pictures and "student" in client.pictures


def test_one_missing_picture_marks_the_dataset_partial():
    client = make_client()
    responses = [make_client(status=404)._session.get.return_value, client._session.get.return_value]
    client._session.get.side_effect = responses
    result = asyncio.run(client._fetch_pictures([{"id": "a"}, {"id": "b"}]))
    assert result["status"] == "partial_failure"
    assert result["by_student"] == {"a": "unsupported", "b": "ok"}


def make_entity(stored=None, status="ok"):
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.entry = SimpleNamespace(options={}, title="School")
    coordinator.last_update_success = True
    coordinator.client = SimpleNamespace(pictures={} if stored is None else {"student": stored})
    coordinator.data = {
        "students": [{"id": "student", "name": "Student", "slug": "student"}],
        "picture": {"status": status, "by_student": {"student": status}},
    }
    return MashovStudentPicture(coordinator, "student", "student", "Student", "entry")


def test_entity_serves_stored_bytes_and_timestamp():
    entity = make_entity((JPEG, "image/png", 1700000000.0))
    assert asyncio.run(entity.async_image()) == JPEG
    assert entity.content_type == "image/png"
    assert entity.image_last_updated.timestamp() == 1700000000.0
    assert entity.unique_id == "mashov_entry_student_picture"
    assert entity.extra_state_attributes["source_status"] == "ok"


def test_entity_without_picture_has_no_image():
    entity = make_entity()
    assert asyncio.run(entity.async_image()) is None
    assert entity.image_last_updated is None


def test_disabling_picture_removes_cached_copy():
    data = {"picture": {"status": "ok", "by_student": {"student": "ok"}}}
    assert "picture" not in filter_cached_data(data, {"enabled_data": ["homework"]})
    assert "picture" in filter_cached_data(data, {"enabled_data": ["picture"]})
