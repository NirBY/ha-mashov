"""Build and save the "Mashov Live" Bubble Card dashboard.

Backs the mashov service that writes a ready-made, Hebrew/RTL Lovelace
dashboard into an existing UI-managed (storage) dashboard. Layout of the
generated "sections" view:
  - hero card (full width): time-of-day greeting for the viewing user, a
    holiday/next-holiday countdown and a "refresh now" button;
  - one grid section per student, holding
      * the student card: name/emoji/class, a "tomorrow" summary line, chips for
        behavior/grades/noticeboard and a read-only homework slider;
      * a Bubble Card pop-up (opened via the card's #hash) with tomorrow's
        timetable, recent homework, behavior, grades, noticeboard and the
        holidays calendar.

All dynamic content is Jinja evaluated by Bubble Card in the browser against
the integration's sensor attributes, so the dashboard stays live without being
regenerated. Students are discovered from loaded Mashov entries; the service's
optional student list only tweaks them (or defines them manually when nothing
has loaded yet).

Privacy: student sections are limited with a "user" visibility condition to the
selected family plus the student's linked person/viewers. Automatically found
children are never shown to everyone by default.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
import re
from typing import Any

from homeassistant.components.lovelace.const import ConfigNotFound  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.exceptions import ServiceValidationError  # type: ignore
from homeassistant.helpers import entity_registry as er  # type: ignore

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LOVELACE_DATA_KEY = "lovelace"
# Substring looked for in Lovelace resource URLs to detect Bubble Card.
BUBBLE_CARD_RESOURCE = "bubble-card"
DEFAULT_DASHBOARD = "mashov-live"
# Home Assistant's own dashboards (Overview, Map); replacing them requires overwrite: true.
PROTECTED_DASHBOARDS = ("lovelace", "map")
DEFAULT_TITLE = "משוב לייב"
# Top-level key written into the saved config so later runs can recognise (and
# safely overwrite) a dashboard this module generated.
DASHBOARD_MARKER = "mashov_live"
# Muted accent colors assigned round-robin to students without a custom accent.
DEFAULT_ACCENTS = ("#9bb0c9", "#d4b2a4", "#a8c4b4", "#c7b8d9", "#d6cfa3", "#a9c7cf")

# Per-student entity slots; each may be discovered or overridden by the service call.
STUDENT_ENTITY_KEYS = ("homework", "behavior", "grades", "timetable", "noticeboard", "holidays", "calendar")

# Shared dark, low-contrast Bubble Card CSS (RTL text, round avatars) used by every card.
QUIET_STYLES = """
.bubble-button-card-container, .bubble-wrapper, .bubble-sub-button-container, .bubble-sub-button-group {
  direction: rtl !important;
}
.bubble-button-card-container {
  background: #2a2e3a !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  box-shadow: none !important;
}
.bubble-name, .bubble-state, .bubble-sub-button-name {
  color: #f2f3f5 !important;
  unicode-bidi: plaintext !important;
  text-align: start !important;
  justify-content: flex-start !important;
}
.bubble-state { opacity: .8 !important; font-weight: 400 !important; }
.bubble-sub-button {
  background: rgba(255,255,255,0.06) !important;
  color: #e6e8ee !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
}
.bubble-sub-button-icon, .bubble-icon { color: #c5c8d0 !important; }
.bubble-icon-container {
  background: transparent !important;
  border-radius: 50% !important;
  overflow: hidden;
}
.bubble-icon-container img, .bubble-entity-picture {
  width: 100% !important;
  height: 100% !important;
  object-fit: cover;
  border-radius: 50% !important;
}
.bubble-range-fill { background: #8b93a7 !important; }
.bubble-range-value { direction: ltr !important; unicode-bidi: isolate !important; }
"""

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean(value: Any) -> str | None:
    """Stringify and strip a service value; empty or missing becomes None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _accent(value: Any, index: int) -> str:
    """Normalize an accent to lowercase #rrggbb.

    Accepts "#RRGGBB" or an [r, g, b] list (what HA's color selector returns).
    Empty falls back to a default accent picked by the student's position.
    The value is later interpolated into CSS, hence the strict validation.
    """
    if value is None or value == "" or value == []:
        return DEFAULT_ACCENTS[index % len(DEFAULT_ACCENTS)]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            channels = tuple(int(channel) for channel in value)
        except (TypeError, ValueError) as err:
            raise ServiceValidationError("Accent color must be #RRGGBB or [r, g, b] with values from 0 to 255") from err
        if all(0 <= channel <= 255 for channel in channels):
            return "#{:02x}{:02x}{:02x}".format(*channels)
    text = _clean(value)
    if text and _HEX_COLOR.match(text):
        return text.lower()
    raise ServiceValidationError("Accent color must be #RRGGBB or [r, g, b] with values from 0 to 255")


def _jinja_literal(text: str) -> str:
    """Keep a user-typed name from being executed as a Bubble Card template.

    Card names are rendered as Jinja, so a name containing "{{" or "{%" would run.
    Each brace is replaced by an expression that outputs it literally. The
    \\x00/\\x01 placeholders stop the braces of the inserted "{{ '{' }}" from
    being escaped again by the second replacement.
    """
    return text.replace("{", "\x00").replace("}", "\x01").replace("\x00", "{{ '{' }}").replace("\x01", "{{ '}' }}")


def person_user_ids(hass: HomeAssistant, persons: Iterable[str] | None) -> list[str]:
    """Resolve person entities to the Home Assistant user IDs linked to them.

    Visibility conditions work on user IDs, not persons. Persons without a
    linked user are skipped with a warning; duplicates are removed, order kept.
    """
    user_ids: list[str] = []
    for entity_id in persons or []:
        entity_id = _clean(entity_id)
        if not entity_id:
            continue
        state = hass.states.get(entity_id)
        user_id = state.attributes.get("user_id") if state else None
        if user_id:
            if user_id not in user_ids:
                user_ids.append(user_id)
        else:
            _LOGGER.warning("Mashov Live: %s has no linked Home Assistant user; it cannot restrict viewing", entity_id)
    return user_ids


_CLASS_SUFFIX = re.compile(r"^(?P<name>.+?)\s*\((?P<label>[^)]+)\)\s*$")


def _split_display_name(full: str) -> tuple[str, str]:
    """Split 'Noa Cohen (4A)' into ('Noa Cohen', '4A'); no suffix gives an empty label.

    The stored student name ends with the class, for example 'Noa Cohen (4A)'.
    """
    match = _CLASS_SUFFIX.match(full.strip())
    if not match:
        return full.strip(), ""
    return match.group("name").strip(), match.group("label").strip()


def _registry_entity(registry, domain: str, unique_id: str) -> str | None:
    return registry.async_get_entity_id(domain, DOMAIN, unique_id)


def discover_students(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Every child on every loaded Mashov hub, with the entities the integration already created.

    Entities are looked up by the unique_id patterns the sensors/calendar use, so
    renamed entity_ids are still found. Discovered children start as
    family_only (see build_live_dashboard). Children missing both homework and
    timetable sensors are skipped because their card would be empty.
    """
    registry = er.async_get(hass)
    found: list[dict[str, Any]] = []
    for entry_id, stored in hass.data.get(DOMAIN, {}).items():
        # Skip anything in hass.data[DOMAIN] that is not a loaded entry with a coordinator.
        if not isinstance(stored, dict) or "coordinator" not in stored:
            continue
        data = getattr(stored["coordinator"], "data", None) or {}
        for stu in data.get("students") or []:
            student_id = stu.get("id")
            full_name = _clean(stu.get("name"))
            if not student_id or not full_name:
                continue
            name, label = _split_display_name(full_name)
            prefix = f"mashov_{entry_id}_{student_id}_"
            record = {
                "id": str(student_id),
                "entry_id": entry_id,
                "name": name,
                "full_name": full_name,
                "label": label,
                "emoji": "",
                "person": None,
                "viewers": [],
                "family_only": True,
                "homework": _registry_entity(registry, "sensor", f"{prefix}homework"),
                "behavior": _registry_entity(registry, "sensor", f"{prefix}behavior"),
                "grades": _registry_entity(registry, "sensor", f"{prefix}grades"),
                "timetable": _registry_entity(registry, "sensor", f"{prefix}timetable"),
                "noticeboard": _registry_entity(registry, "sensor", f"{prefix}message_board"),
                "holidays": _registry_entity(registry, "sensor", f"mashov_{entry_id}_holidays"),
                "calendar": _registry_entity(registry, "calendar", f"mashov_{entry_id}_holidays_calendar"),
            }
            if not record["homework"] and not record["timetable"]:
                _LOGGER.warning(
                    "Mashov Live: skipping %s because the homework and timetable entities are missing", full_name
                )
                continue
            found.append(record)
    found.sort(key=lambda item: item["name"])
    return found


def _match_student(name: str, students: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the discovered student a service-supplied name refers to.

    Tries an exact match (name, stored full name, or "name (label)") first, then
    the first name alone. Ambiguous or unknown names raise instead of guessing.
    """
    exact = [
        student
        for student in students
        if name in {student["name"], student.get("full_name"), f"{student['name']} ({student['label']})".rstrip()}
    ]
    if len(exact) > 1:
        raise ServiceValidationError(f"'{name}' matches more than one student. Use the full name.")
    if len(exact) == 1:
        return exact[0]
    first_name = [student for student in students if student["name"].split()[0] == name]
    if len(first_name) > 1:
        raise ServiceValidationError(f"'{name}' matches more than one student. Use the full name.")
    if len(first_name) == 1:
        return first_name[0]
    raise ServiceValidationError(f"No Mashov student matches '{name}'.")


def _apply_overrides(students: list[dict[str, Any]], raw_students: Iterable[dict[str, Any]]) -> None:
    """Apply per-child tweaks from the service call to discovered students, in place.

    Only non-empty fields override; each student may be customized once.
    """
    customized: set[tuple[str | None, str]] = set()
    for raw in raw_students or []:
        if not isinstance(raw, dict) or not _clean(raw.get("name")):
            continue
        target = _match_student(_clean(raw["name"]) or "", students)
        identity = (target.get("entry_id"), target["id"])
        if identity in customized:
            raise ServiceValidationError(f"'{target['name']}' is customized more than once.")
        customized.add(identity)
        if _clean(raw.get("emoji")):
            target["emoji"] = _clean(raw.get("emoji")) or ""
        if _clean(raw.get("label")):
            target["label"] = _clean(raw.get("label")) or ""
        if _clean(raw.get("person")):
            target["person"] = _clean(raw.get("person"))
        if raw.get("viewers"):
            target["viewers"] = [viewer for viewer in raw["viewers"] if _clean(viewer)]
        if raw.get("accent") not in (None, "", []):
            target["accent"] = raw.get("accent")
        for key in STUDENT_ENTITY_KEYS:
            if _clean(raw.get(key)):
                target[key] = _clean(raw.get(key))


def _finalize_students(students: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve accents and assign each student the URL hash that opens its pop-up.

    The hash uses only ASCII alphanumerics of the student id (falling back to the
    position), so Hebrew names never end up in URLs.
    """
    for index, student in enumerate(students):
        student["accent"] = _accent(student.get("accent"), index)
        token = re.sub(r"[^A-Za-z0-9]", "", str(student.get("id") or "")) or str(index + 1)
        if student.get("entry_id"):
            hub = re.sub(r"[^A-Za-z0-9]", "", student["entry_id"])
            token = f"{hub}-{token}"
        student["hash"] = f"#mashov-student-{token}"
    return students


def normalize_students(raw_students: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manual student list, used when no Mashov hub has loaded children yet.

    Manually listed students are not family_only: without a person, viewers or
    family they are visible to every dashboard user.
    """
    students: list[dict[str, Any]] = []
    for raw in raw_students or []:
        if not isinstance(raw, dict) or not _clean(raw.get("name")):
            continue
        student = {
            "name": _clean(raw.get("name")),
            "full_name": _clean(raw.get("name")),
            "emoji": _clean(raw.get("emoji")) or "",
            "label": _clean(raw.get("label")) or "",
            "person": _clean(raw.get("person")),
            "viewers": [viewer for viewer in (raw.get("viewers") or []) if _clean(viewer)],
            "accent": raw.get("accent"),
            "family_only": False,
        }
        for key in STUDENT_ENTITY_KEYS:
            student[key] = _clean(raw.get(key))
        if not student["homework"] and not student["timetable"]:
            raise ServiceValidationError(f"Student '{student['name']}' needs at least a homework or timetable sensor")
        students.append(student)
    if not students:
        raise ServiceValidationError(
            "No Mashov students were found. Wait until the integration finishes its first refresh, "
            "or pass students with their sensors."
        )
    return _finalize_students(students)


def resolve_students(hass: HomeAssistant, raw_students: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Discovered children, with the optional service list applied as per-child tweaks."""
    discovered = discover_students(hass)
    if not discovered:
        return normalize_students(raw_students or [])
    _apply_overrides(discovered, raw_students or [])
    return _finalize_students(discovered)


# ---------------------------------------------------------------------------
# Jinja building blocks. Each returns a template fragment (a string) that is
# concatenated into card fields; they set variables consumed by later fragments.
# "{%- ... -%}" trims whitespace so fragments add nothing visible themselves.
# ---------------------------------------------------------------------------


def _holiday_scan(holidays: str) -> str:
    """Jinja that scans the holidays sensor's items and sets `today` and `ns`.

    ns.cur: the holiday covering today (end date inclusive; missing end = one day).
    ns.nxt: the future holiday with the earliest start.
    """
    return (
        "{%- set today = now().date() -%}"
        "{%- set ns = namespace(cur=none, nxt=none) -%}"
        "{%- for x in state_attr('" + holidays + "', 'items') or [] -%}"
        "{%- if x.start -%}"
        "{%- set s = as_datetime(x.start).date() -%}"
        "{%- set e = as_datetime(x.end or x.start).date() -%}"
        "{%- if s <= today and today <= e -%}{%- set ns.cur = x -%}"
        "{%- elif s > today and (ns.nxt is none or s < as_datetime(ns.nxt.start).date()) -%}{%- set ns.nxt = x -%}"
        "{%- endif -%}{%- endif -%}{%- endfor -%}"
    )


def _hero(holidays: str | None) -> dict[str, Any]:
    """Full-width header card: greeting, holiday countdown and a refresh button.

    The greeting uses the viewing user's first name (Bubble Card's `user`
    variable), wrapped in Unicode LTR isolates so a Latin name doesn't disturb
    the RTL line. Without a holidays sensor the icon and state stay static.
    """
    card: dict[str, Any] = {
        "type": "custom:bubble-card",
        "card_type": "button",
        "button_type": "name",
        "name": (
            "{%- set h = now().hour -%}"
            "{{ 'בוקר טוב' if h < 12 else 'צהריים טובים' if h < 17 else 'ערב טוב' if h < 21 else 'לילה טוב' }}, "
            "\u2066{{ (user or '').split(' ')[0] }}\u2069 👋"
        ),
        "icon": "mdi:school",
        "card_layout": "large",
        "grid_options": {"columns": "full", "rows": 2},
        "button_action": {"tap_action": {"action": "none"}},
        "sub_button": {
            "main": [
                {
                    "name": "רענון",
                    "icon": "mdi:cloud-refresh",
                    "show_name": True,
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "mashov.refresh_now",
                        "confirmation": {"text": "לרענן עכשיו את כל נתוני משוב?"},
                    },
                }
            ]
        },
        "styles": QUIET_STYLES
        + """
.bubble-name { font-size: 20px !important; font-weight: 650 !important; }
.bubble-state { font-size: 14px !important; }
.bubble-icon-container { width: 52px !important; height: 52px !important; }
.bubble-icon { color: #c5c8d0 !important; --mdc-icon-size: 26px; }
""",
    }
    if holidays:
        # Each template renders separately, so the scan is repeated in each one.
        # State line: days left in the current holiday (counting today), or days
        # until the next one, or "regular school year".
        scan = _holiday_scan(holidays)
        card["icon"] = scan + "{{ 'mdi:palm-tree' if ns.cur else 'mdi:school' }}"
        card["state_content"] = [
            scan + "{%- if ns.cur -%}"
            "🌴 {{ ns.cur.name }} · עוד {{ (as_datetime(ns.cur.end or ns.cur.start).date() - today).days + 1 }} ימים לחזרה ללימודים"
            "{%- elif ns.nxt -%}"
            "📅 עוד {{ (as_datetime(ns.nxt.start).date() - today).days }} ימים ל{{ ns.nxt.name }}"
            "{%- else -%}שנת לימודים רגילה{%- endif -%}"
        ]
    return card


def _tomorrow_holiday(holidays: str | None, value: str) -> str:
    """Jinja that sets ns.h to `value` (a Jinja expression) if date `t` is a holiday.

    Expects `t` and `ns` (with an `h` field) to be defined by the caller.
    Returns nothing when there is no holidays sensor, leaving ns.h empty.
    """
    if not holidays:
        return ""
    return (
        "{%- for x in state_attr('" + holidays + "', 'items') or [] -%}"
        "{%- if x.start and as_datetime(x.start).date() <= t and t <= as_datetime(x.end or x.start).date() -%}"
        "{%- set ns.h = " + value + " -%}{%- endif -%}{%- endfor -%}"
    )


def _lessons_for_day(entity: str) -> str:
    """Jinja that sets `L` to the timetable lessons of Mashov day `d`, ordered by lesson number.

    Expects `d` from the caller. Match Mashov day numbers whether they arrive as 1 or '1'
    (the `int(-1)` filter also drops unparsable values). A namespace is used
    because plain variables assigned inside a Jinja loop don't survive it.
    """
    return (
        "{%- set nsL = namespace(items=[]) -%}"
        "{%- for x in state_attr('" + entity + "', 'items') or [] if x.timeTable is defined"
        " and (x.timeTable.day | int(-1)) == d -%}"
        "{%- set nsL.items = nsL.items + [x] -%}"
        "{%- endfor -%}"
        "{%- set L = nsL.items | sort(attribute='timeTable.lesson') -%}"
    )


def _tomorrow_line(s: dict[str, Any]) -> str:
    """Jinja for the student card's one-line summary of tomorrow.

    Priority: holiday > Saturday (no school) > lesson count + first three subjects
    > "no timetable for tomorrow". Mashov numbers days 1=Sunday..7=Saturday, so
    isoweekday() (Mon=1..Sun=7) is converted with (isoweekday % 7) + 1.
    """
    lessons = _lessons_for_day(s["timetable"]) if s["timetable"] else "{%- set L = [] -%}"
    return (
        "{%- set t = (now() + timedelta(days=1)).date() -%}"
        "{%- set d = (t.isoweekday() % 7) + 1 -%}"
        "{%- set ns = namespace(h='') -%}"
        + _tomorrow_holiday(s["holidays"], "x.name")
        + lessons
        + "{%- set subs = L | map(attribute='groupDetails.subjectName') | unique | list -%}"
        "{%- if ns.h -%}🌴 מחר {{ ns.h }} · אין לימודים"
        "{%- elif d == 7 -%}😴 מחר שבת"
        "{%- elif L -%}🎒 מחר {{ L | count }} שיעורים · {{ subs[:3] | join(' · ') }}"
        "{%- else -%}אין מערכת למחר{%- endif -%}"
    )


def _chip(entity: str, icon: str, nav: str) -> dict[str, Any]:
    """Compact sub-button showing an entity's state; tapping opens the student pop-up."""
    return {
        "entity": entity,
        "icon": icon,
        "show_name": False,
        "show_state": True,
        "show_background": True,
        "state_background": False,
        "tap_action": {"action": "navigate", "navigation_path": nav},
    }


def _student_card(s: dict[str, Any]) -> dict[str, Any]:
    """Per-student Bubble Card button.

    Title is emoji + name (+ class label), escaped with _jinja_literal. Below it:
    a row of chips for whichever behavior/grades/noticeboard sensors exist and a
    read-only homework slider (0-20). The top border uses the student's accent,
    and a linked person supplies the avatar picture.
    """
    chips = [
        _chip(s[key], icon, s["hash"])
        for key, icon in (
            ("behavior", "mdi:account-heart"),
            ("grades", "mdi:star-circle"),
            ("noticeboard", "mdi:bulletin-board"),
        )
        if s[key]
    ]
    bottom: list[dict[str, Any]] = []
    if chips:
        bottom.append({"group": chips, "justify_content": "fill"})
    if s["homework"]:
        bottom.append(
            {
                "group": [
                    {
                        "entity": s["homework"],
                        "name": "שיעורי בית",
                        "icon": "mdi:book-open-page-variant",
                        "sub_button_type": "slider",
                        "read_only_slider": True,
                        "always_visible": True,
                        "show_button_info": True,
                        "show_name": True,
                        "state_content": "state",
                        "min_value": 0,
                        "max_value": 20,
                    }
                ],
                "justify_content": "fill",
            }
        )
    title = " ".join(_jinja_literal(part) for part in (s["emoji"], s["name"]) if part)
    if s["label"]:
        title += f" · {_jinja_literal(s['label'])}"
    card: dict[str, Any] = {
        "type": "custom:bubble-card",
        "card_type": "button",
        "button_type": "name",
        "name": title,
        "state_content": [_tomorrow_line(s)],
        "scrolling_effect": True,
        "card_layout": "large",
        "grid_options": {"columns": 12, "rows": 2},
        "button_action": {"tap_action": {"action": "navigate", "navigation_path": s["hash"]}},
        "sub_button": {"bottom": bottom},
        "styles": QUIET_STYLES
        + f"""
.bubble-button-card-container {{ border-top: 3px solid {s["accent"]} !important; }}
.bubble-icon-container {{ width: 52px !important; height: 52px !important; }}
.bubble-name {{ font-size: 18px !important; font-weight: 650 !important; }}
""",
    }
    if s["person"]:
        card.update({"entity": s["person"], "force_icon": False, "show_state": False})
    else:
        card["icon"] = "mdi:account-school"
    return card


def _popup_markdown(s: dict[str, Any]) -> str:
    """Markdown/Jinja body of the student pop-up; each block appears only if its sensor exists.

    Blocks: tomorrow (holiday / Saturday alert, else a lessons table with
    teacher and room), the six latest homework items, the four latest behavior
    events, four grades, and noticeboard messages with non-empty text.
    Everything is wrapped in a dir="rtl" div for Hebrew layout.
    """
    parts = ['<div dir="rtl">']
    if s["timetable"] or s["holidays"]:
        lessons_loop = (
            _lessons_for_day(s["timetable"]) + "{% for x in L %}"
            "| {{ x.timeTable.lesson }} | {{ x.groupDetails.subjectName }} | "
            "{{ ((x.groupDetails.groupTeachers or [{}])[0]).teacherName or '' }} | {{ x.timeTable.roomNum or '' }} |\n"
            "{% endfor %}"
            if s["timetable"]
            else ""
        )
        parts.append(
            "{% set t = (now() + timedelta(days=1)).date() %}"
            "{% set d = (t.isoweekday() % 7) + 1 %}"
            "{% set ns = namespace(h='') %}"
            + _tomorrow_holiday(s["holidays"], "x.name")
            + '\n{% if ns.h %}<ha-alert dir="rtl" alert-type="success" title="מחר חופש">🌴 {{ ns.h }}</ha-alert>\n'
            '{% elif d == 7 %}<ha-alert dir="rtl" alert-type="info" title="מחר שבת">😴 אין לימודים</ha-alert>\n'
            '{% else %}<ha-alert dir="rtl" alert-type="info" title="🎒 התיק למחר"></ha-alert>\n\n'
            "| # | מקצוע | מורה | חדר |\n|:-:|---|---|:-:|\n" + lessons_loop + "{% endif %}\n"
        )
    if s["homework"]:
        parts.append(
            "\n### 📚 שיעורי בית אחרונים\n"
            f"{{% set hw = (state_attr('{s['homework']}', 'items') or []) | selectattr('lesson_date') | sort(attribute='lesson_date', reverse=true) %}}"
            "{% if hw %}\n| תאריך | מקצוע | משימה |\n|:-:|---|---|\n"
            "{% for x in hw[:6] %}| {{ as_timestamp(x.lesson_date) | timestamp_custom('%d/%m') }} | "
            "{{ x.subject_name }} | {{ (x.homework or '') | replace('\\n', ' ') | truncate(80) }} |\n{% endfor %}"
            "{% else %}\nאין שיעורי בית 🎉{% endif %}\n"
        )
    if s["behavior"]:
        parts.append(
            "\n### 💬 התנהגות\n"
            f"{{% for x in ((state_attr('{s['behavior']}', 'items') or []) | selectattr('lesson_date') | sort(attribute='lesson_date', reverse=true))[:4] %}}"
            "- **{{ as_timestamp(x.lesson_date) | timestamp_custom('%d/%m') }}** · {{ x.subject }} · {{ x.achva_name }}\n"
            "{% else %}אין אירועים\n{% endfor %}"
        )
    if s["grades"]:
        parts.append(
            "\n### ⭐ ציונים\n"
            f"{{% for x in (state_attr('{s['grades']}', 'items') or [])[:4] %}}"
            "- **{{ x.subjectName }}** · {{ x.gradingEvent }} · <b>{{ x.grade }}</b>\n"
            "{% else %}אין ציונים עדיין\n{% endfor %}"
        )
    if s["noticeboard"]:
        parts.append(
            "\n### 📌 לוח מודעות\n"
            f"{{% set nb = (state_attr('{s['noticeboard']}', 'items') or []) %}}"
            "{% set ns2 = namespace(n=0) %}"
            "{% for x in nb if (x.eventtext or '') | striptags | trim %}{% set ns2.n = ns2.n + 1 %}"
            '\n\n<ha-alert dir="rtl" alert-type="warning">\n'
            "{{ x.eventtext | replace('\\r', '') | replace('\\n', ' ') }}\n</ha-alert>\n"
            "{% endfor %}{% if ns2.n == 0 %}אין מודעות{% endif %}"
        )
    parts.append("</div>")
    return "".join(parts)


def _popup(s: dict[str, Any]) -> dict[str, Any]:
    """Bubble Card pop-up opened by the student's #hash: markdown body plus holidays calendar."""
    cards: list[dict[str, Any]] = [{"type": "markdown", "content": _popup_markdown(s)}]
    if s["calendar"]:
        cards.append(
            {
                "type": "custom:bubble-card",
                "card_type": "calendar",
                "entities": [{"entity": s["calendar"], "color": s["accent"]}],
                "days": 30,
                "limit": 2,
                "show_end": True,
            }
        )
    popup: dict[str, Any] = {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": s["hash"],
        "popup_style": "home-assistant",
        "popup_mode": "adaptive-dialog",
        "width_desktop": "720px",
        "styles": (
            ".bubble-pop-up-title, .bubble-name, .bubble-header { direction: rtl !important; "
            "unicode-bidi: plaintext !important; text-align: start !important; }"
        ),
        "cards": cards,
    }
    title = " ".join(_jinja_literal(part) for part in (s["emoji"], s["name"]) if part)
    if s["label"]:
        title += f" · {_jinja_literal(s['label'])}"
    popup["name"] = title
    if s["person"]:
        popup.update({"entity": s["person"], "force_icon": False})
    else:
        popup["icon"] = "mdi:account-school"
    return popup


def build_live_dashboard(
    students: list[dict[str, Any]],
    *,
    title: str,
    family_user_ids: list[str],
    viewer_user_ids: dict[str, list[str]],
) -> dict[str, Any]:
    """Return the Lovelace config for normalized students.

    viewer_user_ids maps a student hash to the users allowed to see that card, on top of family_user_ids.
    Family members see every card. A child found automatically stays limited to the family until a person is linked.
    """
    # The hero uses the first available holidays sensor (holidays are per school,
    # so any student's sensor gives a reasonable countdown).
    sections: list[dict[str, Any]] = [
        {
            "type": "grid",
            "column_span": 3,
            "cards": [_hero(next((s["holidays"] for s in students if s["holidays"]), None))],
        }
    ]
    for s in students:
        section: dict[str, Any] = {"type": "grid", "cards": [_student_card(s), _popup(s)]}
        users = list(dict.fromkeys([*family_user_ids, *viewer_user_ids.get(s["hash"], [])]))
        # Restrict the section whenever any audience was requested (or the child was
        # auto-discovered). If that restriction resolves to no users, refuse rather
        # than silently publishing the card to everyone or hiding it from everyone.
        if family_user_ids or s["person"] or s["viewers"] or s.get("family_only"):
            if not users:
                if s.get("family_only"):
                    raise ServiceValidationError(
                        f"'{s['name']}' was found automatically and has no linked person. "
                        "Choose the family who may see the cards, or link this student to a person with a Home Assistant user."
                    )
                raise ServiceValidationError(
                    f"'{s['name']}' is limited to people who are not linked to a Home Assistant user, "
                    "and no family was selected. Link those people to users, add a family, or clear the person and viewers."
                )
            section["visibility"] = [{"condition": "user", "users": users}]
        sections.append(section)
    return {
        DASHBOARD_MARKER: True,
        "title": title,
        "views": [
            {
                "title": title,
                "path": "home",
                "icon": "mdi:school",
                "type": "sections",
                "max_columns": 3,
                "dense_section_placement": True,
                "background": "linear-gradient(180deg, #1b1e27 0%, #14161d 100%)",
                "sections": sections,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Saving. These helpers use Lovelace internals (hass.data["lovelace"]), so they
# check for the expected attributes and fail with a clear message if HA changes.
# ---------------------------------------------------------------------------


def _lovelace_dashboards(hass: HomeAssistant) -> dict:
    """Return Lovelace's url_path -> dashboard mapping, or raise if the layout is unexpected."""
    lovelace = hass.data.get(LOVELACE_DATA_KEY)
    dashboards = getattr(lovelace, "dashboards", None)
    if not isinstance(dashboards, dict):
        raise ServiceValidationError(
            "Home Assistant dashboard storage is unavailable or its layout changed. Update the Mashov integration."
        )
    return dashboards


def _dashboard_is_empty(config: dict | None) -> bool:
    """True if saving would not destroy user content.

    No config at all counts as empty. A strategy-based dashboard (auto-generated,
    or a custom strategy) is treated as not empty, as is any view with a strategy,
    cards, or a section containing cards. Empty views/sections are fine.
    """
    if not isinstance(config, dict) or not config or config.get("strategy"):
        return not isinstance(config, dict) or not config
    for view in config.get("views") or []:
        if not isinstance(view, dict) or view.get("strategy") or view.get("cards"):
            return False
        if any(section.get("cards") for section in view.get("sections") or []):
            return False
    return True


def _dashboard_is_ours(config: dict | None) -> bool:
    """True if the config was generated by this module (carries DASHBOARD_MARKER), so regenerating is safe."""
    return isinstance(config, dict) and config.get(DASHBOARD_MARKER) is True


async def _bubble_card_installed(hass: HomeAssistant) -> bool | None:
    """Check the Lovelace resources for Bubble Card.

    Returns None when it can't be determined (e.g. YAML-mode resources or an
    API change), so the caller only warns on a definite False. This is a
    best-effort hint; the dashboard is saved either way.
    """
    lovelace = hass.data.get(LOVELACE_DATA_KEY)
    resources = getattr(lovelace, "resources", None)
    if resources is None or not hasattr(resources, "async_items"):
        return None
    # Storage resources stay empty until something loads them. Loading here avoids a false "not installed".
    if getattr(resources, "loaded", True) is False and hasattr(resources, "async_get_info"):
        try:
            await resources.async_get_info()
        except Exception:
            _LOGGER.debug("Could not load Lovelace resources while checking for Bubble Card")
            return None
    return any(BUBBLE_CARD_RESOURCE in str(item.get("url", "")).lower() for item in resources.async_items())


async def async_save_live_dashboard(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate service data, build the dashboard and save it into an existing storage dashboard.

    The target dashboard must already exist (this never creates dashboards) and be
    UI-managed. Existing content is only replaced if the dashboard is empty, was
    generated by Mashov, or overwrite is true. Returns a summary for the service response.
    """
    url_path = _clean(data.get("dashboard")) or DEFAULT_DASHBOARD
    dashboards = _lovelace_dashboards(hass)
    target = dashboards.get(url_path)
    if target is None:
        raise ServiceValidationError(
            f"Dashboard '{url_path}' was not found. Create an empty dashboard first "
            "(Settings > Dashboards > Add dashboard > New dashboard from scratch) and use its URL here."
        )
    if (
        getattr(target, "mode", None) != "storage"
        or not hasattr(target, "async_load")
        or not hasattr(target, "async_save")
    ):
        raise ServiceValidationError(
            f"Dashboard '{url_path}' is not a UI-managed dashboard, or Home Assistant's dashboard API changed."
        )
    if url_path in PROTECTED_DASHBOARDS and not data.get("overwrite"):
        # An Overview the user never customized has no stored config, so it would pass the
        # emptiness check below and be silently replaced. Built-in dashboards need explicit consent.
        raise ServiceValidationError(
            f"'{url_path}' is a built-in Home Assistant dashboard. Create a separate dashboard for "
            "Mashov Live, or pass overwrite: true to replace it."
        )
    try:
        # force=False: the cached stored config is fine; no reload needed.
        existing = await target.async_load(False)
    except ConfigNotFound:
        # A newly created dashboard has no stored config yet.
        existing = None
    if not data.get("overwrite") and not _dashboard_is_empty(existing) and not _dashboard_is_ours(existing):
        raise ServiceValidationError(
            f"Dashboard '{url_path}' already has content that was not created by Mashov. "
            "Choose an empty dashboard, or pass overwrite: true to replace it."
        )

    students = resolve_students(hass, data.get("students") or [])
    family = person_user_ids(hass, data.get("family"))
    if data.get("family") and not family:
        raise ServiceValidationError(
            "The selected family has no linked Home Assistant users. Link a person to a user first."
        )
    # Per student: its linked person plus extra viewers, resolved to HA user IDs.
    viewers = {s["hash"]: person_user_ids(hass, [p for p in [s["person"], *s["viewers"]] if p]) for s in students}
    config = build_live_dashboard(
        students,
        title=_clean(data.get("title")) or DEFAULT_TITLE,
        family_user_ids=family,
        viewer_user_ids=viewers,
    )
    await target.async_save(config)

    bubble = await _bubble_card_installed(hass)
    if bubble is False:
        _LOGGER.warning(
            "Mashov Live saved, but the Bubble Card frontend resource was not found; install Bubble Card 3.4+"
        )
    return {"dashboard": url_path, "students": len(students), "bubble_card_found": bubble}
