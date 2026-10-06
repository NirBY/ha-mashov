"""Per-hub data selection and compatibility with entries created before v1.0.16."""

from copy import deepcopy

from .additional_data import CONF_ADDITIONAL_DATA, STUDENT_RESOURCES

CONF_ENABLED_DATA = "enabled_data"
CONF_MAILBOX_FULL_CONTENT = "mailbox_full_content"
CONF_MAILBOX_LIMIT = "mailbox_limit"
DEFAULT_MAILBOX_LIMIT = 20

# Frozen historical default, including installations from v1.0.7. Never extend
# this tuple when adding a resource: upgrades must not enable new data sources.
LEGACY_CORE_DATA = ("homework", "behavior", "weekly_plan", "timetable", "lessons_history", "grades", "holidays")
DATA_KEYS = (*LEGACY_CORE_DATA, *STUDENT_RESOURCES, "mailbox")


def enabled_data(options):
    """Missing selection preserves the old defaults; an explicit [] disables all."""
    selected = options.get(CONF_ENABLED_DATA)
    if CONF_ENABLED_DATA not in options:
        selected = (*LEGACY_CORE_DATA, *(options.get(CONF_ADDITIONAL_DATA) or []))
    return tuple(key for key in DATA_KEYS if key in (selected or []))


def merge_selection_options(current, changes):
    """Retain old service calls without letting an obsolete key override new choices."""
    merged = {**current, **changes}
    if CONF_ADDITIONAL_DATA in changes and CONF_ENABLED_DATA not in changes:
        selected = set(enabled_data(current)) - set(STUDENT_RESOURCES)
        selected.update(changes[CONF_ADDITIONAL_DATA] or [])
        merged[CONF_ENABLED_DATA] = [key for key in DATA_KEYS if key in selected]
    else:
        merged[CONF_ENABLED_DATA] = list(enabled_data(merged))
    # Keep the old key synchronized for existing automation/configuration readers.
    merged[CONF_ADDITIONAL_DATA] = [key for key in merged[CONF_ENABLED_DATA] if key in STUDENT_RESOURCES]
    # Turning off mailbox also turns off consent to mark messages read. Re-enabling
    # it later must not silently reuse an old full-content opt-in.
    if "mailbox" not in merged[CONF_ENABLED_DATA]:
        merged[CONF_MAILBOX_FULL_CONTENT] = False
    return merged


def cached_selection(data):
    """Infer what an older cache actually fetched, without assuming new selections."""
    if CONF_ENABLED_DATA in data:
        return set(data[CONF_ENABLED_DATA])
    return set(LEGACY_CORE_DATA) | {
        key for student in data.get("by_slug", {}).values() for key in student.get("additional_data", {})
    }


def filter_cached_data(data, options):
    """Remove disabled data and bodies before an old cache can reach entities again."""
    result = deepcopy(data)
    selected = set(enabled_data(options))
    for student in result.get("by_slug", {}).values():
        for key in LEGACY_CORE_DATA[:-1]:
            if key not in selected:
                student[key] = []
                student.setdefault("source_status", {})[key] = "disabled"
        if "additional_data" in student:
            student["additional_data"] = {
                key: value for key, value in student["additional_data"].items() if key in selected
            }
    if "holidays" not in selected:
        result["holidays"] = []
        result["holidays_status"] = "disabled"
        result.pop("holidays_cached", None)
        result.pop("holidays_last_update", None)
    if "mailbox" not in selected:
        result.pop("mailbox", None)
    else:
        mailbox = result.get("mailbox", {})
        if "items" in mailbox:
            mailbox["items"] = mailbox["items"][: options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)]
            mailbox["limit"] = options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)
        if not options.get(CONF_MAILBOX_FULL_CONTENT, False):
            mailbox["full_content"] = False
            mailbox.pop("unread_before_fetch", None)
            for conversation in mailbox.get("items", []):
                conversation.pop("content_status", None)
                for message in conversation.get("messages", []):
                    message.pop("body", None)
    return result
