"""Lesson cancellations from Mashov's timetable changes route (opt-in, read only).

``GET students/<guid>/timetable/changes?start=<date>T00:00:00&end=<date>T00:00:00`` answers
``{"isEnabled": bool, "changes": [...], "cancellations": [...]}``, and each cancellation is
``{"lessonDate", "lesson", "groupId", "cancellationReason"}`` (verified on two schools on
2026-11-24). A school that does not offer the feature answers ``isEnabled: false`` with empty
lists. That is reported as ``not_offered``: it is not an error, so it is neither logged nor
backed off.

``cancellationReason`` is free text written by staff and may contain names. It is kept in the
cached resource and shown only in the cancellations sensor's attributes. It is never logged,
and diagnostics and the Assist/MCP tool never return it. A live row (2026-11-24) carried an
integer instead, apparently a reason code with no published meaning: it is kept as
``reason_code`` and treated like the text. Substitutions (``changes``) have not
been seen with items yet, so only their number is kept.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import re

LESSON_CANCELLATIONS = "lesson_cancellations"
# Status of a school that answers but does not publish cancellations (isEnabled false).
NOT_OFFERED = "not_offered"
REASON_MAX_CHARS = 300
LABEL_MAX_CHARS = 160


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def normalized_group_id(value):
    """Group ids arrive as int; accept a numeric string too, never a bool."""
    if _is_int(value):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def parse_date(value) -> date | None:
    """Calendar date of an ISO date or date-time string, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def mashov_weekday(day: date) -> int:
    """Mashov numbers weekdays 1=Sunday .. 7=Saturday."""
    return day.isoweekday() % 7 + 1


def _kind(value) -> str:
    """A value's JSON type for diagnostics; a string shows only its digit/letter pattern."""
    if isinstance(value, str):
        return "str(" + re.sub(r"[^\W\d_]", "a", re.sub(r"\d", "9", value))[:32] + ")"
    return type(value).__name__


def _row_problem(raw) -> str | None:
    """``field:type`` of the first field outside the verified row shape; never a value."""
    if not isinstance(raw, dict):
        return f"row:{type(raw).__name__}"
    lesson, group, reason = raw.get("lesson"), raw.get("groupId"), raw.get("cancellationReason")
    checks = (
        ("lessonDate", parse_date(raw.get("lessonDate")) is not None),
        ("lesson", _is_int(lesson) and lesson >= 0),
        ("groupId", group is None or _is_int(group)),
        ("cancellationReason", reason is None or isinstance(reason, str) or _is_int(reason)),
    )
    for field, valid in checks:
        if not valid:
            value = raw.get(field)
            # The reason is staff-written text: report its type only, never its pattern.
            return f"{field}:{type(value).__name__ if field == 'cancellationReason' else _kind(value)}"
    return None


def normalize_cancellations(payload, start: date, end: date) -> dict:
    """Keep the cancellations dated ``start``..``end``, soonest first.

    A response that is not the verified object raises ValueError with a ``field:type``
    message (no values), so a changed API shows ``invalid_response`` rather than a plausible
    count. Null lists count as empty. A row outside the verified shape is skipped, and
    ``unparsed_rows``/``unparsed_fields`` say how many and which field, so one odd row does
    not hide the others. Duplicate (date, lesson, group) rows are kept once.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"response:{type(payload).__name__}")
    if not isinstance(payload.get("isEnabled"), bool):
        raise ValueError(f"isEnabled:{type(payload.get('isEnabled')).__name__}")
    lists = {}
    for name in ("changes", "cancellations"):
        value = [] if payload.get(name) is None else payload[name]
        if not isinstance(value, list):
            raise ValueError(f"{name}:{type(value).__name__}")
        lists[name] = value
    period = {"period_start": start.isoformat(), "period_end": end.isoformat(), "changes_count": len(lists["changes"])}
    if not payload["isEnabled"]:
        return {"status": NOT_OFFERED, "items": [], "offered": False, **period}
    rows, unparsed = {}, Counter()
    for raw in lists["cancellations"]:
        if problem := _row_problem(raw):
            unparsed[problem] += 1
            continue
        day, lesson, group, reason = (
            parse_date(raw["lessonDate"]),
            raw["lesson"],
            raw.get("groupId"),
            raw.get("cancellationReason"),
        )
        if start <= day <= end:
            row = rows.setdefault(
                (day, lesson, -1 if group is None else group),
                {
                    "date": day.isoformat(),
                    "lesson": lesson,
                    "group_id": group,
                    "reason": reason.strip()[:REASON_MAX_CHARS] or None if isinstance(reason, str) else None,
                },
            )
            if _is_int(reason) and row["reason"] is None:
                row.setdefault("reason_code", reason)
    result = {"status": "ok", "items": [rows[key] for key in sorted(rows)], "offered": True, **period}
    if unparsed:
        result["unparsed_rows"] = sum(unparsed.values())
        result["unparsed_fields"] = sorted(unparsed)
    return result


def group_labels(timetable, groups) -> dict[int, tuple[str | None, str | None]]:
    """Group id -> (subject, first teacher) from the timetable's group details, then study groups."""
    details = [item.get("groupDetails") for item in timetable or [] if isinstance(item, dict)]
    labels: dict[int, tuple[str | None, str | None]] = {}
    for group in [*details, *(groups or [])]:
        if not isinstance(group, dict) or (group_id := normalized_group_id(group.get("groupId"))) is None:
            continue
        teachers = group.get("groupTeachers")
        teacher = (
            next(
                (str(t["teacherName"]) for t in teachers if isinstance(t, dict) and t.get("teacherName")),
                None,
            )
            if isinstance(teachers, list)
            else None
        )
        subject = group.get("subjectName") or group.get("groupName")
        old_subject, old_teacher = labels.get(group_id, (None, None))
        labels[group_id] = (
            old_subject or (str(subject)[:LABEL_MAX_CHARS] if subject else None),
            old_teacher or (teacher[:LABEL_MAX_CHARS] if teacher else None),
        )
    return labels


def _day_slots(timetable, weekday: int) -> dict[int, list]:
    """Lesson number -> group ids the timetable lists on a Mashov weekday."""
    slots: dict[int, list] = {}
    for item in timetable or []:
        slot = item.get("timeTable") if isinstance(item, dict) else None
        if not isinstance(slot, dict):
            continue
        try:
            if int(slot.get("day")) != weekday:
                continue
            lesson = int(slot.get("lesson"))
        except (TypeError, ValueError):
            continue
        group = slot.get("groupId")
        if group is None:
            group = (item.get("groupDetails") or {}).get("groupId")
        slots.setdefault(lesson, []).append(normalized_group_id(group))
    return slots


def day_shift(timetable, day: date, cancelled: set) -> tuple[set, set]:
    """Lesson numbers whose cancellation moves the day's start, and the day's end.

    A lesson slot counts as cancelled only when every group the timetable lists in it is
    cancelled. Cancelled slots at the start of the day move the start, cancelled slots at
    its end move the end, and a day with every slot cancelled moves both. A cancelled
    lesson between two lessons that still take place moves neither.
    """
    slots = _day_slots(timetable, mashov_weekday(day))
    order = sorted(slots)
    gone = [all((lesson, group) in cancelled for group in slots[lesson]) for lesson in order]
    first = 0
    while first < len(order) and gone[first]:
        first += 1
    if first == len(order):
        return set(order), set(order)
    last = len(order) - 1
    while gone[last]:
        last -= 1
    return set(order[:first]), set(order[last + 1 :])


def cancellation_rows(items, timetable, groups, today: date) -> tuple[list, list]:
    """Return (upcoming soonest first, recent most recent first) rows for the sensor.

    Each row names the subject and teacher when the timetable or study groups list the
    group. Upcoming rows say whether they move that day's start or end (None without a
    timetable). Recent rows never move anything.
    """
    labels = group_labels(timetable, groups)
    by_day: dict[date, set] = {}
    dated = []
    for item in items or []:
        day = parse_date(item.get("date")) if isinstance(item, dict) else None
        if day is None or not _is_int(item.get("lesson")):
            continue
        dated.append((day, item))
        by_day.setdefault(day, set()).add((item["lesson"], normalized_group_id(item.get("group_id"))))
    dated.sort(key=lambda pair: (pair[0], pair[1]["lesson"]))
    shifts: dict[date, tuple[set, set]] = {}
    upcoming, recent = [], []
    for day, item in dated:
        subject, teacher = labels.get(normalized_group_id(item.get("group_id")), (None, None))
        row = {
            "date": day.isoformat(),
            "lesson": item["lesson"],
            "subject": subject,
            "teacher": teacher,
            "group_id": item.get("group_id"),
            "reason": item.get("reason"),
            **({"reason_code": item["reason_code"]} if item.get("reason_code") is not None else {}),
        }
        if day < today:
            recent.append(row)
            continue
        if timetable:
            if day not in shifts:
                shifts[day] = day_shift(timetable, day, by_day[day])
            row["moves_start"] = item["lesson"] in shifts[day][0]
            row["moves_end"] = item["lesson"] in shifts[day][1]
        else:
            row["moves_start"] = row["moves_end"] = None
        upcoming.append(row)
    return upcoming, recent[::-1]


def upcoming_count(items, today: date) -> int:
    """Cancellations dated today or later."""
    return sum(
        1 for item in items or [] if isinstance(item, dict) and (day := parse_date(item.get("date"))) and day >= today
    )


def without_reasons(rows) -> list:
    """Rows for the Assist/MCP tool: reasons (text or code) stay in entity attributes only."""
    return [{key: value for key, value in row.items() if key not in ("reason", "reason_code")} for row in rows]
