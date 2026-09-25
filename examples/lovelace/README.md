# Timetable and holiday cards

The timetable is the recurring school week. Holiday information comes from a separate
sensor for each school; the card overlays inclusive holiday date ranges on the timetable.
An empty weekly plan does not mean there are no holidays.

In both `entities` and the JavaScript `holId` / `HL` variable, replace
`sensor.<school_holidays_entity>` with the holiday sensor belonging to the student's hub:

| School | Holiday sensor | Holiday calendar |
| --- | --- | --- |
| אחד העם | `sensor.mashov_holidays_2` | `calendar.mashov_holidays_calendar_2` |
| נעמי שמר | `sensor.mashov_holidays_mashov_holidays` | `calendar.mashov_holidays_mashov_holidays_calendar` |

These IDs are installation-specific examples. Check **Developer Tools → States** for
your installation. Replace `<studentID>` in timetable and weekly-plan entities too.
Entity IDs are preserved during upgrades; HACS does not rewrite existing dashboards.

For example, the Ahad Haam advanced card dependencies are:

```yaml
entities:
  - sensor.mashov_<studentID>_timetable
  - sensor.mashov_<studentID>_weekly_plan
  - sensor.mashov_holidays_2
```

Set `holId='sensor.mashov_holidays_2'` in that card's content. For Naomi Shemer,
use `sensor.mashov_holidays_mashov_holidays` in both places.

The dynamic card uses `HL` instead of `holId`. Both templates require
`config-template-card` and `html-card`. Existing redacted screenshots remain valid.

Synthetic holiday fixture (no account or student information):

```json
{"Items": [{"name": "סוכות", "start": "2026-09-25", "end": "2026-10-03"}]}
```

The sensor end date is inclusive; an all-day calendar event's end is exclusive
(`2026-10-04` in this example). The card highlights the holiday while retaining the
regular lesson template. It does not assert that those lessons actually take place.

Optional portal sensors expose `source_status`, `total_items`, `stored_items`, and
`items`. For example, a permitted empty resource returns `source_status: ok`, state `0`;
a school restriction returns `source_status: forbidden`, state `unavailable`.
Local portal HTML captures belong in ignored `dataExample/html/`, never in Git.
