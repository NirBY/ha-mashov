"""Sensor platform for the Mashov integration.

Per student (one HA device per student id) the platform creates:
- ``MashovListSensor`` for the core lists (homework, behavior, weekly plan,
  timetable, lessons history, grades). State = item count; attributes carry a
  size-bounded copy of the items plus Hebrew formatted views for cards/TTS.
- ``MashovAdditionalSensor`` for optional portal resources the user enabled
  in the options flow (``CONF_ADDITIONAL_DATA``).

Per hub (config entry) it also creates one ``MashovHolidaysSensor``.

Students are added dynamically when the coordinator reports new ones, and
departed students' entities/devices are cleaned up only after a verified
successful login (see ``async_setup_entry``). Whenever the portal reports a
resource as not ``ok`` (``source_status``), the state is ``None`` (unknown)
rather than 0, so a failed fetch is never mistaken for an empty list.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.json import json_bytes
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _local_timestamp(value: float | None) -> str | None:
    """Format a coordinator timestamp in the Home Assistant timezone."""
    if not value:
        return None
    return dt_util.as_local(datetime.fromtimestamp(value, tz=dt_util.UTC)).isoformat(timespec="seconds")


# NOTE: these package imports sit below the helper above for historical reasons; order is harmless.
from .additional_data import CONF_ADDITIONAL_DATA, STUDENT_RESOURCES
from .const import (
    CONF_MAX_ITEMS_IN_ATTRIBUTES,
    CONF_SCHEDULE_DAY,
    CONF_SCHEDULE_DAYS,
    CONF_SCHEDULE_INTERVAL,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_TYPE,
    DEFAULT_MAX_ITEMS_IN_ATTRIBUTES,
    DEFAULT_SCHEDULE_DAY,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_TYPE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SENSOR_KEY_BEHAVIOR,
    SENSOR_KEY_GRADES,
    SENSOR_KEY_HOMEWORK,
    SENSOR_KEY_LESSONS_HISTORY,
    SENSOR_KEY_TIMETABLE,
    SENSOR_KEY_WEEKLY_PLAN,
)
from .entity import MashovEntity, MashovStudentEntity
from .holidays_utils import (
    HOLIDAY_DEFAULT_NAME,
    HOLIDAY_ICON,
    create_holidays_device_info,
    parse_iso_date_to_date,
    parse_iso_date_to_formatted,
)


def _async_migrate_list_sensor_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Scope legacy `mashov_<student>_<key>` ids to the entry, keeping entity ids and history.

    Two hubs that see the same child (e.g. both parents) otherwise collide on the same unique id.

    Only list-sensor ids of this entry are touched, and an id is rewritten only if the
    target id is free, so the migration is idempotent and never clobbers another entity.
    """
    registry = er.async_get(hass)
    new_prefix = f"mashov_{entry.entry_id}_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = reg_entry.unique_id
        if (
            reg_entry.domain != "sensor"
            or reg_entry.platform != DOMAIN
            or not unique_id.startswith("mashov_")
            or unique_id.startswith(new_prefix)
            or not any(
                unique_id.endswith(f"_{key}")
                for key in (
                    SENSOR_KEY_HOMEWORK,
                    SENSOR_KEY_BEHAVIOR,
                    SENSOR_KEY_WEEKLY_PLAN,
                    SENSOR_KEY_TIMETABLE,
                    SENSOR_KEY_LESSONS_HISTORY,
                    SENSOR_KEY_GRADES,
                )
            )
        ):
            continue
        new_unique_id = new_prefix + unique_id[len("mashov_") :]
        if registry.async_get_entity_id("sensor", DOMAIN, new_unique_id) is None:
            registry.async_update_entity(reg_entry.entity_id, new_unique_id=new_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Mashov sensors and keep them in sync with the student roster.

    ``sync_students`` runs once now and again after every coordinator update, so
    students who join later get sensors without reloading the entry.
    """
    _LOGGER.debug("Setting up sensors for entry: %s", entry.title)
    # Must run before entities are created so they pick up the migrated registry entries.
    _async_migrate_list_sensor_unique_ids(hass, entry)
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data["coordinator"]

    # Student ids that already have entities in this session.
    known = set()

    @callback
    def sync_students():
        """Remove departed students' entities/devices, then add entities for new students."""
        students = (coord.data or {}).get("students", [])
        # --- Cleanup of departed students / disabled optional resources ---
        # Only a real, successful login can prove that a student left this hub.
        # Cached session metadata, failed refreshes and empty rosters cannot delete entries.
        if (
            students
            and getattr(coord.client, "roster_refreshed", False) is True
            and not coord.data_stale
            and coord.last_update_success
        ):
            active = {str(stu["id"]) for stu in students}
            registry = er.async_get(hass)
            prefix = f"mashov_{entry.entry_id}_"
            keys = (
                SENSOR_KEY_HOMEWORK,
                SENSOR_KEY_BEHAVIOR,
                SENSOR_KEY_WEEKLY_PLAN,
                SENSOR_KEY_TIMETABLE,
                SENSOR_KEY_LESSONS_HISTORY,
                SENSOR_KEY_GRADES,
                *STUDENT_RESOURCES,
            )
            for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
                if (
                    registered.domain != "sensor"
                    or registered.platform != DOMAIN
                    or not registered.unique_id.startswith(prefix)
                ):
                    continue
                # unique_id = mashov_<entry>_<student_id>_<key>. Keys can contain "_" and one key
                # may be a suffix of another, so try the longest keys first.
                tail = registered.unique_id[len(prefix) :]
                for key in sorted(keys, key=len, reverse=True):
                    suffix = f"_{key}"
                    if tail.endswith(suffix):
                        student_id = tail[: -len(suffix)]
                        enabled_additional = set(entry.options.get(CONF_ADDITIONAL_DATA) or [])
                        # Remove sensors of students no longer on the roster, and optional
                        # resource sensors the user has since disabled in options.
                        if student_id not in active or (key in STUDENT_RESOURCES and key not in enabled_additional):
                            registry.async_remove(registered.entity_id)
                        break
            # Entity cleanup alone leaves an undeletable student card behind.
            # Detach only this hub, preserving devices shared with another hub.
            # A device is removed only if: it is a student device of ours (not the holidays
            # device), none of its ids is an active student, and no entity of this entry remains.
            devices = dr.async_get(hass)
            for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
                identifiers = {value for domain, value in device.identifiers if domain == DOMAIN}
                if (
                    identifiers
                    and not any(value.startswith("holidays_") for value in identifiers)
                    and identifiers.isdisjoint(active)
                    and not any(
                        entity.config_entry_id == entry.entry_id
                        for entity in er.async_entries_for_device(registry, device.id)
                    )
                ):
                    if hasattr(device, "config_entry_id"):
                        # New HA registries scope each device to one config entry.
                        devices.async_remove_device(device.id)
                    else:
                        # Older registries: unlink this entry; HA deletes the device once orphaned.
                        devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
            # Forget departed students so their sensors are recreated if they return.
            known.intersection_update({stu["id"] for stu in students})
        # --- Create entities for students not seen before ---
        entities = []
        for stu in students:
            if stu["id"] in known:
                continue
            known.add(stu["id"])
            slug = stu["slug"]
            sid = stu["id"]
            name = stu["name"]
            _LOGGER.debug("Creating sensors for student: %s (id=%s, slug=%s)", name, sid, slug)

            entities.extend(
                [
                    MashovListSensor(
                        coord, entry.entry_id, sid, slug, name, SENSOR_KEY_HOMEWORK, "Homework", "homework"
                    ),
                    MashovListSensor(
                        coord, entry.entry_id, sid, slug, name, SENSOR_KEY_BEHAVIOR, "Behavior", "behavior"
                    ),
                    MashovListSensor(
                        coord, entry.entry_id, sid, slug, name, SENSOR_KEY_WEEKLY_PLAN, "Weekly Plan", "weekly_plan"
                    ),
                    MashovListSensor(
                        coord, entry.entry_id, sid, slug, name, SENSOR_KEY_TIMETABLE, "Timetable", "timetable"
                    ),
                    MashovListSensor(
                        coord,
                        entry.entry_id,
                        sid,
                        slug,
                        name,
                        SENSOR_KEY_LESSONS_HISTORY,
                        "Lessons History",
                        "lessons_history",
                    ),
                    MashovListSensor(coord, entry.entry_id, sid, slug, name, SENSOR_KEY_GRADES, "Grades", "grades"),
                ]
            )
            for key in entry.options.get(CONF_ADDITIONAL_DATA, []):
                if key in STUDENT_RESOURCES:
                    entities.append(MashovAdditionalSensor(coord, sid, slug, name, key, entry.entry_id))

        if entities:
            async_add_entities(entities)

    sync_students()
    # One holidays sensor per hub (holidays are per school, not per student).
    async_add_entities([MashovHolidaysSensor(coord, entry.entry_id)])
    entry.async_on_unload(coord.async_add_listener(sync_students))


def _student_meta(data: dict, student_id, fallback_slug: str) -> dict:
    """Find a student by stable id; the slug embeds the class name and changes every school year.

    Falls back to the slug captured at entity creation, then to an empty dict.
    """
    return next(
        (s for s in data.get("students", []) if s.get("id") == student_id),
        next((s for s in data.get("students", []) if s.get("slug") == fallback_slug), {}),
    )


def _student_group(data: dict, student_id, fallback_slug: str) -> dict:
    """Return the student's data bucket; coordinator data is keyed by the *current* slug."""
    slug = _student_meta(data, student_id, fallback_slug).get("slug", fallback_slug)
    return data.get("by_slug", {}).get(slug, {})


class MashovAdditionalSensor(MashovStudentEntity, SensorEntity):
    """Optional portal data; an inaccessible resource is not an empty list.

    State is the item count only when the resource status is ``ok``; otherwise
    (``not_fetched``, forbidden, error, ...) the state is unknown.
    """

    _attr_icon = "mdi:school"

    def __init__(self, coordinator, student_id, slug, name, key, entry_id):
        super().__init__(coordinator)
        self._student_id = student_id
        self._slug = slug
        self._student_name = name
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"mashov_{entry_id}_{student_id}_{key}"

    @property
    def _resource(self):
        """The ``{"items": [...], "status": ...}`` record for this resource, looked up by student id."""
        return (
            _student_group(self.coordinator.data or {}, self._student_id, self._slug)
            .get("additional_data", {})
            .get(self._key, {"items": [], "status": "not_fetched"})
        )

    @property
    def available(self):
        return super().available

    @property
    def native_value(self):
        return len(self._resource.get("items", [])) if self.available and self._resource.get("status") == "ok" else None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._student_id))},
            "name": f"Mashov – {self.student_name}",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }

    @property
    def extra_state_attributes(self):
        import json

        resource = self._resource
        items = resource.get("items", [])
        entry = getattr(self.coordinator, "entry", None)
        options = getattr(entry, "options", {})
        raw_limit = options.get(CONF_MAX_ITEMS_IN_ATTRIBUTES, DEFAULT_MAX_ITEMS_IN_ATTRIBUTES)
        try:
            limit = max(10, min(500, int(raw_limit if raw_limit is not None else DEFAULT_MAX_ITEMS_IN_ATTRIBUTES)))
        except (ValueError, TypeError):
            limit = DEFAULT_MAX_ITEMS_IN_ATTRIBUTES
        stored = []
        # Bound the complete item array, even when one notice/document is enormous.
        # Oversized items are skipped (not truncated) so later small items can still fit;
        # 12KB leaves headroom for the other attributes under HA's 16KB recorder limit.
        for item in items:
            if len(stored) >= limit:
                break
            if len(json.dumps([*stored, item], ensure_ascii=True).encode("utf-8")) <= 12 * 1024:
                stored.append(item)
        return {
            "student_name": self.student_name,
            "data_stale": self.data_stale,
            "source_status": resource.get("status", "not_fetched"),
            "total_items": len(items),
            "stored_items": len(stored),
            "items": stored,
            "last_update": _local_timestamp(getattr(self.coordinator, "last_successful_update", None)),
        }


class MashovListSensor(MashovStudentEntity, SensorEntity):
    """Count of one core per-student list (homework, grades, timetable, ...).

    ``data_key`` selects the list inside the student's coordinator bucket. The
    attributes expose a recent, cleaned, size-bounded subset of the items plus
    Hebrew formatted views, all kept under the recorder's attribute size limit.
    """

    _attr_icon = "mdi:school"

    def __init__(
        self,
        coordinator,
        entry_id: str,
        student_id: int,
        student_slug: str,
        student_name: str,
        key: str,
        name: str,
        data_key: str,
    ):
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_slug = student_slug
        self._student_name = student_name
        self._key = key
        self._data_key = data_key
        self._attr_translation_key = key
        # Scoped to the entry: the same child can appear under two hubs (e.g. both parents).
        self._attr_unique_id = f"mashov_{entry_id}_{student_id}_{key}"

    @property
    def native_value(self):
        group = _student_group(self.coordinator.data or {}, self._student_id, self._student_slug)
        items = group.get(self._data_key) or []
        # A failed/forbidden fetch reports unknown instead of a misleading 0. Missing status means ok
        # (older coordinator data had no source_status).
        return len(items) if group.get("source_status", {}).get(self._data_key, "ok") == "ok" else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        student_meta = _student_meta(data, self._student_id, self._student_slug)
        group = _student_group(data, self._student_id, self._student_slug)
        items = group.get(self._data_key) or []
        if self._data_key == "weekly_plan":
            # Weekly plan items only carry a group id; borrow subject/teacher from the timetable.
            items = self._with_plan_subjects(items, group.get("timetable") or [])

        # Schedule info
        schedule_info = self._compute_schedule_info()

        # Get max items config (from options or default)
        max_items = self._get_max_items_config()

        # Store only recent items to avoid DB size issues (Issue #2).
        # Full data is always available via coordinator.data for automations.
        # Formatting is done on the limited subset so the formatted views stay small too.
        items_for_attributes = self._limit_items_for_storage(items, max_items)
        formatted_data = self._format_data_for_display(items_for_attributes)

        total_count = len(items)
        stored_count = len(items_for_attributes)

        attributes = {
            "student_name": self.student_name,
            "data_stale": self.data_stale,
            "source_status": group.get("source_status", {}).get(self._data_key, "ok"),
            "student_id": self._student_id,
            "year": student_meta.get("year"),
            "school_id": student_meta.get("school_id"),
            "last_update": _local_timestamp(getattr(self.coordinator, "last_successful_update", None)),
            "total_items": total_count,  # Total number of items available
            "stored_items": stored_count,  # Number of items in attributes
            "items": items_for_attributes,  # Limited items (most recent)
            "formatted_summary": formatted_data["summary"],
            "formatted_by_date": formatted_data["by_date"],
            "formatted_by_subject": formatted_data["by_subject"],
            **(
                {"formatted_table_html": formatted_data.get("table_html")}
                if isinstance(formatted_data, dict) and formatted_data.get("table_html")
                else {}
            ),
            # Refresh schedule
            "schedule_type": schedule_info.get("type"),
            "schedule_time": schedule_info.get("time"),
            "schedule_day": schedule_info.get("day"),
            "schedule_interval_minutes": schedule_info.get("interval_minutes"),
            "schedule_friendly": schedule_info.get("friendly"),
            "next_scheduled_refresh": schedule_info.get("next"),
        }
        # Final pass: the per-item limit ignores the formatted fields, which duplicate the items.
        return self._bound_attributes(attributes)

    @staticmethod
    def _with_plan_subjects(items: list, timetable: list) -> list:
        """Name weekly-plan lessons from the timetable groups; plans only carry a group id.

        Items that already have a subject are left untouched; items are copied, never mutated,
        so the coordinator's data is not altered.
        """
        # group_id -> (subject name or group name, first teacher's name)
        lookup = {}
        for entry in timetable:
            details = (entry or {}).get("groupDetails") or {}
            if details.get("groupId") is None:
                continue
            teachers = details.get("groupTeachers") or []
            teacher = (teachers[0] or {}).get("teacherName") if isinstance(teachers, list) and teachers else None
            lookup[details["groupId"]] = (details.get("subjectName") or details.get("groupName"), teacher)
        enriched = []
        for item in items:
            if isinstance(item, dict) and not item.get("subject") and item.get("group_id") in lookup:
                subject, teacher = lookup[item["group_id"]]
                item = {**item, "subject": subject, **({"teacher": teacher} if teacher else {})}
            enriched.append(item)
        return enriched

    @staticmethod
    def _bound_attributes(attributes: dict) -> dict:
        """Budget the complete payload, including duplicated formatted content.

        HA's recorder refuses to store state attributes over 16KB. Degrade in order of
        least value: drop the formatted views (table, by-subject, by-date), shorten the
        summary, then binary-search the largest item prefix that fits. The
        ``items_truncated`` / ``formatting_truncated`` flags tell cards what was cut.
        Mutates and returns ``attributes``.
        """
        budget = 14 * 1024  # Leave room for HA's icon/friendly_name attributes.

        def size():
            return len(json_bytes(attributes))

        attributes["items_truncated"] = attributes["stored_items"] < attributes["total_items"]
        attributes["formatting_truncated"] = False
        if size() <= budget:
            return attributes
        attributes["formatting_truncated"] = True
        # Retain raw items for cards before retaining duplicate presentation fields.
        for key in ("formatted_table_html", "formatted_by_subject", "formatted_by_date"):
            if key in attributes:
                attributes[key] = {} if key != "formatted_table_html" else ""
            if size() <= budget:
                return attributes
        attributes["formatted_summary"] = str(attributes.get("formatted_summary", ""))[:256]
        # Still too big: keep the largest prefix of items (already most-recent-first) that fits.
        items = attributes["items"]
        low, high, best = 0, len(items), 0
        while low <= high:
            count = (low + high) // 2
            attributes["items"] = items[:count]
            attributes["stored_items"] = count
            attributes["items_truncated"] = count < attributes["total_items"]
            if size() <= budget:
                best = count
                low = count + 1
            else:
                high = count - 1
        attributes["items"] = items[:best]
        attributes["stored_items"] = best
        attributes["items_truncated"] = best < attributes["total_items"]
        return attributes

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self._student_id}")},
            "name": f"Mashov – {self.student_name}",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }

    def _get_max_items_config(self) -> int:
        """Get the maximum items to store in attributes from config."""
        try:
            opts = getattr(self.coordinator, "entry", None).options if hasattr(self.coordinator, "entry") else {}
            max_items = opts.get(CONF_MAX_ITEMS_IN_ATTRIBUTES, DEFAULT_MAX_ITEMS_IN_ATTRIBUTES)
            return max(10, min(500, int(max_items)))  # Clamp between 10 and 500
        except Exception:
            return DEFAULT_MAX_ITEMS_IN_ATTRIBUTES

    def _clean_item_for_storage(self, item: dict) -> dict:
        """Remove redundant fields from item to reduce storage size.

        Keeps only user-relevant fields, removing technical IDs and duplicate data.
        This can reduce item size by 40-50%.
        """
        if not isinstance(item, dict):
            return item

        # Common fields to remove (GUIDs, codes, technical IDs)
        remove_fields = {
            "studentGuid",
            "student_guid",
            "reporterGuid",
            "reporter_guid",
            "lessonReporter",
            "lesson_reporter",
            "eventCode",
            "event_code",
            "achvaCode",
            "achva_code",
            "justificationId",
            "justification_id",
            "lessonId",
            "lesson_id",
            "groupId",
            "group_id",
            "lessonType",
            "lesson_type",
            "achvaAval",
            "achva_aval",
            "justified",
            # Grades-specific fields to remove
            "gradingEventId",
            "gradeTypeId",
            "id",  # Generic ID field
            "rate",
            "gradeRate",
        }

        cleaned = {}
        for key, value in item.items():
            # Skip redundant fields
            if key in remove_fields:
                continue

            # Handle nested structures
            if key == "timeTable" and isinstance(value, dict):
                # Keep timeTable but clean it
                tt = {k: v for k, v in value.items() if k not in remove_fields}
                cleaned[key] = tt
            elif key == "groupDetails" and isinstance(value, dict):
                # Keep groupDetails but only essential fields
                gd = {}
                if "subjectName" in value:
                    gd["subjectName"] = value["subjectName"]
                if "groupName" in value:
                    gd["groupName"] = value["groupName"]
                if "groupTeachers" in value and isinstance(value["groupTeachers"], list):
                    # Keep only teacher names, not GUIDs
                    gd["groupTeachers"] = [
                        {"teacherName": t.get("teacherName")}
                        for t in value["groupTeachers"]
                        if isinstance(t, dict) and t.get("teacherName")
                    ]
                cleaned[key] = gd
            elif key == "lessonLog" and isinstance(value, dict):
                # Keep lessonLog but clean it
                ll = {k: v for k, v in value.items() if k not in remove_fields}
                cleaned[key] = ll
            else:
                # Keep all other fields
                cleaned[key] = value

        return cleaned

    def _limit_items_for_storage(self, items: list, max_items: int) -> list:
        """Limit items for storage in attributes to avoid DB size issues.

        Uses intelligent size-based limiting with a 14KB target (16KB limit with 2KB safety margin).
        Keeps the most recent items based on date fields.
        Full data remains available via coordinator.data.

        Order of operations: sort newest first, cut to the user's ``max_items``, strip technical
        fields, then (if still over budget) binary-search the largest count that fits.
        ``_bound_attributes`` later re-checks the whole attribute payload.
        """
        if not items:
            return items

        import json

        # Try to sort by date to keep most recent
        date_fields = ["lesson_date", "timestamp", "lessonDate"]

        def get_sort_key(item):
            """Extract sortable date/time from item.

            Returns an ISO date string, a ``(day, lesson)`` tuple for timetable entries, or "".
            Mixing tuples and strings raises TypeError, which the caller catches and falls
            back to the original order.
            """
            # For nested structures (timetable, weekly_plan)
            if isinstance(item, dict):
                # Check nested structures first
                if "timeTable" in item:
                    tt = item.get("timeTable", {})
                    # Timetables are recurring, use day+lesson as sort key
                    return (tt.get("day", 0), tt.get("lesson", 0))

                # Check for lessonLog in lessons_history
                if "lessonLog" in item:
                    ll = item.get("lessonLog", {})
                    for field in date_fields:
                        val = ll.get(field)
                        if val:
                            return val

                # Direct date fields
                for field in date_fields:
                    val = item.get(field)
                    if val:
                        return val

            return ""

        try:
            # Sort by date descending (most recent first)
            sorted_items = sorted(items, key=get_sort_key, reverse=True)
        except Exception as e:
            _LOGGER.debug("Failed to sort items for limiting: %s", e)
            sorted_items = items

        # Smart size-based limiting with 14KB target (2KB safety margin from 16KB limit)
        MAX_SIZE_BYTES = 14 * 1024  # 14KB

        # Start with user's max_items preference
        limited = sorted_items[:max_items]

        # Clean items to remove redundant fields (saves 40-50% space)
        cleaned = [self._clean_item_for_storage(item) for item in limited]

        try:
            # Check actual JSON size after cleaning
            size = len(json.dumps(cleaned))

            # If under limit, we're good
            if size <= MAX_SIZE_BYTES:
                return cleaned

            # If over limit, binary search to find optimal count
            _LOGGER.debug(
                "Items exceed size limit (%d bytes > %d). Finding optimal count...",
                size,
                MAX_SIZE_BYTES,
            )

            left, right = 1, len(limited)
            best_count = 0

            while left <= right:
                mid = (left + right) // 2
                test_items = [self._clean_item_for_storage(item) for item in sorted_items[:mid]]
                test_size = len(json.dumps(test_items))

                if test_size <= MAX_SIZE_BYTES:
                    best_count = mid
                    left = mid + 1
                else:
                    right = mid - 1

            result = [self._clean_item_for_storage(item) for item in sorted_items[:best_count]]
            _LOGGER.info(
                "Limited %s from %d items (%d bytes) to %d items (%d bytes) to fit 14KB target",
                self._data_key,
                len(limited),
                size,
                best_count,
                len(json.dumps(result)),
            )
            return result

        except Exception as e:
            _LOGGER.warning("Failed to check item sizes, using count-based limit: %s", e)
            # Fallback: use conservative count with cleaning
            # After cleaning: ~350 bytes/item → ~40 items = ~14KB
            safe_count = min(40, len(sorted_items))
            return [self._clean_item_for_storage(item) for item in sorted_items[:safe_count]]

    def _format_data_for_display(self, items: list) -> dict[str, Any]:
        """Format data for better readability and text-to-speech.

        Returns Hebrew ``summary``, ``by_date`` and ``by_subject`` views; the weekly plan and
        timetable formatters may also return ``table_html``.
        """
        if not items:
            return {"summary": "אין נתונים זמינים", "by_date": {}, "by_subject": {}}

        if self._data_key == "homework":
            return self._format_homework_data(items)
        if self._data_key == "behavior":
            return self._format_behavior_data(items)
        if self._data_key == "weekly_plan":
            return self._format_weekly_plan_data(items)
        if self._data_key == "timetable":
            return self._format_timetable_data(items)
        if self._data_key == "lessons_history":
            return self._format_lessons_history(items)
        if self._data_key == "grades":
            return self._format_grades_data(items)
        return {"summary": f"יש {len(items)} פריטים", "by_date": {}, "by_subject": {}}

    def _compute_schedule_info(self) -> dict[str, Any]:
        """Return current refresh schedule configuration and friendly description.

        Display-only: mirrors the coordinator's schedule (entry options overlaid with any
        YAML options), sanitizing each value and falling back to defaults when invalid.
        ``next`` is an estimate computed here, not read from the coordinator's timer.
        Any unexpected error yields the default schedule rather than breaking attributes.
        """
        try:
            from datetime import timedelta

            opts = getattr(self.coordinator, "entry", None).options if hasattr(self.coordinator, "entry") else {}
            # Merge YAML overrides if present
            yaml_opts = (
                getattr(self.coordinator, "hass", None).data.get(DOMAIN, {}).get("yaml_options", {})
                if hasattr(self.coordinator, "hass")
                else {}
            )
            merged = dict(opts)
            if yaml_opts:
                merged.update({k: v for k, v in yaml_opts.items() if v is not None})
            # Basic sanitization for attributes display
            # Time must be HH:MM or HH:MM:SS; seconds are kept for the next-run estimate.
            schedule_type = merged.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE)
            if schedule_type not in ("daily", "weekly", "interval"):
                schedule_type = DEFAULT_SCHEDULE_TYPE
            schedule_time = str(merged.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME))
            try:
                parts = [int(x) for x in schedule_time.split(":")]
                hh, mm = parts[:2]
                ss = parts[2] if len(parts) > 2 else 0
                if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59 and len(parts) in (2, 3)):
                    raise ValueError
            except Exception:
                schedule_time = DEFAULT_SCHEDULE_TIME
                ss = 0
            try:
                schedule_day = int(merged.get(CONF_SCHEDULE_DAY, DEFAULT_SCHEDULE_DAY))
            except Exception:
                schedule_day = DEFAULT_SCHEDULE_DAY
            # Multi-day weekly schedule (0=Monday..6=Sunday); falls back to the legacy single day.
            raw_days = merged.get(CONF_SCHEDULE_DAYS, [schedule_day])
            schedule_days = []
            if isinstance(raw_days, list):
                for d in raw_days:
                    try:
                        di = int(d)
                        if 0 <= di <= 6:
                            schedule_days.append(di)
                    except Exception:
                        pass
            if not schedule_days:
                schedule_days = [schedule_day]
            try:
                schedule_interval = int(merged.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL))
                if schedule_interval < 5 or schedule_interval > 1440:
                    schedule_interval = DEFAULT_SCHEDULE_INTERVAL
            except Exception:
                schedule_interval = DEFAULT_SCHEDULE_INTERVAL

            # --- Friendly Hebrew description and next-run estimate per schedule type ---
            friendly = None
            next_time_iso = None
            now = dt_util.now()

            if schedule_type == "daily":
                try:
                    hh, mm = (int(x) for x in str(schedule_time).split(":")[:2])
                except Exception:
                    hh, mm = (int(x) for x in DEFAULT_SCHEDULE_TIME.split(":"))
                next_dt = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                if next_dt <= now:
                    next_dt = next_dt + timedelta(days=1)
                friendly = f"יומי בשעה {hh:02d}:{mm:02d}"
                next_time_iso = next_dt.isoformat(timespec="seconds")
            elif schedule_type == "weekly":
                try:
                    hh, mm = (int(x) for x in str(schedule_time).split(":")[:2])
                except Exception:
                    hh, mm = (int(x) for x in DEFAULT_SCHEDULE_TIME.split(":"))
                # Our 0=Monday mapping; Python weekday(): Monday=0
                # Compute next closest day from the list
                candidates = []
                for target_wd in schedule_days:
                    target_wd = int(target_wd)
                    days_ahead = (target_wd - now.weekday()) % 7
                    dt = now.replace(hour=hh, minute=mm, second=ss, microsecond=0) + timedelta(days=days_ahead)
                    if dt <= now:
                        dt = dt + timedelta(days=7)
                    candidates.append(dt)
                next_dt = min(candidates) if candidates else now
                # Indexed with the same 0=Monday mapping.
                day_names = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "יום שבת", "יום ראשון"]
                friendly_days = ", ".join(day_names[int(d)] for d in schedule_days)
                friendly = f"שבועי – {friendly_days} {hh:02d}:{mm:02d}"
                next_time_iso = next_dt.isoformat(timespec="seconds")
            elif schedule_type == "interval":
                interval_min = int(schedule_interval)
                # Approximation: measured from now, not from the last actual refresh.
                next_dt = now + timedelta(minutes=interval_min)
                friendly = f"כל {interval_min} דקות"
                next_time_iso = next_dt.isoformat(timespec="seconds")
            else:
                friendly = "ברירת מחדל (24 שעות)"

            return {
                "type": schedule_type,
                "time": schedule_time,
                "day": schedule_day,
                "interval_minutes": schedule_interval,
                "friendly": friendly,
                "next": next_time_iso,
            }
        except Exception as e:
            _LOGGER.debug("Failed computing schedule info: %s", e)
            return {
                "type": DEFAULT_SCHEDULE_TYPE,
                "time": DEFAULT_SCHEDULE_TIME,
                "day": DEFAULT_SCHEDULE_DAY,
                "interval_minutes": DEFAULT_SCHEDULE_INTERVAL,
                "friendly": "",
                "next": None,
            }

    def _format_homework_data(self, items: list) -> dict[str, Any]:
        """Format homework data for display"""

        by_date = {}
        by_subject = {}

        for item in items:
            # Format date
            date_str = item.get("lesson_date", "")
            if date_str:
                try:
                    date_obj = parse_iso_date_to_date(date_str)
                    formatted_date = date_obj.strftime("%d/%m/%Y")
                except Exception:
                    formatted_date = date_str
            else:
                formatted_date = "תאריך לא ידוע"

            # Group by date
            if formatted_date not in by_date:
                by_date[formatted_date] = []

            # Group by subject
            subject = item.get("subject_name", "מקצוע לא ידוע")
            if subject not in by_subject:
                by_subject[subject] = []

            # Format homework entry
            homework_text = item.get("homework", "")
            remark = item.get("remark", "")
            lesson = item.get("lesson", "")
            subject_name = item.get("subject_name", "")

            entry = f"שיעור {lesson} - {subject_name}: {homework_text}"
            if remark and remark != homework_text:
                entry += f" ({remark})"

            by_date[formatted_date].append(entry)
            by_subject[subject].append(entry)

        # Create summary
        total_homework = len(items)
        subjects_count = len(by_subject)
        dates_count = len(by_date)

        summary = f"יש {total_homework} שיעורים ב-{subjects_count} מקצועות על פני {dates_count} תאריכים"

        return {"summary": summary, "by_date": by_date, "by_subject": by_subject}

    def _format_behavior_data(self, items: list) -> dict[str, Any]:
        """Format behavior data for display"""

        by_date = {}
        by_type = {}

        for item in items:
            # Format date
            date_str = item.get("lesson_date", "")
            if date_str:
                try:
                    date_obj = parse_iso_date_to_date(date_str)
                    formatted_date = date_obj.strftime("%d/%m/%Y")
                except Exception:
                    formatted_date = date_str
            else:
                formatted_date = "תאריך לא ידוע"

            # Group by date
            if formatted_date not in by_date:
                by_date[formatted_date] = []

            # Group by behavior type
            behavior_type = item.get("achva_name", "סוג לא ידוע")
            if behavior_type not in by_type:
                by_type[behavior_type] = []

            # Format behavior entry
            subject = item.get("subject", "")
            lesson = item.get("lesson", "")
            reporter = item.get("reporter", "")

            entry = f"שיעור {lesson} - {subject}: {behavior_type}"
            if reporter:
                entry += f" (מ-{reporter})"

            by_date[formatted_date].append(entry)
            by_type[behavior_type].append(entry)

        # Create summary
        total_events = len(items)
        types_count = len(by_type)
        dates_count = len(by_date)

        summary = f"יש {total_events} אירועי התנהגות ב-{types_count} סוגים על פני {dates_count} תאריכים"

        return {
            "summary": summary,
            "by_date": by_date,
            "by_subject": by_type,  # Using by_subject key for consistency
        }

    def _format_weekly_plan_data(self, items: list) -> dict[str, Any]:
        """Format weekly plan data for display, including a weekly table view.

        Two item shapes are supported:
        - Timetable-like items (``timeTable``/``groupDetails`` or flat ``day``/``lesson``):
          rendered as a lessons x weekdays grid.
        - Dated plan items (``lesson_date``): span several weeks, so they are rendered as a
          simple date/lesson/subject/plan table instead of a weekday grid.
        """

        by_date: dict[str, list] = {}
        by_subject: dict[str, list] = {}

        # Collect normalized entries for table construction
        normalized: list[dict[str, Any]] = []

        for item in items:
            # Backwards compatible fields
            tt = item.get("timeTable") or {}
            gd = item.get("groupDetails") or {}

            day_raw = tt.get("day", item.get("day"))
            lesson_raw = tt.get("lesson", item.get("lesson"))
            room = str(tt.get("roomNum") or item.get("room") or "").strip()
            plan = str(item.get("plan") or "").strip()
            subject = gd.get("subjectName") or item.get("subject") or gd.get("groupName") or "מקצוע לא ידוע"

            teacher = None
            teachers = gd.get("groupTeachers") or []
            if isinstance(teachers, list) and teachers:
                teacher = (teachers[0] or {}).get("teacherName")
            if not teacher:
                teacher = item.get("teacher") or "מורה לא ידוע"

            # For legacy formatting by date (if exists)
            date_str = item.get("lesson_date", "")
            if date_str:
                try:
                    date_obj = parse_iso_date_to_date(date_str)
                    formatted_date = date_obj.strftime("%d/%m/%Y")
                except Exception:
                    formatted_date = date_str
                if formatted_date not in by_date:
                    by_date[formatted_date] = []
                by_date[formatted_date].append(f"שיעור {lesson_raw}: {subject}{' – ' + plan if plan else ''}")
            else:
                formatted_date = ""

            if plan:
                by_subject.setdefault(subject, []).append(f"{formatted_date} שיעור {lesson_raw}: {plan}".strip())
            else:
                by_subject.setdefault(subject, []).append(f"שיעור {lesson_raw}{' (' + room + ')' if room else ''}")

            try:
                day_i = int(day_raw) if day_raw is not None else None
                lesson_i = int(lesson_raw) if lesson_raw is not None else None
            except Exception:
                day_i, lesson_i = None, None

            normalized.append(
                {
                    "day": day_i,
                    "lesson": lesson_i,
                    "subject": subject,
                    "teacher": teacher,
                    "room": room,
                }
            )

        # Dated plans: flat table (early return, no weekday grid).
        if any(item.get("lesson_date") for item in items):
            rows = []
            for item in items:
                parsed = parse_iso_date_to_date(item.get("lesson_date"))
                if parsed:
                    cells = [
                        parsed.isoformat(),
                        str(item.get("lesson") or ""),
                        str(item.get("subject") or ""),
                        str(item.get("plan") or ""),
                    ]
                    rows.append("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in cells) + "</tr>")
            return {
                "summary": f"יש {len(items)} שיעורים מתוכננים ב-{len(by_subject)} מקצועות על פני {len(by_date)} ימים",
                "by_date": by_date,
                "by_subject": by_subject,
                "table_html": '<table dir="auto"><tbody>' + "".join(rows) + "</tbody></table>" if rows else "",
            }

        # Determine day mapping and headers.
        # Mashov sources disagree on weekday numbering: if no 0 appears and all days are >= 1,
        # treat them as 1=Sunday..7=Saturday; otherwise as 0=Monday..6=Sunday. The column
        # order (headers) follows the detected convention.
        day_values = [n["day"] for n in normalized if isinstance(n.get("day"), int)]
        uses_sunday_based = False
        if day_values and 0 not in day_values and min(day_values) >= 1:
            # Assume 1..7 (Sun..Sat). Many datasets in Mashov weekly use this.
            uses_sunday_based = True

        headers_sun = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
        headers_mon = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]

        if uses_sunday_based:
            headers = headers_sun

            def to_col(d):
                return max(0, min(6, int(d) - 1))  # 1->0 ... 7->6
        else:
            headers = headers_mon

            def to_col(d):
                return max(0, min(6, int(d)))  # 0=Monday through 6=Sunday

        # Determine max lessons: at least 8 rows by default, clamped to 6..12.
        max_lessons = max([n["lesson"] or 0 for n in normalized] + [8])
        if max_lessons < 6:
            max_lessons = 6
        if max_lessons > 12:
            max_lessons = 12

        # Build table matrix (rows = lessons, cols = weekdays). Out-of-range lessons are clamped
        # into the last/first row; a later item in the same cell overwrites an earlier one.
        table_rows: list[list[str]] = [["" for _ in range(7)] for _ in range(max_lessons)]
        for n in normalized:
            if not isinstance(n.get("day"), int) or not isinstance(n.get("lesson"), int):
                continue
            col = to_col(n["day"])
            row = max(1, min(max_lessons, n["lesson"])) - 1
            text = n["subject"]
            if n.get("teacher"):
                text += f" – {n['teacher']}"
            if n.get("room"):
                text += f" ({n['room']})"
            table_rows[row][col] = text

        # HTML table (works inside Markdown card); uses HA theme CSS variables, cell text is escaped.
        html = [
            '<table style="width:100%; border-collapse:collapse; text-align:center; direction:rtl;">',
            "<thead><tr>"
            + "".join(
                f'<th style="border:1px solid var(--divider-color); padding:4px; background:var(--table-header-background-color, var(--primary-color)) ; color: var(--text-primary-color, #fff);">{h}</th>'
                for h in headers
            )
            + "</tr></thead>",
            "<tbody>",
        ]
        for _i, row in enumerate(table_rows, start=1):
            html.append("<tr>")
            for cell in row:
                cell_html = escape(cell).replace("\n", "<br/>") if cell else ""
                html.append(
                    f'<td style="border:1px solid var(--divider-color); padding:6px; vertical-align:top;">{cell_html}</td>'
                )
            html.append("</tr>")
        html.append("</tbody></table>")
        # Items without any usable weekday have no grid position; do not render an empty grid.
        table_html = "".join(html) if day_values else ""

        # Create summary
        total_plans = len(items)
        subjects_count = len(by_subject)
        dates_count = len(by_date)
        summary = f"יש {total_plans} שיעורים מתוכננים ב-{subjects_count} מקצועות על פני {dates_count or 1} ימים"

        return {
            "summary": summary,
            "by_date": by_date,
            "by_subject": by_subject,
            "table": {
                "headers": headers,
                "rows": table_rows,
                "max_lessons": max_lessons,
                "order": "sun" if uses_sunday_based else "mon",
            },
            "table_html": table_html,
        }

    def _format_timetable_data(self, items: list) -> dict[str, Any]:
        """Format timetable using the same renderer as weekly plan."""
        # Reuse weekly plan formatting which supports timeTable/groupDetails
        return self._format_weekly_plan_data(items)
        # NOTE: unreachable; the summary therefore reads "planned lessons" for the timetable too.

    def _format_lessons_history(self, items: list) -> dict[str, Any]:
        """Format past lessons (remark, homework, and whether the lesson took place)."""
        by_date = {}
        by_subject = {}
        for it in items:
            ds = it.get("lesson_date")
            try:
                d = parse_iso_date_to_date(ds)
                date_key = d.strftime("%d/%m/%Y")
            except Exception:
                date_key = (ds or "").split("T")[0]
            subj = it.get("subject_name") or it.get("group_name") or "מקצוע לא ידוע"
            lesson = it.get("lesson")
            took = it.get("took_place")
            remark = (it.get("remark") or "").strip()
            hw = (it.get("homework") or "").strip()

            text = f"שיעור {lesson} - {subj}"
            if remark:
                text += f": {remark}"
            if hw:
                text += f" (ש.ב: {hw})"
            if took is False:
                text += " [לא התקיים]"

            by_date.setdefault(date_key, []).append(text)
            by_subject.setdefault(subj, []).append(text)

        summary = f"יש {len(items)} שיעורים היסטוריים"
        return {
            "summary": summary,
            "by_date": by_date,
            "by_subject": by_subject,
        }

    def _format_grades_data(self, items: list) -> dict[str, Any]:
        """Format grades data for display"""

        by_date = {}
        by_subject = {}

        for item in items:
            # Format date
            date_str = item.get("eventDate", "")
            if date_str:
                try:
                    date_obj = parse_iso_date_to_date(date_str)
                    formatted_date = date_obj.strftime("%d/%m/%Y")
                except Exception:
                    formatted_date = date_str
            else:
                formatted_date = "תאריך לא ידוע"

            # Group by date
            if formatted_date not in by_date:
                by_date[formatted_date] = []

            # Group by subject
            subject = item.get("subjectName", "מקצוע לא ידוע")
            if subject not in by_subject:
                by_subject[subject] = []

            # Format grade entry
            grade = item.get("grade", "")
            range_grade = item.get("rangeGrade", "")
            grading_event = item.get("gradingEvent", "")
            grade_type = item.get("gradeType", "")
            teacher = item.get("teacherName", "")
            textual_grade = item.get("textualGrade", "")

            # Build entry text
            entry = f"{subject} - {grading_event}: {grade}"
            if range_grade:
                entry += f" ({range_grade})"
            if grade_type:
                entry += f" [{grade_type}]"
            if textual_grade:
                entry += f" - {textual_grade}"
            if teacher:
                entry += f" | מורה: {teacher}"

            by_date[formatted_date].append(entry)
            by_subject[subject].append(entry)

        # Create summary
        total_grades = len(items)
        subjects_count = len(by_subject)
        dates_count = len(by_date)

        # Calculate average if there are numeric grades
        numeric_grades = [item.get("grade") for item in items if isinstance(item.get("grade"), (int, float))]
        avg_text = ""
        if numeric_grades:
            avg = sum(numeric_grades) / len(numeric_grades)
            avg_text = f", ממוצע: {avg:.1f}"

        summary = f"יש {total_grades} ציונים ב-{subjects_count} מקצועות על פני {dates_count} תאריכים{avg_text}"

        return {
            "summary": summary,
            "by_date": by_date,
            "by_subject": by_subject,
        }


class MashovHolidaysSensor(MashovEntity, SensorEntity):
    """School holidays/vacations for the hub, attached to a per-school holidays device.

    When a holidays fetch fails the coordinator may serve a cached list
    (``holidays_cached``); the state then stays the cached count, while
    ``source_status``/``data_stale`` and ``holidays_last_update`` reveal that the
    data is not fresh and when it was actually fetched.
    """

    _attr_icon = HOLIDAY_ICON

    def __init__(self, coordinator, entry_id: str):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_translation_key = "holidays"
        self._attr_unique_id = f"mashov_{entry_id}_holidays"

    @property
    def native_value(self):
        # Number of holidays; unknown only when the fetch failed and no cached copy exists.
        data = self.coordinator.data or {}
        items = data.get("holidays") or []
        return len(items) if data.get("holidays_status", "ok") == "ok" or data.get("holidays_cached") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        items = data.get("holidays") or []

        # Build formatted summary and by_date
        by_date = {}
        for h in items:
            start = h.get("start") or ""
            end = h.get("end") or ""
            name = h.get("name") or HOLIDAY_DEFAULT_NAME

            start_f = parse_iso_date_to_formatted(start)
            end_f = parse_iso_date_to_formatted(end)
            key = f"{start_f}–{end_f}" if end_f and end_f != start_f else start_f
            by_date.setdefault(key, []).append(name)

        summary = f"יש {len(items)} חגים/חופשות"
        # Prefer the holidays' own fetch time: with cached holidays it predates the coordinator refresh.
        last_update = data.get("holidays_last_update", getattr(self.coordinator, "last_successful_update", None))
        return {
            "source_status": data.get("holidays_status", "ok"),
            "data_stale": self.data_stale or data.get("holidays_status", "ok") != "ok",
            "formatted_summary": summary,
            "formatted_by_date": by_date,
            "items": items,
            "last_update": _local_timestamp(last_update),
        }

    @property
    def device_info(self):
        return create_holidays_device_info(
            DOMAIN,
            self._entry_id,
            DEVICE_MANUFACTURER,
            DEVICE_MODEL,
            getattr(getattr(self.coordinator, "entry", None), "title", ""),
        )
