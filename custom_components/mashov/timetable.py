"""Compact complete timetable, independent of the raw sensor item limit."""

from homeassistant.helpers.json import json_bytes

from .cancellations import mashov_weekday, normalized_group_id, parse_date


def _cancelled_dates(cancellations, since=None):
    """(Mashov weekday, lesson, group id) -> ISO dates on which that lesson is cancelled."""
    dates = {}
    for item in cancellations or ():
        if not isinstance(item, dict):
            continue
        day, group = parse_date(item.get("date")), normalized_group_id(item.get("group_id"))
        lesson = item.get("lesson")
        if day is None or group is None or not isinstance(lesson, int) or isinstance(lesson, bool):
            continue
        if since is not None and day < since:
            continue
        dates.setdefault((mashov_weekday(day), lesson, group), set()).add(day.isoformat())
    return dates


def weekly_schedule(items, cancellations=(), since=None):
    """Keep every weekday and simultaneous subject within a bounded payload.

    ``cancellations`` are normalized lesson cancellations. A lesson gets ``cancelled``: the
    dates on which its group's lesson in that slot is cancelled. Matching needs the group
    id, so a cancellation of a group the timetable does not list in that slot is not marked.
    Dates before ``since`` are left out: every date counts against the payload bound, and
    older ones would push lessons out of it.
    """
    cancelled = _cancelled_dates(cancellations, since)
    days = {day: [] for day in range(1, 8)}
    complete = True
    for item in items:
        try:
            slot = item["timeTable"]
            group = item.get("groupDetails") or {}
            day, lesson = int(slot["day"]), int(slot["lesson"])
            if day not in days or lesson < 0:
                complete = False
                continue
            row = {"lesson": lesson, "subject": str(group.get("subjectName") or group.get("groupName") or "—")[:160]}
            if slot.get("roomNum"):
                row["room"] = str(slot["roomNum"])[:60]
            if slot.get("weeks") not in (None, -1, "-1"):
                row["weeks"] = str(slot["weeks"])[:30]
            group_id = normalized_group_id(slot["groupId"] if slot.get("groupId") is not None else group.get("groupId"))
            if dates := cancelled.get((day, lesson, group_id)):
                row["cancelled"] = sorted(dates)
            if row not in days[day]:
                days[day].append(row)
        except (KeyError, TypeError, ValueError, AttributeError):
            complete = False
    result = []
    for day, lessons in days.items():
        result.append({"day": day, "lessons": []})
        for lesson in sorted(lessons, key=lambda x: x["lesson"]):
            result[-1]["lessons"].append(lesson)
            if len(json_bytes(result)) > 6000:
                result[-1]["lessons"].pop()
                complete = False
    return result, complete
