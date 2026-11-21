"""Render the README feature tour from fictional data; never connects to Home Assistant.

Requires Pillow; Hebrew also requires python-bidi. Run: python scripts/build_readme_demo.py
Use --language he to render the translated, right-aligned RTL tour.
Optional: --preview-dir PATH saves every chapter and a contact sheet for visual review.
This is an illustrated feature tour, not a recording of Home Assistant's UI.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H = 1280, 800
BG = "#090f20"
PANEL = "#121d33"
LINE = "#2b3a55"
WHITE = "#eff5ff"
MUTED = "#a6b6d0"
CYAN = "#57e1f2"
PURPLE = "#b4a1ff"
GREEN = "#75e3b4"
CORAL = "#ffb4a1"

# Every example is invented here. No screenshots, credentials, private files,
# environment variables, HA entities or network requests are used as input.
DATA_GROUPS = [
    (
        "LESSONS",
        [
            ("homework", "Homework"),
            ("weekly_plan", "Weekly plan"),
            ("timetable", "Timetable"),
            ("lessons_history", "Lesson history"),
        ],
    ),
    ("GRADES", [("grades", "Grades"), ("periodic_grades", "Term grades"), ("report_cards", "Report cards")]),
    (
        "BEHAVIOR",
        [
            ("behavior", "Behavior"),
            ("daily_behavior", "Daily behavior"),
            ("outside_behavior", "Outside lesson behavior"),
            ("follow_up", "Follow-up notes"),
            ("attendance_counts", "Absences / lateness"),
        ],
    ),
    (
        "STUDENT RECORDS",
        [
            ("study_materials", "Study materials"),
            ("student_files", "Student files"),
            ("justification_requests", "Absence justifications"),
            ("special_hours", "Individual lessons"),
            ("lessons_count", "Lessons / weekly hours"),
            ("study_groups", "Study groups / teachers"),
        ],
    ),
    (
        "SCHOOL",
        [("message_board", "Noticeboard"), ("holidays", "Holidays / calendar"), ("bells", "School bell schedule")],
    ),
    (
        "ACCOUNT & PROFILE",
        [("mailbox", "Mailbox"), ("parent_approvals", "Parent approvals"), ("picture", "Student pictures")],
    ),
]

CHAPTERS = [
    (
        "overview",
        "SCHOOL LIFE, CONNECTED",
        "One family. One place.",
        "Mashov school data, brought into Home Assistant.",
    ),
    ("day", "YOUR SCHOOL DAY", "See what comes next.", "Timetables, weekly plans, grades and behavior at a glance."),
    (
        "checklist",
        "HOMEWORK CHECKLISTS",
        "Small checks. Big progress.",
        "Native Home Assistant to-do lists, one for each child.",
    ),
    (
        "data1",
        "DATA TO FETCH  /  1 OF 2",
        "Choose what matters.",
        "24 selectable sources. New hubs start with nothing selected.",
    ),
    (
        "data2",
        "DATA TO FETCH  /  2 OF 2",
        "Go beyond the school day.",
        "Choose sources per hub; availability depends on school permissions.",
    ),
    (
        "schedules",
        "REFRESH SCHEDULES",
        "Your data. Your rhythm.",
        "Shared defaults, per-student schedules and per-data overrides.",
    ),
    (
        "settings",
        "ACCOUNT & ADVANCED OPTIONS",
        "Make it fit your family.",
        "Independent credentials and school selection for every hub.",
    ),
    (
        "mailbox",
        "OPTIONAL MAILBOX",
        "Stay in the loop.",
        "Headers first. Message content and attachments are separate opt-ins.",
    ),
    (
        "ai",
        "OPTIONAL MCP / ASSIST",
        "Ask about the school day.",
        "Read-only access to selected data, enabled separately for each hub.",
    ),
    (
        "live",
        "BLUEPRINT 01 / 04",
        "Mashov Live dashboard",
        "Create a family view with Bubble Card and student detail popups.",
    ),
    (
        "homework",
        "BLUEPRINT 02 / 04",
        "Homework & behavior",
        "A daily spoken summary of today's homework and behavior.",
    ),
    ("bag", "BLUEPRINT 03 / 04", "Tomorrow starts tonight.", "The bag reminder reads the subjects to pack for school."),
    (
        "notice",
        "BLUEPRINT 04 / 04",
        "School news, delivered.",
        "Notify your phone and optionally announce new noticeboard posts.",
    ),
    (
        "finish",
        "READY FOR YOUR HOME",
        "School life. In sync.",
        "Install through HACS, choose your data, then add your blueprints.",
    ),
]


def font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental") / ("Arial Bold.ttf" if bold else "Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            # Hebrew is reordered explicitly with python-bidi; BASIC prevents a
            # second reordering on machines where Pillow also includes RAQM.
            return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
    raise RuntimeError("Install Segoe UI, DejaVu Sans or Arial to render this demo.")


FONTS = {
    (size, bold): font(size, bold)
    for size in (15, 16, 18, 20, 21, 22, 24, 26, 28, 30, 36, 44, 50, 64)
    for bold in (False, True)
}


class Canvas:
    def __init__(self, language="en"):
        self.rtl = language == "he"
        self.translations = {}
        if self.rtl:
            from bidi import get_display

            self.bidi_display = get_display
            self.translations = json.loads((ROOT / "scripts/readme_demo_he.json").read_text(encoding="utf-8"))
        self.im = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.im)
        # Restrained neon edge lighting; flat panels keep GIF text crisp.
        for y in range(H):
            self.d.line((0, y, W, y), fill=(9 + y // 180, 15 + y // 160, 32 + y // 80))
        for x in range(800, W, 64):
            self.d.line((x, 0, x + 260, 260), fill="#142039", width=1)

    def localized(self, text):
        if not self.rtl:
            return text
        if text in self.translations:
            return self.translations[text]
        if match := re.fullmatch(r"(\d+) / 3 done", text):
            return f"הושלמו {match[1]} מתוך 3"
        if match := re.fullmatch(r"(\d+) / 14    •    FEATURE TOUR", text):
            return f"סיור באינטגרציה • פרק {match[1]} מתוך 14"
        if re.fullmatch(r"[\d :/]+", text) or text in {"M", "MCP / Assist", "https://web.mashov.info/api/"}:
            return text
        raise ValueError(f"Missing Hebrew tour translation: {text!r}")

    def visual_text(self, text):
        text = self.localized(text)
        if self.rtl and re.search(r"[\u0590-\u05ff]", text):
            text = self.bidi_display(text, base_dir="R")
            # Bidi isolates preserve LTR product names, ranges and URLs; the
            # formatting controls themselves must not draw as missing glyphs.
            text = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", text)
        return text

    def text(self, x, y, text, size=22, color=WHITE, bold=False):
        self.d.text(
            (W - x if self.rtl else x, y),
            self.visual_text(text),
            font=FONTS[size, bold],
            fill=color,
            anchor="ra" if self.rtl else "la",
        )

    def line(self, points, fill=LINE):
        if self.rtl:
            points = tuple(W - p if i % 2 == 0 else p for i, p in enumerate(points))
        self.d.line(points, fill=fill)

    def box(self, x, y, w, h, fill=PANEL, outline=LINE, radius=20):
        if self.rtl:
            x = W - x - w
        self.d.rounded_rectangle((x, y, x + w, y + h), radius, fill=fill, outline=outline, width=1)

    def chip(self, x, y, text, color=CYAN, active=True):
        width = int(self.d.textlength(self.visual_text(text), font=FONTS[18, True])) + 28
        self.box(x, y, width, 34, "#20354a" if active else PANEL, color if active else LINE, 17)
        self.text(x + 14, y + 5, text, 18, color if active else MUTED, True)
        return width

    def check(self, x, y, on=True, color=CYAN):
        self.box(x, y, 25, 25, color if on else PANEL, color if on else LINE, 7)
        if on:
            if self.rtl:
                x = W - x - 25
            self.d.line([(x + 6, y + 12), (x + 11, y + 17), (x + 20, y + 7)], fill=BG, width=3)

    def toggle(self, x, y, on=False):
        self.box(x, y, 46, 25, CYAN if on else "#34425b", None, 13)
        cx = x + (33 if on else 13)
        if self.rtl:
            cx = W - cx
        self.d.ellipse((cx - 8, y + 5, cx + 8, y + 21), fill=BG if on else MUTED)

    def row(self, x, y, label, value, w=710, color=WHITE):
        self.text(x, y, label, 20, MUTED)
        self.text(x, y + 29, value, 24, color, True)
        self.line((x, y + 67, x + w, y + 67))

    def header(self, chapter, stage):
        key, kicker, title, subtitle = CHAPTERS[chapter]
        self.box(48, 27, 35, 35, CYAN, None, 10)
        self.text(57, 29, "M", 22, BG, True)
        self.text(97, 30, "MASHOV", 22, WHITE, True)
        self.text(228, 34, "/  HOME ASSISTANT", 16, MUTED)
        self.chip(902, 28, "ILLUSTRATED DEMO", PURPLE)
        self.text(48, 99, kicker, 16, CYAN, True)
        self.text(46, 128, title, 44, WHITE, True)
        self.text(48, 191, subtitle, 22, MUTED)
        for i in range(len(CHAPTERS)):
            x = 48 + i * 85
            self.box(x, 738, 76, 4, CYAN if i <= chapter else LINE, None, 2)
        self.text(48, 758, "FICTIONAL DATA ONLY  /  No live account connected", 15, MUTED)
        self.text(948, 758, f"{chapter + 1:02d} / {len(CHAPTERS):02d}    •    FEATURE TOUR", 15, MUTED)
        return key


def overview(c, stage):
    c.box(48, 252, 1184, 82)
    c.text(73, 267, "Welcome home, Demo family", 28, WHITE, True)
    c.text(73, 305, "Two fictional students  •  Two school hubs", 18, MUTED)
    c.chip(1010, 275, "Refresh now")
    for i, (name, school, initials, accent) in enumerate(
        [
            ("Alex Demo", "Maple Demo School • Class 5A", "AD", CYAN),
            ("Sam Sample", "Cedar Demo School • Class 7B", "SS", PURPLE),
        ]
    ):
        x = 48 + 604 * i
        c.box(x, 356, 580, 244, outline=accent)
        c.box(x + 24, 381, 56, 56, "#24354c", None, 18)
        c.text(x + 33, 393, initials, 22, accent, True)
        c.text(x + 97, 377, name, 28, WHITE, True)
        c.text(x + 97, 419, school, 18, MUTED)
        c.text(x + 24, 471, "Next day: Math, Science, English" if i == 0 else "Next day: Art, History, Sport", 22)
        c.chip(x + 24, 523, "3 homework" if i == 0 else "2 homework", accent)
        c.chip(x + 192, 523, "Grades", accent, stage >= 1)
        c.chip(x + 304, 523, "Notices", accent, stage >= 2)
    c.text(70, 646, "Separate student records", 22, CYAN, True)
    c.text(470, 646, "Family visibility controls", 22, PURPLE, True)
    c.text(880, 646, "Desktop + mobile", 22, GREEN, True)


def day(c, stage):
    c.box(48, 253, 728, 436)
    c.text(74, 275, "Alex Demo  /  Timetable", 26, WHITE, True)
    c.chip(524, 274, "Next school day", CYAN)
    for i, (time, subject, detail) in enumerate(
        [
            ("08:15", "Math", "Fractions • Room 12"),
            ("09:10", "Science", "Plant life • Room 8"),
            ("10:20", "English", "Reading circle • Room 12"),
        ]
    ):
        y = 346 + i * 83
        c.box(72, y, 680, 70, "#1c3047" if i == stage else "#152239", None, 12)
        c.text(89, y + 20, time, 24, CYAN, True)
        c.text(199, y + 6, subject, 24, WHITE, True)
        c.text(199, y + 39, detail, 18, MUTED)
    c.text(75, 625, "Weekly plan: bring a notebook and a ruler.", 21, MUTED)
    c.box(800, 253, 432, 204)
    c.text(828, 276, "Recent grade", 20, MUTED)
    c.text(826, 312, "92", 64, PURPLE, True)
    c.text(930, 340, "Science quiz", 22)
    c.text(828, 414, "Fictional example", 18, MUTED)
    c.box(800, 480, 432, 209)
    c.text(828, 505, "Behavior & calendar", 24, WHITE, True)
    c.text(828, 554, "Great teamwork in class", 22, GREEN)
    c.text(828, 605, "School holidays and bell times", 20, MUTED)
    c.text(828, 640, "Optional next-school-day mode", 18, CYAN)


def checklist(c, stage):
    c.box(48, 253, 760, 436)
    c.text(76, 279, "Alex's homework", 28, WHITE, True)
    c.chip(587, 281, f"{stage + 1} / 3 done", GREEN)
    tasks = [
        ("Math", "Complete the fractions worksheet"),
        ("Science", "Draw and label a leaf"),
        ("English", "Read chapter two"),
    ]
    for i, (subject, task) in enumerate(tasks):
        y = 350 + i * 91
        done = i <= stage
        c.check(80, y + 11, done, GREEN)
        c.text(124, y, subject, 22, GREEN if done else WHITE, True)
        c.text(124, y + 33, task, 21, MUTED)
    c.box(836, 253, 396, 436)
    c.text(865, 282, "Made for real routines", 24, WHITE, True)
    for y, title, desc in [
        (360, "Per-child lists", "Keep everyone's tasks separate."),
        (458, "Saved locally", "Completion survives restarts."),
        (556, "Mashov stays unchanged", "No completion written to school."),
    ]:
        c.text(865, y, title, 22, CYAN, True)
        c.text(865, y + 37, desc, 18, MUTED)


def data(c, stage, second):
    for col, (title, items) in enumerate(DATA_GROUPS[3 if second else 0 : 6 if second else 3]):
        x = 48 + col * 400
        accent = (CYAN, PURPLE, GREEN)[col]
        c.box(x, 254, 384, 435, outline=accent if stage == col else LINE)
        c.text(x + 24, 277, title, 20, accent, True)
        for row, (_, label) in enumerate(items):
            y = 334 + row * 49
            c.check(x + 24, y + 1, col <= stage, accent)
            c.text(x + 65, y, label, 20)
        if second and col == 2:
            c.text(x + 24, 539, "Approvals: view in HA;", 20, MUTED)
            c.text(x + 24, 571, "answer in the Mashov app.", 20, MUTED)
            c.text(x + 24, 627, "Pictures: kept in memory only.", 18, MUTED)
        elif len(items) < 5:
            c.text(x + 24, 631, "Select only what you need.", 18, MUTED)


def schedules(c, stage):
    c.box(48, 253, 330, 436)
    c.text(74, 280, "SCHEDULE SCOPE", 18, CYAN, True)
    for i, (a, b) in enumerate(
        [
            ("Shared account", "School data + defaults"),
            ("Alex Demo", "General default"),
            ("Alex Demo", "Homework override"),
        ]
    ):
        y = 340 + i * 100
        c.box(70, y, 285, 81, "#233a50" if stage == i else PANEL, CYAN if stage == i else LINE, 12)
        c.text(87, y + 10, a, 22, WHITE, True)
        c.text(87, y + 44, b, 18, MUTED)
    c.box(402, 253, 830, 436)
    for i, label in enumerate(["Daily", "Weekly", "Interval"]):
        c.chip(430 + i * 169, 281, label, CYAN, stage == i)
    values = [
        ("Refresh time", "14:00 • Home Assistant timezone", "Every day"),
        ("Refresh time + weekdays", "16:00 • Monday, Wednesday, Friday", "Selected weekdays"),
        ("Interval minutes", "60 minutes", "Allowed interval: 5–1440 minutes"),
    ]
    a, b, d = values[stage]
    c.row(432, 353, a, b, 768, CYAN)
    c.text(432, 448, d, 22)
    c.toggle(432, 500, stage == 0)
    c.text(494, 498, "Inherit default schedule", 22, MUTED)
    c.text(432, 557, "Switch students and data types without losing drafts.", 21, MUTED)
    c.text(432, 596, "One Submit saves all schedule changes.", 21, WHITE, True)
    c.chip(432, 639, "Current schedules", PURPLE)
    c.chip(674, 639, "One refresh queue", GREEN)


def settings(c, stage):
    for i, (title, rows) in enumerate(
        [
            (
                "Account & school",
                [
                    ("School / hub", "Maple Demo School"),
                    ("Username / password", "Fictional demo account"),
                    ("Automatic school year", "On • rollover September 1"),
                ],
            ),
            (
                "Advanced settings",
                [
                    ("Homework date window", "7 days back / 21 forward"),
                    ("Items in attributes", "100 • configurable 10–500"),
                    ("API base", "https://web.mashov.info/api/"),
                ],
            ),
        ]
    ):
        x = 48 + i * 604
        c.box(x, 253, 580, 436)
        c.text(x + 27, 279, title, 28, CYAN if i == 0 else PURPLE, True)
        for j, (a, b) in enumerate(rows):
            c.row(x + 27, 346 + j * 105, a, b, 526)
    c.text(75, 657, "School search + manual fallback", 18, MUTED)
    c.text(679, 657, "Refresh now • validated option updates", 18, MUTED)


def mailbox(c, stage):
    c.box(48, 253, 574, 436)
    c.text(76, 280, "Demo school inbox", 28, WHITE, True)
    c.chip(416, 282, "2 unread", CYAN)
    for i, (subject, state) in enumerate(
        [
            ("Science fair next week", "Unread • headers only"),
            ("Library book reminder", "Unread • headers only"),
            ("Class newsletter", "Already read in Mashov"),
        ]
    ):
        y = 350 + i * 100
        c.text(77, y, subject, 24, WHITE, True)
        c.text(77, y + 39, state, 20, CYAN if i < 2 else MUTED)
        c.line((77, y + 78, 592, y + 78))
    c.text(77, 657, "Unread conversations stay unread.", 20, GREEN)
    c.box(646, 253, 586, 436)
    c.text(674, 280, "Choose your access", 28, PURPLE, True)
    for y, title, desc, on in [
        (349, "Headers + unread count", "Mailbox category selected", True),
        (430, "Full message content", "Off by default • already-read messages only", stage >= 1),
        (511, "Download attachments", "Off by default • needs full content", stage >= 2),
    ]:
        c.toggle(674, y + 3, on)
        c.text(738, y, title, 22, WHITE, True)
        c.text(674, y + 39, desc, 18, MUTED)
    c.text(674, 596, "Recent inbox: 20 conversations (1–50)", 20)
    c.text(674, 632, "File limit: 25 MB (1–100) • signed-in downloads", 18, MUTED)


def ai(c, stage):
    c.box(48, 253, 360, 436)
    c.text(76, 281, "ENABLE PER HUB", 18, CYAN, True)
    c.toggle(76, 340, stage >= 1)
    c.text(139, 338, "MCP / Assist", 24, WHITE, True)
    c.text(76, 401, "Off by default", 22, MUTED)
    for y, a, b in [
        (460, "Selected datasets only", "Choose APIs in HA's MCP Server."),
        (550, "Administrator sign-in", "Compatible client + OAuth."),
    ]:
        c.text(76, y, a, 22, CYAN, True)
        c.text(76, y + 35, b, 18, MUTED)
    c.box(432, 253, 800, 436)
    c.text(461, 281, "An example conversation", 24, MUTED)
    c.box(568, 345, 632, 68, "#293853", None, 18)
    c.text(591, 365, "What homework does Alex have?", 26, WHITE, True)
    if stage >= 1:
        c.box(460, 442, 691, 145, "#18313e", CYAN, 18)
        c.text(484, 462, "Alex has 3 tasks:", 24, CYAN, True)
        c.text(484, 507, "Math worksheet, a leaf drawing,", 24)
        c.text(484, 546, "and chapter two for English.", 24)
    c.text(461, 631, "Read-only answers • student pictures are never exposed", 20, MUTED)


BLUEPRINTS = {
    "live": (
        "01",
        "SCRIPT BLUEPRINT",
        "Build the family view",
        "Run once to create or update.",
        [
            ("Requirements", "Bubble Card 3.4+ + empty UI dashboard"),
            ("Dashboard / title / family", "mashov-demo / Demo family / Demo Parent"),
            ("Optional student customization", "Name, emoji, class, photo, accent, viewers"),
            ("Per-child options", "Sensor overrides + next-school-day toggle"),
        ],
        "Auto-discovers students across hubs",
        "Replace existing content: off by default",
    ),
    "homework": (
        "02",
        "AUTOMATION BLUEPRINT",
        "Listen after school",
        "Daily run time: 15:00 by default.",
        [
            ("Mashov entities", "Homework + behavior + holidays"),
            ("Voice destination", "Demo speaker + TTS engine + language"),
            ("Playback controls", "Temporary volume + start / finish timeouts"),
            ("Runs when", "Today's data exists; daytime; not a holiday"),
        ],
        "Today's homework + behavior, spoken in Hebrew",
        "Previous speaker volume is restored",
    ),
    "bag": (
        "03",
        "AUTOMATION BLUEPRINT",
        "Pack with confidence",
        "Daily run time: 18:00 by default.",
        [
            ("Mashov entities", "Timetable + holidays + optional weekly plan"),
            ("School-day mode", "Tomorrow / optional next school day per child"),
            ("Voice options", "Speaker, TTS engine/service, language, plan"),
            ("Playback controls", "Quiet hours, max/fallback volume, timeouts"),
        ],
        "Read the subjects and optional lesson plan",
        "Skips nights, Saturdays, holidays and missing lessons",
    ),
    "notice": (
        "04",
        "AUTOMATION BLUEPRINT",
        "Catch the new notices",
        "Runs when refreshed data includes a new notice.",
        [
            ("Watch", "One or more student noticeboard sensors"),
            ("Notify", "HA notification + optional phone action"),
            ("Optional voice", "Speaker, TTS engine, language, volume"),
            ("Message / playback limits", "Characters per notice + TTS timeout"),
        ],
        "Notifications still arrive during quiet hours",
        "No speech 22:00–07:00 • no restart re-announcements",
    ),
}


def blueprint(c, key, stage):
    number, kind, title, timing, rows, outcome, guard = BLUEPRINTS[key]
    c.box(48, 253, 350, 436, outline=PURPLE)
    c.text(76, 278, kind, 16, PURPLE, True)
    c.text(73, 315, number, 64, PURPLE, True)
    # Split the editorial description explicitly to stay legible at README width.
    words = title.split()
    c.text(76, 414, " ".join(words[:2]), 30, WHITE, True)
    c.text(76, 456, " ".join(words[2:]), 30, WHITE, True)
    timing_lines = {
        "live": ["Run once to create", "or update the view."],
        "homework": ["Daily at 15:00", "by default."],
        "bag": ["Daily at 18:00", "by default."],
        "notice": ["New posts detected", "on data refresh."],
    }
    for i, line in enumerate(timing_lines[key]):
        c.text(76, 539 + i * 33, line, 22, MUTED)
    c.chip(76, 625, ["Choose entities", "Set options", "Ready to import"][stage], CYAN)
    c.box(422, 253, 810, 436)
    for i, (label, value) in enumerate(rows):
        c.row(449, 271 + i * 83, label, value, 756, CYAN if i == stage else WHITE)
    c.text(449, 616, outcome, 21, GREEN, True)
    c.text(449, 653, guard, 18, MUTED)


def finish(c, stage):
    for i, (n, title, body, foot) in enumerate(
        [
            ("01", "Connect", "HACS or manual install", "Choose account + school"),
            ("02", "Personalize", "Data, schedules, mailbox", "Multiple students + hubs"),
            ("03", "Automate", "Four ready-made blueprints", "Dashboard + daily routines"),
        ]
    ):
        x = 48 + i * 400
        color = (CYAN, PURPLE, GREEN)[i]
        c.box(x, 253, 384, 302, outline=color if i <= stage else LINE)
        c.text(x + 26, 275, n, 50, color, True)
        c.text(x + 26, 351, title, 30, WHITE, True)
        c.text(x + 26, 418, body, 22)
        c.text(x + 26, 472, foot, 20, MUTED)
    c.box(48, 579, 1184, 110)
    c.text(77, 597, "English  /  Hebrew  /  Arabic  /  Russian  /  Ukrainian", 24, WHITE, True)
    c.text(77, 642, "Sensors • calendar • to-do • images • freshness status • cache • diagnostics", 22, MUTED)


def render(chapter, stage, language="en"):
    c = Canvas(language)
    key = c.header(chapter, stage)
    if key in BLUEPRINTS:
        blueprint(c, key, stage)
    elif key.startswith("data"):
        data(c, stage, key == "data2")
    else:
        {
            "overview": overview,
            "day": day,
            "checklist": checklist,
            "schedules": schedules,
            "settings": settings,
            "mailbox": mailbox,
            "ai": ai,
            "finish": finish,
        }[key](c, stage)
    return c.im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "he"), default="en")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    if args.output is None:
        suffix = "-he" if args.language == "he" else ""
        args.output = ROOT / f"docs/images/mashov-feature-tour{suffix}.gif"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stills = [render(i, 2, args.language) for i in range(len(CHAPTERS))]
    # One shared palette avoids flicker and keeps text consistent between scenes.
    palette_sheet = Image.new("RGB", (W, H * len(stills)))
    for i, frame in enumerate(stills):
        palette_sheet.paste(frame, (0, i * H))
    palette = palette_sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    frames, durations = [], []
    previous = None
    for chapter in range(len(CHAPTERS)):
        first = render(chapter, 0, args.language)
        if previous is not None:
            # Short transitions, long readable holds. No flashing or rapid zooms.
            for mix in (0.25, 0.5, 0.75):
                frames.append(Image.blend(previous, first, mix).quantize(palette=palette, dither=Image.Dither.NONE))
                durations.append(80)
        for stage in range(3):
            frame = render(chapter, stage, args.language)
            frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
            durations.append(1900 if chapter < 9 else 2400)
            previous = frame
    for mix in (0.25, 0.5, 0.75):
        frames.append(
            Image.blend(previous, render(0, 0, args.language), mix).quantize(palette=palette, dither=Image.Dither.NONE)
        )
        durations.append(80)
    frames[0].save(
        args.output, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=1
    )
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        sheet = Image.new("RGB", (W, math.ceil(len(stills) / 2) * H // 2), BG)
        for i, frame in enumerate(stills):
            frame.save(args.preview_dir / f"{i + 1:02d}-{CHAPTERS[i][0]}.png")
            sheet.paste(frame.resize((W // 2, H // 2), Image.Resampling.LANCZOS), ((i % 2) * W // 2, (i // 2) * H // 2))
        sheet.save(args.preview_dir / "contact-sheet.jpg", quality=90)
    print(
        f"Saved {args.output}: {args.output.stat().st_size / 1024 / 1024:.2f} MiB, {sum(durations) / 1000:.2f}s, {len(frames)} frames"
    )


if __name__ == "__main__":
    main()
