"""Full-week data survives sensor storage limits without inventing school times."""

from homeassistant.helpers.json import json_bytes

from custom_components.mashov.timetable import weekly_schedule


def slot(day, lesson, subject="Math", **extra):
    return {"timeTable": {"day": day, "lesson": lesson, **extra}, "groupDetails": {"subjectName": subject}}


def test_full_week_includes_zero_lesson_and_simultaneous_subjects():
    items = [slot(6, 2), slot(1, 1), slot(1, 0), slot(1, 1, "Art"), slot(1, 1)]
    rows, complete = weekly_schedule(items)
    assert complete
    assert len(rows) == 7
    assert [x["lesson"] for x in rows[0]["lessons"]] == [0, 1, 1]
    assert len(rows[5]["lessons"]) == 1
    assert rows[6]["lessons"] == []


def test_invalid_and_oversize_data_is_explicitly_partial():
    rows, complete = weekly_schedule([slot(0, 1), {}, slot(1, 2)])
    assert not complete and rows[0]["lessons"][0]["lesson"] == 2
    rows, complete = weekly_schedule([slot(day, n, "א" * 160) for day in range(1, 8) for n in range(20)])
    assert not complete
    assert len(json_bytes(rows)) < 6300


def test_alternating_weeks_are_flagged_not_assumed_daily():
    rows, _ = weekly_schedule([slot(1, 1, weeks=2)])
    assert rows[0]["lessons"][0]["weeks"] == "2"


def test_cancellations_mark_only_the_matching_group_in_that_slot():
    # 2026-11-26 is a Thursday: Mashov day 5.
    items = [slot(5, 1, "Math"), slot(5, 2, "English", groupId=2), slot(5, 2, "English", groupId=3)]
    items[0]["groupDetails"]["groupId"] = 1  # the group id may come from the group details only
    cancellations = [
        {"date": "2026-11-26", "lesson": 1, "group_id": 1},
        {"date": "2026-11-19", "lesson": 1, "group_id": 1},
        {"date": "2026-11-26", "lesson": 2, "group_id": 2},
        {"date": "2026-11-26", "lesson": 1, "group_id": 99},
        {"date": "2026-11-27", "lesson": 1, "group_id": 1},
        {"date": "bad", "lesson": 1, "group_id": 1},
    ]
    rows, complete = weekly_schedule(items, cancellations)
    assert complete
    lessons = rows[4]["lessons"]
    assert lessons[0]["cancelled"] == ["2026-11-19", "2026-11-26"]
    # Same subject and room in two groups: only the cancelled group's row is marked, so both stay.
    assert [row.get("cancelled") for row in lessons[1:]] == [["2026-11-26"], None]
    assert weekly_schedule(items)[0][4]["lessons"][1:] == [{"lesson": 2, "subject": "English"}]
