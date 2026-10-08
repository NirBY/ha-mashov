[← README](../README.md) · [Dashboard](dashboard.md) · [Services](services.md)

# Automation blueprints

These automations speak or send notices; they do not create dashboard views. For picture examples of dashboard views, see the [Mashov Live guide](dashboard.md) and [Lovelace examples](../examples/lovelace/README.md).

## Daily homework and behavior

A ready-to-use blueprint that speaks today's homework and behavior in Hebrew at a fixed time, with safe defaults and volume handling.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

If you hit a cache issue when importing, use the commit‑pinned link:

[Import pinned version](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fv1.1.0%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_daily_homework_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_daily_homework_announce.yaml`.

What does it do?
- Daily voice announcement at **15:00** that reads the student’s **name**, **today’s behaviors**, and **today’s homework** (Hebrew).
- Runs **only in daytime** and **skips holidays** using your Mashov holidays sensor (`Items[start/end]`).
- Triggers **only if there is data for today** in the homework and/or behavior sensors.
- Temporarily **sets the speaker to max volume**, speaks via **`tts.speak`** (configurable), then **restores the original volume** after playback.
- Works with any `media_player` (Sonos, Nest, etc.); volume restore is state-aware.
- Fully **templated blueprint**: select your own Mashov sensors and speaker at import time.
- Safe defaults: 15:00 schedule, Hebrew TTS (`iw` by default; language support depends on the engine), 07:00–22:00 guard rails.
- GitHub-friendly: no hardcoded entity IDs; can be imported with a **My Home Assistant** one-click link.

How to use
1. Click the import button above and select your `holiday_sensor`, `homework_sensor`, `behavior_sensor`, `media_player`, and `tts_engine`.
2. Save the automation. By default it runs every day at 15:00.

---

## Bag reminder

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fbag_reminder_tomorrow.yaml)

What does it do?
- Runs once daily at 18:00 to help a student pack their school bag for tomorrow.
- Skips automatically if it’s night-time, Saturday, or a listed holiday (from the holiday sensor).
- Reads tomorrow’s subjects only when timetable data actually exists for tomorrow.
- Builds a Hebrew TTS message: “שלום {Student}… אנא לסדר תיק למחר… {subjects + teacher names [+ plan]}”.
- Temporarily raises the speaker to a configurable max volume, then restores the previous (or fallback) volume after TTS ends.
- Pulls subjects and teacher names from the Mashov timetable; optionally appends each lesson’s “plan” from the weekly plan sensor.
- Waits for the speaker state to finish playing before restoring volume, to avoid cutting the message.
- Provides rich trace/log lines explaining why it ran or skipped (night block, Saturday, holiday, has data).

Blueprint file location: `blueprints/automation/mashov/bag_reminder_tomorrow.yaml`.

How to use
1. Click the import button above, pick your Mashov timetable sensor, (optional) weekly plan sensor, holiday sensor, media player and voice settings.
2. Save the automation. Defaults: 18:00, Hebrew, night guard 22:00–07:00.

---

## Noticeboard notices

Get a phone notification, and optionally hear it on a speaker, when the school posts a new notice
on a child's Mashov noticeboard. Added in v1.0.15.

One‑click import (My Home Assistant):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint URL.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNirBY%2Fha-mashov%2Fmain%2Fblueprints%2Fautomation%2Fmashov%2Fmashov_noticeboard_announce.yaml)

Blueprint file location: `blueprints/automation/mashov/mashov_noticeboard_announce.yaml`.

Requirements
- **Noticeboard** turned on for the hub ([how](../README.md#data-to-fetch)). Hubs created in v1.0.15 keep it enabled; new setups choose it explicitly.

What does it do?
- Watches one or more noticeboard sensors (one per child). A notice counts as new when its Mashov notice ID was not
  there before, so a notice that replaces another is announced, and a removed notice is not.
- Sends a Home Assistant notification (on by default) and, if you enter one, a phone notification
  (for example `notify.mobile_app_my_phone`). HTML is removed and long notices are shortened.
- Optionally reads the notice aloud in Hebrew: turns the speaker on, raises the volume, speaks with `tts.speak`,
  then restores the previous volume (or a fallback volume if it was unknown).
- **Never speaks during quiet hours, 22:00–07:00.** This is built in and cannot be turned off, so there are no
  surprise announcements at night. A notice that arrives then is still sent as a notification.
- Never re-announces existing notices after a Home Assistant restart, a reload, or a temporary outage.
- Logs every decision to the logbook (announced, quiet hours, nothing new), like the other Mashov blueprints.

Timing: notices arrive with the integration's refresh, not instantly. With the default daily refresh at 14:00,
a morning notice is announced at 14:00. For faster updates, set an interval (for example 60 minutes) for that student’s Noticeboard in Configure → Refresh schedules.

How to use
1. Click the import button above and create an automation from the blueprint.
2. Select the noticeboard sensors, and optionally a phone notify action, a speaker and a TTS engine.
3. Save. Nothing is announced right away; the next new notice triggers it.

Playback waits up to the configured TTS timeout for a slow speaker to start, then waits
up to that timeout for playback to finish before restoring volume (120 seconds each by default).
If playback never starts or never finishes, the timeout bounds the wait.

---
