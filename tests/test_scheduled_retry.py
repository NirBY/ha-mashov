"""A failed daily/weekly refresh is retried, and a run missed while HA was down is caught up.

Before, a refresh that failed at its daily time left the data stale until the same
time the next day (a week for weekly schedules), and an HA restart reset the stale
flag without refreshing, so dashboards showed old data as current.
"""

from datetime import datetime, timedelta
import time
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.mashov import SCHEDULED_RETRY_DELAYS, MashovCoordinator, _async_setup_scheduler, _last_slot
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.mashov_client import MashovError

from .test_setup_resilience import DATA, _patch_cache, _patch_client

DAILY = {"enabled_data": ["homework"], "schedule_type": "daily", "schedule_time": "14:00"}
DAILY_SLOT = {"schedule_type": "daily", "schedule_time": "14:00:00", "schedule_days": [0]}


def _coordinator(hass, entry, options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    coordinator = MashovCoordinator(hass, MagicMock(), entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}
    return coordinator


def _refreshes(coordinator, outcomes, keys=("homework",)):
    """A refresh stand-in recording each outcome ("ok", "fail" or "auth") on the coordinator."""
    pending = list(outcomes)

    async def refresh(*_args, **_kwargs):
        outcome = pending.pop(0)
        coordinator.auth_failed = outcome == "auth"
        coordinator.failed_datasets = set(keys) if outcome in ("fail", "auth") else set()

    return AsyncMock(side_effect=refresh)


async def _schedule(hass, entry, catch_up=False):
    """Set up the timers; return (daily timer callbacks, catch-up keys)."""
    with (
        patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()) as daily,
        patch("custom_components.mashov.async_track_time_interval", return_value=MagicMock()),
    ):
        caught_up = await _async_setup_scheduler(hass, entry, catch_up=catch_up)
    await hass.async_block_till_done(wait_background_tasks=True)
    return daily, caught_up


async def _advance(hass, seconds):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds + 1))
    await hass.async_block_till_done(wait_background_tasks=True)


def test_last_slot_for_daily_weekly_and_interval():
    tz = dt_util.get_time_zone("Asia/Jerusalem")
    saturday_1300 = datetime(2026, 11, 21, 13, 0, tzinfo=tz)
    assert _last_slot(DAILY_SLOT, saturday_1300) == datetime(2026, 11, 20, 14, 0, tzinfo=tz)
    assert _last_slot(DAILY_SLOT, saturday_1300.replace(hour=15)) == datetime(2026, 11, 21, 14, 0, tzinfo=tz)
    wednesdays = {"schedule_type": "weekly", "schedule_time": "14:00:00", "schedule_days": [2]}
    assert _last_slot(wednesdays, saturday_1300) == datetime(2026, 11, 18, 14, 0, tzinfo=tz)
    assert _last_slot({"schedule_type": "interval", "schedule_time": "14:00:00"}, saturday_1300) is None


async def test_failed_daily_run_is_retried_until_it_succeeds(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.async_refresh = _refreshes(coordinator, ["fail", "fail", "ok"])
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    assert coordinator.async_refresh.await_count == 1
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert coordinator.async_refresh.await_count == 2
    await _advance(hass, SCHEDULED_RETRY_DELAYS[1])
    assert coordinator.async_refresh.await_count == 3
    await _advance(hass, SCHEDULED_RETRY_DELAYS[2])
    assert coordinator.async_refresh.await_count == 3  # succeeded; nothing more until tomorrow
    await coordinator.async_shutdown()


async def test_retries_stop_after_the_last_delay(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.async_refresh = _refreshes(coordinator, ["fail"] * 10)
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    for delay in SCHEDULED_RETRY_DELAYS:
        await _advance(hass, delay)
    await _advance(hass, 2 * 3600)
    assert coordinator.async_refresh.await_count == 1 + len(SCHEDULED_RETRY_DELAYS)
    await coordinator.async_shutdown()


async def test_auth_failure_is_not_retried(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.async_refresh = _refreshes(coordinator, ["auth"])
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert coordinator.async_refresh.await_count == 1
    await coordinator.async_shutdown()


async def test_retry_is_skipped_when_data_was_refreshed_meanwhile(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.async_refresh = _refreshes(coordinator, ["fail"])
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    coordinator.failed_datasets.clear()  # e.g. a manual refresh_now succeeded
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert coordinator.async_refresh.await_count == 1
    await coordinator.async_shutdown()


async def test_unload_cancels_a_pending_retry(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.async_refresh = _refreshes(coordinator, ["fail", "ok"])
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    for unsubscribe in hass.data[DOMAIN][mock_config_entry.entry_id]["unsub_daily"]:
        unsubscribe()
    daily.return_value.assert_called_once()  # the daily timer itself is cancelled too
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert coordinator.async_refresh.await_count == 1
    await coordinator.async_shutdown()


async def test_weekly_timer_skips_other_days_but_retries_are_not_gated(hass, mock_config_entry):
    today = dt_util.now().weekday()
    other_day = (today + 1) % 7
    options = {**DAILY, "schedule_type": "weekly", "schedule_days": [other_day]}
    coordinator = _coordinator(hass, mock_config_entry, options)
    coordinator.async_refresh = _refreshes(coordinator, ["fail", "ok"])
    daily, _ = await _schedule(hass, mock_config_entry)

    await daily.call_args.args[1]()
    coordinator.async_refresh.assert_not_awaited()

    hass.config_entries.async_update_entry(mock_config_entry, options={**options, "schedule_days": [today]})
    daily, _ = await _schedule(hass, mock_config_entry)
    await daily.call_args.args[1]()
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert coordinator.async_refresh.await_count == 2
    await coordinator.async_shutdown()


async def test_failed_data_schedule_group_is_retried(hass, mock_config_entry):
    options = {
        "enabled_data": ["homework", "grades"],
        "schedule_time": "14:00",
        "data_schedules": {"grades": {"schedule_type": "daily", "schedule_time": "08:00"}},
    }
    coordinator = _coordinator(hass, mock_config_entry, options)
    calls = []

    async def refresh_datasets(keys, student_data=None):
        calls.append(tuple(keys))
        coordinator.failed_datasets = set(keys) if len(calls) == 1 else set()

    coordinator.async_refresh_datasets = refresh_datasets
    daily, _ = await _schedule(hass, mock_config_entry)

    grades_timer = next(call.args[1] for call in daily.call_args_list if call.kwargs["hour"] == 8)
    await grades_timer()
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert calls == [("grades",), ("grades",)]
    await coordinator.async_shutdown()


async def test_run_missed_since_the_cache_is_caught_up(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    slot = _last_slot(DAILY_SLOT, dt_util.now())
    coordinator.last_successful_update = slot.timestamp() - 3600
    coordinator.async_refresh = _refreshes(coordinator, ["ok"])

    _, caught_up = await _schedule(hass, mock_config_entry, catch_up=True)
    assert caught_up == {"homework"}
    coordinator.async_refresh.assert_awaited_once()
    await coordinator.async_shutdown()


async def test_no_catch_up_when_the_cache_is_newer_than_the_last_run(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.last_successful_update = _last_slot(DAILY_SLOT, dt_util.now()).timestamp() + 5
    coordinator.async_refresh = _refreshes(coordinator, ["ok"])

    _, caught_up = await _schedule(hass, mock_config_entry, catch_up=True)
    assert caught_up == set()
    coordinator.async_refresh.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_catch_up_after_a_failed_startup_refresh_waits_before_trying_again(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.last_successful_update = _last_slot(DAILY_SLOT, dt_util.now()).timestamp() - 3600
    coordinator.failed_datasets = {"homework"}  # the startup refresh just failed (network)
    coordinator.async_refresh = _refreshes(coordinator, ["ok"])

    await _schedule(hass, mock_config_entry, catch_up=True)
    coordinator.async_refresh.assert_not_awaited()
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    coordinator.async_refresh.assert_awaited_once()
    await coordinator.async_shutdown()


async def test_failed_refresh_at_reload_is_retried_even_after_todays_run(hass, mock_config_entry):
    """Today's run succeeded; a reload afterwards (new data or credentials) fails to refresh."""
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.last_successful_update = _last_slot(DAILY_SLOT, dt_util.now()).timestamp() + 60
    coordinator.failed_datasets = {"homework"}
    coordinator.async_refresh = _refreshes(coordinator, ["ok"])

    _, caught_up = await _schedule(hass, mock_config_entry, catch_up=True)
    assert caught_up == {"homework"}
    coordinator.async_refresh.assert_not_awaited()
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    coordinator.async_refresh.assert_awaited_once()
    await coordinator.async_shutdown()


async def test_catch_up_uses_each_schedules_own_last_refresh(hass, mock_config_entry):
    """Grades missed its 08:00 run; a later homework refresh must not hide that after a restart."""
    options = {
        "enabled_data": ["homework", "grades"],
        "schedule_time": "14:00",
        "data_schedules": {"grades": {"schedule_type": "daily", "schedule_time": "08:00"}},
    }
    coordinator = _coordinator(hass, mock_config_entry, options)
    now = dt_util.now()
    grades_slot = _last_slot({"schedule_type": "daily", "schedule_time": "08:00:00", "schedule_days": [0]}, now)
    latest_slot = max(grades_slot, _last_slot(DAILY_SLOT, now)).timestamp()
    coordinator.last_successful_update = latest_slot + 60
    coordinator.data = {"completed_at": {"homework": latest_slot + 60, "grades": grades_slot.timestamp() - 86400}}
    calls = []

    async def refresh_datasets(keys, student_data=None):
        calls.append(tuple(keys))

    coordinator.async_refresh_datasets = refresh_datasets
    _, caught_up = await _schedule(hass, mock_config_entry, catch_up=True)
    assert calls == [("grades",)]
    assert caught_up == {"grades"}
    await coordinator.async_shutdown()


async def test_refreshes_record_completion_per_data_type_and_child(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, {"enabled_data": ["homework", "grades", "picture"]})
    coordinator.client = MagicMock(auth_data={}, async_fetch_all=AsyncMock(return_value=DATA))
    coordinator.data = {**DATA, "completed_at": {"homework": 1.0}}
    coordinator.last_successful_update = 5.0
    with patch("custom_components.mashov.Store") as store_class:
        store_class.return_value.async_save = AsyncMock()
        await coordinator.async_refresh_datasets(["grades"])
        completed = coordinator.data["completed_at"]
        assert completed["homework"] == 1.0 and completed["grades"] > 5.0
        hub_refreshed_at = store_class.return_value.async_save.await_args.args[0]["last_refresh_ts"]
        assert hub_refreshed_at == completed["grades"]

        # A picture-only refresh (after a cached start) records the picture but keeps the hub's
        # refresh time on disk, which the interval-mode startup cooldown reads.
        await coordinator.async_refresh_datasets(["picture"])
        assert store_class.return_value.async_save.await_args.args[0]["last_refresh_ts"] == hub_refreshed_at
        assert coordinator.data["completed_at"]["picture"] >= hub_refreshed_at

        # A child's key accepts a refresh of that type for every child, or one for that child.
        assert coordinator.last_completed({("student-123", "homework")}) == 1.0
        await coordinator.async_refresh_datasets(["homework"], student_data={"student-123": {"homework"}})
        assert coordinator.last_completed({("student-123", "homework")}) > 5.0
        assert coordinator.last_completed({"homework", "grades"}) == 1.0  # the oldest of the keys
    await coordinator.async_shutdown()


async def test_no_catch_up_after_an_auth_failure(hass, mock_config_entry):
    coordinator = _coordinator(hass, mock_config_entry, DAILY)
    coordinator.last_successful_update = _last_slot(DAILY_SLOT, dt_util.now()).timestamp() - 3600
    coordinator.auth_failed = True
    coordinator.failed_datasets = {"homework"}
    coordinator.async_refresh = _refreshes(coordinator, ["ok"])

    _, caught_up = await _schedule(hass, mock_config_entry, catch_up=True)
    await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
    assert caught_up == set()
    coordinator.async_refresh.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_network_failure_at_the_daily_time_recovers_on_the_first_retry(hass: HomeAssistant):
    """End to end through the real coordinator: offline at 14:00, back 5 minutes later."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "school_id": "123456", "school_name": "Test School"},
        options={"schedule_type": "daily", "schedule_time": "14:00", "enabled_data": ["homework"]},
        title="Test School (123456)",
    )
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    client.async_fetch_all.side_effect = [MashovError("offline"), DATA]
    cache = {"data": {**DATA, "enabled_data": ["homework"]}, "last_refresh_ts": time.time(), "auth": {}}
    try:
        with (
            _patch_cache(cache),
            patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()) as daily,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            client.async_fetch_all.assert_not_awaited()

            await daily.call_args.args[1]()
            assert client.async_fetch_all.await_count == 1
            assert coordinator.data_stale and not coordinator.last_update_success

            await _advance(hass, SCHEDULED_RETRY_DELAYS[0])
            assert client.async_fetch_all.await_count == 2
            assert not coordinator.data_stale and coordinator.last_update_success
            assert not coordinator.failed_datasets
            await hass.config_entries.async_unload(entry.entry_id)
    finally:
        patcher.stop()


async def test_restart_after_a_missed_run_refreshes_everything_once(hass: HomeAssistant):
    """A stale cache at startup gets one full refresh, which also covers the pictures."""
    selection = ["homework", "picture"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "school_id": "123456", "school_name": "Test School"},
        options={"schedule_type": "daily", "schedule_time": "14:00", "enabled_data": selection},
        title="Test School (123456)",
    )
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    client.pictures = {}
    try:
        cache = {
            "data": {**DATA, "enabled_data": selection},
            "last_refresh_ts": time.time() - 2 * 86400,
            "auth": {},
        }
        with _patch_cache(cache):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done(wait_background_tasks=True)
    finally:
        patcher.stop()
    assert entry.state is ConfigEntryState.LOADED
    assert [call.kwargs.get("selected_data") for call in client.async_fetch_all.await_args_list] == [None]
    await hass.config_entries.async_unload(entry.entry_id)
