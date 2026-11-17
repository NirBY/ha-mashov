"""Parent approvals: read-only fetching, bounded requests, per-child split, sensors and privacy."""

from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers import llm
from homeassistant.helpers.json import json_bytes
import pytest

from custom_components.mashov.approvals import (
    ACTIVITIES_PATH,
    ANSWER_STATUSES,
    ANSWERS_KEY,
    ANSWERS_PATH,
    FORM_KINDS,
    FORMS_PATH,
    PARENT_APPROVALS,
    SCHOOL_TIME_ZONE,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    answer_status,
    fetch_parent_approvals,
    open_forms,
    open_pending,
)
from custom_components.mashov.data_schedule import merge_partial_data
from custom_components.mashov.data_selection import DATA_KEYS, filter_cached_data
from custom_components.mashov.llm_api import MashovReadTool
from custom_components.mashov.mashov_client import MashovClient
from custom_components.mashov.reporting import diagnostic_summary
from custom_components.mashov.sensor import ATTRIBUTE_BUDGET_BYTES, MashovApprovalsSensor, MashovOpenFormsSensor

from .const import (
    TEST_ACTIVITY_TITLE,
    TEST_ANSWERED_FORM,
    TEST_APPROVALS_NOW,
    TEST_CHILD_A,
    TEST_CHILD_B,
    TEST_CONSENT_FORM,
    TEST_CREATOR_GUID,
    TEST_EXPIRED_FORM,
    TEST_FORM_TITLE,
    TEST_INVALID_FORM_DATA,
    TEST_LATER_ACTIVITY,
    TEST_MALFORMED_ACTIVITIES,
    TEST_OLD_ACTIVITY,
    TEST_OPEN_ACTIVITY,
    TEST_PARENT_GUID,
    TEST_RECENT_EXPIRED_ACTIVITY,
    user_answer,
)
from .test_llm_api import setup_api, unwrap
from .test_roster_change import _response

NOW = datetime.fromisoformat(TEST_APPROVALS_NOW).replace(tzinfo=SCHOOL_TIME_ZONE)
STUDENTS = [TEST_CHILD_A, TEST_CHILD_B]
OPEN_ID = TEST_OPEN_ACTIVITY["id"]
RECENT_ID = TEST_RECENT_EXPIRED_ACTIVITY["id"]
LATER_ID = TEST_LATER_ACTIVITY["id"]
CONSENT_PATH, GENERAL_PATH = (FORMS_PATH.format(consent=consent) for consent in FORM_KINDS.values())


def answers_path(activity_id):
    return ANSWERS_PATH.format(activity_id=activity_id)


def router(activities, answers=None, consent=(), general=(), failures=None):
    """get_json fake routed by path; failures maps a path to a non-ok status."""
    answers, failures = answers or {}, failures or {}
    routes = {
        ACTIVITIES_PATH: list(activities),
        CONSENT_PATH: list(consent),
        GENERAL_PATH: list(general),
    }

    async def get(path, key, expected):
        if path in failures:
            return failures[path], None
        if key == ANSWERS_KEY:
            return "ok", answers.get(int(path.split("/")[1]), [])
        return "ok", routes[path]

    return AsyncMock(side_effect=get)


def requested(get):
    return [call.args[0] for call in get.await_args_list]


async def fetch(get):
    return await fetch_parent_approvals(get, STUDENTS, now=NOW)


def coordinator_for(resource):
    students = [{"id": sid, "name": sid} for sid in STUDENTS]
    return SimpleNamespace(
        data={"students": students, PARENT_APPROVALS: resource},
        entry=SimpleNamespace(title="Account", options={}),
        last_update_success=True,
        data_stale=False,
        last_successful_update=None,
    )


async def test_parses_splits_per_child_and_bounds_answer_requests():
    get = router(
        [*TEST_MALFORMED_ACTIVITIES, TEST_OPEN_ACTIVITY, TEST_RECENT_EXPIRED_ACTIVITY, TEST_OLD_ACTIVITY],
        answers={
            OPEN_ID: [user_answer(TEST_CHILD_A, None), user_answer(TEST_CHILD_B, 1)],
            RECENT_ID: [user_answer(TEST_CHILD_A, 3, RECENT_ID)],
        },
    )
    result = await fetch(get)
    assert requested(get) == [
        ACTIVITIES_PATH,
        answers_path(OPEN_ID),
        answers_path(RECENT_ID),
        CONSENT_PATH,
        GENERAL_PATH,
    ]
    child_a = {r["activity_id"]: r for r in result["by_student"][TEST_CHILD_A]}
    child_b = {r["activity_id"]: r for r in result["by_student"][TEST_CHILD_B]}
    assert child_a[OPEN_ID]["status"] == STATUS_PENDING
    assert child_b[OPEN_ID]["status"] == ANSWER_STATUSES[1]
    assert child_a[RECENT_ID]["status"] == ANSWER_STATUSES[3]
    assert RECENT_ID not in child_b
    assert child_a[OPEN_ID]["type"] == "trip"
    assert child_a[RECENT_ID]["type"] == "culture_basket"
    assert child_a[OPEN_ID]["description"] == "Bring water"
    assert child_a[OPEN_ID]["answer_deadline"] == "2026-11-20T23:59:00+02:00"
    assert (child_a[OPEN_ID]["expired"], child_a[RECENT_ID]["expired"]) == (False, True)
    assert result["unassigned"] == []
    serialized = json.dumps(result)
    assert TEST_CREATOR_GUID not in serialized
    assert TEST_PARENT_GUID not in serialized


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (1, "approved"),
        (2, "approved_with_conditions"),
        (3, "denied"),
        (None, STATUS_PENDING),
        (..., STATUS_PENDING),
        (7, STATUS_UNKNOWN),
        ("1", STATUS_UNKNOWN),
        (True, STATUS_UNKNOWN),
    ],
)
async def test_answer_to_status_mapping_including_missing(answer, expected):
    get = router([TEST_OPEN_ACTIVITY], answers={OPEN_ID: [user_answer(TEST_CHILD_A, answer)]})
    result = await fetch(get)
    assert result["by_student"][TEST_CHILD_A][0]["status"] == expected
    assert answer_status(None if answer is ... else answer) == expected


async def test_expired_activities_are_never_counted_as_pending():
    get = router(
        [TEST_OPEN_ACTIVITY, TEST_RECENT_EXPIRED_ACTIVITY],
        answers={
            OPEN_ID: [user_answer(TEST_CHILD_A, None)],
            RECENT_ID: [user_answer(TEST_CHILD_A, None, RECENT_ID)],
        },
    )
    result = await fetch(get)
    assert [r["activity_id"] for r in open_pending(result["by_student"][TEST_CHILD_A])] == [OPEN_ID]


async def test_open_activity_without_a_known_child_is_unassigned_pending():
    unknown_child = [user_answer("someone-else", 1)]
    get = router(
        [TEST_OPEN_ACTIVITY, TEST_LATER_ACTIVITY, TEST_RECENT_EXPIRED_ACTIVITY], answers={OPEN_ID: unknown_child}
    )
    result = await fetch(get)
    assert result["by_student"] == {}
    # Expired, unattributed activities are dropped rather than reported as open.
    assert [(r["activity_id"], r["status"]) for r in result["unassigned"]] == [
        (OPEN_ID, STATUS_PENDING),
        (LATER_ID, STATUS_PENDING),
    ]


async def test_failed_answers_are_counted_and_do_not_block_other_activities():
    answered = {**TEST_LATER_ACTIVITY, "isAnswered": True}
    get = router(
        [TEST_OPEN_ACTIVITY, answered],
        answers={LATER_ID: [user_answer(TEST_CHILD_A, 1, LATER_ID)]},
        failures={answers_path(OPEN_ID): "forbidden"},
    )
    result = await fetch(get)
    assert result["answers_failures"] == 1
    assert [(r["activity_id"], r["status"]) for r in result["unassigned"]] == [(OPEN_ID, STATUS_PENDING)]
    assert result["by_student"][TEST_CHILD_A][0]["status"] == ANSWER_STATUSES[1]
    get = router([answered], failures={answers_path(LATER_ID): "fetch_failed"})
    assert (await fetch(get))["unassigned"][0]["status"] == STATUS_UNKNOWN


async def test_activity_list_failure_still_fetches_forms():
    get = router([], consent=[TEST_CONSENT_FORM], failures={ACTIVITIES_PATH: "forbidden"})
    result = await fetch(get)
    assert result["status"] == "forbidden"
    assert result["by_student"] == {}
    assert result["forms_status"] == {"consent": "ok", "general": "ok"}
    assert len(result["forms"]["consent"]) == 1


async def test_form_parsing_tolerates_invalid_form_data_and_skips_malformed():
    invalid = {**TEST_CONSENT_FORM, "formId": "form-x", "formData": TEST_INVALID_FORM_DATA}
    get = router(
        [],
        consent=[TEST_CONSENT_FORM, invalid, TEST_ANSWERED_FORM, TEST_EXPIRED_FORM, {"formData": "{}"}, "bad"],
        general=[{**TEST_CONSENT_FORM, "formData": None}],
    )
    result = await fetch(get)
    consent = result["forms"]["consent"]
    assert len(consent) == 4
    assert (consent[0]["title"], consent[0]["question_count"]) == (TEST_FORM_TITLE, 2)
    assert (consent[1]["title"], consent[1]["question_count"]) == (None, None)
    assert [f["question_count"] for f in open_forms(consent)] == [2, None]
    assert result["forms"]["general"][0]["question_count"] is None


async def test_sensors_state_and_attributes():
    get = router(
        [TEST_LATER_ACTIVITY, TEST_OPEN_ACTIVITY, {**TEST_OPEN_ACTIVITY, "id": 106}],
        answers={
            OPEN_ID: [user_answer(TEST_CHILD_A, None)],
            LATER_ID: [user_answer(TEST_CHILD_A, ..., LATER_ID), user_answer(TEST_CHILD_B, 2, LATER_ID)],
        },
        consent=[TEST_CONSENT_FORM, TEST_ANSWERED_FORM],
    )
    coordinator = coordinator_for(await fetch(get))
    child_a = MashovApprovalsSensor(coordinator, TEST_CHILD_A, "a", "A", "entry")
    child_b = MashovApprovalsSensor(coordinator, TEST_CHILD_B, "b", "B", "entry")
    attrs = child_a.extra_state_attributes
    assert child_a.native_value == 2
    assert child_b.native_value == 0
    assert [item["activity_id"] for item in attrs["pending"]] == [OPEN_ID, LATER_ID]
    assert attrs["next_deadline"] == attrs["pending"][0]["answer_deadline"]
    assert attrs["data_stale"] is False
    assert child_b.extra_state_attributes["next_deadline"] is None
    account = MashovOpenFormsSensor(coordinator, "entry")
    attrs = account.extra_state_attributes
    assert account.native_value == 2  # one open consent form + one unassigned activity (106)
    assert (attrs["consent_forms_count"], attrs["general_forms_count"], attrs["unassigned_activities_count"]) == (
        1,
        0,
        1,
    )
    assert attrs["unassigned_activities"][0]["activity_id"] == 106
    assert account.device_info["identifiers"] == {("mashov", f"{PARENT_APPROVALS}_entry")}
    assert account.unique_id == f"mashov_entry_{PARENT_APPROVALS}"
    assert child_a.unique_id == f"mashov_entry_{TEST_CHILD_A}_{PARENT_APPROVALS}"


def test_failed_source_is_unknown_not_zero():
    resource = {"status": "forbidden", "forms_status": {"consent": "forbidden", "general": "forbidden"}}
    coordinator = coordinator_for(resource)
    assert MashovApprovalsSensor(coordinator, TEST_CHILD_A, "a", "A", "entry").native_value is None
    account = MashovOpenFormsSensor(coordinator, "entry")
    assert account.native_value is None
    assert account.extra_state_attributes["data_stale"] is True


async def test_attributes_respect_the_storage_budget():
    many = [{**TEST_OPEN_ACTIVITY, "id": 1000 + index, "title": TEST_ACTIVITY_TITLE * 20} for index in range(200)]
    get = router(many, consent=[{**TEST_CONSENT_FORM, "formId": index} for index in range(200)])
    resource = await fetch(get)
    resource["by_student"] = {TEST_CHILD_A: resource["unassigned"]}
    coordinator = coordinator_for(resource)
    for sensor in (
        MashovApprovalsSensor(coordinator, TEST_CHILD_A, "a", "A", "entry"),
        MashovOpenFormsSensor(coordinator, "entry"),
    ):
        attrs = sensor.extra_state_attributes
        assert len(json_bytes(attrs)) <= ATTRIBUTE_BUDGET_BYTES
        assert attrs["truncated"] is True
    assert MashovApprovalsSensor(coordinator, TEST_CHILD_A, "a", "A", "entry").native_value == len(many)


def fake_portal(url, headers=None):
    """Every route the client may request, answered with synthetic data."""
    path = url.split("/api/", 1)[1]
    payloads = {
        ACTIVITIES_PATH: [TEST_OPEN_ACTIVITY],
        answers_path(OPEN_ID): [user_answer(TEST_CHILD_A, None)],
        CONSENT_PATH: [TEST_CONSENT_FORM],
    }
    return _response(200, payloads.get(path, {} if path.startswith("mail/counts") else []))


def portal_client(enabled):
    client = MashovClient("123", 2027, "test", "test", enabled_data=enabled)
    client._students = [{"id": sid, "slug": sid, "name": sid} for sid in STUDENTS]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = fake_portal
    return client


async def test_full_refresh_only_ever_issues_get_requests():
    client = portal_client(list(DATA_KEYS))
    result = await client.async_fetch_all()
    assert result[PARENT_APPROVALS]["by_student"][TEST_CHILD_A][0]["status"] == STATUS_PENDING
    assert {name.split(".")[0] for name, _args, _kwargs in client._session.method_calls} == {"get"}
    urls = [call.args[0] for call in client._session.get.call_args_list]
    assert any(url.endswith(answers_path(OPEN_ID)) for url in urls)


@pytest.mark.parametrize("selected", [None, {"homework"}])
async def test_feature_off_means_zero_approval_requests(selected):
    enabled = ["homework", "mailbox"] if selected is None else [*DATA_KEYS]
    client = portal_client(enabled)
    result = await client.async_fetch_all(selected_data=selected)
    assert PARENT_APPROVALS not in result
    urls = [call.args[0] for call in client._session.get.call_args_list]
    assert not any("schoolActivities" in url or "user/forms" in url for url in urls)


async def test_forbidden_activity_list_backs_off():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(403)
    assert await client._fetch_account_json(ACTIVITIES_PATH, PARENT_APPROVALS, list) == ("forbidden", None)
    assert await client._fetch_account_json(ACTIVITIES_PATH, PARENT_APPROVALS, list) == ("forbidden", None)
    assert client._session.get.call_count == 1


async def test_answers_back_off_per_activity_path():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = [_response(403), _response(200, []), _response(404), _response(404)]
    assert await client._fetch_account_json(answers_path(OPEN_ID), ANSWERS_KEY, list) == ("forbidden", None)
    assert await client._fetch_account_json(answers_path(LATER_ID), ANSWERS_KEY, list) == ("ok", [])
    # The forbidden activity is parked; it does not cost another request.
    assert await client._fetch_account_json(answers_path(OPEN_ID), ANSWERS_KEY, list) == ("forbidden", None)
    # A removed activity (404) is not parked and never blocks a sibling.
    assert await client._fetch_account_json(answers_path(RECENT_ID), ANSWERS_KEY, list) == ("unsupported", None)
    assert await client._fetch_account_json(answers_path(RECENT_ID), ANSWERS_KEY, list) == ("unsupported", None)
    assert client._session.get.call_count == 4


def test_disabling_purges_and_partial_refresh_preserves():
    data = {"students": [], "by_slug": {}, PARENT_APPROVALS: {"status": "ok", "by_student": {}}}
    assert PARENT_APPROVALS not in filter_cached_data(data, {"enabled_data": ["homework"]})
    assert PARENT_APPROVALS in filter_cached_data(data, {"enabled_data": [PARENT_APPROVALS]})
    merged = merge_partial_data(data, {"students": [], "by_slug": {}}, {"homework"})
    assert merged[PARENT_APPROVALS] == data[PARENT_APPROVALS]


async def test_assist_items_name_the_child_and_never_expose_ids(hass):
    _, coordinator, context = setup_api(hass)
    get = router(
        [TEST_OPEN_ACTIVITY, TEST_LATER_ACTIVITY],
        answers={OPEN_ID: [user_answer("child", None)]},
        consent=[TEST_CONSENT_FORM],
    )
    coordinator.data[PARENT_APPROVALS] = await fetch_parent_approvals(get, ["child"], now=NOW)
    request = llm.ToolInput(tool_name="mashov__read", tool_args={"dataset": PARENT_APPROVALS})
    result = unwrap(await MashovReadTool("account").async_call(hass, request, context))
    assert result["total"] == 3
    assert all(set(item) == {"title", "child", "deadline", "status"} for item in result["items"])
    assert [item["child"] for item in result["items"]] == ["Child", None, None]
    assert TEST_PARENT_GUID not in json.dumps(result)


async def test_diagnostics_export_route_statuses_only():
    get = router([TEST_OPEN_ACTIVITY], consent=[TEST_CONSENT_FORM], failures={GENERAL_PATH: "x"})
    coordinator = coordinator_for(await fetch(get))
    report = diagnostic_summary(coordinator)
    assert report["parent_approvals_status"] == {"status": "ok", "consent": "ok", "general": "other_error"}
    assert TEST_ACTIVITY_TITLE not in json.dumps(report)
