"""Lesson cancellations: verified route shape, enabled and not-offered schools, sensor and timetable marks.

Synthetic data only. Reasons are staff-written text: they may reach the cancellations
sensor's attributes, never logs, diagnostics or the Assist/MCP tool.
"""

from copy import deepcopy
from datetime import date, timedelta
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import Context
from homeassistant.helpers import llm
from homeassistant.helpers.json import json_bytes
import pytest
import yaml

from custom_components.mashov.additional_data import STUDENT_RESOURCES
from custom_components.mashov.cancellations import (
    LESSON_CANCELLATIONS,
    NOT_OFFERED,
    cancellation_rows,
    mashov_weekday,
    normalize_cancellations,
    without_reasons,
)
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_schedule import SHARED_DATA, STUDENT_DATA, merge_partial_data
from custom_components.mashov.data_selection import DATA_KEYS, LEGACY_CORE_DATA, enabled_data
from custom_components.mashov.llm_api import MashovReadTool
from custom_components.mashov.mashov_client import MashovClient
from custom_components.mashov.reporting import diagnostic_summary
from custom_components.mashov.sensor import MashovCancellationsSensor, MashovListSensor, _optional_student_sensors

from .test_roster_change import _response

REASON = "Synthetic reason naming Teacher Example"
TODAY = date(2026, 11, 24)
START, END = date(2026, 11, 17), date(2026, 12, 15)
LANGUAGES = ("en", "he", "ar", "ru", "uk")


@pytest.fixture(autouse=True)
def _fixed_clock(freezer):
    """Pin the clock to noon US/Pacific on TODAY.

    The code reads today from Home Assistant's time zone, which the test harness sets to
    US/Pacific. Noon there is the same date in UTC and Israel, so the rows dated relative
    to TODAY no longer depend on the time of day the tests run.
    """
    freezer.move_to("2026-11-24 20:00:00+00:00")


def raw(day, lesson, group, reason=REASON):
    return {
        "lessonDate": f"{day.isoformat()}T00:00:00",
        "lesson": lesson,
        "groupId": group,
        "cancellationReason": reason,
    }


def enabled_payload():
    return {
        "isEnabled": True,
        # Substitutions have no verified item shape; only their number may be kept.
        "changes": [{"teacher": "Private Substitute"}, {}],
        "cancellations": [
            raw(date(2026, 11, 26), 3, 12),
            raw(date(2026, 11, 19), 1, 11),
            raw(date(2026, 11, 26), 3, 12, "Duplicate row"),
            raw(date(2026, 11, 1), 2, 11),  # outside the requested window
            {**raw(date(2026, 11, 26), 1, None), "cancellationReason": None},
        ],
    }


def not_offered_payload():
    return {"isEnabled": False, "changes": [], "cancellations": []}


# --- Response shape ---------------------------------------------------------------------------


def test_enabled_school_keeps_verified_rows_sorted_and_counts_changes_only():
    result = normalize_cancellations(enabled_payload(), START, END)
    assert result["status"] == "ok"
    assert result["offered"] is True
    assert result["period_start"] == "2026-11-17" and result["period_end"] == "2026-12-15"
    assert [(i["date"], i["lesson"], i["group_id"]) for i in result["items"]] == [
        ("2026-11-19", 1, 11),
        ("2026-11-26", 1, None),
        ("2026-11-26", 3, 12),
    ]
    assert result["items"][0]["reason"] == REASON
    assert result["items"][1]["reason"] is None
    assert result["changes_count"] == 2
    assert "Private Substitute" not in json.dumps(result)


def test_school_without_the_feature_is_not_offered():
    result = normalize_cancellations(not_offered_payload(), START, END)
    assert result == {
        "status": NOT_OFFERED,
        "items": [],
        "offered": False,
        "period_start": "2026-11-17",
        "period_end": "2026-12-15",
        "changes_count": 0,
    }


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ("list", "response:list"),
        ("no_flag", "isEnabled:NoneType"),
        ("text_flag", "isEnabled:str"),
        ("text_list", "cancellations:str"),
    ],
)
def test_changed_response_is_invalid_with_a_detail_and_no_values(change, detail):
    payload = enabled_payload()
    if change == "list":
        payload = payload["cancellations"]
    elif change == "no_flag":
        del payload["isEnabled"]
    elif change == "text_flag":
        payload["isEnabled"] = "true"
    else:
        payload["cancellations"] = REASON
    with pytest.raises(ValueError, match=f"^{detail}$"):
        normalize_cancellations(payload, START, END)


def test_null_lists_count_as_empty():
    payload = {"isEnabled": True, "changes": None, "cancellations": None}
    result = normalize_cancellations(payload, START, END)
    assert (result["status"], result["items"], result["changes_count"]) == ("ok", [], 0)
    assert "unparsed_rows" not in result


@pytest.mark.parametrize(
    ("row", "field"),
    [
        ("row", "row:str"),
        ({**raw(START, 1, 5), "lessonDate": "/Date(1763337600000)/"}, "lessonDate:str(/aaaa(9999999999999)/)"),
        ({**raw(START, 1, 5), "lessonDate": None}, "lessonDate:NoneType"),
        ({**raw(START, 1, 5), "lesson": True}, "lesson:bool"),
        ({**raw(START, 1, 5), "lesson": "1"}, "lesson:str(9)"),
        ({**raw(START, 1, 5), "lesson": None}, "lesson:NoneType"),
        ({**raw(START, 1, 5), "lesson": -1}, "lesson:int"),
        ({**raw(START, 1, 5), "groupId": "x"}, "groupId:str(a)"),
        ({**raw(START, 1, 5), "cancellationReason": 5.5}, "cancellationReason:float"),
        ({**raw(START, 1, 5), "cancellationReason": True}, "cancellationReason:bool"),
        ({**raw(START, 1, 5), "cancellationReason": ["text"]}, "cancellationReason:list"),
    ],
)
def test_a_row_outside_the_shape_is_counted_without_hiding_the_others(row, field):
    payload = enabled_payload()
    payload["cancellations"] += [row, deepcopy(row)]
    result = normalize_cancellations(payload, START, END)
    assert result["status"] == "ok"
    assert len(result["items"]) == 3
    assert result["unparsed_rows"] == 2
    assert result["unparsed_fields"] == [field]
    # A reason's text and pattern never reach the diagnostics.
    assert "Teacher" not in field and "aaaaaaaaa" not in field


# --- Client -----------------------------------------------------------------------------------


def make_client(payload, status=200):
    client = MashovClient("123", 2027, "test", "test", enabled_data=[LESSON_CANCELLATIONS])
    client._students = [{"id": "child", "slug": "child", "name": "Child"}]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = lambda url, **kwargs: _response(status, deepcopy(payload))
    return client


async def test_route_uses_verified_date_times_and_includes_the_last_day():
    client = make_client(enabled_payload())
    result = await client._fetch_lesson_cancellations("child", START, END)
    url = client._session.get.call_args.args[0]
    assert url.endswith("students/child/timetable/changes?start=2026-11-17T00:00:00&end=2026-12-16T00:00:00")
    assert client._session.get.call_args.kwargs["headers"] == {"X-Csrf-Token": "synthetic"}
    assert result["status"] == "ok" and len(result["items"]) == 3
    client._session.post.assert_not_called()


async def test_not_offered_is_quiet_and_never_backed_off(caplog):
    client = make_client(not_offered_payload())
    with caplog.at_level(logging.DEBUG, logger="custom_components.mashov"):
        first = await client._fetch_lesson_cancellations("child", START, END)
        second = await client._fetch_lesson_cancellations("child", START, END)
    assert first["status"] == second["status"] == NOT_OFFERED
    assert client._session.get.call_count == 2
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert client._resource_retry_after == {}


async def test_forbidden_route_is_parked_like_other_optional_resources():
    client = make_client({}, status=403)
    assert (await client._fetch_lesson_cancellations("child", START, END))["status"] == "forbidden"
    assert (await client._fetch_lesson_cancellations("child", START, END))["status"] == "forbidden"
    assert client._session.get.call_count == 1


@pytest.mark.parametrize(
    ("payload", "status", "expected"),
    [
        ([raw(START, 1, 5)], 200, {"items": [], "status": "invalid_response", "invalid_detail": "response:list"}),
        (
            {"isEnabled": True, "cancellations": REASON},
            200,
            {"items": [], "status": "invalid_response", "invalid_detail": "cancellations:str"},
        ),
        ({}, 503, {"items": [], "status": "http_503"}),
    ],
)
async def test_failures_never_log_reasons_or_become_zero(caplog, payload, status, expected):
    client = make_client(payload, status)
    with caplog.at_level(logging.DEBUG):
        result = await client._fetch_lesson_cancellations("child", START, END)
    assert result == expected
    assert "Teacher Example" not in caplog.text


async def test_odd_rows_are_reported_on_the_sensor_without_their_text(caplog):
    payload = enabled_payload()
    payload["cancellations"].append({**raw(date(2026, 11, 20), None, 5)})
    client = make_client(payload)
    with caplog.at_level(logging.DEBUG):
        result = await client._fetch_lesson_cancellations("child", START, END)
    assert result["status"] == "ok" and len(result["items"]) == 3
    assert (result["unparsed_rows"], result["unparsed_fields"]) == (1, ["lesson:NoneType"])
    assert "Teacher Example" not in caplog.text
    attributes = cancellations_sensor(result).extra_state_attributes
    assert (attributes["unparsed_rows"], attributes["unparsed_fields"]) == (1, ["lesson:NoneType"])
    invalid = cancellations_sensor({"items": [], "status": "invalid_response", "invalid_detail": "response:list"})
    assert invalid.extra_state_attributes["invalid_detail"] == "response:list"
    assert "invalid_detail" not in cancellations_sensor(result).extra_state_attributes


async def test_refresh_stores_the_resource_per_child_and_not_offered_is_no_closure():
    client = make_client(not_offered_payload())
    client._students.append({"id": "sibling", "slug": "sibling", "name": "Sibling"})
    result = await client.async_fetch_all()
    for slug in ("child", "sibling"):
        resource = result["by_slug"][slug]["additional_data"][LESSON_CANCELLATIONS]
        assert resource["status"] == NOT_OFFERED
    assert all("/timetable/changes?start=" in call.args[0] for call in client._session.get.call_args_list)
    assert result["closed_features"] == []
    assert client._refresh_statuses[LESSON_CANCELLATIONS] == {NOT_OFFERED}


async def test_enabled_refresh_keeps_rows_inside_the_homework_window():
    today = date.today()
    payload = {
        "isEnabled": True,
        "changes": [],
        "cancellations": [raw(today, 1, 5), raw(today - timedelta(days=60), 1, 5)],
    }
    client = make_client(payload)
    resource = (await client.async_fetch_all())["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS]
    assert [item["date"] for item in resource["items"]] == [today.isoformat()]
    assert resource["period_start"] == (today - timedelta(days=7)).isoformat()
    assert resource["period_end"] == (today + timedelta(days=21)).isoformat()


# --- Sensor -----------------------------------------------------------------------------------


def slot(day, lesson, group, subject="Math", teacher=None, **extra):
    details = {"groupId": group, "subjectName": subject}
    if teacher:
        details["groupTeachers"] = [{"teacherGuid": "guid", "teacherName": teacher}]
    return {"timeTable": {"groupId": group, "day": day, "lesson": lesson, **extra}, "groupDetails": details}


TOMORROW = TODAY + timedelta(days=1)
DAY = mashov_weekday(TOMORROW)
TIMETABLE = [
    slot(DAY, 1, 1, "Math", "Teacher One"),
    slot(DAY, 2, 2, "Bible"),
    slot(DAY, 3, 3, "English A"),
    slot(DAY, 3, 4, "English B"),
    slot(DAY, 4, 5, "Art"),
]
STUDY_GROUPS = [{"groupId": 2, "subjectName": "Bible", "groupTeachers": [{"teacherName": "Teacher Two"}]}]


def item(day, lesson, group, reason=REASON):
    return {"date": day.isoformat(), "lesson": lesson, "group_id": group, "reason": reason}


def resource(*items, status="ok", **extra):
    return {"status": status, "items": list(items), "offered": status == "ok", "changes_count": 0, **extra}


def coordinator(cancellations=None, timetable=TIMETABLE, selected=(LESSON_CANCELLATIONS,)):
    coord = MagicMock(last_update_success=True, data_stale=False, last_successful_update=None, failed_datasets=set())
    coord.entry = SimpleNamespace(options={"enabled_data": list(selected)}, title="School")
    additional = {"study_groups": {"status": "ok", "items": STUDY_GROUPS}}
    if cancellations is not None:
        additional[LESSON_CANCELLATIONS] = cancellations
    coord.data = {
        "students": [{"id": "child", "slug": "child", "name": "Child", "year": 2027}],
        "by_slug": {
            "child": {
                "timetable": timetable,
                "source_status": {"timetable": "ok"},
                "additional_data": additional,
            }
        },
    }
    return coord


def cancellations_sensor(cancellations, **kwargs):
    entity = _optional_student_sensors(
        coordinator(cancellations, **kwargs), ("child", "child", "Child"), [LESSON_CANCELLATIONS], "entry"
    )[0]
    assert isinstance(entity, MashovCancellationsSensor)
    return entity


def test_state_counts_upcoming_and_rows_name_subject_and_teacher():
    entity = cancellations_sensor(
        resource(
            item(TODAY - timedelta(days=3), 2, 2),
            item(TODAY - timedelta(days=1), 1, 1),
            item(TODAY, 4, 99),
            item(TOMORROW, 2, 2),
            item(TOMORROW, 1, 1),
        )
    )
    attributes = entity.extra_state_attributes
    assert entity.native_value == 3
    assert attributes["source_status"] == "ok" and attributes["offered"] is True
    assert attributes["data_stale"] is False
    assert attributes["next_cancellation"] == TODAY.isoformat()
    assert [(row["date"], row["lesson"]) for row in attributes["upcoming"]] == [
        (TODAY.isoformat(), 4),
        (TOMORROW.isoformat(), 1),
        (TOMORROW.isoformat(), 2),
    ]
    assert [row["date"] for row in attributes["recent"]] == [
        (TODAY - timedelta(days=1)).isoformat(),
        (TODAY - timedelta(days=3)).isoformat(),
    ]
    first = attributes["upcoming"][1]
    assert (first["subject"], first["teacher"], first["reason"]) == ("Math", "Teacher One", REASON)
    # Group 2 has no teacher in the timetable; the study group supplies it.
    assert attributes["upcoming"][2]["teacher"] == "Teacher Two"
    assert attributes["upcoming"][0]["subject"] is None and attributes["upcoming"][0]["group_id"] == 99
    assert {"upcoming", "recent"} <= MashovCancellationsSensor._unrecorded_attributes


def test_not_offered_is_a_clear_status_without_a_stale_warning():
    entity = cancellations_sensor(resource(status=NOT_OFFERED, offered=False))
    attributes = entity.extra_state_attributes
    assert entity.native_value is None
    assert attributes["source_status"] == NOT_OFFERED
    assert attributes["offered"] is False
    assert attributes["data_stale"] is False
    assert attributes["upcoming"] == attributes["recent"] == []


def test_failure_is_unknown_and_retained_rows_are_marked_stale():
    entity = cancellations_sensor(resource(status="http_503", offered=None))
    assert entity.native_value is None
    assert entity.extra_state_attributes["data_stale"] is True
    assert entity.extra_state_attributes["offered"] is None
    old = coordinator(resource(item(TOMORROW, 1, 1))).data
    incoming = deepcopy(old)
    incoming["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS] = {"status": "http_503", "items": []}
    merged = merge_partial_data(old, incoming, {LESSON_CANCELLATIONS})
    retained = merged["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS]
    entity = cancellations_sensor(retained)
    assert entity.native_value == 1
    assert entity.extra_state_attributes["items_retained"] is True
    assert entity.extra_state_attributes["data_stale"] is True
    # A school that stopped offering the feature replaces the old rows instead of keeping them.
    incoming["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS] = resource(status=NOT_OFFERED)
    merged = merge_partial_data(old, incoming, {LESSON_CANCELLATIONS})
    assert merged["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS]["items"] == []


def test_attributes_fit_the_recorder_budget_with_upcoming_first():
    rows = [item(TOMORROW + timedelta(days=n // 8), n % 8, n, "א" * 300) for n in range(200)]
    rows += [item(TODAY - timedelta(days=1), 1, 1)]
    entity = cancellations_sensor(resource(*rows))
    attributes = entity.extra_state_attributes
    assert len(json_bytes(attributes)) <= 14 * 1024
    assert attributes["truncated"] is True
    assert 0 < len(attributes["upcoming"]) < attributes["total_upcoming"] == 200
    assert attributes["recent"] == []
    assert entity.native_value == 200


def test_only_boundary_cancellations_move_the_start_or_end():
    def flags(*cancelled, timetable=TIMETABLE):
        upcoming, _ = cancellation_rows([item(TOMORROW, *c) for c in cancelled], timetable, [], TODAY)
        return {(row["lesson"], row["group_id"]): (row["moves_start"], row["moves_end"]) for row in upcoming}

    assert flags((1, 1)) == {(1, 1): (True, False)}
    assert flags((1, 1), (2, 2)) == {(1, 1): (True, False), (2, 2): (True, False)}
    assert flags((4, 5)) == {(4, 5): (False, True)}
    assert flags((2, 2)) == {(2, 2): (False, False)}
    # One of two simultaneous groups still meets, so the slot is not cancelled.
    assert flags((3, 3), (4, 5)) == {(3, 3): (False, False), (4, 5): (False, True)}
    assert flags((3, 3), (3, 4), (4, 5))[(3, 3)] == (False, True)
    every = flags((1, 1), (2, 2), (3, 3), (3, 4), (4, 5))
    assert set(every.values()) == {(True, True)}
    assert flags((1, 77)) == {(1, 77): (False, False)}
    assert flags((1, 1), timetable=[]) == {(1, 1): (None, None)}
    _, recent = cancellation_rows([item(TODAY - timedelta(days=1), 1, 1)], TIMETABLE, [], TODAY)
    assert "moves_start" not in recent[0]


def timetable_sensor(cancellations, selected=(LESSON_CANCELLATIONS, "timetable")):
    coord = coordinator(cancellations, selected=selected)
    return MashovListSensor(coord, "entry", "child", "child", "Child", "timetable", "timetable", "timetable")


def test_timetable_week_marks_only_the_cancelled_group_and_reports_status():
    attributes = timetable_sensor(resource(item(TOMORROW, 3, 3), item(TOMORROW, 1, 1))).extra_state_attributes
    assert attributes["cancellations_status"] == "ok"
    lessons = attributes["weekly_schedule"][DAY - 1]["lessons"]
    marks = {row["subject"]: row.get("cancelled") for row in lessons}
    assert marks == {
        "Math": [TOMORROW.isoformat()],
        "Bible": None,
        "English A": [TOMORROW.isoformat()],
        "English B": None,
        "Art": None,
    }
    assert REASON not in json.dumps(attributes["weekly_schedule"])


def test_timetable_without_offered_or_selected_cancellations_is_unmarked():
    attributes = timetable_sensor(resource(status=NOT_OFFERED, offered=False)).extra_state_attributes
    assert attributes["cancellations_status"] == NOT_OFFERED
    assert not any("cancelled" in row for day in attributes["weekly_schedule"] for row in day["lessons"])
    failed = timetable_sensor(resource(item(TOMORROW, 1, 1), status="http_503")).extra_state_attributes
    assert failed["cancellations_status"] == "http_503"
    assert not any("cancelled" in row for day in failed["weekly_schedule"] for row in day["lessons"])
    unselected = timetable_sensor(None, selected=("timetable",)).extra_state_attributes
    assert "cancellations_status" not in unselected


# --- Assist / MCP and diagnostics -------------------------------------------------------------


async def test_assist_gets_rows_without_reasons(hass):
    # Names come from the timetable and study groups, which the tool shows only when selected.
    coord = coordinator(
        resource(item(TODAY - timedelta(days=1), 2, 2), item(TOMORROW, 1, 1)),
        selected=(LESSON_CANCELLATIONS, "timetable", "study_groups"),
    )
    coord.entry.options["mcp_enabled"] = True
    coord.entry.entry_id = "account"
    hass.data[DOMAIN] = {"account": {"coordinator": coord}}
    hass.auth.async_get_user = AsyncMock(return_value=SimpleNamespace(is_admin=True))
    context = llm.LLMContext(
        platform="mcp_server", context=Context(user_id="admin"), language="en", assistant="mcp_server", device_id=None
    )
    tool = MashovReadTool("account")
    request = llm.ToolInput(tool_name=tool.name, tool_args={"dataset": LESSON_CANCELLATIONS, "student_id": "child"})
    result = await tool.async_call(hass, request, context)
    result = result.data if hasattr(result, "data") else result
    assert REASON not in json.dumps(result)
    assert [(row["date"], row["subject"]) for row in result["items"]] == [
        ((TODAY - timedelta(days=1)).isoformat(), "Bible"),
        (TOMORROW.isoformat(), "Math"),
    ]
    assert result["items"][1]["moves_start"] is True
    assert result["metadata"]["upcoming"] == 1 and result["metadata"]["offered"] is True
    assert result["data_stale"] is False
    coord.data["by_slug"]["child"]["additional_data"][LESSON_CANCELLATIONS] = resource(
        status=NOT_OFFERED, offered=False
    )
    result = await tool.async_call(hass, request, context)
    result = result.data if hasattr(result, "data") else result
    assert result["status"] == NOT_OFFERED and result["data_stale"] is False
    assert result["metadata"]["offered"] is False


def test_diagnostics_count_statuses_and_never_include_reasons():
    coord = coordinator(resource(item(TOMORROW, 1, 1)))
    coord.data["by_slug"]["sibling"] = {"additional_data": {LESSON_CANCELLATIONS: resource(status=NOT_OFFERED)}}
    summary = diagnostic_summary(coord)
    assert summary["optional_resource_status_counts"][LESSON_CANCELLATIONS] == {"ok": 1, NOT_OFFERED: 1}
    assert REASON not in json.dumps(summary)


# --- Selection, registration and translations --------------------------------------------------


def test_opt_in_per_child_data_type_that_upgrades_never_enable():
    assert LESSON_CANCELLATIONS in STUDENT_RESOURCES and LESSON_CANCELLATIONS in DATA_KEYS
    assert LESSON_CANCELLATIONS in STUDENT_DATA and LESSON_CANCELLATIONS not in SHARED_DATA
    assert LESSON_CANCELLATIONS not in LEGACY_CORE_DATA
    assert LESSON_CANCELLATIONS not in enabled_data({})
    assert LESSON_CANCELLATIONS not in enabled_data({"additional_data": ["study_groups"]})
    assert LESSON_CANCELLATIONS not in MashovClient("123", 2027, "test", "test").enabled_data


def test_services_offer_the_data_type():
    services = yaml.safe_load(Path("custom_components/mashov/services.yaml").read_text(encoding="utf-8"))
    fields = services["set_options"]["fields"]
    assert fields["enabled_data"]["selector"]["select"]["options"] == list(DATA_KEYS)
    assert fields["additional_data"]["selector"]["select"]["options"] == list(STUDENT_RESOURCES)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_names_every_data_type(language):
    strings = json.loads(Path(f"custom_components/mashov/translations/{language}.json").read_text(encoding="utf-8"))
    selectors = strings["selector"]
    assert set(selectors["enabled_data"]["options"]) == set(DATA_KEYS)
    assert set(selectors["additional_data"]["options"]) == set(STUDENT_RESOURCES)
    assert selectors["enabled_data"]["options"][LESSON_CANCELLATIONS].strip()
    assert selectors["additional_data"]["options"][LESSON_CANCELLATIONS].strip()
    assert strings["entity"]["sensor"][LESSON_CANCELLATIONS]["name"].strip()


async def test_first_registration_form_offers_and_saves_cancellations(hass):
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client = mock_client.return_value
        for name in ("async_init", "async_close", "async_open_session"):
            setattr(client, name, AsyncMock(return_value=None))
        client.async_fetch_schools_catalog = AsyncMock(return_value=[])
        form = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert form["step_id"] == "user"
        sections = {str(key): value for key, value in form["data_schema"].schema.items()}
        selector = {str(key): value for key, value in sections["data"].schema.schema.items()}["enabled_data"]
        assert selector.config["translation_key"] == "enabled_data"
        assert LESSON_CANCELLATIONS in selector.config["options"]
        created = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {
                "username": "synthetic",
                "password": "synthetic",
                "school_name": "123456",
                "enabled_data": ["timetable", LESSON_CANCELLATIONS],
            },
        )
    assert created["type"] == "create_entry"
    assert created["options"]["enabled_data"] == ["timetable", LESSON_CANCELLATIONS]
    assert created["options"]["additional_data"] == [LESSON_CANCELLATIONS]


def test_a_numeric_reason_is_kept_as_a_code_and_the_row_still_counts():
    payload = {"isEnabled": True, "changes": [], "cancellations": [raw(START, 2, 5, 7), raw(END, 3, 6, None)]}
    result = normalize_cancellations(payload, START, END)
    assert "unparsed_rows" not in result
    assert [(i["date"], i["reason"], i.get("reason_code")) for i in result["items"]] == [
        (START.isoformat(), None, 7),
        (END.isoformat(), None, None),
    ]
    upcoming, recent = cancellation_rows(
        [item(TOMORROW, 1, 1) | {"reason": None, "reason_code": 7}], TIMETABLE, [], TODAY
    )
    assert upcoming[0]["reason_code"] == 7 and upcoming[0]["moves_start"] is True
    assert "reason_code" not in without_reasons(upcoming)[0]


def test_a_lesson_running_only_in_some_weeks_makes_a_shift_unknown():
    """Lesson 1 runs only in some weeks, so it may or may not start that day."""
    timetable = [slot(DAY, 1, 1, "Math", weeks="1"), slot(DAY, 2, 2, "Bible"), slot(DAY, 3, 3, "English A")]
    upcoming, _ = cancellation_rows([item(TOMORROW, 2, 2)], timetable, [], TODAY)
    assert (upcoming[0]["moves_start"], upcoming[0]["moves_end"]) == (None, False)
    # Lessons 2 and 3 cancelled: the end moves either way; the start depends on that week.
    upcoming, _ = cancellation_rows([item(TOMORROW, 2, 2), item(TOMORROW, 3, 3)], timetable, [], TODAY)
    assert [(row["moves_start"], row["moves_end"]) for row in upcoming] == [(None, True), (None, True)]


def test_unexpected_group_details_do_not_break_the_rows():
    timetable = [{"timeTable": {"day": DAY, "lesson": 1}, "groupDetails": ["unexpected"]}, slot(DAY, 2, 2, "Bible")]
    upcoming, _ = cancellation_rows([item(TOMORROW, 2, 2)], timetable, [], TODAY)
    assert (upcoming[0]["subject"], upcoming[0]["moves_start"], upcoming[0]["moves_end"]) == ("Bible", False, True)


def test_a_numeric_string_group_id_is_kept_as_a_number():
    payload = {"isEnabled": True, "changes": [], "cancellations": [raw(START, 1, "5")]}
    result = normalize_cancellations(payload, START, END)
    assert result["items"][0]["group_id"] == 5
    assert "unparsed_rows" not in result


def test_a_cancelled_regular_lesson_beside_a_some_weeks_lesson_makes_the_shift_unknown():
    """The week-specific lesson left in that slot may or may not take place that day."""
    timetable = [slot(DAY, 1, 1, "Math"), slot(DAY, 1, 4, "Art", weeks="2"), slot(DAY, 2, 2, "Bible")]
    upcoming, _ = cancellation_rows([item(TOMORROW, 1, 1)], timetable, [], TODAY)
    assert (upcoming[0]["moves_start"], upcoming[0]["moves_end"]) == (None, False)
