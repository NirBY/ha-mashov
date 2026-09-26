# Mashov v1.0.10

Arabic, Russian and Ukrainian UI support, fixes from the live-installation review,
and cleanup of accidentally tracked working files.

## Added
- Arabic (`ar`), Russian (`ru`) and Ukrainian (`uk`) translations for setup/options, entity names, weekdays, schedule selectors and service labels, alongside English and Hebrew.
- An **Automatic school year** option for legacy hubs with a pinned year. Enable it explicitly to switch to September 1 rollover.
- Core-resource and holiday status diagnostics, plus visible `data_stale` and actual last successful refresh timestamps.

## Fixed
- Remove repeated student/device names without renaming existing entity IDs or user-defined names; update device/student names after class changes.
- Keep cached sensor/calendar data visible after startup and periodic refresh failures. Mark it stale instead of claiming a new successful refresh.
- Isolate holiday fetch failures from student data; retry holiday authentication once and retain previous holidays when available.
- Expose failed/blocked core and optional resources as `unknown` with `source_status`, rather than misleading zero counts or hidden error attributes. Optional 403/404 responses now log a warning while retaining the 24-hour cooldown.
- Remove departed-student sensor registrations only after a real login and successful refresh with a nonempty roster; never delete from cached, empty or failed rosters. Add newly returned students dynamically.
- Accept `HH:MM:SS`, optional-resource selections and item limits in `mashov.set_options`; ignore obsolete unknown fields while validating known settings.
- Avoid unique-ID collisions when changing a password on duplicate legacy hubs; reject username changes that would duplicate an account.
- Do not restore empty auth caches or year-only session metadata. Delete the hub's cache and issue notification when the hub is removed.
- Render dated weekly plans as date-labelled HTML tables, preserving multiple weeks; use safe date parsing and escape table content.
- Reduce transient-network alert noise: with cached data, create one persistent notification on the third consecutive failed refresh. Authentication/no-cache errors remain immediate; recovery resets the counter.

## Compatibility and upgrade
- Upgrade in HACS and restart Home Assistant. Existing accounts, active entity IDs, raw item schemas, selected options and dashboard references are retained.
- Failed resource states intentionally change to `unknown`; successful empty results remain `0`. Automations that test only for `unavailable` should also check `unknown` or `source_status`.
- Existing explicitly configured years remain pinned until **Automatic school year** is enabled. Per-hub holiday entities remain separate to preserve dashboard references and independent hub removal.
- Legacy `set_options` calls without `entry_id` still target the first loaded hub and now warn when ambiguous. `refresh_now` without `entry_id` still refreshes every hub.
- Portal content and existing Hebrew formatted summaries/cards/speech blueprints are unchanged; the new UI translations do not translate school-provided text.
- Recorder history is not purged when an obsolete registry entry is removed. Rollback before the v1.0.9 unique-ID migration requires a matching HA backup.
- Minimum Home Assistant version remains 2025.3.

## Repository cleanup
- Removed accidental Git output (`tatus`), the working brands ZIP, a duplicate icon outside the integration, and the unused coordinator placeholder.
- Expanded `.gitignore` for scratch scripts, packaging artifacts and local HA access/diagnostic files. Kept the actual integration icon and coordinator implementation.

## Validation
- 110 Home Assistant regression tests, Ruff lint/format, and GitHub CI (Python 3.13/3.14, hassfest and HACS).
- Real HA test entities cover translated names, visible blocked-source attributes, cache fallback, name updates, conservative orphan cleanup and upgrade/reload ID preservation.
- [All 17 review findings and decisions](https://github.com/NirBY/ha-mashov/blob/v1.0.10/docs/review-v1.0.10.md).
