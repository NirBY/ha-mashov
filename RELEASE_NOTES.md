# Mashov v1.2.0 — Homework checklists and read-only MCP

Each child now has a native Home Assistant homework checklist. Completion is saved locally across refreshes, reloads and restarts, separately for every account, child and school year. Changed assignment text reopens a task; nothing is written back to Mashov. Generated live dashboards include the child's checklist in their pop-up.

## Read-only MCP for school questions

Enable MCP separately in each hub's Configure → Advanced settings. It is off by default for existing and new installations. Select only the intended Mashov APIs in Home Assistant's MCP Server settings, disable “Expose all LLM APIs”, and keep administrator authentication enabled.

Compatible AI clients can read all selected school datasets, with source status, freshness and pagination. Disabled datasets and mailbox-body consent remain respected. The API never returns credentials or cookies and cannot modify Mashov or control devices. Connect other MCP clients over Streamable HTTP and OAuth; messaging bots need an MCP adapter in their backend. See [setup and bot examples](https://github.com/NirBY/ha-mashov/blob/v1.2.0/docs/homework-and-mcp.md).

## Compatibility and upgrade

- Existing hub selections, schedules, sensor IDs and automation inputs are preserved. No new portal data sources are enabled.
- Bag reminders accept an optional TTS engine entity for `tts.speak`; leaving it empty retains the previous legacy service.
- Update through HACS and restart Home Assistant. Re-import the bag reminder blueprint for the TTS option. Regenerate a Mashov Live dashboard to include checklists in student pop-ups.
- English and Hebrew READMEs explain the new features; Configure translations cover all five supported languages.

Validation: 335 Home Assistant tests and Ruff checks; local HA 2026.10.2 checklist persistence and MCP scope/authentication verified.
