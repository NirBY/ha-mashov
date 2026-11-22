"""Render student details with real HA templates: school joins, failures and privacy."""

from homeassistant.helpers.template import Template
import pytest

from custom_components.mashov.dashboard_cards import attendance_card, bells_card, subjects_card
from custom_components.mashov.live_dashboard import (
    _student_card,
    normalize_students,
    student_detail_cards,
    student_room_cards,
)

from .test_attendance import normalized


async def test_attendance_uses_totals_and_preserves_school_period_and_unmapped_warning(hass):
    resource = normalized()
    hass.states.async_set("sensor.attendance", "6", {**resource, "total_items": 3, "stored_items": 3})
    text = Template(attendance_card("sensor.attendance", "#5adcf0")["content"], hass).async_render()
    assert "<h2>6</h2>" in text and "<h2>3</h2>" in text
    assert "2026-09-01" in text and "2027-08-31" in text
    assert "Math | 5 | 3 | 0" in text
    assert "4 אירועים נוספים" in text


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
async def test_failed_attendance_is_not_rendered_as_zero(hass, state):
    hass.states.async_set("sensor.attendance", state, {"absences": 0, "lateness": 0})
    text = Template(attendance_card("sensor.attendance", "#5adcf0")["content"], hass).async_render()
    assert "אינם זמינים" in text
    assert "<h2>0</h2>" not in text


async def test_stale_attendance_and_partial_rows_are_explicit(hass):
    hass.states.async_set(
        "sensor.attendance", "6", {**normalized(), "data_stale": True, "total_items": 3, "stored_items": 1}
    )
    text = Template(attendance_card("sensor.attendance", "#5adcf0")["content"], hass).async_render()
    assert "הרענון טרם הושלם" in text
    assert "הפירוט חלקי" in text


async def test_groups_join_lesson_counts_by_identity_not_position_and_escape_school_text(hass):
    hass.states.async_set(
        "sensor.groups",
        "2",
        {
            "items": [
                {
                    "groupId": 7,
                    "subjectName": "Math | [link](http://school.test)",
                    "groupTeachers": [{"teacherName": "A<br>B"}],
                },
                {"groupId": 8, "subjectName": "English", "groupTeachers": []},
            ]
        },
    )
    hass.states.async_set(
        "sensor.lessons",
        "2",
        {
            "items": [
                {"groupId": 8, "weeklyHours": 5, "lessonsCount": 80},
                {"groupId": 7, "weeklyHours": 3, "lessonsCount": 42},
            ]
        },
    )
    text = Template(subjects_card("sensor.groups", "sensor.lessons", "#5adcf0")["content"], hass).async_render()
    assert "AB</small> | 3 | 42" in text
    assert "</small> | 5 | 80" in text
    assert "&#124;" in text and "[link]" not in text
    assert "<br>B" not in text
    text = Template(subjects_card("sensor.groups", None, "#5adcf0")["content"], hass).async_render()
    assert "| — | —" in text


@pytest.mark.parametrize(
    "items,expected",
    [
        ([], "לא פרסם זמני צלצולים"),
        ([{"lessonNumber": 1, "startTime": "08:00:00", "endTime": "08:45:00"}], "1 | 08:00 | 08:45"),
    ],
)
async def test_bell_times_and_valid_empty_schedule(hass, items, expected):
    hass.states.async_set("sensor.bells", str(len(items)), {"items": items})
    text = Template(bells_card("sensor.bells", "#5adcf0")["content"], hass).async_render()
    assert expected in text


def test_new_sources_are_discrete_cards_and_picture_replaces_person_avatar():
    student = normalize_students(
        [
            {
                "name": "Noa",
                "homework": "sensor.hw",
                "timetable": "sensor.tt",
                "picture": "image.noa",
                "person": "person.noa",
                "attendance_counts": "sensor.attendance",
                "study_groups": "sensor.groups",
                "lessons_count": "sensor.lessons",
                "bells": "sensor.bells",
            }
        ]
    )[0]
    hero = _student_card(student)
    assert hero["entity"] == "image.noa"
    homework = hero["sub_button"]["bottom"][-1]["group"][0]
    assert homework["show_state"] is True
    assert "sub_button_type" not in homework
    cards = student_detail_cards(student)
    assert len(cards) == 5
    assert sum(card["type"] == "custom:mashov-weekly-card" for card in cards) == 1
    combined = str(cards)
    assert all(
        entity in combined for entity in ("sensor.attendance", "sensor.groups", "sensor.lessons", "sensor.bells")
    )
    assert "mailbox" not in combined
    assert "animation" not in combined


async def test_room_buttons_open_matching_readable_topics_with_complete_homework(hass):
    student = normalize_students(
        [
            {
                "name": "Noa",
                "homework": "sensor.hw",
                "behavior": "sensor.behavior",
                "grades": "sensor.grades",
                "noticeboard": "sensor.notices",
            }
        ]
    )[0]
    cards = student_room_cards(student)
    hero = cards[0]
    popups = {card["hash"]: card for card in cards if card.get("card_type") == "pop-up"}
    assert hero["tap_action"]["navigation_path"] in popups
    assert hero["button_action"]["tap_action"] == hero["tap_action"]
    for row in hero["sub_button"]["bottom"]:
        for chip in row["group"]:
            assert chip["tap_action"]["action"] == "navigate"
            popup = popups[chip["tap_action"]["navigation_path"]]
            assert len(popup["cards"]) == 1
            content = popup["cards"][0]["content"]
            assert chip["entity"] in content
            assert "<details>" not in content
    long_task = "Read the complete chapter " * 8 + "and answer question seven."
    hass.states.async_set(
        "sensor.hw",
        "7",
        {"items": [{"lesson_date": "2026-11-21", "subject_name": "Math", "homework": long_task} for _ in range(7)]},
    )
    text = Template(popups[student["hash"] + "-homework"]["cards"][0]["content"], hass).async_render()
    assert text.count(long_task) == 7
