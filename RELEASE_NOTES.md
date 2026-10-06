# Mashov v1.0.15

## Fix: keep student data paired during reauthentication

A login expiring during a refresh could replace the student list before results were
assembled. If children changed order, data could be assigned to the wrong child; adding
a child could fail the refresh with `IndexError`. Each refresh now uses a fixed roster
for requests, results and metadata. A changed roster takes effect on the next refresh.
Regression tests cover reordering, additions and removals, including the next refresh.

## Noticeboard notifications

- New hubs enable the existing Noticeboard resource by default. Existing hubs keep their
  current selection; enable it in Configure → Additional student data if wanted.
- New automation blueprint: `blueprints/automation/mashov/mashov_noticeboard_announce.yaml`.
  It compares notice IDs, so a replacement is detected even when the notice count stays
  unchanged. Startup and recovery states establish a baseline without repeating notices.
- Supports phone and Home Assistant notifications, plus optional Hebrew TTS. Speech is
  not started during 22:00–07:00; notifications are still sent. Quiet hours are rechecked
  after speaker preparation. Speaker volume is restored even after a TTS service failure.
- The blueprint is available for import; installing the integration does not create or
  enable an automation automatically. Notifications arrive at the configured refresh interval.
- Mashov's mail inbox and unread-message count remain unsupported. The Noticeboard
  exposes general school notices only and does not change mail read/unread status.

## Upgrade

Update through HACS and restart Home Assistant. Existing hub settings and entity IDs
are preserved. No new optional resources are enabled for existing hubs.

Validation includes the full regression suite, Ruff, GitHub CI on Python 3.13 and 3.14,
hassfest/HACS checks, and installation with per-hub refresh and diagnostics on Home Assistant.
Device-removal test assertions also support the newer single-owner device registry.
