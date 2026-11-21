# v1.4.0 — School bells, pictures, lesson counts and groups

Four new read-only sources are available under **Configure → Data to fetch**. They are off by default for new and existing hubs:

- **School bells:** one hub sensor with the ordered lesson/start/end schedule (#18).
- **Student pictures:** an image entity per student; raster images are bounded and kept only in memory, never in the disk cache, Recorder or AI text output (#19).
- **Lesson counts:** lessons held and weekly hours per group (#20). The verified `lessonsCount` endpoint does not provide absence or lateness totals.
- **Study groups:** subjects, groups and teachers per student (#21).

This release also fixes hub registration from the schedules page, duplicated school numbers in new hub titles, failed-setup cleanup, malformed holiday dates, truncated picture downloads and stale retained approval/bell values. The schedule editor loads without blocking Home Assistant's event loop.

Expired sessions start a fresh cookie jar, concurrent rejected logins share one failure, and credentials are checked before saving. Daily/weekly refreshes that raise a transient error retry after delays of 5, 15 and 60 minutes; rejected credentials are not retried. Startup catches missed scheduled runs using each dataset's last completed refresh. A portal outage no longer automatically disables a source refreshed on its own.

Follow-up note attachment downloads (#17) are not included: the attachment schema and route still need a verified sample.

## Upgrade

Update through HACS or install `mashov.zip`, then restart Home Assistant. Enable any of the four new sources explicitly. Existing selections, schedules and entity IDs are preserved. Pictures are fetched again after a restart because they are memory-only.

## Validation

The Windows/Python 3.13 suite passed with **586 passed, 1 skipped**, **87% coverage**. Ruff lint and formatting checks passed. Linux/Python 3.13 and 3.14, hassfest and HACS checks run on the release pull request.
