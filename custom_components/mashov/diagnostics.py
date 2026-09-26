"""Config entry diagnostics for Mashov (the file users attach to GitHub bug reports)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .reporting import diagnostic_summary


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    """Return a sanitized summary plus the hub's bounded technical logs.

    Deliberately excludes the config entry (credentials), raw data and student
    details; diagnostic_summary() decides what is safe to export. Works even when
    setup failed, in which case only versions and technical logs are returned.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
    # Collected in __init__._async_show_issue_notification for internal (programming) errors only.
    logs = hass.data.get(DOMAIN, {}).get("report_logs", {}).get(entry.entry_id, [])
    return diagnostic_summary(coordinator, logs)
