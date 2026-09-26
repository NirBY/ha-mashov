# Mashov v1.0.14

Changes since v1.0.13, reviewed against the implementation.

## Added: Mashov Live dashboard
- New admin-only `mashov.create_live_dashboard` action, with an optional response reporting the dashboard path, student count and Bubble Card detection.
- New script blueprint at `blueprints/script/mashov/mashov_live_dashboard.yaml`. It discovers students across all loaded hubs using registry IDs, including renamed entities. The four blueprint customization slots do not limit the number of discovered children; direct service calls accept more customizations.
- Hebrew/RTL dashboard with greeting, holiday countdown, refresh button, student photos, tomorrow's timetable summary, homework/behavior/grades/notice indicators and per-student popups with school calendars.
- Optional person/family/viewer selection, labels, emoji, accent colors and sensor overrides. Card visibility uses HA users linked to persons; it is a presentation filter, not entity access control.
- Requires Bubble Card 3.4+ and an existing UI-managed dashboard. The service writes the dashboard configuration; it does not create the dashboard container or install Bubble Card. New students appear after running the service again.
- Empty or previously Mashov-generated dashboards can be regenerated. Other content and built-in dashboards require explicit `overwrite: true`. Regenerating a Mashov-generated dashboard replaces its configuration, including later manual edits.

## Integration fixes
- Turning off Automatic school year now saves the selected/current year for hubs that never stored one, preventing an unintended rollover on the next school year.
- Authentication and password-change errors from holiday fetching propagate to the existing recovery notifications instead of being reduced to a generic holiday-fetch failure.
- A closed HTTP session is treated as an operational request failure; other RuntimeErrors still remain internal errors eligible for a reviewed bug report.
- Optional-resource sensor registrations are removed when their resources are deselected, after a successful fresh-roster refresh. Cached, stale or failed refreshes do not trigger this cleanup.
- Core and holiday `last_update` timestamps now use HA's configured timezone with a UTC offset and second precision. Optional-resource sensors also expose `last_update`.

## Fixes made during release review
- Scope student popup links to both hub and student, preventing collisions when two hubs include the same student ID.
- Reject a requested family visibility selection when none of its persons resolves to a HA user, instead of saving unrestricted manual cards.
- Add regression coverage for both cases, existing-dashboard preservation and school-year persistence across rollover.
- Declare Lovelace as an optional startup-order dependency, as required by hassfest for the new dashboard service.

## Examples, translations and maintenance
- Homework/behavior cards consume structured `items`, retain a legacy fallback, escape HTML and handle hyphens in subject names.
- Correct Lovelace install paths and UI-dashboard instructions, refresh-button `perform-action` syntax and weekly-plan examples.
- Add new-service translations in English, Hebrew, Arabic, Russian and Ukrainian, plus desktop/mobile dashboard illustrations.
- Release helper synchronizes `reporting.py` with VERSION/manifest and uses UTF-8 on Windows.
- Expand code/test documentation; comments alone do not change runtime behavior.

## Upgrade and compatibility
Update through HACS and restart HA. Existing entity IDs, settings, holiday school names and notification destinations are preserved. Dashboard creation is opt-in; installing this version does not overwrite dashboards. Templates that compare `last_update` as a raw UTC string should parse it as a timezone-aware timestamp instead.

Validation: full regression suite, Ruff, CI on Python 3.13/3.14, hassfest and HACS checks before release. Existing dashboard screenshots are examples; card visibility is not a security boundary.
