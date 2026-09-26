# Mashov v1.0.12

Fix departed-student device removal and document old-data retention.

## Fixed
- Enable the Home Assistant device-page Delete action for a student absent from that hub's latest known roster, including after startup from cache.
- Complete automatic departed-student cleanup by removing empty device cards after a successful refresh with a roster obtained through a fresh login. Cached sessions, empty rosters and failed/stale refreshes do not trigger automatic deletion.
- Support both legacy shared devices and newer HA devices scoped to one hub. Detach only the affected hub; active students and holiday devices remain protected.

## Data retention and compatibility
- Device removal does not purge HA Recorder history or delete anything from Mashov's servers.
- Successful refreshes replace the local data snapshot; failed refreshes retain the last successful snapshot. Deleting a hub removes its local cache and saved authentication.
- Students still returned by a pinned previous school year cannot be removed individually through this action. Enable Automatic school year first, or delete the obsolete school hub when it is no longer needed.
- README now explains the scope of date windows, attribute limits, cache cleanup and Recorder retention.
- Existing active entity IDs, settings, notification routing and history remain unchanged. Update through HACS and restart Home Assistant.

## Validation
- 146 local regression tests pass, including manual removal, missing-cache safety, automatic cleanup guards and shared-device preservation.
- Ruff and the CI Python 3.13/3.14, hassfest and HACS checks are required before release.
