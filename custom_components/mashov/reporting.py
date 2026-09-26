"""Allowlisted diagnostic summaries and user-reviewed GitHub reports."""

from datetime import UTC, datetime
import json
from urllib.parse import urlencode

import aiohttp
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .additional_data import STUDENT_RESOURCES
from .mashov_client import MashovError

VERSION = "1.0.12"
_EVENTS = {
    "Mashov password change required": "password_change_required",
    "Mashov authentication failed": "authentication_failed",
    "Mashov startup refresh failed": "startup_refresh_failed",
    "Mashov refresh failed": "refresh_failed",
}
_STATUSES = {"ok", "forbidden", "unsupported", "unauthorized", "invalid_response", "fetch_failed"}
_INTERNAL_ERRORS = (
    AssertionError,
    AttributeError,
    TypeError,
    KeyError,
    IndexError,
    NotImplementedError,
    RuntimeError,
    ValueError,
)
_SOURCE_FILES = {
    "__init__.py",
    "mashov_client.py",
    "sensor.py",
    "calendar.py",
    "entity.py",
    "config_flow.py",
    "holidays_utils.py",
}


def root_error(error):
    """Unwrap HA refresh/setup wrappers without inspecting arbitrary exception text."""
    seen = set()
    while isinstance(error, (UpdateFailed, ConfigEntryNotReady)) and error.__cause__ and id(error) not in seen:
        seen.add(id(error))
        error = error.__cause__
    return error


def is_internal_error(error):
    """Offer reports for programming failures, never normal account/network/API failures."""
    error = root_error(error)
    if isinstance(error, (MashovError, aiohttp.ClientError, OSError, TimeoutError)):
        return False
    return isinstance(error, _INTERNAL_ERRORS)


def technical_log(error, title):
    """Build a bounded technical log, excluding messages, locals, paths and portal data."""
    error = root_error(error)
    frames = []
    frame = error.__traceback__
    while frame:
        filename = frame.tb_frame.f_code.co_filename.replace("\\", "/")
        basename = filename.rsplit("/", 1)[-1]
        if "/custom_components/mashov/" in filename and basename in _SOURCE_FILES:
            frames.append({"file": basename, "line": frame.tb_lineno})
        frame = frame.tb_next
    return {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "event": _EVENTS.get(title, "integration_error"),
        "error_type": next(cls.__name__ for cls in _INTERNAL_ERRORS if isinstance(error, cls)),
        "frames": frames[-5:],
    }


def diagnostic_summary(coordinator=None, technical_logs=None):
    """Never export config entries, arbitrary log messages, keys, or student data."""
    result = {"integration_version": VERSION, "home_assistant_version": HA_VERSION}
    if technical_logs:
        result["technical_logs"] = technical_logs[-20:]
    if coordinator is None:
        return result
    result["last_update_success"] = bool(coordinator.last_update_success)
    data = coordinator.data or {}
    result["data_stale"] = bool(getattr(coordinator, "data_stale", False)) or not coordinator.last_update_success
    holiday_status = data.get("holidays_status", "not_fetched")
    result["holidays_status"] = holiday_status if holiday_status in _STATUSES else "other_error"
    core_counts = {}
    for student in data.get("by_slug", {}).values():
        for key in ("homework", "behavior", "weekly_plan", "timetable", "lessons_history", "grades"):
            status = student.get("source_status", {}).get(key, "not_fetched")
            status = status if status in _STATUSES else "other_error"
            bucket = core_counts.setdefault(key, {})
            bucket[status] = bucket.get(status, 0) + 1
    result["core_resource_status_counts"] = core_counts
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


def issue_report_url(title, technical_logs=None):
    """Prepare a form; no request or publication happens inside Home Assistant."""
    event = _EVENTS.get(title, "integration_error")
    summary = diagnostic_summary()
    summary["event"] = event
    if technical_logs:
        # The latest event keeps both links within forwarded-message limits.
        # Downloaded diagnostics retains up to twenty events.
        summary["technical_logs"] = technical_logs[-1:]
    return "https://github.com/NirBY/ha-mashov/issues/new?" + urlencode(
        {
            "template": "bug_report.yml",
            "title": f"[Bug]: {event}",
            "short_title": event,
            "system_health": f"Mashov {VERSION}; Home Assistant {HA_VERSION}",
            "debug_logs": json.dumps(summary, separators=(",", ":")),
        }
    )
