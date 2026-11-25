# v1.7.1 — Notification refresh and weekly card fixes

- **Refresh on new notifications:** if a refresh started by a new notification fails, it is retried after the next check, also after a restart, instead of waiting for the next scheduled refresh. A restart no longer skips an overdue full refresh after several notification refreshes.
- **Weekly card and lesson cancellations:** when a cancelled lesson leaves only a lesson that runs in some weeks at the start or end of a day, that start or end time is left open instead of guessed.

Refresh on new notifications stays off by default in this fix release; it will be on by default from 1.8.0.
