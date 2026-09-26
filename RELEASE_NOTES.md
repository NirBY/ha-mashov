# Mashov v1.0.9

Reliability fixes and compatibility improvements for existing installations.

## Fixed
- Remove blocking version-file reads during setup by using Home Assistant's loaded integration metadata (issue #8).
- Back off core endpoints returning a school-disabled HTTP 403 for 1 hour, then 6 hours, then 24 hours. Cooldowns are isolated per student/resource, reset on success, and do not suppress password-change errors (issue #8).
- Retry transient startup failures automatically; retain cached data when available. Close validation sessions on failed authentication and preserve a loaded entry if platform unloading fails.
- Keep the selected school during account setup, prevent duplicate accounts including legacy entries, and apply credential/options changes with a single reload.
- Scope core sensor unique IDs to each hub to prevent collisions when both parents see the same student. Migrate registered entities in place, preserving entity IDs and their history references.
- Follow students by stable ID after a class/slug change. Automatically log in for the new school year when the year is not explicitly pinned; reject known previous-year cached sessions and clear old cooldowns.
- Resolve weekly-plan subject/teacher labels from timetable groups and include plan text in grouped views. Avoid rendering an empty grid for dated plans.
- Parse holiday timestamps with timezone offsets and use Home Assistant's timezone for displayed update/schedule times.
- Target set_options explicitly with entry_id, validate service inputs, and correctly apply the legacy schedule_day field after migration to schedule_days.

## Upgrade compatibility
- Existing accounts, options, caches, entity IDs, dashboards, and automations are retained; no remove/re-add or manual migration is required.
- Calls to refresh_now without entry_id still refresh all hubs. Legacy set_options calls without entry_id continue to target the first loaded hub; specify entry_id to select another hub.
- Existing attribute keys and item structures are retained. Weekly-plan subject/teacher fields are additive, display text is improved, and timestamps now include the configured timezone offset.
- An explicitly configured school year remains pinned. The minimum Home Assistant version remains 2025.3.
- Restart Home Assistant after installation. Entity-registry unique IDs are migrated forward; rolling back does not automatically reverse that migration.

## Validation
- Regression coverage includes 403 backoff/recovery/isolation, password-change handling, setup retries/cache fallback, account flows, school-year rollover, holiday parsing, complete attribute budgets, and upgrade/reload entity-ID preservation.
- Release checks include Ruff, the full test suite, and GitHub CI on Python 3.13 and 3.14.
