# v1.6.0 — Readable child views and homework checklists

Readable child dashboards, homework checklists and weekly school hours.

- Child/photo and counter buttons open readable messages, grades, behavior and homework.
- Homework shows the last three distinct homework dates by default, with older dates available. Checked tasks stay in place with a strike-through and can be reopened. Completion is stored locally in Home Assistant.
- Days without lessons and school holidays are hidden. Friday is retained when that child has classes.
- Weekly subjects and each child's start/end times use the school's published timetable and bells. Missing times, partial data and week-specific boundary lessons are labeled.
- Attendance breakdowns, subjects/teachers, lesson counters and profile pictures appear when selected.
- The updated Mashov Live blueprint builds the new view and accepts 1–14 recent homework dates. Requires Bubble Card 3.4+; card-mod is optional for native Markdown accents.
- English and Hebrew README GIFs open with the product overview as their default preview, followed by actual interactive cards with entirely fictional demo data.

**Existing 1.6.0 updated in place:** the version number is unchanged. If you already installed 1.6.0, use HACS Redownload or replace the integration with the updated `mashov.zip`.

After updating, restart Home Assistant and refresh the browser after startup. Re-import and run the blueprint to adopt the new layout; ordinary updates preserve saved dashboards. Keep the same persistent `/config` volume and include Mashov's completion storage in backups.

**Known limitation:** cancellations appearing only in Mashov messages or Shahaf/iScool are not applied automatically. Hours recalculate when the published Mashov timetable changes. No Shahaf connector is included.

Validation: 620 Python tests passed (1 skipped), 16 frontend tests passed, Ruff lint and formatting passed. All three local room dashboards were checked with their existing controls and viewer conditions preserved.

Issue #17 (follow-up note attachments) remains open pending verification of the attachment schema and route.
