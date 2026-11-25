# v1.7.0 — No more "new device" emails, lesson cancellations and notification refresh

- **No more "new device" emails (#33).** Home Assistant now logs in to Mashov as a private device and renews expired sessions with that remembered device instead of the password. Adding a hub or changing its credentials logs in once.
- **Lesson cancellations (off by default).** Each child gets a sensor with upcoming and recent cancellations. The weekly card strikes out cancelled lessons and moves the day's start or end time when its first or last lesson is cancelled. To turn it on, tick **Lesson cancellations published in Mashov** under **Configure → Data to fetch**.
- **Refresh on new notifications (off by default).** Between scheduled refreshes, Home Assistant checks Mashov's notification list and refreshes only the data a new notification is about. Nothing is marked as read. Data without notifications, such as the noticeboard, keeps its schedule.
  To turn it on: go to **Settings → Devices & services → Mashov**, select **Configure** on the hub, open **Refresh schedules**, tick **Refresh when Mashov shows a new notification** and select **Submit**. Checks run every 15 minutes by default (5–60, set in **Notification check interval**). Each hub has its own setting.

Thank you @ari-gen-x for reporting #33.

After updating, restart Home Assistant and refresh the browser. Each hub logs in with its password one last time to register as a private device, so expect one final "new device" email.
