# Mashov v1.1.0 — Student refresh schedules

Per-data schedules are optional. Setup and Configure show every category and its effective schedule. Expand Refresh schedules, choose a student and category, then use the native form’s Submit to save all edits. Daily, weekly and interval overrides fetch only the due categories; unmodified categories keep the shared schedule and previously fetched values/timestamps.

Settings are grouped into expandable Data, Refresh schedules, Account and Advanced sections. Current schedules and ⓘ instructions start collapsed to keep the screen compact. Expand the summary when needed; validation automatically opens a section containing an error.

The interactive Refresh schedules editor includes General (shared defaults) and all data types. Choosing a type immediately changes its controls, and one Submit saves all draft changes together. The editor is embedded directly in Setup and Configure → Refresh schedules. The native form’s Submit saves every edited student and category together. Admin access is required; credentials and school-data contents are never returned to this editor.

Existing selections, schedules and entity IDs are preserved. Schedule-only changes reschedule without re-authentication. Manual refresh and initial warm-up fetch all enabled data. Mailbox content is excluded from future Recorder history, but remains visible in live sensor attributes and the integration cache.

Update through HACS and restart Home Assistant. Back up the existing integration folder before a manual installation.

Discard draft now reloads current server settings after a conflict, so editing can continue without a full page reload. Hub shutdown waits only for its own active request; timer rebuilds safely skip removed or replaced hubs. Account values are omitted from schema debug logs and panel_custom is declared in the manifest.

## New schedule screens (English)

Refresh schedules embedded in the native Configure form. Shared scope is selected to keep personal names out of the screenshot:

![Refresh schedules inside the native form](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/inline-schedules-en.jpg)

The same controls embedded in native hub registration, before entering account credentials:

![Refresh schedules inside hub registration](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/inline-registration-en.jpg)

Choose **Student** to edit their General and individual data schedules. All students in the selected account save together with one Submit. Existing schedules remain inherited until changed. Holidays and Mailbox use the explicitly labeled shared scope. During registration, students become available after authentication loads their roster.

Student schedule editor with fictitious students:

![Student schedules using demo data](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/student-schedules-demo-en.jpg)


Hub registration uses the same General/per-data editor. One Submit creates the hub with account details, selected data and all schedules. Both screens follow Home Assistant's language, sharing native labels in English, Hebrew, Arabic, Russian and Ukrainian. Switching language preserves the draft; Hebrew and Arabic use RTL layout.

Registration preview with empty account fields and demo data:

![Interactive hub registration in English](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/hub-registration-demo-en.jpg)

Interactive editor preview using demo data (not a live-account screenshot):

![Interactive schedule editor with demo data](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/interactive-schedules-demo-en.jpg)

Actual Home Assistant screens, cropped to exclude account, school and student details. The examples below were opened as an unsaved draft; existing schedules were preserved.

Compact settings with collapsible sections:

![Compact settings sections](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/settings-sections-en.jpg)

The overview keeps the schedule table and ⓘ instructions collapsed until opened:

![Compact schedule overview](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/data-schedules-overview-en.jpg)

Choose a schedule mode for one data type:

![Schedule mode selection](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/data-schedule-mode-en.jpg)

Weekly mode shows only the refresh time, weekdays and navigation action:

![Weekly schedule settings](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/data-schedule-weekly-en.jpg)

## Previous stable release: v1.0.17

Disabling data now removes it from the integration's disk cache before authentication,
even if the subsequent refresh fails. Turning off full message content removes cached
bodies; reducing the inbox limit also removes excess cached conversations. Recorder
history and backups remain governed by their own retention settings.

Removing Mailbox in Configure automatically resets a previously checked full-content
option. Re-enabling it starts with headers only. Validation errors preserve the submitted
data selection, and the Holidays category is clearly named in all five languages.

The README now starts with all 18 datasets and their new-installation/upgrade defaults,
a red warning about full-content fetching marking conversations read, actual Home Assistant
screenshots, and exact instructions for selecting and disabling data.

## Upgrade

Update through HACS and restart Home Assistant. Existing selections, entity IDs and user
customizations are preserved, including configurations from v1.0.7 onward. New hubs start
with no datasets selected. Mailbox and full content remain opt-in.
