"""Mailbox opt-in, read side effects, failure isolation, privacy and storage bounds."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.recorder.db_schema import StateAttributes
from homeassistant.setup import async_setup_component
import pytest

from custom_components.mashov.mailbox import fetch_mailbox, plain_body
from custom_components.mashov.mashov_client import MashovClient, MashovPasswordChangeRequiredError
from custom_components.mashov.reporting import diagnostic_summary
from custom_components.mashov.sensor import MashovMailboxSensor

from .test_roster_change import _response

CID = "11111111-2222-3333-4444-555555555555"
CID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MESSAGE = {"messageId": "m1", "senderName": "Private sender", "subject": "Private subject", "isNew": True}
INBOX = [{"conversationId": CID, "subject": "Private subject", "isNew": True, "messages": [MESSAGE]}]


def getter():
    read = False

    async def get(path, key, expected):
        nonlocal read
        if key == "mail_counts":
            return "ok", {"unreadConversations": 0 if read else 1, "inboxConversations": 23}
        if key == "mailbox":
            # Even an unexpected body in a list response must not be exposed.
            return "ok", deepcopy([{**INBOX[0], "messages": [{**MESSAGE, "body": "should be removed"}]}])
        read = True
        return "ok", {
            "conversationId": CID,
            "messages": [
                {**MESSAGE, "body": "<p>Full message</p><p>Second line</p>", "recipients": ["Private recipient"]}
            ],
        }

    return AsyncMock(side_effect=get)


async def test_headers_never_fetch_bodies_or_change_unread_count():
    get = getter()
    result = await fetch_mailbox(get)
    assert result["unread_count"] == 1
    assert result["inbox_count"] == 23
    assert "body" not in result["items"][0]["messages"][0]
    assert [call.args[0] for call in get.await_args_list] == ["mail/counts", "mail/inbox/conversations?skip=0&take=20"]


async def test_full_content_is_explicit_and_updates_unread_count_after_get():
    get = getter()
    result = await fetch_mailbox(get, full_content=True, limit=1)
    assert result["unread_before_fetch"] == 1
    assert result["unread_count"] == 0
    item = result["items"][0]
    assert item["content_status"] == "ok"
    assert not item["isNew"]
    assert item["messages"][0]["body"] == "Full message\nSecond line"
    assert "recipients" not in item["messages"][0]
    assert [call.args[0] for call in get.await_args_list] == [
        "mail/counts",
        "mail/inbox/conversations?skip=0&take=1",
        f"mail/conversations/{CID}",
        "mail/counts",
    ]


@pytest.mark.parametrize("failure", ["forbidden", "unsupported", "unauthorized", "invalid_response", "http_500"])
async def test_content_failures_keep_headers_and_have_explicit_status(failure):
    get = AsyncMock(
        side_effect=[("ok", {"unreadConversations": 1}), ("ok", INBOX), (failure, None), ("fetch_failed", None)]
    )
    result = await fetch_mailbox(get, full_content=True)
    assert result["status"] == "ok"
    assert result["items"][0]["content_status"] == failure
    assert "body" not in result["items"][0]["messages"][0]
    assert result["unread_count"] is None
    assert result["counts_status"] == "fetch_failed"


@pytest.mark.parametrize("payload", [["not a record"], [{"conversationId": "../../logout", "messages": []}]])
async def test_invalid_list_cannot_trigger_detail_requests(payload):
    get = AsyncMock(side_effect=[("ok", {}), ("ok", payload), ("ok", {})])
    result = await fetch_mailbox(get, full_content=True)
    assert result["status"] == "invalid_response"
    assert not any(call.args[1] == "mail_content" for call in get.await_args_list)


async def test_mismatched_detail_does_not_attach_another_conversations_body():
    get = AsyncMock(
        side_effect=[
            ("ok", {}),
            ("ok", INBOX),
            ("ok", {"conversationId": CID2, "messages": [{**MESSAGE, "body": "wrong account"}]}),
            ("ok", {}),
        ]
    )
    result = await fetch_mailbox(get, full_content=True)
    assert result["items"][0]["content_status"] == "invalid_response"
    assert "wrong account" not in json.dumps(result)


async def test_limit_bounds_full_content_requests_even_if_server_ignores_take():
    inbox = [*INBOX, {**INBOX[0], "conversationId": CID2}]
    get = AsyncMock(side_effect=[("ok", {}), ("ok", inbox), ("forbidden", None), ("ok", {})])
    result = await fetch_mailbox(get, full_content=True, limit=1)
    assert len(result["items"]) == 1
    assert len([c for c in get.await_args_list if c.args[1] == "mail_content"]) == 1


def test_html_is_plain_text_and_does_not_load_active_content():
    assert (
        plain_body(
            '<p>שלום &amp; תודה</p><script>secret()</script><style>.x{}</style><img src="https://tracker.invalid">סוף'
        )
        == "שלום & תודה\nסוף"
    )


async def test_mailbox_fetched_once_for_account_and_never_for_each_child():
    client = MashovClient("123", 2027, "test", "test", enabled_data=["mailbox"])
    client._students = [{"id": "a", "slug": "a", "name": "A"}, {"id": "b", "slug": "b", "name": "B"}]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._fetch_account_json = getter()
    result = await client.async_fetch_all()
    assert result["mailbox"]["unread_count"] == 1
    assert client._fetch_account_json.await_count == 2
    client._session.get.assert_not_called()


@pytest.mark.parametrize(
    "status,expected", [(403, "forbidden"), (404, "unsupported"), (500, "http_500"), (401, "unauthorized")]
)
async def test_account_api_status_and_retry(status, expected):
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(status)
    client._ensure_valid_session = AsyncMock()
    assert await client._fetch_account_json("mail/counts", "mail_counts", dict) == (expected, None)
    assert client._session.get.call_count == (2 if status == 401 else 1)
    if status in (403, 404):
        await client._fetch_account_json("mail/counts", "mail_counts", dict)
        assert client._session.get.call_count == 1
    client._session.post.assert_not_called()
    client._session.put.assert_not_called()


async def test_detail_404_does_not_back_off_other_conversations():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(404)
    await client._fetch_account_json(f"mail/conversations/{CID}", "mail_content", dict)
    await client._fetch_account_json(f"mail/conversations/{CID2}", "mail_content", dict)
    assert client._session.get.call_count == 2


async def test_detail_permission_failure_is_scoped_to_one_conversation():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = [_response(403), _response(200, {"conversationId": CID2})]
    assert await client._fetch_account_json(f"mail/conversations/{CID}", "mail_content", dict) == ("forbidden", None)
    assert await client._fetch_account_json(f"mail/conversations/{CID2}", "mail_content", dict) == (
        "ok",
        {"conversationId": CID2},
    )
    assert await client._fetch_account_json(f"mail/conversations/{CID}", "mail_content", dict) == ("forbidden", None)
    assert client._session.get.call_count == 2


async def test_account_password_change_is_not_hidden():
    client = MashovClient("123", 2027, "test", "test")
    response = _response(403)
    response.__aenter__.return_value.headers = {"reason": "ChangePass"}
    client._session = MagicMock(closed=False)
    client._session.get.return_value = response
    with pytest.raises(MashovPasswordChangeRequiredError):
        await client._fetch_account_json("mail/counts", "mail_counts", dict)


def test_long_mailbox_body_is_bounded_with_visible_truncation_and_safe_diagnostics():
    data = {
        "mailbox": {
            "status": "ok",
            "counts_status": "ok",
            "unread_count": 2,
            "full_content": True,
            "items": [{**INBOX[0], "messages": [{**MESSAGE, "body": "תוכן פרטי" * 8000}]}],
        }
    }
    coordinator = SimpleNamespace(
        data=data, entry=SimpleNamespace(title="Test", options={}), last_update_success=True, data_stale=False
    )
    sensor = MashovMailboxSensor(coordinator, "entry")
    attrs = sensor.extra_state_attributes
    assert sensor.native_value == 2
    assert len(json.dumps(attrs, ensure_ascii=False).encode()) < 16384
    assert attrs["items"][0]["conversationId"] == CID
    assert attrs["items"][0]["messages"][0]["body_truncated"] is True
    assert attrs["content_truncated"] is True
    assert len(data["mailbox"]["items"][0]["messages"][0]["body"]) > 60000
    report = json.dumps(diagnostic_summary(coordinator))
    assert "Private sender" not in report
    assert CID not in report
    assert "mailbox_status" in report


async def test_closed_account_session_is_an_operational_failure():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=True)
    client._session.get.side_effect = RuntimeError("Session is closed")
    assert await client._fetch_account_json("mail/counts", "mail_counts", dict) == ("fetch_failed", None)


async def test_unrelated_account_runtime_error_remains_reportable():
    client = MashovClient("123", 2027, "test", "test")
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = RuntimeError("Synthetic programming error")
    with pytest.raises(RuntimeError, match="Synthetic programming error"):
        await client._fetch_account_json("mail/counts", "mail_counts", dict)


async def test_recorder_excludes_mailbox_content_but_live_state_keeps_it(hass):
    """Exercise entity registration and Recorder's real event serializer."""
    coordinator = MagicMock()
    coordinator.entry = SimpleNamespace(title="Test", options={})
    coordinator.data = {
        "mailbox": {
            "status": "ok",
            "counts_status": "ok",
            "unread_count": 1,
            "full_content": True,
            "items": [{**INBOX[0], "messages": [{**MESSAGE, "body": "Private body"}]}],
        }
    }
    coordinator.data_stale = False
    coordinator.last_successful_update = None
    coordinator.last_update_success = True
    sensor = MashovMailboxSensor(coordinator, "entry")
    sensor.entity_id = "sensor.test_mailbox"
    events = []
    hass.bus.async_listen("state_changed", events.append)
    assert await async_setup_component(hass, "sensor", {})
    await hass.data["sensor"].async_add_entities([sensor])
    await hass.async_block_till_done()
    state = hass.states.get(sensor.entity_id)
    assert state.state == "1"
    assert state.attributes["items"][0]["messages"][0]["body"] == "Private body"
    event = next(event for event in events if event.data["entity_id"] == sensor.entity_id)
    recorded = json.loads(StateAttributes.shared_attrs_bytes_from_event(event, None))
    assert "items" not in recorded
    assert recorded["counts_status"] == "ok"
    assert recorded["inbox_count"] is None
    assert "Private" not in json.dumps(recorded)
