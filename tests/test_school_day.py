"""Render actual HA templates against dates, holidays and per-child timetables."""

from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import shutil

from homeassistant.helpers.script_variables import ScriptVariables
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
import pytest
import yaml

from custom_components.mashov.live_dashboard import _popup_markdown, _school_target, _tomorrow_line, normalize_students


class Input(str):
    """Blueprint input reference, distinguished from ordinary strings."""


class BlueprintLoader(yaml.SafeLoader):
    """Load blueprint input tags without executing them."""


BlueprintLoader.add_constructor("!input", lambda loader, node: Input(loader.construct_scalar(node)))
ROOT = Path(__file__).parent.parent


def load_blueprint(path):
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=BlueprintLoader)


def resolve(value, inputs):
    if isinstance(value, Input):
        return inputs[value]
    if isinstance(value, dict):
        return {key: resolve(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, inputs) for item in value]
    return value


def lesson(day):
    return {
        "timeTable": {"day": day, "lesson": 1, "groupId": 1, "roomNum": "101"},
        "groupDetails": {"subjectName": f"subject-{day}", "groupTeachers": []},
        "groupTeachers": [],
    }


@pytest.mark.parametrize(
    ("today", "holidays", "days", "expected"),
    [
        ("2026-10-23", [], [1, 2, 3, 4, 5, 6], "25/10"),
        ("2026-10-22", [], [1, 2, 3, 4, 5], "25/10"),
        ("2026-10-23", [{"start": "2026-10-25", "end": "2026-10-27"}], [1, 2, 3, 4, 5], "28/10"),
        ("2026-10-23", [{"start": "2026-10-25", "end": None}], [1, 2, 3, 4, 5], "26/10"),
        ("2026-12-31", [{"start": "2027-01-01", "end": "2027-01-03"}], [1, 2, 3, 4, 5, 6], "04/01"),
        ("2026-10-23", [{"start": "bad", "end": "bad"}], ["1", "2"], "25/10"),
    ],
)
async def test_dashboard_and_bag_choose_same_school_date(hass, freezer, today, holidays, days, expected):
    freezer.move_to(f"{today}T09:00:00+00:00")
    await hass.config.async_set_time_zone("Asia/Jerusalem")
    holidays = [{**item, "name": "Holiday"} for item in holidays]
    hass.states.async_set("sensor.schedule", "6", {"items": [lesson(day) for day in days]})
    hass.states.async_set("sensor.holidays", "1", {"items": holidays})
    student = normalize_students(
        [{"name": "Noa", "timetable": "sensor.schedule", "holidays": "sensor.holidays", "next_school_day": True}]
    )[0]
    original = deepcopy(student)
    for source in (_tomorrow_line(student), _popup_markdown(student)):
        rendered = Template(source, hass).async_render()
        assert expected in rendered
        assert "מחר שבת" not in rendered
    assert student == original
    blueprint = load_blueprint("blueprints/automation/mashov/bag_reminder_tomorrow.yaml")
    inputs = {key: item.get("default") for key, item in blueprint["blueprint"]["input"].items()}
    inputs.update(timetable_entity="sensor.schedule", holiday_entity="sensor.holidays", next_school_day=True)
    raw = resolve(blueprint["variables"], inputs)
    variables = ScriptVariables(
        {key: Template(value, hass) if isinstance(value, str) else value for key, value in raw.items()}
    ).async_render(hass, {})
    assert variables["tomorrow_date_iso"][5:] == expected[3:] + "-" + expected[:2]
    assert expected in variables["speech_text"]
    assert "אנא לסדר תיק ליום " in variables["speech_text"]
    assert "הקרוב, בתאריך " + expected in variables["speech_text"]
    assert "לסדר תיק ביום " not in variables["speech_text"]
    assert variables["should_run"] is True


async def test_default_tomorrow_and_per_child_opt_in(hass, freezer):
    freezer.move_to("2026-10-23T09:00:00+00:00")
    hass.states.async_set("sensor.schedule", "1", {"items": [lesson(1)]})
    legacy, opted_in = normalize_students(
        [
            {"name": "Old", "timetable": "sensor.schedule"},
            {"name": "New", "timetable": "sensor.schedule", "next_school_day": True},
        ]
    )
    assert legacy["next_school_day"] is False
    assert "מחר שבת" in Template(_tomorrow_line(legacy), hass).async_render()
    assert "25/10" in Template(_tomorrow_line(opted_in), hass).async_render()
    blueprint = load_blueprint("blueprints/script/mashov/mashov_live_dashboard.yaml")
    for index in range(1, 5):
        assert (
            blueprint["blueprint"]["input"][f"student_{index}"]["input"][f"s{index}_next_school_day"]["default"]
            is False
        )
    bag = load_blueprint("blueprints/automation/mashov/bag_reminder_tomorrow.yaml")
    assert bag["blueprint"]["input"]["next_school_day"]["default"] is False


async def test_daily_summary_holiday_boolean_survives_loop(hass, freezer):
    freezer.move_to("2026-10-23T09:00:00+00:00")
    hass.states.async_set("sensor.holidays", "1", {"items": [{"start": "2026-10-23", "end": None}]})
    daily = load_blueprint("blueprints/automation/mashov/mashov_daily_homework_announce.yaml")
    result = Template(daily["variables"]["in_holiday_today"], hass).async_render({"holiday_sensor": "sensor.holidays"})
    assert result is True


@pytest.mark.parametrize("enabled", [False, True])
async def test_existing_bag_automation_loads_with_optional_input(hass, tmp_path, enabled):
    """HA must accept old saved inputs and the new opt-in through the real blueprint loader."""
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints/automation/mashov"
    target.mkdir(parents=True)
    source = ROOT / "blueprints/automation/mashov/bag_reminder_tomorrow.yaml"
    shutil.copy(source, target / source.name)
    inputs = {
        "timetable_entity": "sensor.schedule",
        "holiday_entity": "sensor.holidays",
        "speaker_entity": "media_player.speaker",
    }
    if enabled:
        inputs["next_school_day"] = True
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "Bag compatibility",
                    "use_blueprint": {"path": f"mashov/{source.name}", "input": inputs},
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("automation.bag_compatibility") is not None


async def test_no_school_day_within_bound_never_uses_holiday_as_school(hass, freezer):
    freezer.move_to("2026-10-23T09:00:00+00:00")
    hass.states.async_set("sensor.schedule", "1", {"items": [lesson(1)]})
    hass.states.async_set(
        "sensor.holidays", "1", {"items": [{"name": "Long closure", "start": "2026-10-23", "end": "2028-01-01"}]}
    )
    student = normalize_students(
        [{"name": "Noa", "timetable": "sensor.schedule", "holidays": "sensor.holidays", "next_school_day": True}]
    )[0]
    for source in (_tomorrow_line(student), _popup_markdown(student)):
        assert "לא נמצא יום לימודים" in Template(source, hass).async_render()


@pytest.mark.parametrize(
    ("domain", "filename", "inputs"),
    [
        ("script", "mashov_live_dashboard.yaml", {}),
        (
            "automation",
            "mashov_daily_homework_announce.yaml",
            {
                "holiday_sensor": "sensor.holidays",
                "homework_sensor": "sensor.homework",
                "behavior_sensor": "sensor.behavior",
                "media_player": "media_player.speaker",
            },
        ),
    ],
)
async def test_old_dashboard_and_daily_blueprint_inputs_load(hass, tmp_path, domain, filename, inputs):
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / f"blueprints/{domain}/mashov"
    target.mkdir(parents=True)
    shutil.copy(ROOT / f"blueprints/{domain}/mashov/{filename}", target / filename)
    use = {"path": f"mashov/{filename}", "input": inputs}
    config = (
        {"script": {"compatibility": {"use_blueprint": use}}}
        if domain == "script"
        else {"automation": [{"alias": "Compatibility", "use_blueprint": use}]}
    )
    assert await async_setup_component(hass, domain, config)
    await hass.async_block_till_done()
    assert hass.states.get(f"{domain}.compatibility") is not None


@pytest.mark.parametrize("school_days", [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6]])
async def test_actual_september_and_hanukkah_ranges(hass, freezer, school_days):
    """Replay both configured schools' matching holiday snapshots, read on 2026-10-23.

    These are school vacation ranges, not holiday/eve names from a religious
    calendar. Every date of the contiguous Kippur/bridge/Sukkot closure and
    Hanukkah closure must select the actual return day, including the last date.
    """
    holidays = json.loads((ROOT / "tests/fixtures/school_holidays_2026_2027.json").read_text(encoding="utf-8"))
    hass.states.async_set("sensor.schedule", "6", {"items": [lesson(day) for day in school_days]})
    hass.states.async_set("sensor.holidays", "5", {"items": holidays})
    student = normalize_students(
        [{"name": "Child", "timetable": "sensor.schedule", "holidays": "sensor.holidays", "next_school_day": True}]
    )[0]
    cases = {
        "2026-09-09": "2026-09-10",
        "2026-09-10": "2026-09-14",  # Erev Rosh Hashanah IS in the school vacation.
        "2026-09-14": "2026-09-15",  # No extra day after the inclusive end.
        "2026-09-17": "2026-09-18" if 6 in school_days else "2026-10-04",
        "2026-10-04": "2026-10-05",
        "2026-12-03": "2026-12-04" if 6 in school_days else "2026-12-13",
        "2026-12-13": "2026-12-14",
    }
    for start, end, expected in [
        (date(2026, 9, 11), date(2026, 9, 13), "2026-09-14"),
        (date(2026, 9, 18), date(2026, 10, 3), "2026-10-04"),
        (date(2026, 12, 4), date(2026, 12, 12), "2026-12-13"),
    ]:
        for offset in range((end - start).days + 1):
            cases[(start + timedelta(days=offset)).isoformat()] = expected
    blueprint = load_blueprint("blueprints/automation/mashov/bag_reminder_tomorrow.yaml")
    for today, expected in cases.items():
        freezer.move_to(f"{today}T09:00:00+00:00")
        result = Template(_school_target(student) + "{{ t.isoformat() }}", hass).async_render()
        assert result == expected, today
        # Render the actual automation's date variables as HA does, in order.
        variables = {
            "next_school_day": True,
            "timetable_entity": "sensor.schedule",
            "holiday_entity": "sensor.holidays",
        }
        for key in ("target_result", "target_offset", "target_label", "tomorrow_date_iso"):
            variables[key] = Template(blueprint["variables"][key], hass).async_render(variables)
        assert variables["tomorrow_date_iso"] == expected, today
    freezer.move_to("2026-12-03T09:00:00+00:00")
    if 6 in school_days:
        assert "מחר 1 שיעורים" in Template(_tomorrow_line(student), hass).async_render()


async def test_contributed_popup_table_keeps_rows_and_cells_intact(hass, freezer):
    """PR #15: whitespace trimming and API text must not break Markdown tables."""
    freezer.move_to("2026-10-22T09:00:00+00:00")
    row = lesson(6)
    row["groupDetails"]["subjectName"] = "Bible | Torah\nclass"
    row["timeTable"]["roomNum"] = None
    hass.states.async_set("sensor.schedule", "1", {"items": [row]})
    hass.states.async_set(
        "sensor.homework",
        "1",
        {"items": [{"lesson_date": "2026-10-22", "subject_name": "Math | Art", "homework": "Read\npage | 2"}]},
    )
    student = normalize_students([{"name": "Child", "timetable": "sensor.schedule", "homework": "sensor.homework"}])[0]
    body = Template(_popup_markdown(student), hass).async_render()
    assert "|:-:|---|---|:-:|\n| 1 | Bible \\| Torah class |  |  |\n" in body
    assert "Math \\| Art | Read page \\| 2 |\n" in body


async def test_contributed_empty_timetable_message(hass, freezer):
    freezer.move_to("2026-10-22T09:00:00+00:00")
    hass.states.async_set("sensor.schedule", "0", {"items": []})
    student = normalize_students([{"name": "Child", "timetable": "sensor.schedule"}])[0]
    body = Template(_popup_markdown(student), hass).async_render()
    assert "אין מערכת למחר" in body
    assert "| # |" not in body
