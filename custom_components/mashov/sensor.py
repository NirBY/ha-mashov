from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

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
from .holidays_utils import (
    HOLIDAY_DEFAULT_NAME,
    HOLIDAY_ICON,
    create_holidays_device_info,
    parse_iso_date_to_formatted,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    _LOGGER.debug("Setting up sensors for entry: %s", entry.title)
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data["coordinator"]

    all_data = coord.data or {}
    students = all_data.get("students", [])
    _LOGGER.debug("Found %d students for sensor setup", len(students))

    entities = []
    for stu in students:
        slug = stu["slug"]
        sid = stu["id"]
        name = stu["name"]
        _LOGGER.debug("Creating sensors for student: %s (id=%s, slug=%s)", name, sid, slug)

        entities.extend(
            [
                MashovListSensor(coord, sid, slug, name, SENSOR_KEY_HOMEWORK, "Homework", "homework"),
                MashovListSensor(coord, sid, slug, name, SENSOR_KEY_BEHAVIOR, "Behavior", "behavior"),
                MashovListSensor(coord, sid, slug, name, SENSOR_KEY_WEEKLY_PLAN, "Weekly Plan", "weekly_plan"),
                MashovListSensor(coord, sid, slug, name, SENSOR_KEY_TIMETABLE, "Timetable", "timetable"),
                MashovListSensor(
                    coord, sid, slug, name, SENSOR_KEY_LESSONS_HISTORY, "Lessons History", "lessons_history"
                ),
                MashovListSensor(coord, sid, slug, name, SENSOR_KEY_GRADES, "Grades", "grades"),
            ]
        )

    # Global holidays sensor (per entry; ensure unique_id per entry)
    entities.append(MashovHolidaysSensor(coord, entry.entry_id))

    _LOGGER.info("Adding %d Mashov sensor entities", len(entities))
    async_add_entities(entities)


class MashovListSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:school"

    def __init__(
        self, coordinator, student_id: int, student_slug: str, student_name: str, key: str, name: str, data_key: str
    ):
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_slug = student_slug
        self._student_name = student_name
        self._key = key
        self._data_key = data_key
        self._attr_name = f"Mashov {student_name} {name}"
        # unique_id includes the numeric student id for stability
        self._attr_unique_id = f"mashov_{student_id}_{key}"

    @property
    def native_value(self):
        group = (self.coordinator.data or {}).get("by_slug", {}).get(self._student_slug, {})
        items = group.get(self._data_key) or []
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        student_meta = next((s for s in data.get("students", []) if s["slug"] == self._student_slug), {})
        group = data.get("by_slug", {}).get(self._student_slug, {})
        items = group.get(self._data_key) or []

        # Format data for better readability
        formatted_data = self._format_data_for_display(items)
        # Schedule info
        schedule_info = self._compute_schedule_info()

        # Get max items config (from options or default)
        max_items = self._get_max_items_config()

        # Store only recent items to avoid DB size issues (Issue #2)
        # Full data is always available via coordinator.data for automations
        items_for_attributes = self._limit_items_for_storage(items, max_items)

        total_count = len(items)
        stored_count = len(items_for_attributes)

        return {
            "student_name": self._student_name,
            "student_id": self._student_id,
            "year": student_meta.get("year"),
            "school_id": student_meta.get("school_id"),
            "last_update": datetime.now().isoformat(timespec="seconds"),
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

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self._student_id}")},
            "name": f"Mashov – {self._student_name}",
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
        """
        if not items:
            return items

        import json

        # Try to sort by date to keep most recent
        date_fields = ["lesson_date", "timestamp", "lessonDate"]

        def get_sort_key(item):
            """Extract sortable date/time from item."""
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
            best_count = 1

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
        """Format data for better readability and text-to-speech"""
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
        return {"summary": f"יש {len(items)} פריטים", "by_date": {}, "by_subject": {}}

    def _compute_schedule_info(self) -> dict[str, Any]:
        """Return current refresh schedule configuration and friendly description."""
        try:
            from datetime import datetime, timedelta

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
            schedule_type = merged.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE)
            if schedule_type not in ("daily", "weekly", "interval"):
                schedule_type = DEFAULT_SCHEDULE_TYPE
            schedule_time = str(merged.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME))
            try:
                hh, mm = (int(x) for x in schedule_time.split(":"))
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError
            except Exception:
                schedule_time = DEFAULT_SCHEDULE_TIME
            try:
                schedule_day = int(merged.get(CONF_SCHEDULE_DAY, DEFAULT_SCHEDULE_DAY))
            except Exception:
                schedule_day = DEFAULT_SCHEDULE_DAY
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

            friendly = None
            next_time_iso = None
            now = datetime.now()

            if schedule_type == "daily":
                try:
                    hh, mm = (int(x) for x in str(schedule_time).split(":"))
                except Exception:
                    hh, mm = (int(x) for x in DEFAULT_SCHEDULE_TIME.split(":"))
                next_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if next_dt <= now:
                    next_dt = next_dt + timedelta(days=1)
                friendly = f"יומי בשעה {hh:02d}:{mm:02d}"
                next_time_iso = next_dt.isoformat(timespec="seconds")
            elif schedule_type == "weekly":
                try:
                    hh, mm = (int(x) for x in str(schedule_time).split(":"))
                except Exception:
                    hh, mm = (int(x) for x in DEFAULT_SCHEDULE_TIME.split(":"))
                # Our 0=Monday mapping; Python weekday(): Monday=0
                # Compute next closest day from the list
                candidates = []
                for target_wd in schedule_days:
                    target_wd = int(target_wd)
                    days_ahead = (target_wd - now.weekday()) % 7
                    dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=days_ahead)
                    if dt <= now:
                        dt = dt + timedelta(days=7)
                    candidates.append(dt)
                next_dt = min(candidates) if candidates else now
                day_names = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "יום שבת", "יום ראשון"]
                friendly_days = ", ".join(day_names[int(d)] for d in schedule_days)
                friendly = f"שבועי – {friendly_days} {hh:02d}:{mm:02d}"
                next_time_iso = next_dt.isoformat(timespec="seconds")
            elif schedule_type == "interval":
                interval_min = int(schedule_interval)
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
        from datetime import datetime

        by_date = {}
        by_subject = {}

        for item in items:
            # Format date
            date_str = item.get("lesson_date", "")
            if date_str:
                try:
                    date_obj = datetime.fromisoformat(date_str.replace("T00:00:00", ""))
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
        from datetime import datetime

        by_date = {}
        by_type = {}

        for item in items:
            # Format date
            date_str = item.get("lesson_date", "")
            if date_str:
                try:
                    date_obj = datetime.fromisoformat(date_str.replace("T00:00:00", ""))
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
        """Format weekly plan data for display, including a weekly table view."""
        from datetime import datetime

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
            room = (tt.get("roomNum") or item.get("room") or "").strip()
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
                    date_obj = datetime.fromisoformat(date_str.replace("T00:00:00", ""))
                    formatted_date = date_obj.strftime("%d/%m/%Y")
                except Exception:
                    formatted_date = date_str
                if formatted_date not in by_date:
                    by_date[formatted_date] = []
                by_date[formatted_date].append(f"שיעור {lesson_raw}: {subject}")

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

        # Determine day mapping and headers
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
                return max(
                    0, min(6, (int(d) + 6) % 7)
                )  # 0(Mon)->6? We want order Mon..Sun mapped to 0..6 index of headers_mon

            # Explanation: headers_mon starts at Monday, but rendered order is Mon..Sun; mapping (d) to index accordingly

        # Determine max lessons
        max_lessons = max([n["lesson"] or 0 for n in normalized] + [8])
        if max_lessons < 6:
            max_lessons = 6
        if max_lessons > 12:
            max_lessons = 12

        # Build table matrix
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

        # HTML table (works inside Markdown card)
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
                cell_html = cell.replace("\n", "<br/>") if cell else ""
                html.append(
                    f'<td style="border:1px solid var(--divider-color); padding:6px; vertical-align:top;">{cell_html}</td>'
                )
            html.append("</tr>")
        html.append("</tbody></table>")
        table_html = "".join(html)

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
        # Keep summary as-is or optionally tweak text; leaving as-is for consistency

    def _format_lessons_history(self, items: list) -> dict[str, Any]:
        from datetime import datetime

        by_date = {}
        by_subject = {}
        for it in items:
            ds = it.get("lesson_date")
            try:
                d = datetime.fromisoformat((ds or "").replace("T00:00:00", ""))
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


class MashovHolidaysSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = HOLIDAY_ICON

    def __init__(self, coordinator, entry_id: str):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = "Mashov Holidays"
        self._attr_unique_id = f"mashov_{entry_id}_holidays"

    @property
    def native_value(self):
        # number of holidays in the dataset
        data = self.coordinator.data or {}
        items = data.get("holidays") or []
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from datetime import datetime

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
        return {
            "formatted_summary": summary,
            "formatted_by_date": by_date,
            "items": items,
            "last_update": datetime.now().isoformat(timespec="seconds"),
        }

    @property
    def device_info(self):
        return create_holidays_device_info(DOMAIN, self._entry_id, DEVICE_MANUFACTURER, DEVICE_MODEL)
