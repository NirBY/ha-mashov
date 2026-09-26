# Mashov v1.0.11

Restrict bug-report links to internal errors and add optional sanitized technical logs.

## Fixed
- Remove bug-report links from password-change requests, authentication failures, school permissions, timeouts, network errors, HTTP/server failures and invalid API responses.
- Offer reporting for detected internal programming exceptions, including when HA wraps the original exception during startup. Classification does not establish the root cause; the user still reviews and submits the report.
- Preserve programming exceptions from the core API request path instead of disguising them as network failures.
- Notify once on the first internal failure, even when cached data exists; reset suppression after recovery. Operational-error thresholds and cache behavior remain unchanged.

## Added
- Two choices in internal-error notifications: report without logs, or pre-fill the latest sanitized technical event.
- Technical logs include timestamps, standard exception types and integration source filenames/line numbers. Exception text, absolute paths, locals, credentials and student records are excluded.
- Downloadable HA diagnostics includes up to 20 technical events per hub from the current HA session. Removing the hub deletes this history; restarting HA clears it.
- Optional log-file attachment field in the GitHub issue form, with instructions for attaching diagnostics or manually reviewed/redacted HA logs. No automatic GitHub submission or raw-log upload.
- Compact report URLs fit within the existing Telegram/GreenAPI notification forwarding limit.

## Upgrade and validation
- Update through HACS and restart HA. Existing entity IDs, settings, data attributes and notification recipients are preserved.
- README and issue-report instructions updated.
- Regression coverage checks operational-versus-internal classification, wrapped startup errors, notification suppression/recovery, log privacy, per-hub isolation, bounded history and report-link size. Existing regression tests, Ruff, hassfest and HACS validation also run before release.
