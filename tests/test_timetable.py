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
