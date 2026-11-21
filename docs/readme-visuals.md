# README visuals

[English README](../README.md) · [Hebrew README](../README.he.md)

The READMEs use separate English and Hebrew assets:

- [Neon overview](images/mashov-neon-overview.png): conceptual artwork generated with the built-in imagegen tool.
- [Animated feature tour](images/mashov-feature-tour.gif): 1280 × 800, approximately 91 seconds, looping, with readable holds and short dissolves. Rendered locally from code using Pillow.
- [Hebrew neon overview](images/mashov-neon-overview-he.png): right-aligned Hebrew artwork, including the spoken bag reminder and the revised labels requested for the overview.
- [Hebrew feature tour](images/mashov-feature-tour-he.gif): the same 14 chapters and timing, with Hebrew text, right-aligned headings, mirrored card layout and progress rail. Latin product names, URLs and times retain their reading order.

Both are illustrations. The tour is not a capture of Home Assistant or a replacement interface. All names, schools, grades, messages and account examples were invented in the renderer. It makes no network requests and reads no live account, credentials, screenshots, private captures or environment variables. Existing HA screenshots and the original usage GIF are separate assets and were not used to build these visuals.

## Text alternative / chapter transcript

Use this table to read the tour without playing the animation. Times are approximate starts; the GIF itself has no seeking controls.

| Time | Chapter | Content |
| --- | --- | --- |
| 00:00 | Family overview | Fictional Alex Demo and Sam Sample attend Maple Demo School and Cedar Demo School. Separate student records, family visibility, desktop/mobile dashboards and manual refresh. |
| 00:06 | School day | Timetable, weekly plan, grade and behavior examples, holidays, bell times and optional next-school-day mode. |
| 00:12 | Homework | Native per-child HA to-do lists. Completion stays local, survives refreshes/restarts and is not written back to Mashov. |
| 00:18 | Data selection, part 1 | Homework, weekly plan, timetable, lesson history; grades, term grades, report cards; behavior, daily behavior, outside lesson behavior and follow-up notes. |
| 00:24 | Data selection, part 2 | Study materials, student files, absence justifications, individual lessons, lesson counts/weekly hours, study groups/teachers; noticeboard, holidays/calendar, school bells; mailbox, parent approvals and student pictures. Approvals are read only; pictures stay in memory. |
| 00:30 | Refresh schedules | Shared account/school defaults, student General defaults and per-data overrides. Daily time, weekly time/weekdays or interval from 5–1440 minutes; inheritance and current schedules; one Submit saves drafts. |
| 00:36 | Account and advanced | Separate account credentials and school selection per hub, school search/fallback, automatic year rollover. Homework window defaults to 7 days back/21 forward; attributes default to 100 items (10–500); configurable API base. |
| 00:42 | Mailbox | Headers/unread count; optional content only for conversations already read in Mashov; separate attachment opt-in requiring content. Inbox limit defaults to 20 (1–50); file limit 25 MB (1–100). Unread conversations stay unread. Downloads require HA sign-in. |
| 00:48 | MCP / Assist | Off by default, enabled per hub, read-only selected datasets, compatible client with administrator OAuth sign-in and HA MCP Server API selection. Student pictures are excluded. The chat is an illustrative question and answer. |
| 00:53 | Blueprint 01: Mashov Live | Script blueprint. Requires Bubble Card 3.4+ and an empty UI dashboard. Dashboard/title/family, optional name/emoji/class/photo/accent/viewers, sensor overrides and next-school-day mode. Replacement is off by default. |
| 01:01 | Blueprint 02: Homework and behavior | Automation. Default 15:00; homework/behavior/holiday sensors, speaker, engine/language, volume/timeouts. Today's data only, daytime, skips holidays, restores speaker volume. |
| 01:08 | Blueprint 03: Bag reminder | Automation. Default 18:00; timetable, holidays, optional weekly plan, per-child next-school-day toggle, speaker/engine/service/language, quiet hours, volumes and timeouts. Skips missing lessons, Saturdays and holidays. |
| 01:16 | Blueprint 04: Noticeboard | Automation. New notice IDs on refresh, one or more sensors, HA/phone notifications, optional speaker/TTS/language, volumes, text limit and timeout. No speech 22:00–07:00; notifications still arrive; no re-announcement on restart. |
| 01:23 | Getting started | HACS/manual install, account/school, sources/options and four blueprints. English, Hebrew, Arabic, Russian and Ukrainian; sensor/calendar/to-do/image platforms, freshness, cache and diagnostics. |

All 23 data keys are listed in `DATA_GROUPS` in the renderer. The underlying categories come from `data_selection.py` and `additional_data.py`; configuration behavior comes from `config_flow.py`, `services.yaml` and the blueprint YAML files. Availability still depends on school permissions. Current source code, rather than a frozen marketing asset, is authoritative.

## Rebuild the GIF

Requires Python, Pillow and Segoe UI (Windows), DejaVu Sans (Linux) or Arial (macOS). From the repository root:

```sh
python -m pip install Pillow
python scripts/build_readme_demo.py --preview-dir .cache/readme-demo
```

To render Hebrew, install the additional Unicode bidirectional-text dependency and select the locale:

```sh
python -m pip install python-bidi
python scripts/build_readme_demo.py --language he --preview-dir .cache/readme-demo-he
```

The Hebrew version writes `docs/images/mashov-feature-tour-he.gif`. Translations live in `scripts/readme_demo_he.json`; missing translations fail the render instead of falling back silently to English. Text is reordered with Unicode bidi and drawn using a right-hand anchor; panels and controls are repositioned, never mirrored as a finished bitmap. The Hebrew README uses a right-aligned RTL wrapper, right-aligned table columns and separate LTR wrappers for YAML examples.

The renderer writes `docs/images/mashov-feature-tour.gif`. Optional preview output includes one still per chapter and a contact sheet in the ignored `.cache` directory. It uses a shared palette for consistent colors, explicit frame durations and infinite looping. Re-running overwrites only its generated outputs; it does not access HA.

Review the contact sheet and full-size frames after changing content, then check the encoded GIF's dimensions, loop flag, duration and file size. If the timeline changes, update chapter times in this document and both README blueprint tables. The existing `mashov-usage.gif` remains available as the original HA walkthrough.

## Neon artwork provenance

Generated and edited with the **built-in imagegen tool**, not the CLI/API fallback. Selected tool outputs were copied into the repository without local image editing. The following is the initial English generation prompt; the final English synchronization prompt is recorded below:

```text
Use case: ads-marketing. Asset type: wide GitHub README hero artwork, approximately 16:9 landscape.
Create a gorgeous neon product illustration presenting the unofficial Mashov school-data integration for Home Assistant. Concept: school life flows into a connected home. A central floating smoked-glass control panel with the large, perfectly legible title "MASHOV" and subtitle "School life. Connected." is surrounded by seven elegant holographic tiles connected with flowing cyan and violet light trails. The tiles are labeled exactly "Homework", "Timetable", "Grades", "Notices", "Schedules", "Blueprints", "AI access". Use simple recognizable dimensional icons for checklists, calendar grid, grade bars, notification bell, clock, automation nodes, and chat spark. Render thoughtful, restrained 3D glass, soft neon cyan, electric purple and a touch of coral, midnight-navy backdrop, subtle atmospheric glow and fine circuitry, strong depth, premium editorial product launch quality. A small school building icon at one end of the connections and a house outline at the other convey integration. The central panel includes only abstract rows and a few check marks, no fake functional screenshot. Clean hierarchy, large text, generous breathing room, crisp polished edges. Footer text exactly "Unofficial integration for Home Assistant". No real names, real faces, grades, school names, hostnames, private data, credentials, third-party logos, or extra text. This is conceptual marketing artwork, not a claim of the app's actual visual interface.
```

### Hebrew artwork

Edited with the built-in imagegen tool from the existing artwork and saved as a separate Hebrew asset. The final image includes eight tiles and uses “שואלים על הלימודים” / “AI באמצעות MCP”, “מכינים תיק למחר” / “תזכורת קולית”, and “מבחנים ושינויי מערכת” as requested. This artwork is conceptual; the GIF's dataset coverage continues to describe the 23 implemented sources and does not add a separate exam-calendar source.

Final edit prompt (the input was the first Hebrew-localized version of the English hero):

```text
Edit target: provided Hebrew neon Mashov artwork. Preserve premium smoked glass, cyan/purple/coral neon palette, central Mashov panel, connected school and home illustration, 16:9 composition, and crisp quality. Update to EIGHT feature tiles. Layout may be gently reorganized for legibility: four feature tiles above and four below the central panel, school at left, house at right, central panel remains dominant. Each tile should have one dimensional icon and a right-aligned Hebrew heading. All Hebrew text must read correctly right to left; English AI/MCP remain left to right inside the lines. EVERY title, label and subtitle must be RIGHT-ALIGNED inside its own card, not centered.
Exact tile text and icon:
1. "שיעורי בית" with checklist.
2. "מערכת שעות" with weekly timetable.
3. "ציונים" with bars.
4. Heading "מכינים תיק למחר" and smaller subtitle "תזכורת קולית", with backpack plus speaker/sound-wave icon. This is a new tile.
5. "הודעות" with bell.
6. "מבחנים ושינויי מערכת" (can wrap to two right-aligned lines) with calendar and refresh arrows, REPLACES the old "תזמונים" clock tile.
7. "בלופרינטים" with connected automation nodes.
8. Heading "שואלים על הלימודים" and smaller subtitle "AI באמצעות MCP", with a chat bubble. REPLACES old "בינה מלאכותית" wording.
Central exact title "משו״ב", right aligned; exact subtitle "בית הספר והבית מתחברים." right aligned. Footer exact "אינטגרציה לא רשמית עבור Home Assistant" right aligned to overall right margin, mixed language order correct. Keep all eight tiles readable and generous padding. No other text, no private data, no duplicated labels. This is concept marketing artwork.
```

### English artwork synchronization

The English hero was then updated from the final Hebrew hero so both READMEs show the same eight topics. Final edit prompt:

```text
Localize the supplied final Hebrew Mashov neon artwork into ENGLISH. Preserve the eight feature tiles, central Mashov smoked-glass panel, backpack with speaker icon, all icons, connected school and home, cyan/purple/coral lights, midnight backdrop, dimensions, composition, spacing and polished quality. Replace ALL Hebrew text; no Hebrew remains. English must be left-to-right and LEFT-ALIGNED inside every panel with generous padding. Central title "MASHOV"; subtitle "School life. Connected."; footer "Unofficial integration for Home Assistant". Eight tiles exactly: checklist "Homework"; timetable "Timetable"; bars "Grades"; backpack/speaker heading "Pack for tomorrow" with smaller subtitle "Spoken reminder"; bell "Notices"; calendar/refresh icon heading "Exams & timetable updates" (wrap cleanly); automation nodes "Blueprints"; chat heading "Ask about school" with smaller subtitle "AI via MCP". All eight tiles must be legible; no added text, no private data, no clipping. Match the Hebrew version as a companion English README illustration.
```
