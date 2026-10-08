## Mashov v1.1.0



Set refresh schedules for each student and each data type directly inside Home Assistant’s **Setup** and **Configure** forms. Select **Student**, then **General** or a data type; daily, weekly and interval controls update immediately. One **Submit** saves all edits. Existing accounts inherit their current schedules until customized. Students become selectable after registration loads the roster; Mailbox remains account-wide and Holidays school-wide.



Refreshes use one queue across all hubs, including manual and scheduled requests. Unload waits for that hub’s own active request and skips its queued work. Student refreshes preserve siblings’ data and timestamps.



### Fixes



- Cached data stays marked stale after startup authentication or network failures; ongoing failures remain eligible for notification.

- Never-fetched data does not inherit an old update timestamp.

- Mailbox content is excluded from new Recorder history. Live attributes and integration cache remain available; full-content fetching still requires explicit consent and marks fetched conversations read in Mashov.

- Slow speakers wait for noticeboard announcements before restoring volume.

- Drafts survive navigation within Home Assistant. **Discard draft** reloads current server settings after conflicts.

- Safe timer rebuilds after hub removal/reload, private schema debug logging, and corrected optional dependencies.



### Current inline form (English)

Choose the student and data type, then edit its schedule **inside the native form**. The same controls are used during hub registration and Configure. The main form’s **Submit** saves all edits together.

This is the released inline interface. Shared scope is selected to omit personal student names:

![Current inline Refresh schedules form](https://raw.githubusercontent.com/NirBY/ha-mashov/v1.1.0/docs/images/inline-schedules-en.jpg)

### Upgrade

Update **Mashov** through **HACS**, then restart Home Assistant. Existing schedules, data selections, entity IDs and history are preserved. During registration, student-specific schedules become available after authentication loads the roster. Mailbox is account-wide; holidays are school-wide.

See the [full changelog](https://github.com/NirBY/ha-mashov/blob/v1.1.0/CHANGELOG.md).
