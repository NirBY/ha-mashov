"""Opt-in refresh when Mashov lists a new notification.

A hub that opts in reads its seven newest notifications every few minutes (read only)
and refreshes only the data types that new ones are about. Covers the client call
(never marks anything read, renews an expired session once, never logs in again for a
list the session may not read), change detection (first check, read state, restarts,
a full list of new items), pauses after errors, the scheduler/options/service wiring,
and that notification text never reaches the log or the disk.
"""

import asyncio
from datetime import timedelta
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed
import voluptuous as vol

from custom_components.mashov import MashovCoordinator, _async_setup_scheduler, async_remove_entry, async_setup
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_selection import DATA_KEYS
from custom_components.mashov.mashov_client import (
    MashovAuthError,
    MashovClient,
    MashovError,
    MashovNotificationsUnavailable,
    MashovPasswordChangeRequiredError,
)
from custom_components.mashov.notifications import (
    EVENT_DATA_TYPES,
    NOTIFICATION_TAKE,
    NotificationWatcher,
    data_types_for,
    notification_digest,
    notification_interval,
)

SECRET_TEXT = "synthetic-notification-text-never-logged"
HOMEWORK, GRADE, TEXT = 102, 111, 1


def _note(nid: int, event_type: int = HOMEWORK, **extra) -> dict:
    """A notification shaped like Mashov's user/notifications items (synthetic values)."""
    return {
        "id": nid,
        "userId": "parent-guid",
        "appName": "students",
        "eventTime": f"2026-11-24T10:{nid:02d}:00",
        "eventType": event_type,
        "eventText": f"{SECRET_TEXT} {nid}",
        "eventKey": str(nid),
        "eventData": "{}",
        "eventUserId": "student-guid",
        "addTime": f"2026-11-24T10:{nid:02d}:00",
        **extra,
    }


def _unread(count: int, minute: int) -> dict:
    """Mashov's generated "unread conversations" entry: id 0, stamped with the request time."""
    return {
        "id": 0,
        "eventType": 16,
        "eventTime": f"2026-11-25T01:{minute:02d}:00+02:00",
        "eventText": f"{SECRET_TEXT} {count}",
        "readTime": f"2026-11-25T01:{minute:02d}:00+02:00",
    }


def _store_key(entry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.notifications"


# --- Client ---------------------------------------------------------------------------


def _response(status: int, payload=None, headers=None, text: str = ""):
    response = MagicMock(status=status, headers=headers or {})
    response.text = AsyncMock(return_value=text)
    response.json = AsyncMock(return_value=payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def _client(*responses) -> MashovClient:
    client = MashovClient("123", 2027, "test", "test")
    client._students = [{"id": "student-guid", "slug": "a", "name": "Example A"}]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._session = MagicMock(closed=False)
    client._session.get.side_effect = list(responses)
    client._ensure_valid_session = AsyncMock()
    return client


async def test_client_lists_notifications_without_marking_them_read():
    client = _client(_response(200, [_note(1), "not-a-notification"]))

    assert await client.async_fetch_notifications(7) == [_note(1)]
    assert client._session.get.call_args.args[0] == "https://web.mashov.info/api/user/notifications?skip=0&take=7"
    client._session.put.assert_not_called()
    client._session.post.assert_not_called()
    client._ensure_valid_session.assert_not_awaited()


async def test_client_renews_an_expired_session_once():
    client = _client(_response(401), _response(200, []))

    assert await client.async_fetch_notifications(7) == []
    client._ensure_valid_session.assert_awaited_once()


async def test_client_does_not_log_in_again_for_a_list_the_session_may_not_read():
    """A renewed session that still gets 401 (as loginDevice sessions get on user/devices)."""
    client = _client(_response(401), _response(401))

    with pytest.raises(MashovNotificationsUnavailable):
        await client.async_fetch_notifications(7)
    client._ensure_valid_session.assert_awaited_once()
    assert client._session.get.call_count == 2


@pytest.mark.parametrize("status", [403, 404])
async def test_client_reports_a_refused_list(status):
    client = _client(_response(status))

    with pytest.raises(MashovNotificationsUnavailable):
        await client.async_fetch_notifications(7)
    client._ensure_valid_session.assert_not_awaited()


async def test_client_reports_a_required_password_change():
    client = _client(_response(403, headers={"reason": "ChangePass"}))

    with pytest.raises(MashovPasswordChangeRequiredError):
        await client.async_fetch_notifications(7)


@pytest.mark.parametrize(
    "response",
    [_response(500), _response(200, {"not": "a list"}), aiohttp.ClientConnectionError("offline")],
    ids=["server-error", "unexpected-json", "network"],
)
async def test_client_reports_other_failures_as_temporary(response):
    client = _client(response)

    with pytest.raises(MashovError) as err:
        await client.async_fetch_notifications(7)
    assert not isinstance(err.value, (MashovNotificationsUnavailable, MashovAuthError))


async def test_client_logs_in_lazily_after_a_cached_start():
    client = _client(_response(200, []))
    client._headers.pop("X-Csrf-Token")
    client.async_init = AsyncMock(side_effect=lambda _hass: client._headers.update({"X-Csrf-Token": "fresh"}))

    await client.async_fetch_notifications(7)
    client.async_init.assert_awaited_once()
    assert client._session.get.call_args.kwargs["headers"]["X-Csrf-Token"] == "fresh"


# --- Change detection ------------------------------------------------------------------


def test_event_types_map_only_to_data_the_hub_fetches():
    assert all(set(keys) <= set(DATA_KEYS) for keys in EVENT_DATA_TYPES.values())
    assert data_types_for({"eventType": "102"}) == {"homework", "lessons_history"}
    assert data_types_for({"eventType": TEXT}) == set()
    assert data_types_for({"eventType": None}) == set()


def test_digest_ignores_the_read_state_but_not_a_changed_notification():
    note = _note(1)
    assert notification_digest(note) == notification_digest({**note, "readTime": "2026-11-24T11:00:00"})
    assert notification_digest(note) != notification_digest({**note, "eventTime": "2026-11-24T12:00:00"})
    assert SECRET_TEXT not in notification_digest(note)


def test_generated_entries_are_identified_by_content_not_request_time():
    assert notification_digest(_unread(3, 47)) == notification_digest(_unread(3, 52))
    assert notification_digest(_unread(3, 47)) != notification_digest(_unread(4, 47))


def test_interval_is_clamped_to_the_allowed_range():
    assert notification_interval({}) == 15
    assert notification_interval({"notification_interval": 1}) == 5
    assert notification_interval({"notification_interval": "90"}) == 60
    assert notification_interval({"notification_interval": "soon"}) == 15


def _watcher(hass, entry, options, lists, *, mock_refresh=True):
    """A watcher over a real coordinator whose client returns ``lists`` in order."""
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    coordinator = MashovCoordinator(hass, MagicMock(), entry)
    coordinator.client.async_fetch_notifications = AsyncMock(side_effect=list(lists))
    if mock_refresh:
        coordinator.async_refresh_datasets = AsyncMock()
    return NotificationWatcher(hass, entry, coordinator), coordinator


ENABLED = {"enabled_data": ["homework", "grades", "behavior", "mailbox", "message_board"]}


async def test_first_check_only_records_the_list(hass, mock_config_entry, hass_storage):
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [[_note(2), _note(1)]])

    await watcher.async_check()
    coordinator.async_refresh_datasets.assert_not_awaited()
    stored = hass_storage[_store_key(mock_config_entry)]["data"]
    assert stored == {"seen": [notification_digest(_note(2)), notification_digest(_note(1))]}
    assert SECRET_TEXT not in json.dumps(hass_storage[_store_key(mock_config_entry)])


async def test_a_new_notification_refreshes_only_its_enabled_data_types(hass, mock_config_entry):
    lists = [[_note(1, GRADE)], [_note(2), _note(1, GRADE)], [_note(2), _note(1, GRADE)]]
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, lists)

    for _ in lists:
        await watcher.async_check()
    # Homework also concerns lessons_history, which this hub does not fetch.
    coordinator.async_refresh_datasets.assert_awaited_once_with({"homework"})
    coordinator.client.async_fetch_notifications.assert_awaited_with(NOTIFICATION_TAKE)


async def test_reading_a_notification_in_the_app_is_not_a_change(hass, mock_config_entry):
    lists = [[_note(1)], [_note(1, readTime="2026-11-24T11:00:00")]]
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, lists)

    for _ in lists:
        await watcher.async_check()
    coordinator.async_refresh_datasets.assert_not_awaited()


async def test_a_generated_entry_refreshes_only_when_its_content_changes(hass, mock_config_entry):
    """Seen live: Mashov restamps "unread conversations" on every request."""
    lists = [[_unread(3, 47), _note(1)], [_unread(3, 52), _note(1)], [_unread(4, 57), _note(1)]]
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, lists)

    for _ in lists:
        await watcher.async_check()
    coordinator.async_refresh_datasets.assert_awaited_once_with({"mailbox"})


async def test_notifications_about_data_the_hub_does_not_fetch_are_ignored(hass, mock_config_entry):
    lists = [[_note(1)], [_note(3, TEXT), _note(2, GRADE), _note(1)]]
    watcher, coordinator = _watcher(hass, mock_config_entry, {"enabled_data": ["homework"]}, lists)

    for _ in lists:
        await watcher.async_check()
    coordinator.async_refresh_datasets.assert_not_awaited()


async def test_a_full_list_of_new_notifications_refreshes_every_notified_type(hass, mock_config_entry):
    """Older notifications may have scrolled past unseen, whatever their type."""
    full = [_note(nid, TEXT) for nid in range(20, 20 + NOTIFICATION_TAKE)]
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [[_note(1)], full])

    await watcher.async_check()
    await watcher.async_check()
    # The noticeboard has no notifications, so it stays with its schedule.
    coordinator.async_refresh_datasets.assert_awaited_once_with({"homework", "grades", "behavior", "mailbox"})


async def test_a_restart_remembers_what_was_seen_and_catches_up(hass, mock_config_entry):
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [[_note(1, GRADE)]])
    await watcher.async_check()

    # Home Assistant restarts; a homework notification arrived while it was down.
    coordinator.client.async_fetch_notifications = AsyncMock(return_value=[_note(2), _note(1, GRADE)])
    restarted = NotificationWatcher(hass, mock_config_entry, coordinator)
    await restarted.async_check()
    coordinator.async_refresh_datasets.assert_awaited_once_with({"homework"})


async def test_a_refused_list_stops_the_checks_until_reload(hass, mock_config_entry, caplog):
    refused = MashovNotificationsUnavailable("Mashov refused the notification list (HTTP 403)")
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [refused, [_note(1)]])

    await watcher.async_check()
    await watcher.async_check()
    assert coordinator.client.async_fetch_notifications.await_count == 1
    assert "until the hub reloads" in caplog.text


async def test_a_rejected_login_pauses_checks_until_a_refresh_succeeds(hass, mock_config_entry):
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [MashovAuthError("rejected"), [_note(1)]])
    coordinator.last_successful_update = 100.0
    fetch = coordinator.client.async_fetch_notifications

    await watcher.async_check()
    await watcher.async_check()  # paused: no second login attempt
    assert fetch.await_count == 1
    coordinator.last_successful_update = 200.0  # a scheduled refresh succeeded
    await watcher.async_check()
    assert fetch.await_count == 2


async def test_no_checks_while_refreshes_are_refused_for_credentials(hass, mock_config_entry):
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [[_note(1)]])
    coordinator.auth_failed = True

    await watcher.async_check()
    coordinator.client.async_fetch_notifications.assert_not_awaited()


async def test_a_temporary_failure_is_tried_again_at_the_next_check(hass, mock_config_entry):
    lists = [MashovError("HTTP 500"), [_note(1)], [_note(2), _note(1)]]
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, lists)

    for _ in lists:
        await watcher.async_check()
    assert coordinator.client.async_fetch_notifications.await_count == 3
    coordinator.async_refresh_datasets.assert_awaited_once_with({"homework"})


async def test_notification_text_never_reaches_the_log(hass, mock_config_entry, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.mashov")
    watcher, coordinator = _watcher(hass, mock_config_entry, ENABLED, [[_note(1)], [_note(2), _note(1)]])

    await watcher.async_check()
    await watcher.async_check()
    assert "New Mashov notifications" in caplog.text
    assert SECRET_TEXT not in caplog.text


async def test_the_triggered_refresh_queues_after_the_check(hass, mock_config_entry):
    """The check holds the shared refresh queue; the refresh it starts must not deadlock on it."""
    lists = [[_note(1)], [_note(2), _note(1)]]
    watcher, coordinator = _watcher(hass, mock_config_entry, {"enabled_data": ["homework"]}, lists, mock_refresh=False)
    coordinator._async_fetch_data = AsyncMock(return_value={"students": []})

    await watcher.async_check()
    await asyncio.wait_for(watcher.async_check(), timeout=5)
    coordinator._async_fetch_data.assert_awaited_once_with({"homework"}, student_data=None)
    await coordinator.async_shutdown()


# --- Wiring ----------------------------------------------------------------------------


def _loaded(hass, entry, options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    coordinator = MashovCoordinator(hass, MagicMock(), entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}
    return coordinator


async def test_checks_start_only_when_enabled_and_survive_a_reschedule(hass, mock_config_entry):
    _loaded(hass, mock_config_entry, {"schedule_type": "daily"})
    with (
        patch("custom_components.mashov.notifications.async_track_time_interval") as timer,
        patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()),
    ):
        await _async_setup_scheduler(hass, mock_config_entry)
        timer.assert_not_called()

        hass.config_entries.async_update_entry(
            mock_config_entry,
            options={"schedule_type": "daily", "notification_refresh": True, "notification_interval": 7},
        )
        await _async_setup_scheduler(hass, mock_config_entry)
        assert timer.call_args.args[2] == timedelta(minutes=7)
        watcher = hass.data[DOMAIN][mock_config_entry.entry_id]["notification_watcher"]

        first_timer = timer.return_value
        await _async_setup_scheduler(hass, mock_config_entry)
        first_timer.assert_called_once()  # the old timer was cancelled
        assert hass.data[DOMAIN][mock_config_entry.entry_id]["notification_watcher"] is watcher


async def test_checks_run_at_the_configured_interval(hass, mock_config_entry):
    coordinator = _loaded(hass, mock_config_entry, {"notification_refresh": True, "notification_interval": 5})
    coordinator.client.async_fetch_notifications = AsyncMock(return_value=[])
    with patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()):
        await _async_setup_scheduler(hass, mock_config_entry)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5, seconds=1))
    await hass.async_block_till_done()
    coordinator.client.async_fetch_notifications.assert_awaited_once_with(NOTIFICATION_TAKE)
    for unsub in hass.data[DOMAIN][mock_config_entry.entry_id]["unsub_daily"]:
        unsub()
    await coordinator.async_shutdown()


async def test_options_form_saves_the_notification_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    form = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    refresh = next(value for key, value in form["data_schema"].schema.items() if str(key) == "refresh")
    defaults = {str(key): key.default() for key in refresh.schema.schema if str(key).startswith("notification")}
    assert defaults == {"notification_refresh": False, "notification_interval": 15}

    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"refresh": {"notification_refresh": True, "notification_interval": 10}}
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.options["notification_refresh"] is True
    assert mock_config_entry.options["notification_interval"] == 10


async def test_inline_schedule_editor_keeps_the_notification_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})["inline_schedule_editor"] = True
    form = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    refresh = next(value for key, value in form["data_schema"].schema.items() if str(key) == "refresh")
    assert {str(key) for key in refresh.schema.schema} == {
        "schedule_editor",
        "notification_refresh",
        "notification_interval",
    }


async def test_set_options_service_accepts_the_notification_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    await async_setup(hass, {})

    await hass.services.async_call(
        DOMAIN,
        "set_options",
        {"entry_id": mock_config_entry.entry_id, "notification_refresh": True, "notification_interval": 30},
        blocking=True,
    )
    assert mock_config_entry.options["notification_refresh"] is True
    assert mock_config_entry.options["notification_interval"] == 30
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_options", {"entry_id": mock_config_entry.entry_id, "notification_interval": 2}, blocking=True
        )


async def test_removing_the_hub_removes_its_notification_digests(hass, mock_config_entry, hass_storage):
    mock_config_entry.add_to_hass(hass)
    hass_storage[_store_key(mock_config_entry)] = {
        "version": 1,
        "minor_version": 1,
        "key": _store_key(mock_config_entry),
        "data": {"seen": ["0123456789abcdef"]},
    }

    await async_remove_entry(hass, mock_config_entry)
    assert _store_key(mock_config_entry) not in hass_storage
