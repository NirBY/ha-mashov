[← README](../README.md) · [Automation blueprints](blueprints.md) · [Services](services.md)

# Mashov Live dashboard

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fscript%2Fmashov%2Fmashov_live_dashboard.yaml)

## What it shows
- A greeting card with the current holiday countdown (or days until the next holiday) and a refresh button.
- One quiet card per student, showing the linked person's photo, a live "tomorrow" line (holiday, Saturday, or the number of lessons and first subjects), behavior, grades and notice counts, and a homework bar.
- A pop-up per student with tomorrow's lessons (teacher and room), recent homework, behavior, grades, notices and the school calendar.
- Hebrew right‑to‑left layout, with English words and numbers kept left‑to‑right.

## Visibility
- **Family** (people selected in the General section) see every card.
- Each student card is also visible to the **linked person** and any **extra viewers**, so a child who logs in sees only their own card.
- A child found automatically, with no linked person and no extra viewers, is visible only to the family. Choose at least one family member, or link that child to a person who has a Home Assistant user.
- Only people linked to a Home Assistant user can be used for visibility. This hides cards in the dashboard; it does not restrict access to the underlying entities.

## Requirements
- Bubble Card 3.4 or newer (HACS → Frontend).
- An empty UI dashboard: **Settings → Dashboards → Add dashboard → New dashboard from scratch**. Note its URL (for example `mashov-live`).

## Setup
1. Click the import button above and create a script from the blueprint.
2. Enter the dashboard URL and the family members. Every child on every Mashov hub is included, with the name, class and sensors the integration already created. The four student sections are optional: type a child's name to set an emoji, color, linked person or extra viewers. Empty sections are skipped.
3. Optional, per child: turn on **Show the next school day for this child**. It is off by default. It skips Saturdays, dates covered by the school holiday sensor (inclusive start/end; no extra day is added before a holiday), and weekdays absent from that child's weekly timetable. The card and pop-up name the actual target day and date when it is later than tomorrow.
4. Save and run the script. Run it again after a new child is added; you do not need to edit the script.

The script only writes into a dashboard that is empty or that it built itself. To replace a dashboard
that has other content, or a built-in one such as the Overview (`lovelace`), turn on **Replace existing
content**; the previous content is lost. Only administrators can run the service.

Blueprint file location: `blueprints/script/mashov/mashov_live_dashboard.yaml`.

---

## Picture examples

Desktop layout with fictitious student names:

![Mashov Live desktop layout](images/mashov_live_desktop.png)

Mobile layout:

![Mashov Live mobile layout](images/mashov_live_mobile.png)

For individual timetable, homework and behavior cards, see the [Lovelace card examples](../examples/lovelace/README.md).

Existing scripts keep their previous behavior because the new input defaults to `false`. Re-import the blueprint, enable the option only in the desired child sections, then run the script again to regenerate the dashboard. Direct service calls use `next_school_day: true` inside that child’s `students` item. This changes display only; stored school data, entity IDs and fetch schedules are preserved. The search looks up to 366 days ahead; no matching day produces a clear message. Without timetable or holiday data, only the available data can be used to skip dates.

### Holiday boundaries

The search uses school-reported vacation ranges, inclusive of both dates. It does not mark a date as closed because its name contains “holiday” or “eve”, and never adds the preceding date to a vacation. A holiday eve outside the vacation stays a school day when that child has lessons. Adjacent vacation ranges are skipped together, with the first day after their final end eligible again.

Verified against the matching holiday caches of both configured schools on 2026-10-23: Rosh Hashanah 11–13 September; Yom Kippur 20–21 September, bridge 22–24 September and Sukkot 25 September–3 October; Hanukkah 6–12 December. For a child studying Fridays, 3 December selects 4 December (a school day); 4 December selects 13 December (Saturday followed by the full vacation). A five-day timetable skips that Friday too. These are test snapshots, not hardcoded dates used by the integration. The school calendar remains authoritative for each child.
