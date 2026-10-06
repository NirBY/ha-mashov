"""Allowlisted diagnostic summaries and user-reviewed GitHub reports.

Privacy model: everything here is built from an allowlist, never by filtering
a larger object. What can be exported:
  - integration and Home Assistant versions,
  - update success / staleness flags,
  - per-resource status *counts* (status values limited to _STATUSES),
  - the number of students,
  - technical logs: event code, exception class name, and mashov source
    file names + line numbers.
What is never exported: config entries, credentials, usernames, school ids,
student names or data, exception messages, local variables, absolute paths,
or any portal response content.

Bug reports are offered only for internal (programming) errors. Account,
network and portal/API failures are the user's environment, not a bug, so they
never produce a report link. Nothing is sent from Home Assistant: the user gets
a prefilled GitHub issue form to review and submit themselves.
"""

from datetime import UTC, datetime
import json
from urllib.parse import urlencode

import aiohttp
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .additional_data import STUDENT_RESOURCES
from .mashov_client import MashovError

VERSION = "1.0.15"
# Notification title -> stable event code. Only the code is exported, never the title text.
_EVENTS = {
    "Mashov password change required": "password_change_required",
    "Mashov authentication failed": "authentication_failed",
    "Mashov startup refresh failed": "startup_refresh_failed",
    "Mashov refresh failed": "refresh_failed",
}
# Known resource status values; anything else is exported as "other_error" so free text can't leak.
_STATUSES = {"ok", "forbidden", "unsupported", "unauthorized", "invalid_response", "fetch_failed"}
# Exception classes that indicate a bug in the integration (and may be reported).
# technical_log() relies on the error being one of these to name its type.
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
# Only traceback frames from these integration files are kept (by basename).
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
    """Unwrap HA refresh/setup wrappers without inspecting arbitrary exception text.

    Follows __cause__ through UpdateFailed/ConfigEntryNotReady so classification
    looks at the real error; `seen` guards against cause cycles.
    """
    seen = set()
    while isinstance(error, (UpdateFailed, ConfigEntryNotReady)) and error.__cause__ and id(error) not in seen:
        seen.add(id(error))
        error = error.__cause__
    return error


def is_internal_error(error):
    """Offer reports for programming failures, never normal account/network/API failures."""
    error = root_error(error)
    # External failures are checked first: some of them subclass builtins that
    # also appear in _INTERNAL_ERRORS (e.g. aiohttp.InvalidURL is also a ValueError).
    if isinstance(error, (MashovError, aiohttp.ClientError, OSError, TimeoutError)):
        return False
    return isinstance(error, _INTERNAL_ERRORS)


def technical_log(error, title):
    """Build a bounded technical log, excluding messages, locals, paths and portal data.

    Must only be called for errors where is_internal_error() is True, otherwise
    the error_type lookup has no match. Frames are reduced to basename + line
    for files of this integration, keeping the innermost five.
    """
    error = root_error(error)
    frames = []
    frame = error.__traceback__
    while frame:
        # Normalize Windows separators so the path checks below work on every OS.
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
    """Build the allowlisted diagnostics dict (see the module docstring).

    Never export config entries, arbitrary log messages, keys, or student data.
    Without a coordinator only the version info (and logs) is returned, which is
    what the GitHub report link uses. Per-student data is aggregated into status
    counts per resource, so no individual student can be identified.
    """
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
        # Optional resources: only keys defined in STUDENT_RESOURCES are exported.
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
    """Return a prefilled GitHub "new issue" URL for the bug_report.yml template.

    Prepare a form; no request or publication happens inside Home Assistant.
    The user opens the link, reviews the prefilled fields and decides whether to submit.
    """
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
