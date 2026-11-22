[**English**](README.md) · [**עברית**](README.he.md)

# Mashov — Home Assistant integration (HACS)

Unofficial integration for **משו״ב (Mashov)**. Choose which school data to bring into Home Assistant for each account and school hub.

Community project; not affiliated with Mashov. [Release notes](RELEASE_NOTES.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

[Mashov connects homework, timetables, grades, spoken bag reminders, notices, exams and timetable updates, blueprints and AI via MCP to Home Assistant — neon concept illustration](docs/images/mashov-neon-overview.png)

## The new child view

![Actual Mashov cards: weekly start/end times, a homework checklist and older homework days](docs/images/mashov-children-live.gif)

This GIF records the **actual interactive cards** using fictional names, homework and school data. It shows checking a task without removing it, opening older homework days, and recalculating hours after a published timetable change. It is a component demo, not a connection to a live school account.

- **Weekly school table:** each child's subjects and daily start/end times, using the school's bell schedule. Missing times are labeled.
- **Homework:** the last **3 dates with homework**, a collapsible list, persistent checkboxes with strike-through, and **Show older days**. The blueprint lets you choose 1–14 recent homework dates.
- **Readable detail buttons:** messages, grades, behavior and homework open their content; attendance and lesson counters have labeled breakdowns.
- **Reusable blueprint:** [Import the new-view blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fscript%2Fmashov%2Fmashov_live_dashboard.yaml), then create and run its script. Requires Mashov **1.6.0+**, Bubble Card **3.4+**, and an empty UI dashboard. [Setup and upgrade guide](docs/dashboard.md).

The table updates when Mashov's published timetable changes. **Cancellations appearing only in messages or Shahaf/iScool are not applied automatically.** The cards and completion data survive normal upgrades with the same persistent HA configuration; future compatibility still requires testing.

## What it looks like

**Explore the integration in 90 seconds:** family dashboards, timetables, homework checklists, all 24 data sources, refresh schedules, account and advanced options, optional mailbox and AI access, and all four blueprints.

[Animated Mashov feature tour: fictional family data, selectable sources, settings and four blueprint walkthroughs](docs/images/mashov-feature-tour.gif)

The neon artwork and animated tour are **illustrations**, not screenshots of a new interface. Every person, school, grade, message and entity example in the tour is fictional; no live Home Assistant account was used. [Actual dashboard screenshots](docs/dashboard.md) · [Original HA walkthrough](docs/images/mashov-usage.gif) · [Tour transcript and rebuild instructions](docs/readme-visuals.md)

### All blueprints shown in the tour

| Blueprint | In the GIF | What it does / main options | Get started |
| --- | --- | --- | --- |
| [Mashov Live dashboard](blueprints/script/mashov/mashov_live_dashboard.yaml) | 00:53 · 01/04 | **Script:** discovers students across hubs and builds a family dashboard. Choose dashboard, title, family, optional student styling/viewers/sensor overrides and next-school-day mode. Requires **Bubble Card 3.4+** and an empty UI dashboard. | [Import](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fscript%2Fmashov%2Fmashov_live_dashboard.yaml) · [Guide](docs/dashboard.md) |
| [Daily homework & behavior](blueprints/automation/mashov/mashov_daily_homework_announce.yaml) | 01:01 · 02/04 | **Automation:** speaks today's homework and behavior, default **15:00**. Select homework/behavior/holiday sensors, speaker, TTS engine, language, time, volume and playback timeouts. Skips holidays, nighttime and days without today's data; restores volume. | [Import](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml) · [Guide](docs/blueprints.md#daily-homework-and-behavior) |
| [Bag reminder](blueprints/automation/mashov/bag_reminder_tomorrow.yaml) | 01:08 · 03/04 | **Automation:** reads tomorrow's subjects, default **18:00**. Select timetable/holiday sensors, optional weekly plan, speaker, TTS settings, time, quiet hours, volumes and timeouts. Optional next-school-day mode per child. | [Import](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fbag_reminder_tomorrow.yaml) · [Guide](docs/blueprints.md#bag-reminder) |
| [Noticeboard notices](blueprints/automation/mashov/mashov_noticeboard_announce.yaml) | 01:16 · 04/04 | **Automation:** announces new notice IDs on refresh. Select noticeboard sensors, HA/phone notifications, optional speaker/TTS, language, volumes, text limit and timeout. No speech **22:00–07:00**; notifications still arrive. | [Import](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_noticeboard_announce.yaml) · [Guide](docs/blueprints.md#noticeboard-notices) |

GIF times are approximate chapter starts. Enable the corresponding data sources before using a blueprint. Importing adds a template; create and configure a script or automation from it. For Mashov Live, run the configured script to build the view.

## 📦 Installation

Requires **Home Assistant 2025.3 or newer**.

**HACS:** open **HACS → Integrations → ⋯ → Custom repositories**, add `https://github.com/NirBY/ha-mashov` as an **Integration**, install Mashov and restart Home Assistant.

**Manual:** copy `custom_components/mashov` to `/config/custom_components/mashov`, then restart Home Assistant.

For updates, install through HACS and restart. Existing data selections, schedules, entity IDs and customizations are preserved; no new data source is enabled automatically.

Saved dashboards remain in HA's persistent configuration through upgrades. The [dashboard guide](docs/dashboard.md#keeping-the-dashboard-through-upgrades) explains backups and frontend dependencies, and covers the readable attendance, subject, lesson and bell-time cards with optional neon styling.

## ⚙️ Configuration

1. Open **Settings → Devices & services → Add integration → Mashov**.
2. Enter your username/password and choose the school. Type to filter the school list; if the catalog is unavailable, enter its name or Semel in the fallback text field.
3. Choose categories in **Data to fetch** and set **Refresh schedules** if needed, then **Submit**. New hubs start with nothing selected; an empty selection connects the account but creates no school-data sensors.

Each account/school combination is a separate hub. Configure credentials for each hub independently. The school year advances automatically on September 1 unless you pin it; enable **Automatic school year** to resume automatic rollover.

You may also set the **shared schedule** in `configuration.yaml`, then restart Home Assistant:

```yaml
mashov:
  schedule_type: daily       # daily | weekly | interval
  schedule_time: "14:00"     # daily/weekly
  schedule_days: [0, 2, 4]   # weekly: Monday, Wednesday, Friday
  schedule_interval: 60      # interval: minutes
```

YAML overrides the shared UI schedule. Separate student/data schedules remain independent. API base, data selection, date window and item limit are configured through Options. The legacy single `schedule_day` remains supported.

[Picture examples of the current setup and Configure forms](docs/configuration.md)

## 🧩 Features

- All **24 data types** are selectable; only enabled categories are fetched. Multiple hubs and students are supported without mixing their records.
- **Student-specific General and per-data schedules:** daily, weekly or interval, edited inside Setup/Configure. One Submit saves all drafts.
- **One refresh queue** across hubs, including scheduled, manual and startup requests. Selective refreshes preserve other students’ values and timestamps.
- **Sensors and holiday calendars**, with structured records, formatted summaries, actual update times, source status and stale-data indicators.
- **Opt-in account mailbox:** unread count and recent headers, with separately consented plain-text content for already-read conversations and optional attachment downloads for signed-in Home Assistant users.
- **Cache and session persistence**, retry/backoff for unavailable sources, automatic school-year rollover and cleanup of departed students after a verified roster refresh.
- **English, Hebrew, Arabic, Russian and Ukrainian** UI labels; Hebrew/Arabic schedule editing supports right-to-left layout.
- **Mashov Live dashboard**, individual Lovelace cards and three announcement/reminder blueprints; see the linked guides below.
- **Manual actions and diagnostics:** refresh, validated option updates, admin-only dashboard creation and sanitized internal-error reports reviewed before submission.

## Options

Open **Settings → Devices & services → Mashov → Configure** beside the hub you want to change. Sections group Data to fetch, Refresh schedules, Account and school, and Advanced settings. Current schedules and help start collapsed.

| Setting | Default / behavior |
| --- | --- |
| Homework date window | 7 days back, 21 days forward; a request window, not a history-deletion policy |
| Shared refresh | Daily at 14:00, in Home Assistant’s timezone |
| Recent mailbox conversations | 20; range 1–50 |
| Maximum mail attachment size | 25 MB; range 1–100 |
| Items in sensor attributes | 100; range 10–500, further reduced to fit the attribute-size budget |
| API base | `https://web.mashov.info/api/` |
| Automatic school year | Enabled unless the account has a pinned year |

### Refresh schedules

Select **Student**, then **General — default schedule** or a data type. Uncheck inheritance to customize it. Daily shows a time; Weekly shows time and weekdays; Interval shows minutes (5–1440). Switching students/types keeps the draft; the main **Submit** saves all edits together. Cancelling leaves saved settings unchanged.

During registration, set initial defaults first; students become selectable once authentication loads the roster. Student schedules use stable IDs. New students inherit account defaults, and Holidays/Mailbox retain school/account scope. Select **Shared account / school data and defaults** for those resources.

**Current schedules** shows all categories and their effective schedules. Disabled categories are never fetched. Identical schedules are batched, and every refresh waits for active work to finish. Unload waits only for that hub’s active request and skips its queued work. Manual refresh updates all selected data. A daily or weekly refresh that fails for a network or server reason is retried after 5, 15 and 60 minutes; a rejected login is not retried. After a restart, a daily or weekly refresh that was missed while Home Assistant was off, or that failed, runs right away. Night-time fetching may cause Mashov login/activity emails; choose daytime schedules if this is undesirable.

[Current inline-form pictures](docs/configuration.md) · [Schedule actions and YAML examples](docs/services.md#mashovset_options)

<a id="data-to-fetch-1"></a>

### Data to fetch

Available in **v1.1.0**. New hubs start with nothing selected; upgrades keep existing selections.

| Group | Data types |
| --- | --- |
| Lessons | Homework, weekly plan, timetable, lesson history |
| Grades | Grades, term grades, report cards |
| Behavior | Behavior, daily behavior, outside lesson behavior, follow-up notes, absence and lateness counters |
| Student records | Study materials, student files, absence justification requests, individual lessons, lessons held and weekly hours per group, study groups and teachers |
| School | Noticeboard, holidays and calendar, school bell schedule (one hub sensor) |
| Mailbox | Unread count and recent headers; message content is optional |
| Parent approvals | Trips/activities waiting for your answer and open forms; read only |
| Student pictures | Each child's Mashov profile picture as an image entity; kept in memory only (never written to the cache or history, not exposed to AI tools), so it is fetched again after a restart |

The selection applies to all students in the hub. Mailbox and parent approvals belong to the account; holidays belong to the school. Availability depends on school permissions. File records are listed, not downloaded; this integration does not submit school forms or absence requests.

### Selecting and disabling data

Add categories from the list or remove their chips with **×**, then **Submit**. Selection changes reload the hub and attempt an immediate refresh. For a basic dashboard, select Homework, Behavior, Weekly plan, Timetable, Lesson history and Grades; add Holidays for the calendar.

Removing a category clears its active/disk cache **before login**, even if refresh fails, and disables its entities while retaining IDs and history. Disabling an entity manually in HA does not stop its category’s requests. An empty selection retains authentication and student discovery. [Action examples](docs/services.md#mashovset_options)

### Absence and lateness counters (optional)

Select **Absence and lateness counters (school year)** for one sensor per student. Its state is the total number of absence events, including justified and online absences. Attributes include `lateness`, justified/unjustified totals, and `items`: counts and original event names for each subject/teaching group. These are lesson events, not days absent. `lessons_count` is the portal's total lessons held.

The range is September 1 through August 31 of the selected school year, shown as `period_start`, `period_end` and `school_year`; the homework date window does not affect it. This option reads the portal's behavior counters, school event definitions and study-group labels, even if the separate Behavior and Study Groups options are off. It never submits a justification.

Schools use different event codes. Absences and lateness follow Mashov's standard categories. Custom events without a standard category are preserved as `unclassified_events`, with `classification_complete: false`; they are not guessed from their names or included in the absence/lateness totals. Compare those event rows with your school's definitions when using totals in an automation. Failed requests show a source status instead of a false zero; temporary failures retain the last successful counts and their original dates with `items_retained: true` and `data_stale: true`. Attribute limits may omit subject rows; the totals still include every fetched event.

### Mailbox (optional)

Select **Mailbox — headers and unread count** for one sensor per account/school hub. Headers do not mark conversations read. **Full message content is off by default.** When enabled, bodies are fetched only for conversations you have already read in Mashov. Unread conversations are never opened by the integration, so they stay unread until you open them in Mashov, and their bodies appear after that. The integration fetches plain-text bodies only; attachments are a separate opt-in (below). Removing Mailbox resets full-content consent; enabling it again starts with headers only.

The limit applies to recent inbox conversations (20 by default, 1–50). Sent mail, drafts, archives and older inbox pages are not fetched. Long bodies may be shortened in attributes; check `stored_conversations`, `fetched_conversations`, `body_truncated` and `content_status`. Failed counts are not displayed as zero. See [Privacy & Security](#-privacy--security) before enabling access.

#### Mail attachments (optional)

**Download mail attachments** is off by default. It requires Mailbox **and** full message content, because attachment IDs come from the conversation request, which is made only for conversations already read in Mashov. Turning off Mailbox or full content turns attachments off as well.

- Every file type is saved, once per attachment, under `<config>/mashov_files/<entry_id>/<conversation>/<message>/<fileId>-<name>` (the Home Assistant configuration folder, so backups include it). File names are sanitized; Hebrew names are kept.
- Each message lists `attachments` with `fileId`, `fileName`, `mime_type`, `size`, `status` and `download_url`; the sensor adds `attachment_count`. Files are not added to the Media browser and are not previewed there.
- `download_url` (`/api/mashov/attachment/...`) works only for signed-in Home Assistant users. It always sends the file as a download (`Content-Disposition: attachment`) with `X-Content-Type-Options: nosniff`, so a browser never displays it inline.
- Files above **Maximum attachment size** (25 MB by default, 1–100) are skipped with status `too_large`; no partial file is kept, and the file is not downloaded again until Home Assistant restarts. All of a hub's attachments together are limited to **500 MB**; a file that would exceed it gets `quota_exceeded`. Other statuses are `ok`, `http_<code>` and `error`. A failed file never fails the refresh; `http_<code>` and `error` are retried on the next one.
- SVG files can contain script, so they are stored as `<name>.svg.txt` with `neutralized: true` and are served only as plain text.
- Retention: after each successful inbox fetch, folders of conversations outside the fetched window are deleted. Turning the option off or deleting the hub deletes the hub's whole folder.

### Parent approvals (optional)

Select **Parent approvals — trips and forms (read only)**. Each child gets a **Pending approvals** sensor: the state is the number of trips and school activities still waiting for your answer. `pending` lists them by answer deadline (title, type, dates, deadline and a short plain-text description), and `next_deadline` is the earliest one. The hub gets one **Open forms and approvals** sensor: unanswered, unexpired consent questionnaires (`consent_forms`) and online forms (`general_forms`), plus open activities Mashov did not assign to any child of this account (`unassigned_activities`).

**The integration never answers approvals or forms for you.** It only reads Mashov's lists; approving, the yearly digital approval and submitting forms stay in the Mashov app. Answers are fetched only for activities that are still open or whose deadline passed in the last 7 days. Times are school-local (Israel). A failed source shows `unknown`, not 0. The form fields are not yet verified against a live account.

### 🧠 Entities (per child)

Each selected student category creates its corresponding sensor. Core sensors cover homework, behavior, weekly plan, timetable, lesson history and grades; additional sources follow the Data to fetch table. Find actual entity IDs under **Settings → Devices & services → Entities**; IDs are preserved on upgrade and internally scoped to each hub.

| Field | Meaning |
| --- | --- |
| State | Number of records; `unknown` for unavailable sources, `0` for a successful empty response |
| `items` | Cleaned records for cards and automations |
| `formatted_summary`, `formatted_by_date`, `formatted_by_subject` | Display helpers where supported |
| `total_items`, `stored_items` | Available records versus records included in size-limited attributes |
| `last_update`, `data_stale`, `source_status` | Actual successful update time, stale-data flag and source availability |
| `schedule_type`, `schedule_scope` | Effective refresh schedule and whether it is shared or student-specific |

Weekly-plan subjects/teachers are filled from timetable groups where available. Date-labelled plans keep different weeks separate. Class/name changes do not swap students’ data. [Picture examples of record cards](examples/lovelace/README.md#picture-examples)

#### School hub entities

With Holidays selected, each hub gets its own holiday sensor and calendar. Use the holiday entities from the student’s own school in cards and automations. The calendar exposes all-day holiday events; the sensor provides count, records and formatted summaries. Calendar support was contributed by [@aviadlevy](https://github.com/aviadlevy).

Mailbox is also a hub-level entity, with unread count and recent conversation attributes; it is not repeated per student.

## Homework checklists and AI bots

Each child has a native HA homework checklist with completion saved locally across
refreshes and restarts. Nothing is written back to Mashov.

An optional read-only MCP connection lets AI bots answer questions such as “What
homework does each child have?” or summarize grades, behavior and school notices.
Enable MCP separately for each hub, then select only its Mashov APIs in Home
Assistant's MCP Server settings. Connect a compatible client using Streamable HTTP
at `https://YOUR_HA_HOST/api/mcp` and sign in as an HA administrator through OAuth.
Bots without native MCP support need an MCP client adapter; Telegram/WhatsApp are
message channels and do not connect to MCP by themselves.
[Setup and bot examples](docs/homework-and-mcp.md).

## Guides and examples

| Guide | Contents |
| --- | --- |
| [Services](docs/services.md) | Refresh, option changes, schedule maps and dashboard creation examples |
| [Automation blueprints](docs/blueprints.md) | Homework/behavior announcement, bag reminder and new noticeboard notifications |
| [Mashov Live dashboard](docs/dashboard.md) | Setup, family visibility, student popups and desktop/mobile picture examples |
| [Homework checklists and MCP](docs/homework-and-mcp.md) | Per-child completion and read-only access to all selected school datasets |
| [Lovelace card examples](examples/lovelace/README.md) | Timetable, homework, behavior and refresh cards with pictures and entity placeholders |

## Troubleshooting

- **401 / authentication failures**: check credentials and school choice, and update credentials through **Configure**. New credentials are tried before they are saved, and the hub logs in with them right away instead of at its next scheduled refresh. Password-change responses display a link to the Mashov login page.
- **403 / school-disabled resources**: core resources such as weekly plan retry after 1 hour, then 6 hours, then 24 hours. Each student's resource has its own cooldown, which resets after success. Optional resources use a separate 24-hour cooldown. A school permission denial does not necessarily mean the password is wrong.
- **HTTP 5xx on a data type (possibly closed by the school)**: when every request for one data type returns a server error on three separate refreshes, at least an hour apart, the integration stops fetching that type and creates a **Mashov data type turned off** notice under **Settings → System → Repairs**. One successful or non-5xx result resets the count. A refresh only counts while Mashov answers another data type, in the same refresh or within the hour before, so an outage of the whole portal never switches anything off. A failed refresh never switches anything off. To fetch the type again, select it under **Configure → Data to fetch**. The count is kept in memory, so after a restart it starts again; with a daily schedule, three refreshes take about three days.
- **Startup connection failures**: HA retries transient setup failures when no cached data is available. When cached data exists, the integration retains it until a refresh succeeds.
- **Different host**: open **Options → API base** and paste the base prefix you see in your browser DevTools Network tab (up to `/api/`).
  Common defaults: `https://web.mashov.info/api/`, sometimes `https://mobileapi.mashov.info/api/`.
- **No schools in dropdown**: temporary catalog issue — the flow falls back to text; enter the name or Semel to resolve.
- **Autocomplete not working**: suggestions are limited to 50 schools; type the school name or Semel to search beyond those suggestions.
- **Multiple kids missing**: ensure your account actually lists multiple students in Mashov. Check HA logs for `custom_components.mashov` debug entries.
- **Session errors**: if you see "Unclosed client session" errors, restart Home Assistant to clear any stale connections.
- **Mailbox reload race**: a closed session during mailbox fetching is treated as an operational fetch failure. Other unexpected runtime errors remain reportable.
- **"New Device" emails**: session persistence reduces unnecessary logins but cannot prevent fresh authentication after a server-side session expiry. Authentication is saved after successful refreshes in `.storage/mashov.<entry_id>.cache`. Avoid unnecessary reloads and never share this file; it contains authentication data.

### Enable debug logs
```yaml
logger:
  logs:
    custom_components.mashov: debug
```

## 🔐 Privacy & Security

Credentials are stored by Home Assistant; saved sessions and school data also live in `.storage/mashov.<entry_id>.cache`. Never share that file. Review logs and diagnostics before sharing, and remove credentials, student details, grades, messages, cookies and tokens.

**Every Home Assistant user, including a non-admin child account, can read mailbox sensor attributes.** Dashboard visibility hides cards only; it does not restrict entity access. Enable Mailbox only if that access is acceptable.

**Downloaded mail attachments are stored in `<config>/mashov_files`.** Any signed-in Home Assistant user, including a non-admin child account, can download them through `download_url`, and they are included in backups of the configuration folder. Enable attachments only if that is acceptable.

Mailbox `items` is excluded from new Recorder history automatically. Previously recorded content remains. The integration keeps the latest snapshot without age-based expiry; failed requests can leave it visible as stale. Turning off full content removes cached bodies; removing Mailbox removes headers and resets consent. Deleting a hub removes its integration cache and saved session, not existing Recorder history or backups.

To exclude the whole mailbox sensor from future history, merge this into your existing `recorder` configuration and restart Home Assistant:

```yaml
recorder:
  exclude:
    entities:
      - sensor.REPLACE_WITH_YOUR_MAILBOX_ENTITY_ID
```

This does not restrict live access or remove old history, cache or backups. Internal-error report links open a form for your review; nothing is posted automatically. Diagnostics omit mailbox content and account credentials.

## 📄 License

[MIT © 2025](LICENSE) · [Project notice](NOTICE.md)
