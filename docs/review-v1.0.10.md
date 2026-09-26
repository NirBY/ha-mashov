# Live-installation review: v1.0.10

The report was checked against v1.0.9. The following decisions preserve existing
accounts, entity IDs and automation inputs while correcting misleading states.

| # | Finding | Resolution |
|---|---|---|
| 1 | Repeated student/device names | Short translated entity names and `has_entity_name`; registered IDs and custom names retained. |
| 2 | Departed students leave restored entities | Remove only this hub's recognized student sensor registrations after a real login and successful refresh with a nonempty roster. Never use cached/failed/empty rosters to delete. New students are added dynamically. History is not purged. |
| 3 | Forbidden core resource looks like zero | Per-resource `source_status`; failed source state is `unknown`, successful empty source remains `0`. Cooldowns retain the failure status. |
| 4 | Cache exists but entities become unavailable | Cached values remain available after failed startup/refresh; `data_stale` and actual `last_update` identify old data. |
| 5 | Incomplete service validation | Accept optional resources, item limits, automatic year and seconds in refresh times. Ignore unknown legacy keys; validate supported values before saving. |
| 6 | Duplicate legacy hub unique ID | Password updates retain an existing legacy ID if another hub owns the canonical account ID. Changing username to an existing account is rejected in the form. |
| 7 | Empty auth becomes a restore attempt | Restore requires cookies or a CSRF token; year metadata alone is insufficient. |
| 8 | Ambiguous legacy set_options target | Preserve first-loaded-hub behavior for compatibility; warn with multiple hubs and document explicit `entry_id`. |
| 9 | Legacy year remains pinned | Add **Automatic school year** to Configure and the service. Existing explicit years remain pinned until the user opts in; new automatic entries still roll over on September 1. |
| 10 | Downgrade cannot reverse unique IDs | Keep forward migration; document restoring a matching HA backup when downgrading before v1.0.9. Do not silently rename existing entities again. |
| 11 | Holidays failure discards student refresh | Isolate holiday errors, retry 401 once, preserve prior holidays where available, expose holiday status and keep fresh student data. |
| 12 | Holiday entities per hub | Retained deliberately: deleting or sharing existing entities would break dashboards and hub ownership. The API currently uses a common holiday endpoint; identical data does not make existing entity references interchangeable. |
| 13 | Optional forbidden/unsupported resources lack explanation | Log a warning on actual 403/404 requests (24-hour cooldown), expose attributes in HA by using `unknown` instead of `unavailable`, retain allowlisted diagnostics. |
| 14 | Missing plan HTML/date parsing | The recurring timetable already rendered a grid. Dated plans now render a separate date-labelled table, preserving multiple weeks; safe date parsing and escaped HTML prevent malformed cells. |
| 15 | Class/name changes remain stale | Read the latest student name by stable ID and update device registry names on coordinator changes; user overrides remain intact. |
| 16 | Cache survives hub deletion | `async_remove_entry` deletes the hub cache and issue notification. Normal unload/reload retains cache. |
| 17 | Transient-error notification noise | With cached data, notify on the third consecutive failed refresh, once per outage. Authentication/no-cache failures remain immediate. Successful refresh resets the counter and clears the issue. |

## Language support

Arabic (`ar`), Russian (`ru`) and Ukrainian (`uk`) join English and Hebrew for
setup/options, entity names, weekday/schedule selectors and service labels.
Home Assistant entity-state tests verify the new translated names. School text,
legacy Hebrew formatted summaries and existing cards/speech blueprints are not
machine-translated. Raw attribute keys and item structures remain unchanged.

## Repository cleanup

Removed the accidental `tatus` Git-output capture, `mashov_brands_files.zip` working
archive, duplicated `custom_components/icon.png`, and unused placeholder
`custom_components/mashov/coordinator.py`. The real icon and coordinator implementation
remain in the integration. Ignore rules prevent these scratch outputs, temporary
scripts and local HA access/diagnostic files from being recommitted. Git history is
not rewritten.
