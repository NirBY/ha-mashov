[**English**](README.md) · [**עברית**](README.he.md)

# Mashov — Home Assistant Integration (HACS)

Unofficial integration for **משו״ב (Mashov)**. Bring school information into Home Assistant and choose the data fetched for each account and school hub.

**Current release: v1.1.0 · Requires Home Assistant 2025.3 or newer.**

**v1.1.0** adds student-specific refresh schedules and an editor embedded in Setup and Configure. Update through HACS and restart Home Assistant.

Community project; not affiliated with Mashov. See [release notes](RELEASE_NOTES.md) for upgrade details and the [Changelog](CHANGELOG.md) for version history.

## Quick start

1. In **HACS → Integrations → ⋯ → Custom repositories**, add `https://github.com/NirBY/ha-mashov` as an **Integration**. Install Mashov and restart Home Assistant.
2. Open **Settings → Devices & services → Add integration → Mashov** and enter your credentials and school.
3. Select categories in **Data to fetch**, then **Submit**. You can change them later in **Mashov → Configure**.

> **New hubs start with all 18 categories off.** Submitting an empty selection connects the account but creates no school-data sensors. Dashboards and blueprints need their corresponding categories enabled. For a basic student dashboard, select Homework, Behavior, Weekly plan, Timetable, Lesson history and Grades; add Holidays for the calendar and holiday-aware automations.

Upgrades preserve existing selections, entity IDs and customizations. New sources and mailbox content are never enabled by an upgrade. Hubs created in v1.0.15 retain their previously enabled Noticeboard selection.

## Available data

Choose what to fetch in **Data to fetch**. New hubs start with nothing selected; upgrades keep your selections.

**Data to fetch — v1.1.0**

| Group | Available data |
| --- | --- |
| Lessons | Homework, weekly plan, timetable, lesson history |
| Grades | Grades, term grades, report cards |
| Behavior | Behavior, daily behavior, outside lesson behavior, follow-up notes |
| Student records | Study materials, student files, absence justification requests, individual lessons |
| School | Noticeboard, holidays and calendar |
| Mailbox | Unread count and recent headers; message content is optional |

Selections apply to all students in the hub. Mailbox belongs to the account; holidays belong to the school. Availability depends on school permissions. Files are listed, not downloaded.

**Fetching full mailbox content marks conversations as read in Mashov.** It requires separate consent.

## Refresh schedules

In **Configure → Refresh schedules**, edit schedules directly inside the form. Select **Student**, then **General — default schedule** or a data type. Controls update immediately; switching types or students preserves the draft. Uncheck inheritance to customize a schedule. The form’s **Submit** saves all settings and all students together. No separate editor link is needed.

Select **Student** in the interactive editor to edit that child's schedules. **General** is this student's default; individual data types can override it. Switching students preserves drafts, and one Submit saves all students in the selected account together. Existing account schedules remain inherited until overridden, so upgrading does not change current refresh times. Holidays remain school-wide and Mailbox account-wide; select **Shared account / school data and defaults** to edit those resources. A student's timer requests only that student's due resources and preserves siblings' values and timestamps. Manual refresh still updates all selected data. New students inherit existing account defaults; schedules use stable student IDs, so name changes do not swap schedules. In registration, initial defaults are saved first; students become selectable after authentication loads the roster.

Hub registration embeds the same schedule controls in **Refresh schedules**. Enter account details, select data and set initial General/per-data schedules before one **Submit**. Students become available after authentication loads the roster. Setup and Configure follow Home Assistant’s language, including Hebrew and English.

The collapsed **Current schedules** overview shows all 18 categories and their effective schedule. In **Refresh schedules**, choose a student and data type, then select Daily, Weekly or Interval. Daily shows a time, Weekly adds weekdays, and Interval shows minutes (5–1440). Keep inheritance checked to use existing defaults. Finish with the main form’s Submit; cancelling leaves saved settings unchanged.

Times use Home Assistant's timezone. Disabled categories never fetch data, even if they have a schedule. Equal schedules are batched; different schedules fetch only their due categories. Other categories retain their values and their actual last-fetch timestamps. Manual refresh and initial cache warm-up still fetch all enabled data. Existing daily, weekly, interval and legacy single-weekday configurations keep their schedules without requiring migration or re-adding the integration. YAML shared schedule settings still override the shared UI schedule; separate overrides remain independent.

Example action: fetch homework every 30 minutes and grades weekly on Friday (0=Monday); all other selected types keep the shared schedule:

```yaml
action: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  data_schedules:
    homework:
      schedule_type: interval
      schedule_interval: 30
    grades:
      schedule_type: weekly
      schedule_time: "18:00"
      schedule_days: [4]
```

`data_schedules` replaces the complete override map. Send `{}` to return every type to the shared schedule. Reducing intervals increases portal requests and can generate more login/activity emails.

Refresh jobs use one queue across all Mashov hubs: a scheduled or manual refresh waits for the active job to finish. Reloading a hub drains its active request and skips its queued jobs before closing the connection.

### Selecting and disabling data

In **Configure → Data to fetch**, add categories from the list or remove selected chips with **×**, then **Submit**. Configure each hub separately. A selection change reloads the hub and attempts an immediate refresh; the default daily refresh is at 14:00.


Removing a category clears its active and disk cache **before login**, even if the next refresh fails, and disables its entities while preserving IDs and history. Disabling an entity in HA does not stop fetching its category; remove it in Configure to stop requests. An empty selection retains authentication and the student roster.

### Mailbox consent and retention

Headers do not mark conversations read. The separate, default-off **Full message content (marks conversations read)** checkbox fetches plain-text bodies and **marks fetched conversations read in Mashov**, even if you have not opened them. Attachments are not downloaded. The conversation limit defaults to **20**, range **1–50**.

Turning off full content removes cached bodies. Removing Mailbox also resets full-content consent; adding it again starts with headers only. Previously marked conversations do not become unread again.

The cache stores the last snapshot **without age-based expiry**; failures can leave older data visible as stale. The default request window of 7 days back and 21 forward is not a history deletion policy. Recorder history and backups have independent retention policies; disabling data or deleting a hub does not purge them. Deleting a hub removes its integration cache and saved authentication.

> **Mailbox privacy:** Home Assistant users, including non-admin child accounts, can read mailbox sensor attributes. Dashboard card visibility does not restrict access to these entities. With the privacy fix in this working tree, the mailbox `items` attribute (headers and bodies) is excluded from future Recorder history automatically. Existing history is not purged. Enable mailbox access only if everyone with access to your HA instance may see this information.

To also exclude the unread count and other mailbox metadata from future history, exclude the actual mailbox sensor ID in `configuration.yaml`, then restart Home Assistant:

```yaml
recorder:
  exclude:
    entities:
      - sensor.REPLACE_WITH_YOUR_MAILBOX_ENTITY_ID
```

Merge this into your existing `recorder` configuration. This does not remove existing history, the integration cache or backups, and does not restrict live access to the sensor.

## 🧩 Features
- Simple **Config Flow (UI)** via Settings → Devices & Services → Add Integration → **Mashov**.
- **Daily refresh** (14:00 by default) + `mashov.refresh_now` service for on-demand updates.
- **Sensors** expose compact **state** (count) + rich **attributes** (lists you can use in automations / dashboards).
- **Calendar entity** for school holidays - integrates with Home Assistant calendar view 📅
- **Diagnostics** endpoint for safe issue reporting (redacts credentials).
- **Mashov Live dashboard** (Bubble Card) built by a script blueprint, with person photos and per-person card visibility.
- **Choose each data source** per school hub, including homework, timetable, grades, holidays and additional student data. New hubs start with no datasets selected; existing hubs keep their choices.
- **Mailbox**: opt-in unread count and recent inbox headers, with a separate, default-off full-content option that marks fetched conversations read in Mashov.
- **Noticeboard notices**: optional sensor plus a blueprint that notifies and reads new notices aloud, with built-in quiet hours.

---

## 📦 Installation

### Via HACS (recommended)
1. Open **HACS → Integrations → ⋯ → Custom repositories**.
2. Add repository URL: `https://github.com/NirBY/ha-mashov`. Select **Category: Integration**.
3. Search for **Mashov** in HACS, install, and **Restart Home Assistant**.

### Manual
1. Copy `custom_components/mashov` into your HA `/config/` folder.
2. Restart Home Assistant.

> The integration includes a custom `icon.png`.

---

## ⚙️ Configuration

1. **Add Integration → Mashov**.
2. Enter **username / password**.
3. Pick your **school** from the dropdown with **fast autocomplete** (type to filter). If the list doesn't load, a text field appears; type the **school name in Hebrew** or the **Semel** and we'll resolve it.
4. Select the required categories in **Data to fetch** (initially empty), then **Submit**. Only selected sensors/calendar are created. Mailbox full content requires a separate opt-in and marks fetched conversations read.

### Options

To configure options, go to: **Settings → Devices & Services → Mashov → Configure**

Credential updates in **Configure** apply only to the specific Mashov hub entry you opened. If you have multiple Mashov hubs, updating one hub's username or password does **not** automatically update the others.

Duplicate accounts for the same school are detected during setup. Different accounts
can expose the same child in separate hubs without sensor unique-ID collisions.
The school year advances automatically on September 1 unless an existing entry has
an explicitly configured year; that year remains pinned until you enable
**Automatic school year** in Configure (or `automatic_school_year: true` with `mashov.set_options`).

- **Homework window**: days back (default 7), days forward (default 21)
- **Daily refresh time**: default `14:00`
- **API base**: default `https://web.mashov.info/api/` (override if your deployment differs)
- **Max items in attributes**: maximum items to store in sensor attributes (default 100, range: 10-500)
  - Controls how many recent items are stored in sensor attributes to prevent database size issues
  - Sensors automatically clean technical fields and limit size to fit within Home Assistant's 16KB limit
  - Full data is always available via `coordinator.data` for advanced automations
  - Attributes show `total_items` (all available) and `stored_items` (actually stored in attributes)

#### Important note about night-time polling
- Pulling data at night may trigger email notifications from Mashov about account activity/logins. If this is undesirable:
  - Prefer scheduling the daily/weekly refresh to daytime hours (e.g., `14:00`).
  - Use the Options screen or YAML to set `schedule_type` and `schedule_time` accordingly.
  - Avoid long-running `interval` mode during overnight hours.

### Data to fetch

Every dataset is now selectable, including the six main sensors (homework, behavior,
weekly plan, timetable, lessons history, grades), holidays and ten additional student
resources below. Deselecting a type stops its requests, removes its active/disk cache before login on reload, and disables its entities.
New installations select only what they need. Existing installations retain their
previous core data and optional selections; no mailbox or newly added source is enabled
by upgrading. Disabled entities retain their entity IDs, user customizations and history
and can be enabled again. Entities disabled manually in Home Assistant remain disabled.

**What changed, and since which version**

| Version | Change |
| --- | --- |
| v1.0.7 | The nine additional data types became available. Turn them on per school hub, as described below. |
| v1.0.15 | Hubs created in this version started with **Noticeboard** turned on; that choice is preserved when upgrading. |
| v1.0.15 | New blueprint that notifies you about new noticeboard notices and reads them aloud (see [below](#-automation-blueprint-new-noticeboard-notice)). |
| v1.0.16 | All datasets are selectable. Existing hubs, including those configured since v1.0.7, retain their selections and entity IDs. New setups start with an empty selection. Adds mailbox and individual lessons. |

**How to turn them on**

1. Go to **Settings → Devices & services → Mashov**.
2. Next to the school hub, click **Configure** (with several hubs, do this for each one).
3. In **Data to fetch** (Hebrew UI: **סוגי מידע לשליפה**), select what you want to keep enabled.
4. Click **Submit**. A changed selection reloads the hub and fetches the selected data immediately.
   An empty selection stops dataset polling; credentials and student discovery remain part of account setup.

From an automation or script you can do the same with the `mashov.set_options` action:

```yaml
action: mashov.set_options
data:
  entry_id: <your hub's entry id>   # optional with a single hub
  enabled_data: [homework, timetable, message_board, periodic_grades]
```

The list replaces the entire selection, so include everything you want to keep.
Older automations using `additional_data` still work: that key changes only the optional
student sources and preserves the selected core data and mailbox.

**What each one gives you** (one sensor per child; the state is the number of items)

| Option (English / Hebrew) | Key | Contents |
| --- | --- | --- |
| Noticeboard / לוח מודעות | `message_board` | Notices the school posts for parents: text (`eventtext`, HTML), ID (`eventid`), expiration date |
| Daily behavior / התנהגות יומית | `daily_behavior` | Daily behavior records within the homework date window |
| Outside lesson behavior / התנהגות מחוץ לשיעור | `outside_behavior` | Behavior events outside lessons (breaks, trips), within the date window |
| Follow-up notes / הערות מעקב | `follow_up` | Staff follow-up notes, within the date window |
| Term grades / ציונים תקופתיים | `periodic_grades` | Term (period) grades |
| Report cards / תעודות | `report_cards` | Report card records (metadata only) |
| Study materials / חומרי לימוד | `study_materials` | Study material records (metadata only, files are not downloaded) |
| Student files / קובצי תלמיד | `student_files` | Student file records (metadata only, files are not downloaded) |
| Absence justification requests / בקשות להצדקת היעדרות | `justification_requests` | Absence justification requests, within the date window |
| Individual lessons / שעות פרטניות | `special_hours` | Individual-lesson records (`specialHoursLessons`), when published by the school |

The "date window" is the homework days-back/days-forward setting. Find the new sensors in
**Developer Tools → States** by searching for the option name; the records are in the `items` attribute.

**Good to know**
- These student resources do not submit forms or download files. The separate mailbox full-content option
  below has read-status side effects and requires explicit opt-in.
- Each school decides what parents can see. A type your school does not allow shows state `unknown` with
  `source_status: forbidden` (or `unsupported`). It is checked again after 24 hours, separately for each child.
  An allowed type with no records shows `0`.
- Attributes are limited in size. When records are left out, `stored_items` is smaller than `total_items`.
- Parent approvals and the Shahaf exam calendar are not integrated. A read-only online-form list is also
  exposed by the portal (`user/forms?isParentsConsent=false`); its route was verified on 2026-10-06 but the
  tested account had no records, so form content/answer status has not been validated or added.

### Mailbox (optional)

Select **Mailbox — headers and unread count** to create one sensor per account/school hub,
not one per child. Its state is the current number of unread conversations. Attributes
contain the inbox count and the latest **20 conversations** (configurable from 1 to 50),
with conversation/message IDs, subject, sender, date, read status and attachment indicator.
Header-only mode does not open conversations or mark them read.

**Full message content is off by default. Enabling it marks fetched conversations as read
in Mashov, even if you have not opened them yourself.** This behavior was confirmed against
the live portal: the conversation GET alone changed the unread count from 1 to 0.
Only the fetched recent inbox conversations are opened; older inbox pages, sent mail,
drafts and archived conversations are not fetched. Turning off Mailbox also resets
full-content consent; selecting it again starts in header-only mode.

Bodies are exposed as plain text in `items[].messages[].body`; HTML is not executed and
images/attachments are never downloaded. Attributes stay below Home Assistant's recorder
budget. Long bodies can be shortened in sensor attributes (`body_truncated: true` and
`content_truncated: true`); the coordinator retains the fetched full text. Check
`stored_conversations` versus `fetched_conversations` for omitted records. Per-conversation
`content_status` shows failed body fetches, and `counts_status` shows unread-count failures;
failures are never presented as zero unread. The unread count is refreshed after body fetching.

```yaml
action: mashov.set_options
data:
  entry_id: <your hub's entry id>
  enabled_data: [homework, timetable, mailbox]
  mailbox_full_content: false
  mailbox_limit: 20
```

Message content stays in your Home Assistant instance/cache. The privacy fix excludes
`items` from future Recorder history; previously recorded content is not deleted. Diagnostics contain technical statuses only, never message bodies, subjects, senders
or conversation IDs. Selection changes do not delete existing Recorder history.

### Configuration via configuration.yaml (optional)
You can also configure the shared refresh schedule via YAML. Scheduling values in YAML
override the shared Options UI schedule, but do not override separate per-data schedules.
Configure the API base, homework window, and item limit
through the Options UI.

```yaml
mashov:
  # Scheduling
  schedule_type: daily        # daily | weekly | interval
  schedule_time: "14:00"      # for daily/weekly
  schedule_day: 0             # 0=Monday ... 6=Sunday
  schedule_days: [0, 2, 4]    # optional multiple days for weekly
  schedule_interval: 120      # minutes (for interval mode)
```

---

## 🧠 Entities (per child)

For each child **N**, these sensors are created when their categories are selected:

The IDs below are illustrative. Home Assistant assigns entity IDs from entity names
and its registry; select your actual IDs in **Settings → Devices & Services → Entities**.
Upgrading preserves existing entity IDs and history references. Internal unique IDs
are scoped to each hub automatically.

- **Weekly Plan** – `sensor.mashov_<student_id>_weekly_plan`
- **Homework** – `sensor.mashov_<student_id>_homework`
- **Behavior** – `sensor.mashov_<student_id>_behavior`
- **Timetable** – `sensor.mashov_<student_id>_timetable`
- **Lessons History** – `sensor.mashov_<student_id>_lessons_history` (`…_lesson_history` on new installations)
- **Grades** – `sensor.mashov_<student_id>_grades`

**State** = number of items.
**Attributes** (common): `items`, `formatted_summary`, `formatted_by_date`, `formatted_by_subject` (and for timetable: also table helpers).

Weekly-plan subjects and teachers are filled from timetable groups where available,
and grouped views include the plan text. Dated plans render a date-labelled HTML table
instead of combining different weeks into one grid. Students continue updating after
a class-name change because data lookup follows their stable student ID. Schedule
timestamps use Home Assistant's configured timezone. `last_update` is the
actual last successful refresh time in Home Assistant's timezone, or null for legacy caches without a timestamp.

> **Tip**: Use `{{ state_attr('sensor.mashov_<id>_homework', 'items') }}` to access raw lists.
>
> **Note**: The `items` attribute contains cleaned, size-optimized recent items (technical fields removed). To see all items:
> - `total_items` = total number of items available
> - `stored_items` = number of items in the `items` attribute
> - Full raw data is always available via `coordinator.data` for advanced automations

### School hub entities

Each hub with Holidays selected has its own holiday sensor and calendar. Select the matching school's
entities in cards and automations; IDs can have suffixes on installations with multiple hubs.
- **Holidays Sensor** – `sensor.mashov_<school>_holidays_count` on new installations (older: `sensor.mashov_holidays`, `sensor.mashov_holidays_2`, …)
  State = number of holidays. Attributes: `items`, `formatted_summary`, `formatted_by_date`.

- **Holidays Calendar** – `calendar.mashov_<school>_holidays_calendar` on new installations (older: `calendar.mashov_holidays_calendar`, …)
  Full calendar integration for school holidays. Shows events in Home Assistant calendar view with start/end dates.
  _Contributed by [@aviadlevy](https://github.com/aviadlevy)_

---

## 🔔 Automation Blueprint: Daily Homework & Behavior Announcement

A ready-to-use blueprint that speaks today's homework and behavior in Hebrew at a fixed time, with safe defaults and volume handling.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

If you hit a cache issue when importing, use the commit‑pinned link:

[Import pinned version](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fe9aade5%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_daily_homework_announce.yaml`.

What does it do?
- Daily voice announcement at **15:00** that reads the student’s **name**, **today’s behaviors**, and **today’s homework** (Hebrew).
- Runs **only in daytime** and **skips holidays** using your Mashov holidays sensor (`Items[start/end]`).
- Triggers **only if there is data for today** in the homework and/or behavior sensors.
- Temporarily **sets the speaker to max volume**, speaks via **`tts.speak`** (configurable), then **restores the original volume** after playback.
- Works with any `media_player` (Sonos, Nest, etc.); volume restore is state-aware.
- Fully **templated blueprint**: select your own Mashov sensors and speaker at import time.
- Safe defaults: 15:00 schedule, Hebrew (`he-IL`) TTS, 07:00–22:00 guard rails.
- GitHub-friendly: no hardcoded entity IDs; can be imported with a **My Home Assistant** one-click link.

How to use
1. Click the import button above and select your `holiday_sensor`, `homework_sensor`, `behavior_sensor`, `media_player`, and optional `tts_service`.
2. Save the automation. By default it runs every day at 15:00.

---

## 🎒 Automation Blueprint: Bag Reminder (Tomorrow's Subjects)

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fbag_reminder_tomorrow.yaml)

What does it do?
- Runs once daily at 18:00 to help a student pack their school bag for tomorrow.
- Skips automatically if it’s night-time, Saturday, or a listed holiday (from the holiday sensor).
- Reads tomorrow’s subjects only when timetable data actually exists for tomorrow.
- Builds a Hebrew TTS message: “שלום {Student}… אנא לסדר תיק למחר… {subjects + teacher names [+ plan]}”.
- Temporarily raises the speaker to a configurable max volume, then restores the previous (or fallback) volume after TTS ends.
- Pulls subjects and teacher names from the Mashov timetable; optionally appends each lesson’s “plan” from the weekly plan sensor.
- Waits for the speaker state to finish playing before restoring volume, to avoid cutting the message.
- Provides rich trace/log lines explaining why it ran or skipped (night block, Saturday, holiday, has data).

Blueprint file location: `blueprints/automation/mashov/bag_reminder_tomorrow.yaml`.

How to use
1. Click the import button above, pick your Mashov timetable sensor, (optional) weekly plan sensor, holiday sensor, media player and voice settings.
2. Save the automation. Defaults: 18:00, Hebrew, night guard 22:00–07:00.

---

## 📌 Automation Blueprint: New Noticeboard Notice

Get a phone notification, and optionally hear it on a speaker, when the school posts a new notice
on a child's Mashov noticeboard. Added in v1.0.15.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_noticeboard_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_noticeboard_announce.yaml`.

Requirements
- **Noticeboard** turned on for the hub ([how](#data-to-fetch)). Hubs created in v1.0.15 keep it enabled; new setups choose it explicitly.

What does it do?
- Watches one or more noticeboard sensors (one per child). A notice counts as new when its Mashov notice ID was not
  there before, so a notice that replaces another is announced, and a removed notice is not.
- Sends a Home Assistant notification (on by default) and, if you enter one, a phone notification
  (for example `notify.mobile_app_my_phone`). HTML is removed and long notices are shortened.
- Optionally reads the notice aloud in Hebrew: turns the speaker on, raises the volume, speaks with `tts.speak`,
  then restores the previous volume (or a fallback volume if it was unknown).
- **Never speaks during quiet hours, 22:00–07:00.** This is built in and cannot be turned off, so there are no
  surprise announcements at night. A notice that arrives then is still sent as a notification.
- Never re-announces existing notices after a Home Assistant restart, a reload, or a temporary outage.
- Logs every decision to the logbook (announced, quiet hours, nothing new), like the other Mashov blueprints.

Timing: notices arrive with the integration's refresh, not instantly. With the default daily refresh at 14:00,
a morning notice is announced at 14:00. For faster updates, switch the hub to interval mode (for example every
60 minutes) in Configure.

How to use
1. Click the import button above and create an automation from the blueprint.
2. Select the noticeboard sensors, and optionally a phone notify action, a speaker and a TTS engine.
3. Save. Nothing is announced right away; the next new notice triggers it.

Playback waits up to the configured TTS timeout for a slow speaker to start, then waits
up to that timeout for playback to finish before restoring volume (120 seconds each by default).
If playback never starts or never finishes, the timeout bounds the wait.

---

## ✨ Script Blueprint: Mashov Live dashboard (Bubble Card)

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fscript%2Fmashov%2Fmashov_live_dashboard.yaml)

What does it build?
- A greeting card with the current holiday countdown (or days until the next holiday) and a refresh button.
- One quiet card per student, showing the linked person's photo, a live "tomorrow" line (holiday, Saturday, or the number of lessons and first subjects), behavior, grades and notice counts, and a homework bar.
- A pop-up per student with tomorrow's lessons (teacher and room), recent homework, behavior, grades, notices and the school calendar.
- Hebrew right‑to‑left layout, with English words and numbers kept left‑to‑right.

Who sees which card?
- **Family** (people selected in the General section) see every card.
- Each student card is also visible to the **linked person** and any **extra viewers**, so a child who logs in sees only their own card.
- A child found automatically, with no linked person and no extra viewers, is visible only to the family. Choose at least one family member, or link that child to a person who has a Home Assistant user.
- Only people linked to a Home Assistant user can be used for visibility. This hides cards in the dashboard; it does not restrict access to the underlying entities.

Requirements
- Bubble Card 3.4 or newer (HACS → Frontend).
- An empty UI dashboard: **Settings → Dashboards → Add dashboard → New dashboard from scratch**. Note its URL (for example `mashov-live`).

How to use
1. Click the import button above and create a script from the blueprint.
2. Enter the dashboard URL and the family members. Every child on every Mashov hub is included, with the name, class and sensors the integration already created. The four student sections are optional: type a child's name to set an emoji, color, linked person or extra viewers. Empty sections are skipped.
3. Save and run the script. Run it again after a new child is added; you do not need to edit the script.

The script only writes into a dashboard that is empty or that it built itself. To replace a dashboard
that has other content, or a built-in one such as the Overview (`lovelace`), turn on **Replace existing
content**; the previous content is lost. Only administrators can run the service.

Blueprint file location: `blueprints/script/mashov/mashov_live_dashboard.yaml`.

---

## 🛠️ Services

### `mashov.refresh_now`
Trigger an immediate refresh.
```yaml
service: mashov.refresh_now
data:
  entry_id: YOUR_ENTRY_ID  # optional; if omitted, all entries refresh
```

Calling without `entry_id` refreshes all configured Mashov hubs.

### `mashov.set_options`

Update a hub's options without opening Configure:

```yaml
service: mashov.set_options
data:
  entry_id: YOUR_ENTRY_ID
  schedule_type: weekly
  schedule_time: "14:00"
  schedule_days: [0, 2, 4]  # Monday, Wednesday, Friday
```

For backward compatibility, omitting `entry_id` targets the first loaded hub.
Specify it when selecting a particular hub. The legacy `schedule_day` field remains
supported; supplying it without `schedule_days` replaces the selected days with
that one day. Invalid service inputs are rejected. YAML scheduling overrides still apply.

### `mashov.create_live_dashboard`

Build the Mashov Live dashboard into an existing UI dashboard. With no `students` list it includes every child from every hub. The script blueprint above calls this service; you can also call it directly:

```yaml
action: mashov.create_live_dashboard
data:
  dashboard: mashov-live          # URL of an existing, empty UI dashboard
  title: משוב לייב
  family: [person.parent_1, person.parent_2]
  overwrite: false                # true replaces other content or a built-in dashboard
  students:                       # optional tweaks; omitted children still appear
    - name: נועה                  # full name, or a unique first name
      emoji: "🚀"
      person: person.noa          # photo + this user sees the card
      viewers: [person.grandma]   # optional extra viewers
      accent: [155, 176, 201]     # RGB list or "#9bb0c9"
response_variable: result
```

The response reports the dashboard, the number of students and whether the Bubble Card resource was found. There is no limit on the number of children.

---

## 🧱 Lovelace Cards (Examples)
Ready-made cards live in [`examples/lovelace/cards/`](examples/lovelace/cards/). HACS installs only
`custom_components/`, so copy the cards from GitHub. Full instructions and the placeholder table are in
[examples/lovelace/README.md](examples/lovelace/README.md).

| Card | Shows | Needs |
| --- | --- | --- |
| [`homework_list_by_date.yaml`](examples/lovelace/cards/homework_list_by_date.yaml) | Homework grouped by date | config-template-card, html-card |
| [`behavior_list_by_date.yaml`](examples/lovelace/cards/behavior_list_by_date.yaml) | Behavior events grouped by date | config-template-card, html-card |
| [`weekly_plan_table_advanced.yaml`](examples/lovelace/cards/weekly_plan_table_advanced.yaml) | This week's timetable with plans and holidays | config-template-card, html-card |
| [`weekly_plan_table_dynamic.yaml`](examples/lovelace/cards/weekly_plan_table_dynamic.yaml) | The same, two days at a time with paging (mobile) | config-template-card, html-card |
| [`refresh_all_button.yaml`](examples/lovelace/cards/refresh_all_button.yaml) | Refresh all hubs | nothing |

**How to add a card**
- **UI dashboard (the default):** edit the dashboard → **Add card** → **Manual**, and paste the whole file.
  `!include` does not work in UI dashboards.
- **YAML dashboard:** copy the files to `/config/lovelace/cards/examples/` and include them:
  ```yaml
  views:
    - title: Mashov
      cards:
        - !include lovelace/cards/examples/homework_list_by_date.yaml
  ```

Then replace every placeholder (for example `sensor.mashov_<studentID>_homework`) with your own entity ID.
Each placeholder appears twice in a card: once under `entities` and once inside the JavaScript.
For the weekly cards, use the holiday sensor of the student's own school hub.

Example previews:

## 🔍 Troubleshooting

- **401 / authentication failures**: check credentials and school choice, and update credentials through **Configure**. Password-change responses display a link to the Mashov login page.
- **403 / school-disabled resources**: core resources such as weekly plan retry after 1 hour, then 6 hours, then 24 hours. Each student's resource has its own cooldown, which resets after success. Optional resources use a separate 24-hour cooldown. A school permission denial does not necessarily mean the password is wrong.
- **Startup connection failures**: HA retries transient setup failures when no cached data is available. When cached data exists, the integration retains it until a refresh succeeds.
- **Different host**: open **Options → API base** and paste the base prefix you see in your browser DevTools Network tab (up to `/api/`).
  Common defaults: `https://web.mashov.info/api/`, sometimes `https://mobileapi.mashov.info/api/`.
- **No schools in dropdown**: temporary catalog issue — the flow falls back to text; enter the name or Semel to resolve.
- **Autocomplete not working**: suggestions are limited to 50 schools; type the school name or Semel to search beyond those suggestions.
- **Multiple kids missing**: ensure your account actually lists multiple students in Mashov. Check HA logs for `custom_components.mashov` debug entries.
- **Session errors**: if you see "Unclosed client session" errors, restart Home Assistant to clear any stale connections.
- **Mailbox reload race**: a closed session during mailbox fetching is treated as an operational fetch failure. Other unexpected runtime errors remain reportable.
- **"New Device" emails**: session persistence reduces unnecessary logins but cannot prevent fresh authentication after a server-side session expiry. Authentication is saved after successful refreshes in `.storage/mashov.<entry_id>.cache`. Avoid unnecessary reloads and never share this file; it contains authentication data.

### Notifications, GitHub, Telegram and GreenAPI

Authentication and full-refresh failures create a persistent notification in the HA
UI. A successful refresh dismisses that hub's notification. Only detected internal
programming errors offer GitHub reporting; account, network, HTTP/API availability
and school-permission failures do not. The link opens a prefilled issue form for review; publishing or closing an issue
on GitHub does not synchronize its status back into HA.

The integration does not include GitHub issue monitoring or automatic Telegram/
GreenAPI delivery. Configure those separately if needed. To forward HA notifications,
use a `persistent_notification` trigger for added/updated notifications; listening
only for calls to the `persistent_notification.create` service misses notifications
created directly by integration code. For HACS release alerts, monitor the relevant
`update` entities rather than relying on the legacy `sensor.hacs` entity.

### Enable debug logs
```yaml
logger:
  logs:
    custom_components.mashov: debug
```

---

## 🔐 Privacy & Security
- Credentials are stored by Home Assistant in the config entry store.
- The integration mirrors the Mashov web client behavior (headers, cookies, API calls). Endpoints may change without notice.
- Before sharing logs, screenshots, or diagnostics in GitHub issues, review them and remove personal data such as usernames, student names, IDs, grades, homework text, session cookies, tokens, phone numbers, email addresses, and any other sensitive school or account details.
- If you are unsure whether something is safe to share, redact it first. Only upload the minimum data needed to reproduce the problem.

---

## 📄 License
MIT © 2025

---
