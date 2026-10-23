# Mashov v1.1.1 — Next school day, per child

Choose **Show the next school day for this child** in the live dashboard blueprint, or **Use the next school day for this child** in each child's bag reminder. Both options are **off by default**; existing installations keep tomorrow mode.

When enabled, the card, pop-up and bag reminder skip Saturdays, weekdays without timetable lessons, and the full school-reported vacation ranges. Adjacent holidays are handled together. Holiday eves remain school days when outside the school's vacation ranges. The displayed target includes its weekday and date; spoken bag reminders explicitly say which coming day the bag is for.

## Fixes and compatibility

- Timetable pop-ups render proper table rows; pipes and newlines in timetable and homework cells cannot break the table. Empty timetables show a message.
- Holiday checks work correctly in daily and bag announcements. Existing Google Translate automations continue to work without selecting a new TTS engine.
- Re-enabling previously purged data forces a refresh even after a failed reload. Existing data selections, schedules and entity IDs are preserved.
- Teacher names support both timetable layouts. Updated linked documentation and guides are included.

## Credit

Thank you to **[Aviad Levy (@aviadlevy)](https://github.com/aviadlevy)** for **[PR #15](https://github.com/NirBY/ha-mashov/pull/15)**: the original Friday-to-Sunday dashboard improvement and the timetable/table-cell fixes. This release incorporates those fixes and extends the school-day behavior to an optional setting per child, including multi-day school vacations.

## Upgrade

Update through HACS and restart Home Assistant. Re-import the updated blueprints, then enable the new option separately for each desired child. Run the dashboard script again to regenerate an existing dashboard. Existing automations keep their current inputs and tomorrow behavior; daily homework/behavior summaries continue to report today, and noticeboard notifications continue to report new notices. Check that holiday sensor inputs refer to the current school's holiday entity if an old sensor has been renamed.
