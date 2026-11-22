"""Compact complete timetable, independent of the raw sensor item limit."""

from homeassistant.helpers.json import json_bytes


def weekly_schedule(items):
    """Keep every weekday and simultaneous subject within a bounded payload."""
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
            if row not in days[day]:
                days[day].append(row)
        except (KeyError, TypeError, ValueError):
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
