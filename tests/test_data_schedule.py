"""Real HA flow navigation and selective timers must preserve independent datasets."""

import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.helpers.http import current_request
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.mashov import SET_OPTIONS_SCHEMA, MashovCoordinator, _async_setup_scheduler
from custom_components.mashov.calendar import MashovHolidaysCalendar
from custom_components.mashov.config_flow import OptionsFlowHandler
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_schedule import effective_schedule, merge_partial_data, schedule_groups
from custom_components.mashov.data_selection import DATA_KEYS, LEGACY_CORE_DATA
from custom_components.mashov.mashov_client import MashovClient, MashovError
from custom_components.mashov.sensor import MashovAdditionalSensor, MashovListSensor

from .test_roster_change import _response
from .test_setup_resilience import _patch_cache, _patch_client


def snapshot(homework="old homework", grades="old grades"):
    return {
        "students": [{"id": "s", "slug": "s", "name": "Student"}],
        "by_slug": {
            "s": {
                "homework": [homework],
                "grades": [grades],
                "source_status": {"homework": "ok", "grades": "ok"},
                "source_last_update": {"homework": 10, "grades": 20},
            }
        },
        "holidays": [{"name": "Holiday"}],
        "holidays_status": "ok",
        "holidays_last_update": 5,
        "mailbox": {"items": [{"subject": "Private"}], "last_update": 7},
    }


@pytest.mark.parametrize("key", DATA_KEYS)
async def test_each_dataset_can_be_fetched_without_other_selected_routes(key):
    client = MashovClient("123", 2027, "test", "test", enabled_data=list(DATA_KEYS))
    client._students = [{"id": "s", "slug": "s", "name": "Student"}]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(200, [])
    client._fetch_student_resource = AsyncMock(return_value={"items": [], "status": "ok"})
    client._fetch_account_json = AsyncMock(side_effect=[("ok", {}), ("ok", [])])
    result = await client.async_fetch_all(selected_data=[key])
    assert client.enabled_data == tuple(DATA_KEYS)
    assert client._session.get.call_count == (1 if key in LEGACY_CORE_DATA else 0)
    assert client._fetch_student_resource.await_count == (1 if key not in (*LEGACY_CORE_DATA, "mailbox") else 0)
    if client._fetch_student_resource.await_count:
        assert client._fetch_student_resource.call_args.args[1] == key
    assert client._fetch_account_json.await_count == (2 if key == "mailbox" else 0)
    assert ("mailbox" in result) == (key == "mailbox")


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"additional_data": ["message_board"]},
        {"enabled_data": []},
        {"schedule_type": "weekly", "schedule_day": 4, "schedule_time": "08:15:30"},
        {"schedule_type": "interval", "schedule_interval": 90},
    ],
)
def test_older_entries_inherit_the_exact_shared_schedule(options):
    before = deepcopy(options)
    for key in DATA_KEYS:
        assert effective_schedule(options, key) == effective_schedule(options, "homework")
    assert options == before


def test_service_rejects_unknown_datasets_and_invalid_override_values():
    for value in [
        {"wrong": {"schedule_type": "daily"}},
        {"grades": {"schedule_type": "daily", "schedule_time": "25:00"}},
        {"grades": {"schedule_type": "interval", "schedule_interval": 1}},
    ]:
        with pytest.raises(vol.Invalid):
            SET_OPTIONS_SCHEMA({"data_schedules": value})


async def test_timers_group_equal_schedules_skip_disabled_and_cancel_on_change(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    options = {
        "enabled_data": ["homework", "behavior", "grades", "holidays"],
        "schedule_time": "14:00",
        "data_schedules": {
            "grades": {"schedule_type": "weekly", "schedule_days": [dt_util.now().weekday()], "schedule_time": "08:00"},
            "holidays": {"schedule_type": "interval", "schedule_interval": 90},
            "mailbox": {"schedule_type": "interval", "schedule_interval": 5},
        },
    }
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    coordinator.async_refresh_datasets = AsyncMock()
    hass.data[DOMAIN] = {mock_config_entry.entry_id: {"coordinator": coordinator}}
    with (
        patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()) as daily,
        patch("custom_components.mashov.async_track_time_interval", return_value=MagicMock()) as interval,
    ):
        await _async_setup_scheduler(hass, mock_config_entry)
        assert coordinator.update_interval is None
        assert daily.call_count == 2
        assert interval.call_count == 1
        assert len(schedule_groups(options)) == 3
        await daily.call_args_list[0].args[1]()
        coordinator.async_refresh_datasets.assert_awaited_with(("homework", "behavior"))
        await daily.call_args_list[1].args[1]()
        coordinator.async_refresh_datasets.assert_awaited_with(("grades",))
        await interval.call_args.args[1]()
        coordinator.async_refresh_datasets.assert_awaited_with(("holidays",))
        hass.config_entries.async_update_entry(mock_config_entry, options={**options, "data_schedules": {}})
        await _async_setup_scheduler(hass, mock_config_entry)
        assert daily.return_value.call_count == 2
        interval.return_value.assert_called_once()
        assert len(hass.data[DOMAIN][mock_config_entry.entry_id]["unsub_daily"]) == 1
    await coordinator.async_shutdown()


async def test_partial_refresh_preserves_other_data_and_timestamps_and_manual_refreshes_all(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["homework", "grades", "holidays", "mailbox"]}
    )
    client = MagicMock()
    client.auth_data = {}
    client.async_fetch_all = AsyncMock(return_value=snapshot("new homework", "should not replace"))
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = snapshot()
    await coordinator.async_refresh_datasets(["homework"])
    client.async_fetch_all.assert_awaited_with(selected_data={"homework"})
    assert coordinator.data["by_slug"]["s"]["grades"] == ["old grades"]
    assert coordinator.data["by_slug"]["s"]["homework"] == ["new homework"]
    assert coordinator.data["by_slug"]["s"]["source_last_update"]["grades"] == 20
    assert coordinator.data["by_slug"]["s"]["source_last_update"]["homework"] > 20
    assert coordinator.data["holidays_last_update"] == 5
    assert coordinator.data["mailbox"]["last_update"] == 7
    sensor = MashovListSensor(
        coordinator, mock_config_entry.entry_id, "s", "s", "Student", "grades", "Grades", "grades"
    )
    coordinator.data["by_slug"]["s"]["grades"] = [{"grade": 90}]
    assert datetime.fromisoformat(sensor.extra_state_attributes["last_update"]).timestamp() == 20
    client.async_fetch_all.reset_mock()
    await coordinator.async_refresh()
    client.async_fetch_all.assert_awaited_once_with()
    await coordinator.async_shutdown()


async def test_concurrent_groups_do_not_overlap_or_overwrite_and_failure_is_scoped(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework", "grades"]})
    active = 0

    async def fetch(selected_data):
        nonlocal active
        active += 1
        assert active == 1
        await asyncio.sleep(0)
        active -= 1
        return snapshot("new homework", "new grades")

    client = MagicMock(auth_data={})
    client.async_fetch_all = AsyncMock(side_effect=fetch)
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = snapshot()
    await asyncio.gather(
        coordinator.async_refresh_datasets(["homework"]), coordinator.async_refresh_datasets(["grades"])
    )
    assert coordinator.data["by_slug"]["s"]["homework"] == ["new homework"]
    assert coordinator.data["by_slug"]["s"]["grades"] == ["new grades"]
    client.async_fetch_all.side_effect = MashovError("Synthetic network failure")
    await coordinator.async_refresh_datasets(["grades"])
    for key, stale in [("homework", False), ("grades", True)]:
        sensor = MashovListSensor(coordinator, mock_config_entry.entry_id, "s", "s", "Student", key, key, key)
        assert sensor.data_stale is stale
    await coordinator.async_shutdown()


def test_merge_never_copies_unrequested_data_to_a_different_student():
    previous = snapshot()
    incoming = snapshot("new", "")
    incoming["students"][0]["id"] = "different-student-with-same-slug"
    merged = merge_partial_data(previous, incoming, {"homework"})
    assert merged["by_slug"]["s"]["grades"] == []
    assert previous["by_slug"]["s"]["grades"] == ["old grades"]


@pytest.mark.parametrize("source", ["setup", "options"])
async def test_flow_navigates_multiple_datasets_and_commits_only_on_save(hass, mock_config_entry, source):
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as mock_client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        mock_client.return_value.async_init = AsyncMock()
        mock_client.return_value.async_close = AsyncMock()
        mock_client.return_value.async_open_session = AsyncMock()
        mock_client.return_value.async_fetch_schools_catalog = AsyncMock(return_value=[])
        if source == "setup":
            manager = hass.config_entries.flow
            form = await manager.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
            data = {
                "username": "user",
                "password": "secret",
                "school_name": "123",
                "enabled_data": ["homework", "grades"],
            }
        else:
            mock_config_entry.add_to_hass(hass)
            manager = hass.config_entries.options
            form = await manager.async_init(mock_config_entry.entry_id)
            data = {"enabled_data": ["homework", "grades"], "password": "new-secret"}
        summary = form["description_placeholders"]["schedule_summary"]
        assert len([line for line in summary.splitlines() if line.startswith("|")]) == 20
        assert "<details>" in summary and "<details open" not in summary
        flow_id = form["flow_id"]
        sections = {str(key): value for key, value in form["data_schema"].schema.items()}
        assert sections["refresh"].options["collapsed"] is True
        assert sections["account"].options["collapsed"] is (source == "options")
        account = {key: value for key, value in data.items() if key in {"username", "password", "school_name"}}
        overview = await manager.async_configure(
            flow_id,
            {
                "account": account,
                "data": {"enabled_data": data["enabled_data"]},
                "refresh": {"edit_data_schedules": True},
            },
        )
        assert overview["step_id"] == "data_schedules"
        for key, kind, changes in [
            ("homework", "daily", {"schedule_time": "09:00"}),
            ("grades", "weekly", {"schedule_time": "18:00", "schedule_days": ["4"]}),
        ]:
            editor = await manager.async_configure(flow_id, {"dataset": key})
            assert editor["step_id"] == "data_schedule"
            settings = await manager.async_configure(flow_id, {"schedule_type": kind})
            assert settings["step_id"] == "data_schedule_settings"
            field_names = {str(field) for field in settings["data_schema"].schema}
            assert "schedule_interval" not in field_names
            assert ("schedule_days" in field_names) is (kind == "weekly")
            bad = await manager.async_configure(flow_id, {"schedule_time": "24:99"})
            assert bad["errors"]["base"] == "invalid_data_schedule"
            overview = await manager.async_configure(flow_id, changes)
            assert overview["step_id"] == "data_schedules"
        if source == "options":
            assert mock_config_entry.data["password"] != "new-secret"
            assert "data_schedules" not in mock_config_entry.options
        result = await manager.async_configure(flow_id, {"dataset": "save"})
        assert result["type"] == "create_entry"
        options = result["options"] if source == "setup" else result["data"]
        assert options["data_schedules"]["homework"]["schedule_time"] == "09:00"
        assert options["data_schedules"]["grades"]["schedule_days"] == [4]
        assert "edit_data_schedules" not in options
        if source == "options":
            assert mock_config_entry.data["password"] == "new-secret"


async def test_return_to_shared_and_cancel_preserve_existing_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    original = {
        "enabled_data": ["grades"],
        "schedule_time": "13:30",
        "data_schedules": {"grades": {"schedule_type": "daily", "schedule_time": "18:00"}},
    }
    hass.config_entries.async_update_entry(mock_config_entry, options=original)
    manager = hass.config_entries.options
    for commit in (False, True):
        form = await manager.async_init(mock_config_entry.entry_id)
        flow_id = form["flow_id"]
        await manager.async_configure(flow_id, {"edit_data_schedules": True})
        await manager.async_configure(flow_id, {"dataset": "grades"})
        overview = await manager.async_configure(flow_id, {"schedule_type": "shared"})
        assert "13:30" in overview["description_placeholders"]["schedule_summary"]
        assert mock_config_entry.options == original
        if not commit:
            manager.async_abort(flow_id)
            assert mock_config_entry.options == original
        else:
            result = await manager.async_configure(flow_id, {"dataset": "save"})
            assert result["data"]["data_schedules"] == {}
            assert result["data"]["schedule_time"] == "13:30"


async def test_weekly_form_requires_days_but_daily_allows_empty_days(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    manager = hass.config_entries.options
    form = await manager.async_init(mock_config_entry.entry_id)
    flow_id = form["flow_id"]
    result = await manager.async_configure(flow_id, {"schedule_type": "weekly", "schedule_days": []})
    assert result["errors"]["refresh"]["schedule_days"] == "invalid_data_schedule"
    await manager.async_configure(flow_id, {"edit_data_schedules": True, "schedule_type": "daily"})
    await manager.async_configure(flow_id, {"dataset": "homework"})
    await manager.async_configure(flow_id, {"schedule_type": "weekly"})
    result = await manager.async_configure(flow_id, {"schedule_days": []})
    assert result["errors"]["base"] == "invalid_data_schedule"
    result = await manager.async_configure(flow_id, {"schedule_action": "back"})
    assert result["step_id"] == "data_schedule"
    result = await manager.async_configure(flow_id, {"schedule_type": "daily"})
    assert {str(field) for field in result["data_schema"].schema} == {"schedule_time", "schedule_action"}
    result = await manager.async_configure(flow_id, {"schedule_time": "11:30"})
    assert result["step_id"] == "data_schedules"
    manager.async_abort(flow_id)


async def test_other_successes_do_not_suppress_persistent_group_failure(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework", "grades"]})
    client = MagicMock(auth_data={})
    client.async_fetch_all = AsyncMock()
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = snapshot()
    with patch("custom_components.mashov._async_show_error_notification") as notify:
        for attempt in range(3):
            client.async_fetch_all.side_effect = MashovError("Grades offline")
            await coordinator.async_refresh_datasets(["grades"])
            client.async_fetch_all.side_effect = None
            client.async_fetch_all.return_value = snapshot()
            await coordinator.async_refresh_datasets(["homework"])
            assert coordinator._consecutive_failures == attempt + 1
        assert notify.call_count == 1
        await coordinator.async_refresh_datasets(["grades"])
        assert coordinator._consecutive_failures == 0
    await coordinator.async_shutdown()


async def test_legacy_timestamp_only_applies_to_previously_fetched_resources(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"enabled_data": ["homework", "grades", "special_hours"]}
    )
    previous = snapshot()
    previous["by_slug"]["s"].pop("grades")
    previous["by_slug"]["s"]["source_status"].pop("grades")
    previous["by_slug"]["s"].pop("source_last_update")
    client = MagicMock(auth_data={}, async_fetch_all=AsyncMock(return_value=snapshot()))
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = previous
    coordinator.last_successful_update = 20
    await coordinator.async_refresh_datasets(["homework"])
    for key in ("grades", "special_hours"):
        assert key not in coordinator.data["by_slug"]["s"]["source_last_update"]
    grades = MashovListSensor(
        coordinator, mock_config_entry.entry_id, "s", "s", "Student", "grades", "Grades", "grades"
    )
    special = MashovAdditionalSensor(coordinator, "s", "s", "Student", "special_hours", mock_config_entry.entry_id)
    assert grades.native_value is None
    assert grades.extra_state_attributes["last_update"] is None
    assert special.extra_state_attributes["last_update"] is None
    await coordinator.async_shutdown()


@pytest.mark.parametrize("language,expected", [("en", "Homework"), ("he", "שיעורי בית")])
async def test_summary_uses_frontend_users_language_instead_of_system_default(
    hass, mock_config_entry, language, expected
):
    hass.config.language = "he" if language == "en" else "en"
    flow = OptionsFlowHandler(mock_config_entry)
    flow.hass = hass
    token = current_request.set({"hass_user": SimpleNamespace(id="synthetic-user")})
    try:
        with patch(
            "homeassistant.components.frontend.storage.async_user_store",
            AsyncMock(return_value=SimpleNamespace(data={"language": {"language": language}})),
        ):
            summary = await flow._schedule_summary({})
        assert expected in summary
    finally:
        current_request.reset(token)


async def test_holiday_calendar_exposes_its_effective_schedule(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            "data_schedules": {"holidays": {"schedule_type": "weekly", "schedule_time": "08:15", "schedule_days": [4]}}
        },
    )
    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    coordinator.data = {"holidays": [], "holidays_status": "ok"}
    calendar = MashovHolidaysCalendar(coordinator, mock_config_entry.entry_id)
    assert calendar.extra_state_attributes["schedule_type"] == "weekly"
    assert calendar.extra_state_attributes["schedule_scope"] == "custom"
    assert calendar.extra_state_attributes["schedule_time"] == "08:15:00"
    await coordinator.async_shutdown()


@pytest.mark.parametrize("days,should_migrate", [([0, 4], False), (["4", "0", "4"], True)])
async def test_migration_log_only_appears_for_actual_changes(hass, mock_config_entry, caplog, days, should_migrate):
    caplog.set_level("INFO", logger="custom_components.mashov")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"schedule_days": days})
    patcher, _client = _patch_client()
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        assert ("Migrated options: normalized schedule_days" in caplog.text) is should_migrate
        assert mock_config_entry.options["schedule_days"] == [0, 4]
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


async def test_manual_and_scheduled_refreshes_across_hubs_wait_for_active_refresh(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework"]})
    other_entry = MockConfigEntry(domain=DOMAIN, data={}, options={"enabled_data": ["grades"]}, title="Other hub")
    other_entry.add_to_hass(hass)
    started = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def first_fetch(selected_data):
        order.append("first starts")
        started.set()
        await release.wait()
        order.append("first finishes")
        return snapshot()

    async def second_fetch():
        order.append("second starts")
        return snapshot()

    first = MashovCoordinator(
        hass, MagicMock(auth_data={}, async_fetch_all=AsyncMock(side_effect=first_fetch)), mock_config_entry
    )
    second_client = MagicMock(auth_data={}, async_fetch_all=AsyncMock(side_effect=second_fetch))
    second = MashovCoordinator(hass, second_client, other_entry)
    first.data = snapshot()
    second.data = snapshot()
    active = asyncio.create_task(first.async_refresh_datasets(["homework"]))
    await started.wait()
    waiting = asyncio.create_task(second.async_refresh())
    for _ in range(10):
        await asyncio.sleep(0)
    second_client.async_fetch_all.assert_not_awaited()
    release.set()
    await asyncio.gather(active, waiting)
    assert order == ["first starts", "first finishes", "second starts"]
    await first.async_shutdown()
    await second.async_shutdown()


async def test_shutdown_drains_active_refresh_and_skips_queued_refresh(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework", "grades"]})
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(selected_data):
        started.set()
        await release.wait()
        return snapshot()

    client = MagicMock(auth_data={}, async_fetch_all=AsyncMock(side_effect=fetch))
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = snapshot()
    active = asyncio.create_task(coordinator.async_refresh_datasets(["homework"]))
    await started.wait()
    queued = asyncio.create_task(coordinator.async_refresh_datasets(["grades"]))
    shutdown = asyncio.create_task(coordinator.async_shutdown())
    for _ in range(10):
        await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await asyncio.gather(active, queued, shutdown)
    assert client.async_fetch_all.await_count == 1


async def test_student_fetch_never_calls_other_child_routes():
    client = MashovClient("123", 2027, "test", "test", enabled_data=["homework", "grades", "holidays", "mailbox"])
    client._students = [{"id": sid, "slug": sid, "name": sid} for sid in ("a", "b")]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._session.get.return_value = _response(200, [])
    client._fetch_account_json = AsyncMock()
    result = await client.async_fetch_all(selected_data={"homework"}, student_data={"a": {"homework"}})
    assert client._session.get.call_count == 1
    assert "/students/a/homework" in client._session.get.call_args.args[0]
    assert len(result["students"]) == 2
    assert result["by_slug"]["b"]["source_status"]["homework"] == "not_fetched"
    client._fetch_account_json.assert_not_awaited()


def test_student_groups_and_legacy_inheritance():
    from custom_components.mashov.data_schedule import STUDENT_SCHEDULES_SCHEMA, student_schedule_groups

    options = {
        "enabled_data": ["homework", "grades", "holidays"],
        "schedule_type": "daily",
        "schedule_time": "14:00",
        "student_schedules": {
            "a": {
                "general": {"schedule_type": "interval", "schedule_interval": 45},
                "overrides": {"grades": {"schedule_type": "daily", "schedule_time": "18:00"}},
            }
        },
    }
    groups = student_schedule_groups(options, [{"id": "a"}, {"id": "b"}])
    assert len(groups) == 3
    assert effective_schedule(options, "homework", "a")["schedule_interval"] == 45
    assert effective_schedule(options, "grades", "a")["schedule_time"] == "18:00:00"
    assert effective_schedule(options, "homework", "b")["schedule_time"] == "14:00:00"
    shared = next(group for group in groups if "holidays" in group[1])
    assert shared[2] == {"b": {"homework", "grades"}}
    with pytest.raises(vol.Invalid):
        STUDENT_SCHEDULES_SCHEMA({"a": {"overrides": {"mailbox": {"schedule_type": "daily"}}}})


async def test_student_refresh_preserves_sibling_values_timestamps_and_failures(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework", "grades"]})
    previous = snapshot()
    previous["students"].append({"id": "b", "slug": "b", "name": "Sibling"})
    previous["by_slug"]["b"] = deepcopy(previous["by_slug"]["s"])
    incoming = deepcopy(previous)
    incoming["by_slug"]["s"]["homework"] = ["new"]
    incoming["by_slug"]["b"]["homework"] = []
    incoming["by_slug"]["b"]["source_status"]["homework"] = "not_fetched"
    client = MagicMock(auth_data={}, async_fetch_all=AsyncMock(return_value=incoming))
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.data = previous
    await coordinator.async_refresh_datasets(["homework"], student_data={"s": {"homework"}})
    for key in ("homework", "grades", "source_last_update"):
        assert coordinator.data["by_slug"]["b"][key] == previous["by_slug"]["b"][key]
    assert coordinator.data["by_slug"]["s"]["homework"] == ["new"]
    client.async_fetch_all.side_effect = MashovError("offline")
    await coordinator.async_refresh_datasets(["homework"], student_data={"s": {"homework"}})
    assert coordinator.failed_datasets == {("s", "homework")}
    client.async_fetch_all.side_effect = None
    await coordinator.async_refresh_datasets(["homework"], student_data={"b": {"homework"}})
    assert coordinator.failed_datasets == {("s", "homework")}
    sensor = MashovListSensor(
        coordinator, mock_config_entry.entry_id, "s", "s", "Student", "homework", "Homework", "homework"
    )
    sibling = MashovListSensor(
        coordinator, mock_config_entry.entry_id, "b", "b", "Sibling", "homework", "Homework", "homework"
    )
    assert sensor.data_stale
    assert not sibling.data_stale
    await coordinator.async_shutdown()


async def test_student_timer_passes_only_due_student_pairs(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            "enabled_data": ["homework"],
            "schedule_type": "daily",
            "schedule_time": "14:00",
            "student_schedules": {"a": {"general": {"schedule_type": "interval", "schedule_interval": 45}}},
        },
    )
    client = MagicMock()
    client._students = [{"id": "a"}, {"id": "b"}]
    coordinator = MashovCoordinator(hass, client, mock_config_entry)
    coordinator.async_refresh_datasets = AsyncMock()
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": coordinator}
    with (
        patch("custom_components.mashov.async_track_time_interval", return_value=MagicMock()) as interval,
        patch("custom_components.mashov.async_track_time_change", return_value=MagicMock()) as daily,
    ):
        await _async_setup_scheduler(hass, mock_config_entry)
        assert interval.call_count == daily.call_count == 1
        await interval.call_args.args[1]()
        coordinator.async_refresh_datasets.assert_awaited_with(("homework",), student_data={"a": {"homework"}})
        await daily.call_args.args[1]()
        coordinator.async_refresh_datasets.assert_awaited_with(("homework",), student_data={"b": {"homework"}})
    for cancel in hass.data[DOMAIN][mock_config_entry.entry_id]["unsub_daily"]:
        cancel()
    await coordinator.async_shutdown()


async def test_shutdown_does_not_wait_for_other_hubs(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    async with coordinator._fetch_lock:
        await asyncio.wait_for(coordinator.async_shutdown(), timeout=0.5)
    assert coordinator._stopped


async def test_roster_timer_rebuild_ignores_removed_or_replaced_hub(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    old = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    await _async_setup_scheduler(hass, mock_config_entry, expected_coordinator=old)
    replacement = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": replacement}
    with patch("custom_components.mashov.async_track_time_change") as timer:
        await _async_setup_scheduler(hass, mock_config_entry, expected_coordinator=old)
        timer.assert_not_called()
    await old.async_shutdown()
    await replacement.async_shutdown()


def test_inline_schedule_selector_is_in_form_and_flattens_all_student_drafts():
    from custom_components.mashov.schedule_flow import GroupedSettingsSchema, schedule_fields

    options = {"schedule_type": "daily", "schedule_time": "14:00", "enabled_data": ["homework"]}
    form = GroupedSettingsSchema(vol.Schema(schedule_fields(options)), inline={"entry_id": "demo", "options": options})
    draft = {
        "general": {"schedule_type": "interval", "schedule_interval": 45},
        "overrides": {},
        "student_schedules": {"a": {"overrides": {"homework": {"schedule_type": "daily", "schedule_time": "18:00"}}}},
    }
    result = form({"refresh": {"schedule_editor": draft}})
    assert result["schedule_interval"] == 45
    assert result["student_schedules"]["a"]["overrides"]["homework"]["schedule_time"] == "18:00"
    assert "schedule_editor" not in result
    invalid = deepcopy(draft)
    invalid["student_schedules"]["a"]["overrides"]["homework"] = {"schedule_type": "weekly", "schedule_days": []}
    with pytest.raises(vol.Invalid):
        form({"refresh": {"schedule_editor": invalid}})


async def test_native_inline_options_submit_commits_all_student_schedules(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})["inline_schedule_editor"] = True
    form = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    draft = {
        "general": {"schedule_type": "interval", "schedule_interval": 45},
        "overrides": {},
        "student_schedules": {
            "a": {"general": {"schedule_type": "daily", "schedule_time": "18:00"}, "overrides": {}},
            "b": {"overrides": {"homework": {"schedule_type": "interval", "schedule_interval": 90}}},
        },
    }
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"data": {"enabled_data": ["homework"]}, "refresh": {"schedule_editor": draft}}
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.options["schedule_interval"] == 45
    saved = mock_config_entry.options["student_schedules"]
    assert set(saved) == {"a", "b"}
    assert saved["a"]["general"]["schedule_time"] == "18:00"
    assert saved["b"]["overrides"]["homework"]["schedule_interval"] == 90
    assert mock_config_entry.options["enabled_data"] == ["homework"]


async def test_native_inline_registration_submit_saves_general_and_overrides(hass):
    hass.data.setdefault(DOMAIN, {})["inline_schedule_editor"] = True
    with (
        patch("custom_components.mashov.config_flow.MashovClient") as client,
        patch("custom_components.mashov.async_setup", return_value=True),
        patch("custom_components.mashov.async_setup_entry", return_value=True),
    ):
        client.return_value.async_init = AsyncMock()
        client.return_value.async_close = AsyncMock()
        client.return_value.async_open_session = AsyncMock()
        client.return_value.async_fetch_schools_catalog = AsyncMock(return_value=[])
        manager = hass.config_entries.flow
        form = await manager.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await manager.async_configure(
            form["flow_id"],
            {
                "account": {"username": "demo", "password": "demo", "school_name": "123"},
                "data": {"enabled_data": ["homework", "grades"]},
                "refresh": {
                    "schedule_editor": {
                        "general": {"schedule_type": "interval", "schedule_interval": 45},
                        "overrides": {
                            "grades": {"schedule_type": "weekly", "schedule_time": "18:00", "schedule_days": [4]}
                        },
                        "student_schedules": {},
                    }
                },
            },
        )
        assert result["type"] == "create_entry"
        entry = result["result"]
        assert entry.options["schedule_interval"] == 45
        assert entry.options["data_schedules"]["grades"]["schedule_days"] == [4]
        assert entry.options["enabled_data"] == ["homework", "grades"]
        assert "password" not in entry.options
