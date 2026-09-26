from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .reporting import diagnostic_summary


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
    logs = hass.data.get(DOMAIN, {}).get("report_logs", {}).get(entry.entry_id, [])
    return diagnostic_summary(coordinator, logs)
