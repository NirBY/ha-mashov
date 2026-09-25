"""Allowlisted diagnostic summaries and user-reviewed GitHub reports."""

import json
from urllib.parse import urlencode

from homeassistant.const import __version__ as HA_VERSION

from .additional_data import STUDENT_RESOURCES

VERSION = "1.0.7"
_EVENTS = {
    "Mashov password change required": "password_change_required",
    "Mashov authentication failed": "authentication_failed",
    "Mashov startup refresh failed": "startup_refresh_failed",
    "Mashov refresh failed": "refresh_failed",
}
_STATUSES = {"ok", "forbidden", "unsupported", "unauthorized", "invalid_response", "fetch_failed"}


def diagnostic_summary(coordinator=None):
    """Never export config entries, arbitrary log messages, keys, or student data."""
    result = {"integration_version": VERSION, "home_assistant_version": HA_VERSION}
    if coordinator is None:
        return result
    result["last_update_success"] = bool(coordinator.last_update_success)
    data = coordinator.data or {}
    result["student_count"] = len(data.get("students", []))
    counts = {}
    for student in data.get("by_slug", {}).values():
        for key, resource in student.get("additional_data", {}).items():
            if key not in STUDENT_RESOURCES or not isinstance(resource, dict):
                continue
            status = resource.get("status")
            if status not in _STATUSES:
                status = "other_error"
            bucket = counts.setdefault(key, {})
            bucket[status] = bucket.get(status, 0) + 1
    result["optional_resource_status_counts"] = counts
    return result


def issue_report_url(title):
    """Prepare a form; no request or publication happens inside Home Assistant."""
    event = _EVENTS.get(title, "integration_error")
    summary = diagnostic_summary()
    summary["event"] = event
    return "https://github.com/NirBY/ha-mashov/issues/new?" + urlencode(
        {
            "template": "bug_report.yml",
            "title": f"[Bug]: {event}",
            "short_title": event,
            "system_health": f"Mashov {VERSION}; Home Assistant {HA_VERSION}",
            "debug_logs": json.dumps(summary, indent=2),
        }
    )
