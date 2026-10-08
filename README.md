[**English**](README.md) · [**עברית**](README.he.md)

# Mashov — Home Assistant integration (HACS)

Unofficial integration for **משו״ב (Mashov)**. Choose which school data to bring into Home Assistant for each account and school hub.

Community project; not affiliated with Mashov. [Release notes](RELEASE_NOTES.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## 📦 Installation

Requires **Home Assistant 2025.3 or newer**.

**HACS:** open **HACS → Integrations → ⋯ → Custom repositories**, add `https://github.com/NirBY/ha-mashov` as an **Integration**, install Mashov and restart Home Assistant.

**Manual:** copy `custom_components/mashov` to `/config/custom_components/mashov`, then restart Home Assistant.

For updates, install through HACS and restart. Existing data selections, schedules, entity IDs and customizations are preserved; no new data source is enabled automatically.

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

- All **18 data types** are selectable; only enabled categories are fetched. Multiple hubs and students are supported without mixing their records.
- **Student-specific General and per-data schedules:** daily, weekly or interval, edited inside Setup/Configure. One Submit saves all drafts.
- **One refresh queue** across hubs, including scheduled, manual and startup requests. Selective refreshes preserve other students’ values and timestamps.
- **Sensors and holiday calendars**, with structured records, formatted summaries, actual update times, source status and stale-data indicators.
- **Opt-in account mailbox:** unread count and recent headers, with separately consented plain-text content. No attachment downloads.
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
| Items in sensor attributes | 100; range 10–500, further reduced to fit the attribute-size budget |
| API base | `https://web.mashov.info/api/` |
| Automatic school year | Enabled unless the account has a pinned year |

### Refresh schedules

Select **Student**, then **General — default schedule** or a data type. Uncheck inheritance to customize it. Daily shows a time; Weekly shows time and weekdays; Interval shows minutes (5–1440). Switching students/types keeps the draft; the main **Submit** saves all edits together. Cancelling leaves saved settings unchanged.

During registration, set initial defaults first; students become selectable once authentication loads the roster. Student schedules use stable IDs. New students inherit account defaults, and Holidays/Mailbox retain school/account scope. Select **Shared account / school data and defaults** for those resources.

**Current schedules** shows all categories and their effective schedules. Disabled categories are never fetched. Identical schedules are batched, and every refresh waits for active work to finish. Unload waits only for that hub’s active request and skips its queued work. Manual refresh updates all selected data. Night-time fetching may cause Mashov login/activity emails; choose daytime schedules if this is undesirable.

[Current inline-form pictures](docs/configuration.md) · [Schedule actions and YAML examples](docs/services.md#mashovset_options)

<a id="data-to-fetch-1"></a>

### Data to fetch

Available in **v1.1.0**. New hubs start with nothing selected; upgrades keep existing selections.

| Group | Data types |
| --- | --- |
| Lessons | Homework, weekly plan, timetable, lesson history |
| Grades | Grades, term grades, report cards |
| Behavior | Behavior, daily behavior, outside lesson behavior, follow-up notes |
| Student records | Study materials, student files, absence justification requests, individual lessons |
| School | Noticeboard, holidays and calendar |
| Mailbox | Unread count and recent headers; message content is optional |

The selection applies to all students in the hub. Mailbox belongs to the account; holidays belong to the school. Availability depends on school permissions. File records are listed, not downloaded; this integration does not submit school forms or absence requests.

### Selecting and disabling data

Add categories from the list or remove their chips with **×**, then **Submit**. Selection changes reload the hub and attempt an immediate refresh. For a basic dashboard, select Homework, Behavior, Weekly plan, Timetable, Lesson history and Grades; add Holidays for the calendar.

Removing a category clears its active/disk cache **before login**, even if refresh fails, and disables its entities while retaining IDs and history. Disabling an entity manually in HA does not stop its category’s requests. An empty selection retains authentication and student discovery. [Action examples](docs/services.md#mashovset_options)

### Mailbox (optional)

Select **Mailbox — headers and unread count** for one sensor per account/school hub. Headers do not mark conversations read. **Full message content is off by default; enabling it marks fetched conversations read in Mashov**, even if you never open them. It fetches plain-text bodies only, with no images or attachments. Removing Mailbox resets full-content consent; enabling it again starts with headers only.

The limit applies to recent inbox conversations (20 by default, 1–50). Sent mail, drafts, archives and older inbox pages are not fetched. Long bodies may be shortened in attributes; check `stored_conversations`, `fetched_conversations`, `body_truncated` and `content_status`. Failed counts are not displayed as zero. See [Privacy & Security](#-privacy--security) before enabling access.

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

## Guides and examples

| Guide | Contents |
| --- | --- |
| [Services](docs/services.md) | Refresh, option changes, schedule maps and dashboard creation examples |
| [Automation blueprints](docs/blueprints.md) | Homework/behavior announcement, bag reminder and new noticeboard notifications |
| [Mashov Live dashboard](docs/dashboard.md) | Setup, family visibility, student popups and desktop/mobile picture examples |
| [Lovelace card examples](examples/lovelace/README.md) | Timetable, homework, behavior and refresh cards with pictures and entity placeholders |

## Troubleshooting

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

### Enable debug logs
```yaml
logger:
  logs:
    custom_components.mashov: debug
```

## 🔐 Privacy & Security

Credentials are stored by Home Assistant; saved sessions and school data also live in `.storage/mashov.<entry_id>.cache`. Never share that file. Review logs and diagnostics before sharing, and remove credentials, student details, grades, messages, cookies and tokens.

**Every Home Assistant user, including a non-admin child account, can read mailbox sensor attributes.** Dashboard visibility hides cards only; it does not restrict entity access. Enable Mailbox only if that access is acceptable.

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
