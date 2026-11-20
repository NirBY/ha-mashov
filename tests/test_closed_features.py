"""Closed school features: several separate HTTP 5xx refreshes retire a data type, nothing else does.

A single 5xx, a network error, a success or a refusal must never retire a data type. A
confirmed closure is notified once (translated Repairs issue) and persisted as an opt-out.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import issue_registry as ir
import pytest

from custom_components import mashov as integration
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_schedule import merge_partial_data
from custom_components.mashov.llm_api import MAX_PAGE_BYTES, MAX_TEXT_CHARS, _bounded_page
from custom_components.mashov.mashov_client import (
    CLOSED_FEATURE_MIN_SPACING,
    CLOSED_FEATURE_THRESHOLD,
    MashovClient,
    _dataset_for_account_key,
)

CLOCK_PATH = "custom_components.mashov.mashov_client.time.monotonic"
SELECTED = {"justification_requests", "mailbox", "homework"}


class Clock:
    """Fake monotonic clock that only moves when the test advances it."""

    def __init__(self):
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(name="clock")
def clock_fixture():
    clock = Clock()
    with patch(CLOCK_PATH, side_effect=lambda: clock.now):
        yield clock


def _client(**kwargs):
    client = MashovClient("123", 2027, "test", "test", enabled_data=sorted(SELECTED), **kwargs)
    client._refresh_statuses = {}
    return client


def _refresh(client, statuses, selected=SELECTED):
    """Record one refresh's attempt outcomes and evaluate the closure rule, as async_fetch_all does."""
    client._refresh_statuses = {}
    for dataset, values in statuses.items():
        for value in values:
            client._record_status(dataset, value)
    return client._closed_features(selected)


def test_three_separate_server_error_refreshes_retire_the_data_type(clock):
    client = _client()
    results = []
    for _ in range(CLOSED_FEATURE_THRESHOLD):
        results.append(_refresh(client, {"justification_requests": {"http_503"}}))
        clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert results == [[], [], ["justification_requests"]]


def test_repeats_inside_the_spacing_window_count_once(clock):
    client = _client()
    for _ in range(10):
        assert _refresh(client, {"justification_requests": {"http_503"}}) == []
        clock.advance(60)
    assert client._server_error_streak["justification_requests"][0] == 1


@pytest.mark.parametrize(
    "interrupting",
    [{"ok"}, {"fetch_failed"}, {"forbidden"}, {"unsupported"}, {"http_400"}, {"unauthorized"}, {"http_503", "ok"}],
)
def test_any_other_outcome_resets_the_streak(clock, interrupting):
    client = _client()
    _refresh(client, {"justification_requests": {"http_503"}})
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    _refresh(client, {"justification_requests": {"http_503"}})
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    _refresh(client, {"justification_requests": interrupting})
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert _refresh(client, {"justification_requests": {"http_503"}}) == []


def test_a_mixed_refresh_does_not_count_even_if_most_attempts_failed(clock):
    client = _client()
    for _ in range(CLOSED_FEATURE_THRESHOLD):
        # Child one answers 503 but child two succeeds: the school still serves the feature.
        assert _refresh(client, {"justification_requests": {"http_503", "ok"}}) == []
        clock.advance(CLOSED_FEATURE_MIN_SPACING)


def test_a_network_failed_refresh_breaks_the_streak(clock):
    client = _client()
    _refresh(client, {"justification_requests": {"http_503"}})
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    _refresh(client, {"justification_requests": {"http_503"}})
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    client.note_refresh_failed()
    clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert _refresh(client, {"justification_requests": {"http_503"}}) == []


def test_unselected_data_is_never_evaluated(clock):
    client = _client()
    for _ in range(CLOSED_FEATURE_THRESHOLD):
        assert _refresh(client, {"justification_requests": {"http_503"}}, selected={"homework"}) == []
        clock.advance(CLOSED_FEATURE_MIN_SPACING)


def test_account_routes_map_to_their_data_type():
    assert _dataset_for_account_key("mail_counts") == "mailbox"
    assert _dataset_for_account_key("mailbox") == "mailbox"
    assert _dataset_for_account_key("mail_content") == "mailbox"
    assert _dataset_for_account_key("parent_approvals") == "parent_approvals"
    assert _dataset_for_account_key("consent_forms") == "parent_approvals"


async def test_account_route_outcome_is_recorded_for_its_data_type():
    client = _client()
    response = MagicMock(status=503, headers={})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False)
    client._session.get.return_value = context
    assert await client._fetch_account_json("mail/counts", "mail_counts", dict) == ("http_503", None)
    assert client._refresh_statuses == {"mailbox": {"http_503"}}


def _student_client(students, status_by_student, clock):
    """A client whose optional justification route answers per student (all GET, no login)."""
    client = _client(additional_data=["justification_requests"])
    client._students = [{"id": sid, "slug": sid, "name": sid, "year": 2027} for sid in students]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session_year = client.year

    def get(url, headers=None, **_kwargs):
        sid = url.split("/students/")[1].split("/")[0]
        response = MagicMock(status=status_by_student[sid], headers={})
        response.json = AsyncMock(return_value=[])
        response.text = AsyncMock(return_value="")
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    client._session = MagicMock(closed=False)
    client._session.get.side_effect = get
    return client


async def test_two_children_with_stable_503_are_retired_only_on_the_third_refresh(clock):
    client = _student_client(["a", "b"], {"a": 503, "b": 503}, clock)
    closed = []
    for _ in range(CLOSED_FEATURE_THRESHOLD):
        result = await client.async_fetch_all(selected_data={"justification_requests"})
        closed.append(result["closed_features"])
        assert result["by_slug"]["a"]["additional_data"]["justification_requests"]["status"] == "http_503"
        clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert closed == [[], [], ["justification_requests"]]


async def test_one_child_still_served_keeps_the_data_type(clock):
    client = _student_client(["a", "b"], {"a": 503, "b": 200}, clock)
    for _ in range(CLOSED_FEATURE_THRESHOLD + 1):
        result = await client.async_fetch_all(selected_data={"justification_requests"})
        assert result["closed_features"] == []
        clock.advance(CLOSED_FEATURE_MIN_SPACING)


def test_core_server_error_keeps_the_last_good_items():
    students = [{"id": "1", "slug": "s", "name": "S"}]
    previous = {
        "students": students,
        "by_slug": {
            "s": {
                "homework": [{"homework": "old"}],
                "source_status": {"homework": "ok"},
                "source_last_update": {},
            }
        },
    }
    incoming = {
        "students": students,
        "by_slug": {"s": {"homework": [], "source_status": {"homework": "http_503"}, "additional_data": {}}},
    }
    merged = merge_partial_data(previous, incoming, {"homework"})
    assert merged["by_slug"]["s"]["homework"] == [{"homework": "old"}]
    assert merged["by_slug"]["s"]["source_status"]["homework"] == "http_503"

    # Second consecutive 5xx failure: must STILL retain the items!
    incoming_second = {
        "students": students,
        "by_slug": {"s": {"homework": [], "source_status": {"homework": "http_503"}, "additional_data": {}}},
    }
    merged_second = merge_partial_data(merged, incoming_second, {"homework"})
    assert merged_second["by_slug"]["s"]["homework"] == [{"homework": "old"}]
    assert merged_second["by_slug"]["s"]["source_status"]["homework"] == "http_503"


def test_llm_page_is_bounded_and_always_has_one_item():
    items = [{"body": "x" * (MAX_TEXT_CHARS * 2)} for _ in range(50)]
    page, next_offset = _bounded_page(items, 0, 25)
    assert 1 <= len(page) < 25
    assert next_offset == len(page)
    assert page[0]["body"].endswith("[truncated]")
    assert len(page[0]["body"]) <= MAX_TEXT_CHARS + len(" [truncated]")
    assert len(json_bytes(page)) <= MAX_PAGE_BYTES + MAX_TEXT_CHARS + 64
    last_page, final = _bounded_page(items, 49, 25)
    assert len(last_page) == 1 and final is None


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode()


async def test_retiring_persists_an_opt_out_and_a_translated_issue(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["mailbox", "homework"]})
    await integration.async_retire_data_types(hass, mock_config_entry, ["mailbox"])

    assert mock_config_entry.options["enabled_data"] == ["homework"]
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"closed_feature_{mock_config_entry.entry_id}_mailbox")
    assert issue is not None
    assert issue.translation_key == "closed_feature"
    assert issue.translation_placeholders == {
        "hub": mock_config_entry.title,
        "feature": "Mailbox — headers and unread count",
    }
    assert issue.is_persistent and not issue.is_fixable


async def test_reselecting_the_data_type_clears_the_notice(hass, mock_config_entry, mock_mashov_client):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["homework"]})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await integration.async_retire_data_types(hass, mock_config_entry, ["homework"])
    await hass.async_block_till_done()
    issue_id = f"closed_feature_{mock_config_entry.entry_id}_homework"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert "homework" not in mock_config_entry.options["enabled_data"]

    hass.config_entries.async_update_entry(
        mock_config_entry, options={**mock_config_entry.options, "enabled_data": ["homework"]}
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_retirement_is_skipped_for_a_removed_or_deselected_hub(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["timetable"]})
    await integration.async_retire_data_types(hass, mock_config_entry, ["mailbox"])
    assert mock_config_entry.options["enabled_data"] == ["timetable"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"closed_feature_{mock_config_entry.entry_id}_mailbox") is None


@pytest.mark.parametrize("language", ["en", "he", "ar", "ru", "uk"])
def test_closed_feature_text_has_both_placeholders_in_every_language(language):
    root = Path(__file__).parents[1] / "custom_components/mashov/translations"
    issue = json.loads((root / f"{language}.json").read_text(encoding="utf-8"))["issues"]["closed_feature"]
    assert issue["title"].strip()
    assert "{hub}" in issue["description"] and "{feature}" in issue["description"]


def test_general_outage_across_all_tested_datasets_does_not_retire_features(clock):
    client = _client()
    # When multiple datasets all return 5xx simultaneously, it's a general server outage
    for _ in range(CLOSED_FEATURE_THRESHOLD + 2):
        res = _refresh(
            client,
            {
                "justification_requests": {"http_503"},
                "homework": {"http_503"},
                "mailbox": {"http_503"},
            },
        )
        assert res == []
        clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert not client._server_error_streak


def test_student_schedules_partial_student_coverage_does_not_retire_features(clock):
    client = _client()
    # 2 students in hub, but only 1 student was queried for homework in this refresh
    for _ in range(CLOSED_FEATURE_THRESHOLD + 2):
        client._refresh_statuses = {}
        client._refresh_students = {}
        client._record_status("homework", "http_503", "child_1")
        # client._closed_features with student_count=2
        assert client._closed_features(SELECTED, student_count=2) == []
        clock.advance(CLOSED_FEATURE_MIN_SPACING)
    assert "homework" not in client._server_error_streak
