"""School-specific attendance codes, student isolation, full-year totals and stale data."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.attendance import ATTENDANCE_COUNTS, normalize_attendance
from custom_components.mashov.data_schedule import merge_partial_data
from custom_components.mashov.mashov_client import MashovClient
from custom_components.mashov.sensor import MashovAttendanceSensor, _optional_student_sensors

from .test_roster_change import _response


@pytest.fixture
def enable_custom_integrations():
    yield


def payload():
    return [
        {
            "student": {"studentGuid": "child", "birthDate": "private", "studentId": 123},
            "lessonsCount": 100,
            "eventsCount": [
                {"groupId": 5, "eventCode": 61, "eventName": "Absence", "justified": 2, "notJustified": 3},
                {"groupId": 5, "eventCode": 62, "eventName": "Late", "justified": 1, "notJustified": 2},
                {"groupId": 6, "eventCode": 69, "eventName": "Online absence", "justified": 0, "notJustified": 1},
                {"groupId": 6, "eventCode": 70, "eventName": "Custom", "justified": 0, "notJustified": 4},
                {"groupId": 6, "eventCode": 67, "eventName": "Disruption", "justified": 0, "notJustified": 2},
            ],
        }
    ]


DEFINITIONS = [{"code": code, "commonBehaveId": common} for code, common in ((61, 1), (62, 3), (69, 16), (67, 4))]
GROUPS = [
    {"groupId": 5, "subjectName": "Math", "groupName": "Math A"},
    {"groupId": 6, "subjectName": "English", "groupName": "English A"},
    {"groupId": 7, "subjectName": "Science", "groupName": "Science A"},
]


def normalized():
    return normalize_attendance(payload(), DEFINITIONS, GROUPS, "child", 2027)


def test_counts_follow_school_mapping_and_include_justifications_and_zero_groups():
    result = normalized()
    assert result["absences"] == 6
    assert result["lateness"] == 3
    assert result["justified_absences"] == 2
    assert result["unjustified_absences"] == 4
    assert result["justified_lateness"] == 1
    assert result["unjustified_lateness"] == 2
    assert result["other_events"] == 2
    assert result["unclassified_events"] == 4
    assert result["total_events"] == 15
    assert result["classification_complete"] is False
    assert result["lessons_count"] == 100
    assert [row["absences"] for row in result["items"]] == [5, 1, 0]
    assert [row["subject"] for row in result["items"]] == ["Math", "English", "Science"]
    assert result["items"][0]["events"][0]["justified"] == 2
    assert "private" not in json.dumps(result)
    assert "studentGuid" not in json.dumps(result)
    assert result["period_start"] == "2026-09-01"
    assert result["period_end"] == "2027-08-31"


def test_no_guessing_from_event_codes_or_names_and_keep_unmatched_groups():
    result = normalize_attendance(payload(), [{"code": 61, "commonBehaveId": 3}], [], "CHILD", 2027)
    assert result["absences"] == 0
    assert result["lateness"] == 5
    assert result["items"][0]["subject"] is None
    assert result["unclassified_events"] == 10


@pytest.mark.parametrize("change", ["foreign", "mixed", "duplicate", "negative", "bool", "string", "events", "profile"])
def test_malformed_or_foreign_payload_cannot_report_a_plausible_total(change):
    rows = payload()
    if change == "foreign":
        rows[0]["student"]["studentGuid"] = "sibling"
    elif change == "mixed":
        rows.append(deepcopy(rows[0]))
    elif change == "duplicate":
        rows[0]["eventsCount"].append(deepcopy(rows[0]["eventsCount"][0]))
    elif change in ("negative", "bool", "string"):
        rows[0]["eventsCount"][0]["justified"] = {"negative": -1, "bool": True, "string": "1"}[change]
    elif change == "events":
        rows[0]["eventsCount"] = None
    else:
        rows[0]["student"] = None
    with pytest.raises(ValueError):
        normalize_attendance(rows, DEFINITIONS, GROUPS, "child", 2027)


def sensor(resource):
    coord = MagicMock(last_update_success=True, data_stale=False, last_successful_update=None)
    coord.entry = SimpleNamespace(options={"enabled_data": [ATTENDANCE_COUNTS]})
    coord.data = {
        "students": [{"id": "child", "slug": "child", "name": "Child"}],
        "by_slug": {"child": {"additional_data": {ATTENDANCE_COUNTS: resource}}},
    }
    return _optional_student_sensors(coord, ("child", "child", "Child"), [ATTENDANCE_COUNTS], "entry")[0]


def test_sensor_state_is_absences_not_subject_count_and_failure_is_not_zero():
    entity = sensor(normalized())
    assert isinstance(entity, MashovAttendanceSensor)
    assert entity.native_value == 6
    assert entity.extra_state_attributes["lateness"] == 3
    assert entity.extra_state_attributes["period_start"] == "2026-09-01"
    assert sensor({"status": "forbidden", "items": []}).native_value is None
    assert sensor(normalize_attendance([], [], [], "child", 2027)).native_value == 0


def test_size_limits_do_not_change_totals():
    resource = normalized()
    resource["items"] *= 500
    entity = sensor(resource)
    attrs = entity.extra_state_attributes
    assert attrs["stored_items"] < attrs["total_items"]
    assert entity.native_value == attrs["absences"] == 6
    assert len(json.dumps(attrs, default=str).encode()) < 16384


def test_transient_failure_retains_counts_and_original_school_year_together():
    old = sensor(normalized()).coordinator.data
    incoming = deepcopy(old)
    incoming["by_slug"]["child"]["additional_data"][ATTENDANCE_COUNTS] = {"status": "http_503", "items": []}
    merged = merge_partial_data(old, incoming, {ATTENDANCE_COUNTS})
    resource = merged["by_slug"]["child"]["additional_data"][ATTENDANCE_COUNTS]
    entity = sensor(resource)
    assert entity.native_value == 6
    assert entity.extra_state_attributes["items_retained"] is True
    assert entity.extra_state_attributes["data_stale"] is True
    assert resource["period_start"] == "2026-09-01"
    assert resource["status"] == "http_503"
    assert old["by_slug"]["child"]["additional_data"][ATTENDANCE_COUNTS]["status"] == "ok"


def client():
    client = MashovClient("123", 2027, "test", "test", enabled_data=[ATTENDANCE_COUNTS])
    client._students = [
        {"id": "child", "slug": "child", "name": "Child"},
        {"id": "sibling", "slug": "sibling", "name": "Sibling"},
    ]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)

    def response(url, **kwargs):
        if url.endswith("achvas"):
            return _response(200, DEFINITIONS)
        if url.endswith("groups"):
            return _response(200, GROUPS)
        rows = payload()
        rows[0]["student"]["studentGuid"] = "sibling" if "/sibling/" in url else "child"
        return _response(200, rows)

    client._session.get.side_effect = response
    return client


async def test_read_only_full_year_and_dictionary_once_for_siblings():
    c = client()
    result = await c.async_fetch_all()
    urls = [call.args[0] for call in c._session.get.call_args_list]
    assert sum(url.endswith("achvas") for url in urls) == 1
    assert sum(url.endswith("groups") for url in urls) == 2
    assert sum(url.endswith("behave/count?start=2026-09-01&end=2027-08-31") for url in urls) == 2
    c._session.post.assert_not_called()
    for name in ("child", "sibling"):
        assert result["by_slug"][name]["additional_data"][ATTENDANCE_COUNTS]["absences"] == 6


async def test_independent_student_schedule_and_no_dependency_requests_when_not_due():
    c = client()
    await c.async_fetch_all(student_data={"child": set(), "sibling": set()})
    c._session.get.assert_not_called()
    result = await c.async_fetch_all(student_data={"child": {ATTENDANCE_COUNTS}})
    assert not any("/sibling/" in call.args[0] for call in c._session.get.call_args_list)
    assert result["by_slug"]["sibling"]["additional_data"] == {}
    assert ATTENDANCE_COUNTS not in MashovClient("123", 2027, "test", "test").enabled_data


async def test_reuses_selected_groups_and_dependency_failure_is_not_zero():
    c = client()
    c._fetch_student_resource = AsyncMock(return_value={"status": "ok", "items": payload()})
    groups = {"status": "ok", "items": GROUPS}
    result = await c._fetch_attendance_counts("child", "ok", DEFINITIONS, groups)
    assert result["absences"] == 6
    assert c._fetch_student_resource.await_count == 1
    result = await c._fetch_attendance_counts("child", "http_503", [], groups)
    assert result == {"status": "http_503", "items": []}
    result = await c._fetch_attendance_counts("child", "ok", DEFINITIONS, {"status": "forbidden", "items": []})
    assert result == {"status": "forbidden", "items": []}


async def test_counter_permissions_and_invalid_envelope_are_reported():
    c = client()
    c._session.get.side_effect = None
    c._session.get.return_value = _response(403, [])
    first = await c._fetch_attendance_counts("child", "ok", DEFINITIONS)
    second = await c._fetch_attendance_counts("child", "ok", DEFINITIONS)
    assert first == second == {"status": "forbidden", "items": []}
    assert c._session.get.call_count == 1
    c = client()
    c._fetch_student_resource = AsyncMock(return_value={"status": "ok", "items": [{"student": None}]})
    assert (await c._fetch_attendance_counts("child", "ok", DEFINITIONS, {"status": "ok", "items": GROUPS}))[
        "status"
    ] == "invalid_response"
