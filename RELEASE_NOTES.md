# Mashov v1.0.17

Disabling data now removes it from the integration's disk cache before authentication,
even if the subsequent refresh fails. Turning off full message content removes cached
bodies; reducing the inbox limit also removes excess cached conversations. Recorder
history and backups remain governed by their own retention settings.

Removing Mailbox in Configure automatically resets a previously checked full-content
option. Re-enabling it starts with headers only. Validation errors preserve the submitted
data selection, and the Holidays category is clearly named in all five languages.

The README now starts with all 18 datasets and their new-installation/upgrade defaults,
a red warning about full-content fetching marking conversations read, actual Home Assistant
screenshots, and exact instructions for selecting and disabling data.

## Upgrade

Update through HACS and restart Home Assistant. Existing selections, entity IDs and user
customizations are preserved, including configurations from v1.0.7 onward. New hubs start
with no datasets selected. Mailbox and full content remain opt-in.
