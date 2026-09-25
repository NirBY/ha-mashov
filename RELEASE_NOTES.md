# Mashov v1.0.7

This release adds nine opt-in, read-only portal resources, privacy-safe GitHub bug
report links in HA issue notifications, and safer diagnostics and refresh handling.

- Choose additional resources per school in **Mashov → Configure**. Unavailable school
  features remain unavailable rather than appearing as zero items; 403/404 responses
  back off for 24 hours. File metadata is read without downloading attachments or
  submitting forms.
- Error notifications open a prefilled GitHub form with an allowlisted technical event
  summary and versions. Review and submit it yourself. No GitHub token is stored in HA,
  and full HA logs are not automatically published.
- Diagnostics export counts, known resource statuses and versions only. Login headers,
  tokens, response bodies and usernames are no longer deliberately dumped to logs.
  Old log files and manually attached logs still require review.
- Reauthentication retries are bounded. Core server/network errors and holiday-fetch
  errors fail the refresh instead of replacing cached data with successful empty lists.
- Coordinator config entries, async scheduled callbacks, local weekdays, option changes
  and cache persistence follow current HA behavior. Daily/weekly schedules disable
  coordinator polling instead of leaving a hidden 24-hour poll enabled.
- Updated timetable examples explain per-school holiday entities and inclusive dates.
  Existing dashboards need their holiday entity references updated in both places.
- Minimum HA version is 2025.3. CI tests Python 3.13 and 3.14. Existing entity IDs remain
  unchanged. Restart Home Assistant after installing the release.
- Historical test fixtures use synthetic usernames. When updating an existing clone
  after the privacy rewrite, start a fresh clone; do not merge old history back in.

See [timetable examples](examples/lovelace/README.md) and [CHANGELOG](CHANGELOG.md).
