"""Per-hub data selection and compatibility with entries created before v1.0.16."""

from copy import deepcopy

from .additional_data import CONF_ADDITIONAL_DATA, STUDENT_RESOURCES

CONF_ENABLED_DATA = "enabled_data"
CONF_MAILBOX_FULL_CONTENT = "mailbox_full_content"
CONF_MAILBOX_LIMIT = "mailbox_limit"
DEFAULT_MAILBOX_LIMIT = 20
CONF_MAILBOX_ATTACHMENTS = "mailbox_attachments"
CONF_MAILBOX_ATTACHMENT_MAX_MB = "mailbox_attachment_max_mb"
DEFAULT_MAILBOX_ATTACHMENT_MAX_MB = 25
MIN_MAILBOX_ATTACHMENT_MAX_MB = 1
MAX_MAILBOX_ATTACHMENT_MAX_MB = 100
BYTES_PER_MB = 1024 * 1024

# Frozen historical default, including installations from v1.0.7. Never extend
# this tuple when adding a resource: upgrades must not enable new data sources.
LEGACY_CORE_DATA = ("homework", "behavior", "weekly_plan", "timetable", "lessons_history", "grades", "holidays")
DATA_KEYS = (*LEGACY_CORE_DATA, *STUDENT_RESOURCES, "mailbox", "parent_approvals")


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
    # Attachments need detail GETs; they never outlive full-content consent.
    if merged.get(CONF_MAILBOX_ATTACHMENTS) and not merged.get(CONF_MAILBOX_FULL_CONTENT):
        merged[CONF_MAILBOX_ATTACHMENTS] = False
    return merged


def _mailbox_selected(options):
    return "mailbox" in enabled_data(options)


def attachments_enabled(options):
    """Attachment downloads require mailbox, full content and their own opt-in."""
    return bool(
        options.get(CONF_MAILBOX_ATTACHMENTS) and options.get(CONF_MAILBOX_FULL_CONTENT) and _mailbox_selected(options)
    )


def attachment_max_bytes(options):
    """Per-file download cap when attachments are enabled, otherwise None."""
    if not attachments_enabled(options):
        return None
    return options.get(CONF_MAILBOX_ATTACHMENT_MAX_MB, DEFAULT_MAILBOX_ATTACHMENT_MAX_MB) * BYTES_PER_MB


# Opt-in -> (error key, prerequisite). Order matters: a reset full-content box
# must be seen by the attachments check that follows it.
MAILBOX_DEPENDENCIES = (
    (CONF_MAILBOX_FULL_CONTENT, "mailbox_required", _mailbox_selected),
    (
        CONF_MAILBOX_ATTACHMENTS,
        "full_content_required",
        lambda options: _mailbox_selected(options) and bool(options.get(CONF_MAILBOX_FULL_CONTENT)),
    ),
)


def mailbox_option_errors(submitted, current, reset_removed=False):
    """Return (submitted, errors) for mailbox opt-ins whose prerequisite is missing.

    With reset_removed (Configure form), removing a prerequisite that the hub
    had takes precedence over the old checked box, which is reset instead.
    """
    errors = {}
    for key, error, satisfied in MAILBOX_DEPENDENCIES:
        if not submitted.get(key) or satisfied({**current, **submitted}):
            continue
        if reset_removed and satisfied(current):
            submitted = {**submitted, key: False}
        else:
            errors[key] = error
    return submitted, errors


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
    # Metadata must describe retained data, not records purged on a failed
    # reload. Re-enabling those records must trigger a new startup fetch.
    retained = cached_selection(data) & selected
    if retained != cached_selection(data):
        result[CONF_ENABLED_DATA] = [key for key in DATA_KEYS if key in retained]
    if data.get(CONF_MAILBOX_FULL_CONTENT) and not options.get(CONF_MAILBOX_FULL_CONTENT, False):
        result[CONF_MAILBOX_FULL_CONTENT] = False
    if data.get(CONF_MAILBOX_ATTACHMENTS) and not attachments_enabled(options):
        result[CONF_MAILBOX_ATTACHMENTS] = False
    if options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT) < data.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT):
        result[CONF_MAILBOX_LIMIT] = options[CONF_MAILBOX_LIMIT]
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
    for key in {"mailbox", "parent_approvals"} - selected:
        result.pop(key, None)
    if "mailbox" in selected:
        _filter_mailbox(result.get("mailbox", {}), options)
    return result


def _filter_mailbox(mailbox, options):
    """Bound cached conversations and drop content the current consent excludes."""
    if "items" in mailbox:
        mailbox["items"] = mailbox["items"][: options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)]
        mailbox["limit"] = options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)
    full_content = options.get(CONF_MAILBOX_FULL_CONTENT, False)
    if not full_content:
        mailbox["full_content"] = False
        mailbox.pop("unread_before_fetch", None)
    for conversation in mailbox.get("items", []):
        if not full_content:
            conversation.pop("content_status", None)
        for message in conversation.get("messages", []):
            if not full_content:
                message.pop("body", None)
            if not attachments_enabled(options):
                message.pop("attachments", None)
