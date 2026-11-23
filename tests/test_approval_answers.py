"""Opt-in answering of school activities and the portal's list toggles."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
import voluptuous as vol

from custom_components.mashov import _require_admin_user
from custom_components.mashov.approval_service import ANSWER_SCHEMA, REFUSALS, REMARK_MAX_LENGTH, async_handle_answer
from custom_components.mashov.approvals import (
    ANSWER_CODES,
    ANSWER_PATH,
    ANSWERS_PATH,
    DETAIL_PATH,
    PARENT_APPROVALS,
    SCHOOL_TIME_ZONE,
    answer_body,
    answer_refusal,
    display_activities,
    fetch_parent_approvals,
)
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_selection import (
    CONF_ALLOW_APPROVAL_ANSWERS,
    CONF_APPROVALS_HIDE_ANSWERED,
    CONF_APPROVALS_NEWEST_FIRST,
    CONF_APPROVALS_SHOW_ENDED,
    CONF_ENABLED_DATA,
    approval_answers_enabled,
    mailbox_option_errors,
    merge_selection_options,
)
from custom_components.mashov.mashov_client import (
    MashovAnswerRefusedError,
    MashovClient,
    MashovError,
    MashovPasswordChangeRequiredError,
)
from custom_components.mashov.sensor import MashovApprovalsSensor

from .const import (
    TEST_ACTIVITY_QUESTIONS,
    TEST_ADMIN_USER_ID,
    TEST_AFTER_DEADLINE,
    TEST_ANSWERED_ACTIVITY,
    TEST_APPROVAL_REMARK,
    TEST_APPROVALS_NOW,
    TEST_CHILD_A,
    TEST_CHILD_A_SLUG,
    TEST_CHILD_B,
    TEST_CSRF_TOKEN,
    TEST_ENDED_ACTIVITY,
    TEST_ENTRY_ID,
    TEST_INVALID_ANSWER,
    TEST_LATER_ACTIVITY,
    TEST_OPEN_ACTIVITY,
    TEST_PARENT_GUID,
    TEST_UNKNOWN_ENTRY_ID,
    user_answer,
)
from .test_parent_approvals import coordinator_for, router
from .test_roster_change import _response

NOW = datetime.fromisoformat(TEST_APPROVALS_NOW).replace(tzinfo=SCHOOL_TIME_ZONE)
AFTER_DEADLINE = datetime.fromisoformat(TEST_AFTER_DEADLINE).replace(tzinfo=SCHOOL_TIME_ZONE)
OPEN_ID = TEST_OPEN_ACTIVITY["id"]
ANSWERS = [user_answer(TEST_CHILD_A, None)]
APPROVALS_ON = {CONF_ENABLED_DATA: [PARENT_APPROVALS], CONF_ALLOW_APPROVAL_ANSWERS: True}


# --- Pure rules -------------------------------------------------------------


def test_answer_codes_match_the_portal_form():
    assert ANSWER_CODES == {"approved": 1, "approved_with_conditions": 2, "denied": 3}


def test_answer_body_is_the_portal_request():
    body = answer_body(OPEN_ID, TEST_CHILD_A, TEST_PARENT_GUID, "denied", TEST_APPROVAL_REMARK)
    assert body == {
        "activityId": OPEN_ID,
        "studentGuid": TEST_CHILD_A,
        "userId": TEST_PARENT_GUID,
        "answer": 3,
        "remark": TEST_APPROVAL_REMARK,
    }


@pytest.mark.parametrize(
    ("detail", "answers", "now", "reason"),
    [
        ([TEST_OPEN_ACTIVITY], ANSWERS, NOW, None),
        ([{**TEST_OPEN_ACTIVITY, "activityData": ""}], ANSWERS, NOW, None),
        # The cached record says open; the deadline passed after the last refresh (B-28).
        ([TEST_OPEN_ACTIVITY], ANSWERS, AFTER_DEADLINE, "deadline_passed"),
        ([{**TEST_OPEN_ACTIVITY, "activityData": TEST_ACTIVITY_QUESTIONS}], ANSWERS, NOW, "has_questions"),
        ([{**TEST_OPEN_ACTIVITY, "activityData": {}}], ANSWERS, NOW, "has_questions"),
        ([], ANSWERS, NOW, "unknown_activity"),
        (["not a record"], ANSWERS, NOW, "unknown_activity"),
        ([TEST_LATER_ACTIVITY], ANSWERS, NOW, "unknown_activity"),
        ([{**TEST_OPEN_ACTIVITY, "endAnswerDate": None}], ANSWERS, NOW, "deadline_unknown"),
        ([{**TEST_OPEN_ACTIVITY, "endAnswerDate": TEST_INVALID_ANSWER}], ANSWERS, NOW, "deadline_unknown"),
        ([TEST_OPEN_ACTIVITY], [user_answer(TEST_CHILD_B, None)], NOW, "student_not_covered"),
    ],
)
def test_answer_refusal_uses_data_read_now(detail, answers, now, reason):
    assert answer_refusal(detail, answers, OPEN_ID, TEST_CHILD_A, now=now) == reason


async def test_display_toggles_follow_the_portal():
    get = router(
        [TEST_OPEN_ACTIVITY, TEST_LATER_ACTIVITY, TEST_ANSWERED_ACTIVITY, TEST_ENDED_ACTIVITY],
        answers={
            OPEN_ID: ANSWERS,
            TEST_LATER_ACTIVITY["id"]: [user_answer(TEST_CHILD_A, None, TEST_LATER_ACTIVITY["id"])],
            TEST_ANSWERED_ACTIVITY["id"]: [user_answer(TEST_CHILD_A, 1, TEST_ANSWERED_ACTIVITY["id"])],
            TEST_ENDED_ACTIVITY["id"]: [user_answer(TEST_CHILD_A, 2, TEST_ENDED_ACTIVITY["id"])],
        },
    )
    records = (await fetch_parent_approvals(get, [TEST_CHILD_A], now=NOW))["by_student"][TEST_CHILD_A]

    def ids(**toggles):
        return [r["activity_id"] for r in display_activities(records, now=NOW, **toggles)]

    defaults = {"show_ended": False, "hide_answered": False, "newest_first": False}
    assert ids(**defaults) == [OPEN_ID, TEST_LATER_ACTIVITY["id"], TEST_ANSWERED_ACTIVITY["id"]]
    assert TEST_ENDED_ACTIVITY["id"] in ids(**{**defaults, "show_ended": True})
    assert ids(**{**defaults, "hide_answered": True}) == [OPEN_ID, TEST_LATER_ACTIVITY["id"]]
    # Same start date: ties keep Mashov's order.
    assert ids(**{**defaults, "newest_first": True}) == [
        TEST_ANSWERED_ACTIVITY["id"],
        OPEN_ID,
        TEST_LATER_ACTIVITY["id"],
    ]


# --- Options ----------------------------------------------------------------


def test_answering_needs_parent_approvals():
    assert approval_answers_enabled(APPROVALS_ON)
    assert not approval_answers_enabled({**APPROVALS_ON, CONF_ENABLED_DATA: ["homework"]})
    assert not approval_answers_enabled({CONF_ENABLED_DATA: [PARENT_APPROVALS]})
    _, errors = mailbox_option_errors({CONF_ALLOW_APPROVAL_ANSWERS: True}, {CONF_ENABLED_DATA: ["homework"]})
    assert errors == {CONF_ALLOW_APPROVAL_ANSWERS: "approvals_required"}


def test_deselecting_approvals_revokes_answer_consent():
    merged = merge_selection_options(APPROVALS_ON, {CONF_ENABLED_DATA: ["homework"]})
    assert merged[CONF_ALLOW_APPROVAL_ANSWERS] is False
    assert CONF_ALLOW_APPROVAL_ANSWERS not in merge_selection_options({}, {CONF_ENABLED_DATA: ["homework"]})


def admin_check(user):
    hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=AsyncMock(return_value=user)))
    call = SimpleNamespace(context=SimpleNamespace(user_id=TEST_ADMIN_USER_ID if user else None))
    return _require_admin_user(hass, call, REFUSALS["unknown_activity"])


@pytest.mark.parametrize("user", [None, SimpleNamespace(is_admin=False)])
async def test_only_an_admin_user_can_allow_answering(user):
    with pytest.raises(ServiceValidationError):
        await admin_check(user)


async def test_an_admin_user_passes_the_check():
    await admin_check(SimpleNamespace(is_admin=True))


def test_options_form_resets_answering_when_approvals_are_removed():
    submitted, errors = mailbox_option_errors(
        {CONF_ENABLED_DATA: ["homework"], CONF_ALLOW_APPROVAL_ANSWERS: True}, APPROVALS_ON, reset_removed=True
    )
    assert errors == {}
    assert submitted[CONF_ALLOW_APPROVAL_ANSWERS] is False


# --- Client write -----------------------------------------------------------


def answer_client(detail, answers=ANSWERS, put_statuses=(200,), credential=True):
    client = MashovClient("123", 2027, "test", "test")
    client._headers = {"X-Csrf-Token": TEST_CSRF_TOKEN}
    client._auth_data = {"credential": {"userId": TEST_PARENT_GUID}} if credential else {}
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = [_response(200, detail), _response(200, answers)]
    client._session.put.side_effect = [_response(status) for status in put_statuses]
    client._ensure_valid_session = AsyncMock()
    return client


async def test_answer_rechecks_mashov_then_sends_the_portal_put():
    client = answer_client([TEST_OPEN_ACTIVITY])
    await client.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", TEST_APPROVAL_REMARK, NOW)
    gets = [call.args[0] for call in client._session.get.call_args_list]
    assert gets == [
        client._api_base + DETAIL_PATH.format(activity_id=OPEN_ID),
        client._api_base + ANSWERS_PATH.format(activity_id=OPEN_ID),
    ]
    put = client._session.put.call_args
    assert put.args[0] == client._api_base + ANSWER_PATH.format(activity_id=OPEN_ID, student_id=TEST_CHILD_A)
    assert put.kwargs["json"] == answer_body(OPEN_ID, TEST_CHILD_A, TEST_PARENT_GUID, "approved", TEST_APPROVAL_REMARK)
    assert put.kwargs["headers"]["X-Csrf-Token"] == TEST_CSRF_TOKEN


async def test_refused_or_unverifiable_answers_send_nothing():
    questions = answer_client([{**TEST_OPEN_ACTIVITY, "activityData": TEST_ACTIVITY_QUESTIONS}])
    with pytest.raises(MashovAnswerRefusedError) as refused:
        await questions.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", "", NOW)
    assert refused.value.reason == "has_questions"
    no_parent = answer_client([TEST_OPEN_ACTIVITY], credential=False)
    unverifiable = answer_client([TEST_OPEN_ACTIVITY])
    unverifiable._session.get.side_effect = [_response(500), _response(200, ANSWERS)]
    for client in (no_parent, unverifiable):
        with pytest.raises(MashovError):
            await client.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", "", NOW)
    for client in (questions, no_parent, unverifiable):
        client._session.put.assert_not_called()


async def test_answer_retries_once_after_401_and_reports_http_errors():
    client = answer_client([TEST_OPEN_ACTIVITY], put_statuses=(401, 200))
    await client.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", "", NOW)
    assert client._session.put.call_count == 2
    client._ensure_valid_session.assert_awaited_once()
    failing = answer_client([TEST_OPEN_ACTIVITY], put_statuses=(500,))
    with pytest.raises(MashovError) as failed:
        await failing.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", "", NOW)
    assert not isinstance(failed.value, MashovPasswordChangeRequiredError)


async def test_answer_reports_a_required_password_change():
    client = answer_client([TEST_OPEN_ACTIVITY], put_statuses=(403,))
    client._session.put.side_effect = None
    client._session.put.return_value = _response(403)
    client._session.put.return_value.__aenter__.return_value.headers = {"reason": "changepass"}
    with pytest.raises(MashovPasswordChangeRequiredError):
        await client.async_answer_school_activity(OPEN_ID, TEST_CHILD_A, "approved", "", NOW)


# --- Service ----------------------------------------------------------------


def service_hass(options, client=None, hubs=1):
    coordinator = SimpleNamespace(
        entry=SimpleNamespace(options=options),
        data={"students": [{"id": TEST_CHILD_A, "slug": TEST_CHILD_A_SLUG}]},
        async_refresh_datasets=AsyncMock(),
    )
    client = client or SimpleNamespace(async_answer_school_activity=AsyncMock())
    data = {f"{TEST_ENTRY_ID}{index}": {"coordinator": coordinator, "client": client} for index in range(hubs)}
    return SimpleNamespace(data={DOMAIN: data}), coordinator, client


def call(**overrides):
    return SimpleNamespace(
        data=ANSWER_SCHEMA({"activity_id": OPEN_ID, "student": TEST_CHILD_A_SLUG, "answer": "approved", **overrides})
    )


async def test_service_answers_then_refreshes_approvals():
    hass, coordinator, client = service_hass(APPROVALS_ON)
    await async_handle_answer(hass, call())
    client.async_answer_school_activity.assert_awaited_once_with(OPEN_ID, TEST_CHILD_A, "approved", "")
    coordinator.async_refresh_datasets.assert_awaited_once_with({PARENT_APPROVALS})


@pytest.mark.parametrize(
    ("options", "overrides", "hubs"),
    [
        ({CONF_ENABLED_DATA: [PARENT_APPROVALS]}, {}, 1),
        ({**APPROVALS_ON, CONF_ENABLED_DATA: ["homework"]}, {}, 1),
        (APPROVALS_ON, {"student": TEST_CHILD_B}, 1),
        (APPROVALS_ON, {}, 2),
        (APPROVALS_ON, {"entry_id": TEST_UNKNOWN_ENTRY_ID}, 1),
    ],
)
async def test_service_refuses_before_any_request(options, overrides, hubs):
    hass, _coordinator, client = service_hass(options, hubs=hubs)
    with pytest.raises(ServiceValidationError):
        await async_handle_answer(hass, call(**overrides))
    client.async_answer_school_activity.assert_not_called()


async def test_service_maps_client_errors():
    refused = SimpleNamespace(
        async_answer_school_activity=AsyncMock(side_effect=MashovAnswerRefusedError("deadline_passed"))
    )
    hass, coordinator, _client = service_hass(APPROVALS_ON, refused)
    with pytest.raises(ServiceValidationError, match=REFUSALS["deadline_passed"]):
        await async_handle_answer(hass, call())
    failed = SimpleNamespace(async_answer_school_activity=AsyncMock(side_effect=MashovError("HTTP 500")))
    hass, coordinator, _client = service_hass(APPROVALS_ON, failed)
    with pytest.raises(HomeAssistantError):
        await async_handle_answer(hass, call())
    coordinator.async_refresh_datasets.assert_not_called()


async def test_a_failed_refresh_after_a_sent_answer_is_not_an_error():
    hass, coordinator, client = service_hass(APPROVALS_ON)
    coordinator.async_refresh_datasets.side_effect = MashovError(REFUSALS["unknown_activity"])
    await async_handle_answer(hass, call())
    client.async_answer_school_activity.assert_awaited_once()


@pytest.mark.parametrize("activity_id", [True, OPEN_ID + 0.5])
def test_service_schema_rejects_inexact_activity_ids(activity_id):
    with pytest.raises(vol.Invalid):
        ANSWER_SCHEMA({"activity_id": activity_id, "student": TEST_CHILD_A, "answer": "approved"})


def test_service_schema_bounds_input():
    with pytest.raises(vol.Invalid):
        ANSWER_SCHEMA({"activity_id": OPEN_ID, "student": TEST_CHILD_A, "answer": TEST_INVALID_ANSWER})
    with pytest.raises(vol.Invalid):
        ANSWER_SCHEMA(
            {
                "activity_id": OPEN_ID,
                "student": TEST_CHILD_A,
                "answer": "approved",
                "remark": TEST_APPROVAL_REMARK * REMARK_MAX_LENGTH,
            }
        )


# --- Sensor -----------------------------------------------------------------


async def test_child_sensor_lists_activities_with_hub_toggles():
    get = router(
        [TEST_OPEN_ACTIVITY, TEST_ANSWERED_ACTIVITY],
        answers={
            OPEN_ID: ANSWERS,
            TEST_ANSWERED_ACTIVITY["id"]: [user_answer(TEST_CHILD_A, 1, TEST_ANSWERED_ACTIVITY["id"])],
        },
    )
    coordinator = coordinator_for(await fetch_parent_approvals(get, [TEST_CHILD_A], now=NOW))
    sensor = MashovApprovalsSensor(coordinator, TEST_CHILD_A, "a", "A", "entry")
    assert len(sensor.extra_state_attributes["activities"]) == 2
    assert sensor.native_value == 1
    coordinator.entry.options = {
        CONF_APPROVALS_HIDE_ANSWERED: True,
        CONF_APPROVALS_SHOW_ENDED: False,
        CONF_APPROVALS_NEWEST_FIRST: True,
    }
    assert [a["activity_id"] for a in sensor.extra_state_attributes["activities"]] == [OPEN_ID]
    assert "activities" in MashovApprovalsSensor._unrecorded_attributes


async def test_service_is_registered_and_automations_cannot_grant_writes(hass, mock_config_entry):
    from custom_components.mashov import async_setup

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_ENABLED_DATA: [PARENT_APPROVALS]})
    await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "answer_school_activity")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_options",
            {"entry_id": mock_config_entry.entry_id, CONF_ALLOW_APPROVAL_ANSWERS: True},
            blocking=True,
        )
    assert not mock_config_entry.options.get(CONF_ALLOW_APPROVAL_ANSWERS)
