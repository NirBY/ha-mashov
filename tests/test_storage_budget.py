"""The recorder budget covers formatted fields as well as raw records."""

from types import SimpleNamespace

from homeassistant.helpers.json import json_bytes

from custom_components.mashov.sensor import MashovListSensor


def test_large_formatted_fields_do_not_push_attributes_over_budget():
    """Huge formatted fields are truncated so the whole attribute payload stays within 14 KiB."""
    attrs = {
        "items": [{"subject": "מקצוע" * 30} for _ in range(20)],
        "stored_items": 20,
        "total_items": 20,
        "formatted_table_html": "<td>" + "טקסט" * 10000,
        "formatted_by_date": {"example": ["טקסט" * 10000]},
        "formatted_by_subject": {"example": ["טקסט" * 10000]},
        "formatted_summary": "Example",
    }
    result = MashovListSensor._bound_attributes(attrs)
    assert len(json_bytes(result)) <= 14 * 1024
    assert result["formatting_truncated"]
    assert result["stored_items"] == len(result["items"])
    assert result["total_items"] == 20


def test_single_oversized_item_can_be_omitted():
    """A single item larger than the budget is dropped rather than stored."""
    sensor = MashovListSensor(
        SimpleNamespace(), "entry", "synthetic", "example", "Example", "homework", "Homework", "homework"
    )
    assert sensor._limit_items_for_storage([{"homework": "x" * 20000}], 100) == []


def test_small_payload_preserves_presentation():
    """Payloads within budget keep their formatted fields untouched."""
    attrs = {"items": [{"a": 1}], "stored_items": 1, "total_items": 1, "formatted_table_html": "<p>Example</p>"}
    result = MashovListSensor._bound_attributes(attrs)
    assert result["formatted_table_html"] == "<p>Example</p>"
    assert not result["formatting_truncated"]
