"""Read-only portal data, school permissions, and storage limits."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mashov.mashov_client import MashovClient, MashovPasswordChangeRequiredError
from custom_components.mashov.sensor import MashovAdditionalSensor


@pytest.fixture
def enable_custom_integrations():
    yield


def make_client(status=200, payload=None, headers=None, body=""):
    client = MashovClient("123", 2027, "test", "test", additional_data=["message_board"])
    response = MagicMock(status=status, headers=headers or {})
    response.json = AsyncMock(return_value=[] if payload is None else payload)
    response.text = AsyncMock(return_value=body)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock()
    client._session.get.return_value = context
    return client


def fetch(client, sid="student", key="message_board"):
    return asyncio.run(client._fetch_student_resource(sid, key, "2026-09-01", "2026-10-01"))


def test_only_get_requests_and_date_parameters():
    client = make_client(payload=[{"justified": True, "id": 1}])
    result = fetch(client, key="justification_requests")
    assert result == {"status": "ok", "items": [{"justified": True, "id": 1}]}
    url = client._session.get.call_args.args[0]
    assert url.endswith("students/student/justificationrequests?start=2026-09-01&end=2026-10-01")
    assert {call[0].split("(")[0] for call in client._session.mock_calls} == {"get"}


@pytest.mark.parametrize("status,expected", [(403, "forbidden"), (404, "unsupported")])
def test_permission_backoff_is_scoped_and_expires(status, expected):
    client = make_client(status=status)
    with patch("custom_components.mashov.mashov_client.time.monotonic", return_value=100):
        assert fetch(client)["status"] == expected
        fetch(client)
        assert client._session.get.call_count == 1
        fetch(client, sid="other-student")
        assert client._session.get.call_count == 2
    with patch("custom_components.mashov.mashov_client.time.monotonic", return_value=86501):
        fetch(client)
        assert client._session.get.call_count == 3


def test_unauthorized_retries_once():
    client = make_client(status=401)
    client._ensure_valid_session = AsyncMock()
    assert fetch(client)["status"] == "unauthorized"
    assert client._session.get.call_count == 2
    client._ensure_valid_session.assert_awaited_once()


@pytest.mark.parametrize("payload", [{"error": "denied"}, "html", ["not a record"]])
def test_invalid_payload_is_not_a_successful_empty_list(payload):
    assert fetch(make_client(payload=payload))["status"] == "invalid_response"


def test_password_change_is_not_silenced():
    client = make_client(status=403, headers={"reason": "ChangePass"})
    with pytest.raises(MashovPasswordChangeRequiredError):
        fetch(client)


def test_empty_list_is_success_and_transient_errors_are_retried():
    assert fetch(make_client()) == {"items": [], "status": "ok"}
    client = make_client(status=500)
    assert fetch(client)["status"] == "http_500"
    fetch(client)
    assert client._session.get.call_count == 2


def make_sensor(resource=None):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.entry = SimpleNamespace(options={})
    coordinator.data = {"by_slug": {"student": {"additional_data": {}}}}
    if resource is not None:
        coordinator.data["by_slug"]["student"]["additional_data"]["message_board"] = resource
    return MashovAdditionalSensor(coordinator, "123", "student", "Student", "message_board", "entry")


@pytest.mark.parametrize("status", ["forbidden", "unsupported", "fetch_failed", "invalid_response"])
def test_failed_sensor_is_unavailable_not_zero(status):
    sensor = make_sensor({"items": [], "status": status})
    assert not sensor.available
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["source_status"] == status


def test_unfetched_sensor_and_valid_empty_sensor():
    assert not make_sensor().available
    sensor = make_sensor({"items": [], "status": "ok"})
    assert sensor.available
    assert sensor.native_value == 0


def test_attributes_skip_oversized_record_and_preserve_ids_and_status():
    items = [{"text": "א" * 20000}, {"id": 2, "justified": True}]
    sensor = make_sensor({"items": items, "status": "ok"})
    attributes = sensor.extra_state_attributes
    assert sensor.native_value == 2
    assert attributes["stored_items"] == 1
    assert attributes["items"] == [items[1]]
    assert len(json.dumps(attributes).encode()) < 16384


def test_optional_data_disabled_by_default():
    assert MashovClient("123", 2027, "test", "test").additional_data == ()


@pytest.mark.parametrize("enabled", [False, True])
def test_refresh_includes_only_selected_resources_without_breaking_core_data(enabled):
    client = make_client()
    client.additional_data = ("message_board",) if enabled else ()
    client._session.closed = False
    client._headers = {"X-Csrf-Token": "test"}
    client._students = [{"id": "student", "slug": "student", "name": "Student"}]
    client._fetch_student_resource = AsyncMock(return_value={"items": [], "status": "forbidden"})
    result = asyncio.run(client.async_fetch_all())
    student = result["by_slug"]["student"]
    assert student["homework"] == []
    if enabled:
        assert student["additional_data"]["message_board"]["status"] == "forbidden"
        client._fetch_student_resource.assert_awaited_once()
    else:
        assert student["additional_data"] == {}
        client._fetch_student_resource.assert_not_awaited()


def test_forbidden_resource_at_one_school_does_not_disable_another_school():
    first = make_client(status=403)
    second = make_client(payload=[{"id": 1}])
    assert fetch(first)["status"] == "forbidden"
    assert fetch(second) == {"items": [{"id": 1}], "status": "ok"}
