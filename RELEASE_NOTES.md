# Mashov v1.3.0

Thanks to [@ziv-daniel](https://github.com/ziv-daniel) for parent approvals (#23), mailbox attachments (#24) and the API reference (#25).

- Read-only parent approvals: a pending-approvals sensor per child, and one hub sensor for open forms and unassigned activities. Nothing is submitted. Approval text is kept out of Recorder history.
- Optional mail attachments, saved under `<config>/mashov_files` and downloaded only by signed-in Home Assistant users. Unread conversations are not opened. SVG files are stored as plain text. One file is limited to 25 MB and one hub to 500 MB.
- A data type is turned off, with a translated Repairs notice, only after HTTP 5xx on three separate refreshes while another source still succeeds. A portal-wide outage does not turn everything off.
- Sanitized parent-portal API reference in `docs/mashov-api-reference.md`.
