"""School bell schedule (#18): opt-in, read-only, school-wide, bounded attributes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.data_schedule import SHARED_DATA
from custom_components.mashov.data_selection import (
    DATA_KEYS,
    LEGACY_CORE_DATA,
    enabled_data,
    filter_cached_data,
)
from custom_components.mashov.mashov_client import MashovClient, _dataset_for_account_key
from custom_components.mashov.sensor import MashovBellsSensor

BELLS = [
    {"lessonNumber": 1, "startTime": "08:00", "endTime": "08:45"},
    {"lessonNumber": 2, "startTime": "08:55", "endTime": "09:40"},
]


@pytest.fixture
def enable_custom_integrations():
    """Override the autouse HA fixture: these tests exercise the client and sensor directly."""
    yield


def make_client():
    return MashovClient("123", 2027, "test", "test")


def test_bells_is_opt_in_and_school_wide():
    """Bells are not in the legacy default set, are a shared (per hub) dataset, and map to their own dataset key."""
    assert "bells" in DATA_KEYS
    assert "bells" not in LEGACY_CORE_DATA
    assert "bells" in SHARED_DATA
    assert _dataset_for_account_key("bells") == "bells"
    assert "bells" not in enabled_data({})
    assert "bells" in enabled_data({"enabled_data": ["bells"]})


@pytest.mark.asyncio
async def test_bells_fetch_is_one_get_and_keeps_only_records():
    client = make_client()
    client._fetch_account_json = AsyncMock(return_value=("ok", [*BELLS, "not a record"]))
    result = {}
    await client._fetch_account_resources(result, {"bells"}, [])
    client._fetch_account_json.assert_awaited_once_with("bells", "bells", list)
    assert result["bells"] == {"items": BELLS, "status": "ok"}


@pytest.mark.asyncio
async def test_bells_failure_is_visible_and_empty():
    client = make_client()
    client._fetch_account_json = AsyncMock(return_value=("forbidden", None))
    result = {}
    await client._fetch_account_resources(result, {"bells"}, [])
    assert result["bells"] == {"items": [], "status": "forbidden"}


@pytest.mark.asyncio
async def test_bells_not_fetched_when_not_selected():
    client = make_client()
    client._fetch_account_json = AsyncMock()
    result = {}
    await client._fetch_account_resources(result, set(), [])
    client._fetch_account_json.assert_not_awaited()
    assert "bells" not in result


def test_disabling_bells_removes_cached_copy():
    data = {"bells": {"items": BELLS, "status": "ok"}}
    assert "bells" not in filter_cached_data(data, {"enabled_data": ["homework"]})
    assert filter_cached_data(data, {"enabled_data": ["bells"]})["bells"]["items"] == BELLS


def make_sensor(resource=None):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.entry = SimpleNamespace(options={}, title="School")
    coordinator.data = {} if resource is None else {"bells": resource}
    return MashovBellsSensor(coordinator, "entry")


def test_sensor_counts_only_successful_fetch():
    assert make_sensor().native_value is None
    assert make_sensor({"items": [], "status": "forbidden"}).native_value is None
    assert make_sensor({"items": BELLS, "status": "ok"}).native_value == 2


def test_sensor_exposes_status_and_bounded_items():
    sensor = make_sensor({"items": [*BELLS, {"text": "א" * 20000}], "status": "ok"})
    attributes = sensor.extra_state_attributes
    assert sensor.native_value == 3
    assert attributes["source_status"] == "ok"
    assert attributes["total_lessons"] == 3
    assert attributes["truncated"] is True
    assert attributes["items"] == BELLS
    assert sensor.unique_id == "mashov_entry_bells"


def test_failed_refresh_keeps_last_bells_as_retained():
    from custom_components.mashov.data_schedule import merge_partial_data

    previous = {"bells": {"items": BELLS, "status": "ok"}}
    incoming = {"students": [], "by_slug": {}, "bells": {"items": [], "status": "http_500"}}
    merged = merge_partial_data(previous, incoming, {"bells"})
    assert merged["bells"]["status"] == "http_500"
    assert merged["bells"]["items"] == BELLS
    assert merged["bells"]["retained"] is True
    # The last good list stays visible (and counted) while the status shows the failure.
    assert make_sensor(merged["bells"]).native_value == 2
    assert make_sensor(merged["bells"]).extra_state_attributes["source_status"] == "http_500"
