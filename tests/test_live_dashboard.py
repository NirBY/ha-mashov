"""Mashov Live dashboard: student normalization, dashboard building, discovery and the service.

Protects per-student visibility (family plus the student's own viewers), rejection of
empty/ambiguous input, automatic discovery of every registered child, and saving into an
existing storage-mode Lovelace dashboard.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.components.lovelace.const import ConfigNotFound
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
import pytest

from custom_components.mashov.const import DOMAIN
from custom_components.mashov.live_dashboard import build_live_dashboard, normalize_students, resolve_students

KID = {
    "name": "Noa",
    "emoji": "🚀",
    "label": "4A",
    "person": "person.noa",
    "accent": [255, 0, 16],
    "homework": "sensor.noa_homework",
    "behavior": "sensor.noa_behavior",
    "timetable": "sensor.noa_timetable",
    "holidays": "sensor.holidays",
    "calendar": "calendar.school",
}

THURSDAY = "2026-10-08 09:00:00+00:00"
FRIDAY = "2026-10-09 09:00:00+00:00"


def _sections(config):
    """Return the sections of the first (only) view of a generated dashboard config."""
    return config["views"][0]["sections"]


def test_normalize_skips_empty_slots_and_converts_accent():
    """Blank/None slots are skipped and an RGB accent list becomes a hex colour with a stable hash."""
    students = normalize_students([KID, {"name": ""}, {"name": "  "}, None])

    assert len(students) == 1
    assert students[0]["accent"] == "#ff0010"
    assert students[0]["hash"] == "#mashov-student-1"
    assert students[0]["grades"] is None


def test_normalize_requires_a_student_and_core_sensor():
    """Input without any named student, or a student without homework/timetable, is rejected."""
    with pytest.raises(ServiceValidationError):
        normalize_students([{"name": ""}])
    with pytest.raises(ServiceValidationError):
        normalize_students([{"name": "Noa", "behavior": "sensor.noa_behavior"}])


def test_build_restricts_only_students_with_viewers():
    """Each student section is visible to the family plus that student's viewers, if any."""
    noa, dan = normalize_students([KID, {"name": "Dan", "homework": "sensor.dan_homework"}])

    config = build_live_dashboard(
        [noa, dan],
        title="Live",
        family_user_ids=["parent"],
        viewer_user_ids={noa["hash"]: ["noa-user"], dan["hash"]: []},
    )
    hero, noa_section, dan_section = _sections(config)

    assert hero["column_span"] == 3
    assert noa_section["visibility"] == [{"condition": "user", "users": ["parent", "noa-user"]}]
    assert dan_section["visibility"] == [{"condition": "user", "users": ["parent"]}]

    noa_card, noa_popup = noa_section["cards"]
    assert noa_card["entity"] == "person.noa"
    assert noa_card["force_icon"] is False
    assert "#ff0010" in noa_card["styles"]
    assert noa_popup["hash"] == noa["hash"]
    assert noa_popup["cards"][-1]["card_type"] == "calendar"

    dan_card, dan_popup = dan_section["cards"]
    assert dan_card["icon"] == "mdi:account-school"
    assert [group["group"][0]["entity"] for group in dan_card["sub_button"]["bottom"]] == ["sensor.dan_homework"]
    assert len(dan_popup["cards"]) == 1


async def test_service_saves_into_existing_storage_dashboard(hass: HomeAssistant):
    """The service resolves person entities to user IDs and saves into the target dashboard."""
    # Fake Lovelace storage dashboard (no saved config yet) and a resource list containing Bubble Card.
    target = SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(side_effect=ConfigNotFound))
    resources = SimpleNamespace(async_items=lambda: [{"url": "/hacsfiles/Bubble-Card/bubble-card.js"}])
    hass.data["lovelace"] = SimpleNamespace(dashboards={"mashov-live": target}, resources=resources)
    hass.states.async_set("person.noa", "home", {"user_id": "noa-user"})
    hass.states.async_set("person.parent", "home", {"user_id": "parent-user"})
    # A person without a linked user contributes no user ID to the visibility list.
    hass.states.async_set("person.guest", "home", {})
    assert await async_setup_component(hass, DOMAIN, {})

    response = await hass.services.async_call(
        DOMAIN,
        "create_live_dashboard",
        {
            "family": ["person.parent"],
            "students": [{**KID, "viewers": ["person.guest"]}, {"name": "", "homework": ""}],
        },
        blocking=True,
        return_response=True,
    )

    assert response == {"dashboard": "mashov-live", "students": 1, "bubble_card_found": True}
    saved = target.async_save.await_args.args[0]
    assert _sections(saved)[1]["visibility"] == [{"condition": "user", "users": ["parent-user", "noa-user"]}]


async def test_service_explains_missing_dashboard(hass: HomeAssistant):
    """An unknown target dashboard raises a validation error saying it was not found."""
    hass.data["lovelace"] = SimpleNamespace(dashboards={}, resources=None)
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(ServiceValidationError, match="was not found"):
        await hass.services.async_call(
            DOMAIN,
            "create_live_dashboard",
            {"dashboard": "missing", "students": [KID]},
            blocking=True,
            return_response=True,
        )


def _register_child(registry, entry_id: str, student_id: str) -> None:
    """Register the sensor and calendar entities a Mashov hub creates for one student."""
    for key in ("homework", "timetable", "behavior", "grades", "message_board"):
        registry.async_get_or_create("sensor", DOMAIN, f"mashov_{entry_id}_{student_id}_{key}")
    registry.async_get_or_create("sensor", DOMAIN, f"mashov_{entry_id}_holidays")
    registry.async_get_or_create("calendar", DOMAIN, f"mashov_{entry_id}_holidays_calendar")


def test_manual_list_has_no_student_cap():
    """A manually supplied student list is not truncated to a fixed maximum."""
    raw = [{"name": f"Child {index}", "homework": f"sensor.child_{index}_homework"} for index in range(10)]

    assert len(normalize_students(raw)) == 10


async def test_discovers_every_child_and_keeps_unlisted_ones_private(hass: HomeAssistant):
    """All children across hubs are discovered; customized ones gain viewers, the rest stay family-only."""
    registry = er.async_get(hass)
    hubs = {}
    # Two hubs with 10 children in total; names carry the class label in parentheses.
    for hub, count in (("one", 6), ("two", 4)):
        children = []
        for index in range(count):
            student_id = f"{hub}-{index}"
            _register_child(registry, hub, student_id)
            children.append({"id": student_id, "name": f"Child {hub} {index} (A{index})"})
        hubs[hub] = {"coordinator": SimpleNamespace(data={"students": children})}
    hass.data[DOMAIN] = hubs

    resolved = resolve_students(hass, [{"name": "Child one 0", "emoji": "🌟", "person": "person.kid"}])

    assert len(resolved) == 10
    first = next(student for student in resolved if student["id"] == "one-0")
    assert first["emoji"] == "🌟"
    assert first["label"] == "A0"
    assert first["person"] == "person.kid"
    assert first["homework"].startswith("sensor.")
    assert first["calendar"].startswith("calendar.")
    untouched = next(student for student in resolved if student["id"] == "two-3")
    assert untouched["emoji"] == ""
    assert untouched["family_only"] is True

    with pytest.raises(ServiceValidationError, match="Choose the family"):
        build_live_dashboard(resolved, title="Live", family_user_ids=[], viewer_user_ids={})

    config = build_live_dashboard(
        resolved,
        title="Live",
        family_user_ids=["parent"],
        viewer_user_ids={first["hash"]: ["kid-user"]},
    )
    limited = [section for section in _sections(config) if "visibility" in section]

    assert len(limited) == 10
    assert all(section["visibility"][0]["users"][0] == "parent" for section in limited)
    matched = next(section for section in limited if section["cards"][1]["hash"] == first["hash"])
    assert matched["visibility"] == [{"condition": "user", "users": ["parent", "kid-user"]}]


async def test_discovery_omits_deselected_entities(hass: HomeAssistant):
    registry = er.async_get(hass)
    _register_child(registry, "hub", "student")
    grade_id = registry.async_get_entity_id("sensor", DOMAIN, "mashov_hub_student_grades")
    registry.async_update_entity(grade_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    hass.data[DOMAIN] = {
        "hub": {"coordinator": SimpleNamespace(data={"students": [{"id": "student", "name": "Example"}]})}
    }
    assert resolve_students(hass, [])[0]["grades"] is None


async def test_unknown_or_ambiguous_customization_is_rejected(hass: HomeAssistant):
    """A customization matching no student or several students is rejected; an exact match applies."""
    registry = er.async_get(hass)
    children = []
    for student_id, name in (("a", "Noa One (1A)"), ("b", "Noa Two (1B)")):
        _register_child(registry, "hub", student_id)
        children.append({"id": student_id, "name": name})
    hass.data[DOMAIN] = {"hub": {"coordinator": SimpleNamespace(data={"students": children})}}

    with pytest.raises(ServiceValidationError, match="more than one"):
        resolve_students(hass, [{"name": "Noa", "emoji": "🌟"}])
    with pytest.raises(ServiceValidationError, match="No Mashov student matches"):
        resolve_students(hass, [{"name": "Someone else"}])

    resolved = resolve_students(hass, [{"name": "Noa One", "emoji": "🌟"}])
    assert next(student for student in resolved if student["id"] == "a")["emoji"] == "🌟"
    assert next(student for student in resolved if student["id"] == "b")["emoji"] == ""


@pytest.mark.parametrize("url_path", ["lovelace", "map"])
async def test_built_in_dashboard_requires_explicit_overwrite(hass: HomeAssistant, url_path: str):
    """An uncustomized Overview/Map has no stored config; it is replaced only with overwrite: true."""
    target = SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(side_effect=ConfigNotFound))
    hass.data["lovelace"] = SimpleNamespace(dashboards={url_path: target}, resources=None)
    assert await async_setup_component(hass, DOMAIN, {})
    # No linked person, so the card needs no user mapping; only the dashboard guard is exercised.
    call = {"dashboard": url_path, "students": [{**KID, "person": None}]}

    with pytest.raises(ServiceValidationError, match="built-in"):
        await hass.services.async_call(DOMAIN, "create_live_dashboard", call, blocking=True, return_response=True)
    target.async_save.assert_not_awaited()

    await hass.services.async_call(
        DOMAIN, "create_live_dashboard", {**call, "overwrite": True}, blocking=True, return_response=True
    )
    target.async_save.assert_awaited_once()


async def test_family_without_user_never_saves_public_manual_cards(hass):
    target = SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(return_value={}))
    hass.data["lovelace"] = SimpleNamespace(dashboards={"mashov-live": target}, resources=None)
    hass.states.async_set("person.parent", "home", {})
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError, match="selected family"):
        await hass.services.async_call(
            DOMAIN,
            "create_live_dashboard",
            {"family": ["person.parent"], "students": [{**KID, "person": None}]},
            blocking=True,
        )
    target.async_save.assert_not_awaited()


async def test_same_student_on_two_hubs_has_distinct_popups(hass):
    registry = er.async_get(hass)
    for hub in ("parent-one", "parent-two"):
        _register_child(registry, hub, "same-child")
    hass.data[DOMAIN] = {
        hub: {"coordinator": SimpleNamespace(data={"students": [{"id": "same-child", "name": "Noa"}]})}
        for hub in ("parent-one", "parent-two")
    }
    students = resolve_students(hass, [])
    assert len(students) == 2
    assert len({student["hash"] for student in students}) == 2


async def test_unrelated_dashboard_requires_overwrite(hass):
    target = SimpleNamespace(
        mode="storage",
        async_save=AsyncMock(),
        async_load=AsyncMock(return_value={"views": [{"cards": [{"type": "markdown", "content": "Keep me"}]}]}),
    )
    hass.data["lovelace"] = SimpleNamespace(dashboards={"mashov-live": target}, resources=None)
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError, match="already has content"):
        await hass.services.async_call(
            DOMAIN, "create_live_dashboard", {"students": [{**KID, "person": None}]}, blocking=True
        )
    target.async_save.assert_not_awaited()


def _lesson(day: int, subject: str) -> dict:
    """A timetable item for Mashov day `day` (1=Sunday..7=Saturday)."""
    return {
        "timeTable": {"day": day, "lesson": 1, "roomNum": "12"},
        "groupDetails": {"subjectName": subject, "groupTeachers": [{"teacherName": "Dana"}]},
    }


def _render_bag_day(hass: HomeAssistant, freezer, when: str, lessons: list, holidays: list) -> tuple[str, str]:
    """Render the student card's line and pop-up body at `when`; return (card line, pop-up)."""
    freezer.move_to(when)
    hass.states.async_set("sensor.noa_timetable", "1", {"items": lessons})
    hass.states.async_set("sensor.holidays", "0", {"items": holidays})
    raw = {"name": "Noa", "timetable": "sensor.noa_timetable", "holidays": "sensor.holidays"}
    student = normalize_students([raw])[0]
    config = build_live_dashboard([student], title="Live", family_user_ids=[], viewer_user_ids={})
    card, popup = _sections(config)[1]["cards"]
    line = Template(card["state_content"][0], hass).async_render(parse_result=False)
    body = Template(popup["cards"][0]["content"], hass).async_render(parse_result=False)
    return line, body


async def test_friday_shows_sundays_bag(hass: HomeAssistant, freezer):
    """When tomorrow is Saturday, the card and pop-up show Sunday's lessons instead of "no school"."""
    line, body = _render_bag_day(hass, freezer, FRIDAY, [_lesson(1, "Math"), _lesson(6, "Art")], [])

    assert line == "🎒 ביום ראשון 1 שיעורים · Math"
    assert 'title="🎒 התיק ליום ראשון"' in body
    assert "| 1 | Math | Dana | 12 |" in body
    assert "Art" not in body


async def test_friday_with_sunday_holiday_shows_the_holiday(hass: HomeAssistant, freezer):
    """A holiday on Sunday wins over Sunday's timetable."""
    holiday = {"name": "Sukkot", "start": "2026-10-11", "end": "2026-10-11"}
    line, body = _render_bag_day(hass, freezer, FRIDAY, [_lesson(1, "Math")], [holiday])

    assert line == "🌴 ביום ראשון Sukkot · אין לימודים"
    assert 'title="מחר שבת, וביום ראשון חופש"' in body
    assert "Math" not in body


async def test_friday_without_sunday_lessons_keeps_shabbat(hass: HomeAssistant, freezer):
    """With no Sunday timetable, Friday still shows the Shabbat message."""
    line, body = _render_bag_day(hass, freezer, FRIDAY, [_lesson(2, "Math")], [])

    assert line == "😴 מחר שבת"
    assert 'title="מחר שבת"' in body


async def test_friday_with_saturday_lessons_shows_saturday(hass: HomeAssistant, freezer):
    """A timetable with Saturday lessons keeps Saturday as tomorrow instead of skipping to Sunday."""
    line, body = _render_bag_day(hass, freezer, FRIDAY, [_lesson(7, "Torah"), _lesson(1, "Math")], [])

    assert line == "🎒 מחר 1 שיעורים · Torah"
    assert 'title="🎒 התיק למחר"' in body
    assert "Math" not in body


async def test_weekday_shows_tomorrows_bag(hass: HomeAssistant, freezer):
    """On other days the card still shows tomorrow (Thursday shows Friday's lessons)."""
    line, body = _render_bag_day(hass, freezer, THURSDAY, [_lesson(6, "Art"), _lesson(1, "Math")], [])

    assert line == "🎒 מחר 1 שיעורים · Art"
    assert 'title="🎒 התיק למחר"' in body


async def test_timetable_cells_cannot_break_the_table(hass: HomeAssistant, freezer):
    """Pipes and newlines in lesson fields stay inside their cell; missing fields leave the cell empty."""
    odd = _lesson(6, "Bible | Torah\nclass")
    odd["groupDetails"]["groupTeachers"] = []
    odd["timeTable"]["roomNum"] = None
    _, body = _render_bag_day(hass, freezer, THURSDAY, [odd], [])

    assert "| 1 | Bible \\| Torah class |  |  |\n" in body


async def test_day_without_lessons_has_no_empty_table(hass: HomeAssistant, freezer):
    """A school day with no timetable shows a message instead of a header-only table."""
    _, body = _render_bag_day(hass, freezer, THURSDAY, [], [])

    assert "אין מערכת למחר" in body
    assert "| # |" not in body


async def test_timetable_rows_stay_on_their_own_lines(hass: HomeAssistant, freezer):
    """The separator row and the first lesson are separate lines, so Home Assistant renders a table."""
    _, body = _render_bag_day(hass, freezer, THURSDAY, [_lesson(6, "Art")], [])

    assert "|:-:|---|---|:-:|\n| 1 | Art | Dana | 12 |\n" in body
