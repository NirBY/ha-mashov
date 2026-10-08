"""Independent resource schedules; absent overrides retain the historical hub schedule."""

from copy import deepcopy
import re

import voluptuous as vol

from .const import (
    CONF_SCHEDULE_DAY,
    CONF_SCHEDULE_DAYS,
    CONF_SCHEDULE_INTERVAL,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_TYPE,
    DEFAULT_SCHEDULE_DAY,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_TYPE,
)
from .data_selection import DATA_KEYS, LEGACY_CORE_DATA, enabled_data

CONF_DATA_SCHEDULES = "data_schedules"
CONF_STUDENT_SCHEDULES = "student_schedules"
SHARED_DATA = frozenset({"holidays", "mailbox"})
STUDENT_DATA = tuple(key for key in DATA_KEYS if key not in SHARED_DATA)
CONF_EDIT_DATA_SCHEDULES = "edit_data_schedules"
TIME_PATTERN = r"^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$"


def _validate_weekly(schedule):
    if schedule[CONF_SCHEDULE_TYPE] == "weekly" and not schedule[CONF_SCHEDULE_DAYS]:
        raise vol.Invalid("A weekly schedule needs at least one weekday")
    return schedule


SCHEDULE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_SCHEDULE_TYPE): vol.In(["daily", "weekly", "interval"]),
            vol.Optional(CONF_SCHEDULE_TIME, default=DEFAULT_SCHEDULE_TIME): vol.Match(TIME_PATTERN),
            vol.Optional(CONF_SCHEDULE_DAYS, default=[DEFAULT_SCHEDULE_DAY]): vol.All(
                [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))],
                lambda days: sorted(set(days)),
            ),
            vol.Optional(CONF_SCHEDULE_INTERVAL, default=DEFAULT_SCHEDULE_INTERVAL): vol.All(
                vol.Coerce(int),
                vol.Range(min=5, max=1440),
            ),
        }
    ),
    _validate_weekly,
)
DATA_SCHEDULES_SCHEMA = vol.Schema({vol.In(DATA_KEYS): SCHEDULE_SCHEMA})
STUDENT_SCHEDULES_SCHEMA = vol.Schema(
    {
        str: vol.Schema(
            {
                vol.Optional("general"): SCHEDULE_SCHEMA,
                vol.Optional("overrides", default={}): vol.Schema({vol.In(STUDENT_DATA): SCHEDULE_SCHEMA}),
            }
        )
    }
)


def normalized_schedule(options):
    """Resolve old options without mutating them; invalid legacy values use defaults."""
    kind = options.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE)
    if kind not in ("daily", "weekly", "interval"):
        kind = DEFAULT_SCHEDULE_TYPE
    clock = str(options.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME))
    if not re.fullmatch(TIME_PATTERN, clock):
        clock = DEFAULT_SCHEDULE_TIME
    clock = ":".join(f"{int(part):02d}" for part in clock.split(":"))
    if len(clock.split(":")) == 2:
        clock += ":00"
    raw_days = options.get(CONF_SCHEDULE_DAYS) or [options.get(CONF_SCHEDULE_DAY, DEFAULT_SCHEDULE_DAY)]
    days = []
    for day in raw_days if isinstance(raw_days, (list, tuple)) else []:
        try:
            value = int(day)
            if 0 <= value <= 6:
                days.append(value)
        except (ValueError, TypeError):
            pass
    try:
        interval = int(options.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL))
        if not 5 <= interval <= 1440:
            interval = DEFAULT_SCHEDULE_INTERVAL
    except (ValueError, TypeError):
        interval = DEFAULT_SCHEDULE_INTERVAL
    return {
        CONF_SCHEDULE_TYPE: kind,
        CONF_SCHEDULE_TIME: clock,
        CONF_SCHEDULE_DAYS: sorted(set(days)) or [DEFAULT_SCHEDULE_DAY],
        CONF_SCHEDULE_INTERVAL: interval,
    }


def effective_schedule(options, key, student_id=None):
    """An override is independent; removing it restores live inheritance."""
    student = (
        (options.get(CONF_STUDENT_SCHEDULES) or {}).get(student_id, {}) if student_id and key not in SHARED_DATA else {}
    )
    override = student.get("overrides", {}).get(key) or student.get("general")
    if override:
        return normalized_schedule(override)
    override = (options.get(CONF_DATA_SCHEDULES) or {}).get(key)
    return normalized_schedule(override if isinstance(override, dict) else options)


def schedule_groups(options):
    """Batch categories with identical effective timers into a single request."""
    groups = {}
    for key in enabled_data(options):
        schedule = effective_schedule(options, key)
        kind = schedule[CONF_SCHEDULE_TYPE]
        signature = (
            (kind, schedule[CONF_SCHEDULE_INTERVAL])
            if kind == "interval"
            else (kind, schedule[CONF_SCHEDULE_TIME], tuple(schedule[CONF_SCHEDULE_DAYS]) if kind == "weekly" else ())
        )
        groups.setdefault(signature, (schedule, []))[1].append(key)
    return list(groups.values())


def student_schedule_groups(options, students):
    """Group due student/resource pairs; shared resources are requested once."""
    groups = {}
    for student_id, keys in [(s["id"], STUDENT_DATA) for s in students] + [(None, SHARED_DATA)]:
        for key in set(keys) & set(enabled_data(options)):
            schedule = effective_schedule(options, key, student_id)
            kind = schedule[CONF_SCHEDULE_TYPE]
            signature = (
                (kind, schedule[CONF_SCHEDULE_INTERVAL])
                if kind == "interval"
                else (
                    kind,
                    schedule[CONF_SCHEDULE_TIME],
                    tuple(schedule[CONF_SCHEDULE_DAYS]) if kind == "weekly" else (),
                )
            )
            group = groups.setdefault(signature, (schedule, set(), {}))
            group[1].add(key)
            if student_id is not None:
                group[2].setdefault(student_id, set()).add(key)
    return list(groups.values())


def merge_partial_data(previous, incoming, requested, student_data=None):
    """Preserve unrequested resources, matching students by identity, never position."""
    result = deepcopy(incoming)
    previous_students = {s["id"]: s["slug"] for s in previous.get("students", [])}
    for student in result.get("students", []):
        student_requested = requested if student_data is None else student_data.get(student["id"], set())
        old = previous.get("by_slug", {}).get(previous_students.get(student["id"]), {})
        current = result["by_slug"][student["slug"]]
        for key in LEGACY_CORE_DATA[:-1]:
            if key not in student_requested:
                current[key] = deepcopy(old.get(key, []))
                current.setdefault("source_status", {})[key] = old.get("source_status", {}).get(key, "not_fetched")
        for key, resource in old.get("additional_data", {}).items():
            if key not in student_requested:
                current.setdefault("additional_data", {})[key] = deepcopy(resource)
        current["source_last_update"] = dict(old.get("source_last_update", {}))
    for key in ("holidays", "holidays_status", "holidays_cached", "holidays_last_update"):
        if "holidays" not in requested and key in previous:
            result[key] = deepcopy(previous[key])
    if "mailbox" not in requested and "mailbox" in previous:
        result["mailbox"] = deepcopy(previous["mailbox"])
    return result
