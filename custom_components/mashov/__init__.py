from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import voluptuous as vol  # type: ignore
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, ServiceCall, callback  # type: ignore
from homeassistant.helpers.event import async_track_time_change  # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # type: ignore

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_SCHOOL_ID, CONF_SCHOOL_NAME, CONF_YEAR, CONF_USERNAME, CONF_PASSWORD,
    CONF_HOMEWORK_DAYS_BACK, CONF_HOMEWORK_DAYS_FORWARD, CONF_API_BASE,
    CONF_SCHEDULE_TYPE, CONF_SCHEDULE_TIME, CONF_SCHEDULE_DAY, CONF_SCHEDULE_DAYS, CONF_SCHEDULE_INTERVAL,
    DEFAULT_HOMEWORK_DAYS_BACK, DEFAULT_HOMEWORK_DAYS_FORWARD, DEFAULT_API_BASE,
    DEFAULT_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TIME, DEFAULT_SCHEDULE_DAY, DEFAULT_SCHEDULE_INTERVAL,
)
from .mashov_client import MashovClient, MashovAuthError, MashovError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_SCHEDULE_TYPE): vol.In(["daily", "weekly", "interval"]),
                vol.Optional(CONF_SCHEDULE_TIME): str,
                vol.Optional(CONF_SCHEDULE_DAY): vol.All(int, vol.Range(min=0, max=6)),
                vol.Optional(CONF_SCHEDULE_DAYS): [vol.All(int, vol.Range(min=0, max=6))],
                vol.Optional(CONF_SCHEDULE_INTERVAL): vol.All(int, vol.Range(min=5, max=1440)),
                vol.Optional(CONF_HOMEWORK_DAYS_BACK): vol.All(int, vol.Range(min=0, max=60)),
                vol.Optional(CONF_HOMEWORK_DAYS_FORWARD): vol.All(int, vol.Range(min=1, max=120)),
                vol.Optional(CONF_API_BASE): str,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up from YAML (optional)."""
    hass.data.setdefault(DOMAIN, {})
    yaml_conf = config.get(DOMAIN) or {}
    hass.data[DOMAIN]["yaml_options"] = yaml_conf
    if yaml_conf:
        _LOGGER.info("Loaded YAML options for Mashov: %s", {k: yaml_conf.get(k) for k in yaml_conf.keys()})
    else:
        _LOGGER.debug("No YAML options provided for Mashov")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Try to log version info (best effort)
    try:
        import os, json
        current_dir = os.path.dirname(os.path.abspath(__file__))
        version_file = os.path.abspath(os.path.join(current_dir, "..", "..", "VERSION"))
        if not os.path.exists(version_file):
            alt = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "VERSION"))
            if os.path.exists(alt):
                version_file = alt
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                version = f.read().strip()
            _LOGGER.info("Setting up Mashov integration v%s for entry: %s", version, entry.title)
        else:
            manifest_file = os.path.join(current_dir, "manifest.json")
            if os.path.exists(manifest_file):
                with open(manifest_file, "r", encoding="utf-8") as f:
                    version = json.load(f).get("version", "unknown")
                _LOGGER.info("Setting up Mashov integration v%s for entry: %s (from manifest)", version, entry.title)
            else:
                _LOGGER.info("Setting up Mashov integration for entry: %s", entry.title)
    except Exception as e:
        _LOGGER.warning("Version discovery failed: %s", e)
        _LOGGER.info("Setting up Mashov integration for entry: %s", entry.title)

    hass.data.setdefault(DOMAIN, {})

    # Normalize entry title: "<school_name> (<school_id>)"
    data = entry.data
    school_id = data.get(CONF_SCHOOL_ID, "")
    school_name = data.get(CONF_SCHOOL_NAME, "")
    expected_title = f"{school_name} ({school_id})" if school_name else f"{school_id}"
    if entry.title and school_id and entry.title.strip() != expected_title.strip():
        _LOGGER.info("Updating hub title: '%s' -> '%s'", entry.title, expected_title)
        hass.config_entries.async_update_entry(entry, title=expected_title)

    client = MashovClient(
        school_id=data[CONF_SCHOOL_ID],
        year=data.get(CONF_YEAR),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        homework_days_back=entry.options.get(CONF_HOMEWORK_DAYS_BACK, DEFAULT_HOMEWORK_DAYS_BACK),
        homework_days_forward=entry.options.get(CONF_HOMEWORK_DAYS_FORWARD, DEFAULT_HOMEWORK_DAYS_FORWARD),
        api_base=entry.options.get(CONF_API_BASE, DEFAULT_API_BASE),
    )

    try:
        await asyncio.create_task(client.async_init(hass))
    except Exception as e:
        _LOGGER.error("Failed to initialize Mashov client: %s", e)
        await client.async_close()
        raise

    coordinator = MashovCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "unsub_daily": None,
    }

    # Configure scheduler per options/YAML
    await _async_setup_scheduler(hass, entry)

    # Reconfigure when options change
    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        _LOGGER.info("Options updated for entry %s; reconfiguring scheduler", updated_entry.title)
        await _async_setup_scheduler(hass, updated_entry)

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_refresh(call: ServiceCall):
        entry_id = call.data.get("entry_id")
        tasks = []
        if entry_id:
            ce = hass.data[DOMAIN].get(entry_id)
            if isinstance(ce, dict) and "coordinator" in ce:
                tasks.append(ce["coordinator"].async_request_refresh())
        else:
            for maybe_entry in hass.data.get(DOMAIN, {}).values():
                if isinstance(maybe_entry, dict) and "coordinator" in maybe_entry:
                    tasks.append(maybe_entry["coordinator"].async_request_refresh())
        if tasks:
            await asyncio.gather(*tasks)

    if DOMAIN not in hass.services.async_services():
        hass.services.async_register(DOMAIN, "refresh_now", _handle_refresh)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.info("Unloading Mashov integration: %s", entry.title)
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data:
        if data.get("unsub_daily"):
            try:
                # Could be a single fn or list
                unsub = data["unsub_daily"]
                if isinstance(unsub, list):
                    for fn in unsub:
                        if callable(fn):
                            fn()
                elif callable(unsub):
                    unsub()
            except Exception as e:
                _LOGGER.debug("Error while unsubscribing timers: %s", e)
        if data.get("client"):
            await data["client"].async_close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def async_get_options_flow(config_entry: ConfigEntry):
    try:
        _LOGGER.debug(
            "async_get_options_flow requested (entry_id=%s, title='%s')",
            getattr(config_entry, "entry_id", ""),
            getattr(config_entry, "title", ""),
        )
    except Exception:
        pass
    from .config_flow import OptionsFlowHandler
    return OptionsFlowHandler(config_entry)


async def _async_setup_scheduler(hass: HomeAssistant, entry: ConfigEntry):
    """Apply merged (YAML-overriding-UI) options and configure polling/timers."""
    from .const import (
        CONF_SCHEDULE_TYPE, CONF_SCHEDULE_TIME, CONF_SCHEDULE_DAY, CONF_SCHEDULE_DAYS, CONF_SCHEDULE_INTERVAL,
        DEFAULT_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TIME, DEFAULT_SCHEDULE_DAY, DEFAULT_SCHEDULE_INTERVAL,
    )

    data = hass.data[DOMAIN][entry.entry_id]

    # Cancel previous timers
    prev = data.get("unsub_daily")
    if prev:
        try:
            if isinstance(prev, list):
                for fn in prev:
                    if callable(fn):
                        fn()
            elif callable(prev):
                prev()
        except Exception as e:
            _LOGGER.debug("Error cancelling previous schedules: %s", e)

    yaml_opts = hass.data.get(DOMAIN, {}).get("yaml_options", {}) or {}
    merged = dict(entry.options)
    if yaml_opts:
        merged.update({k: v for k, v in yaml_opts.items() if v is not None})

    def _as_int(val, default, lo=None, hi=None):
        try:
            v = int(val)
            if lo is not None and v < lo:
                raise ValueError
            if hi is not None and v > hi:
                raise ValueError
            return v
        except Exception:
            return default

    def _as_hhmm(val, default):
        try:
            s = str(val)
            hh, mm = s.split(":")
            H = _as_int(hh, None, 0, 23)
            M = _as_int(mm, None, 0, 59)
            if H is None or M is None:
                raise ValueError
            return f"{H:02d}:{M:02d}"
        except Exception:
            return default

    schedule_type = str(merged.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE))
    if schedule_type not in ("daily", "weekly", "interval"):
        schedule_type = DEFAULT_SCHEDULE_TYPE

    schedule_time = _as_hhmm(merged.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME), DEFAULT_SCHEDULE_TIME)
    schedule_day_single = _as_int(merged.get(CONF_SCHEDULE_DAY, DEFAULT_SCHEDULE_DAY), DEFAULT_SCHEDULE_DAY, 0, 6)
    days_raw = merged.get(CONF_SCHEDULE_DAYS)
    days = []
    if isinstance(days_raw, list):
        for d in days_raw:
            v = _as_int(d, None, 0, 6)
            if v is not None:
                days.append(v)
    if not days:
        days = [schedule_day_single]
    interval_minutes = _as_int(merged.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL), DEFAULT_SCHEDULE_INTERVAL, 5, 1440)

    # Rewire coordinator polling vs. timers
    coordinator: MashovCoordinator = data["coordinator"]
    unsubs = []

    @callback
    async def _refresh_data(now=None):
        _LOGGER.debug("Scheduled refresh fired at %s", now)
        await coordinator.async_request_refresh()

    if schedule_type == "interval":
        # Use *only* coordinator.update_interval (no extra timer)
        coordinator.set_interval_minutes(interval_minutes)
        _LOGGER.info("Interval mode: coordinator polling every %d minutes", interval_minutes)

    else:
        # Disable periodic polling and schedule time-based jobs
        coordinator.set_interval_minutes(None)
        try:
            hh, mm = [int(x) for x in schedule_time.split(":")]
        except Exception:
            hh, mm = 2, 30

        if schedule_type == "daily":
            _LOGGER.info("Daily mode: refresh at %02d:%02d", hh, mm)
            unsubs.append(async_track_time_change(hass, _refresh_data, hour=hh, minute=mm, second=0))

        elif schedule_type == "weekly":
            _LOGGER.info("Weekly mode: days=%s at %02d:%02d", days, hh, mm)
            for d in days:
                unsubs.append(
                    async_track_time_change(hass, _refresh_data, weekday=int(d), hour=hh, minute=mm, second=0)
                )

    hass.data[DOMAIN][entry.entry_id]["unsub_daily"] = unsubs


class MashovCoordinator(DataUpdateCoordinator):
    """Coordinator for Mashov, supporting dynamic interval changes."""

    def __init__(self, hass: HomeAssistant, client: MashovClient, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=f"MashovCoordinator:{entry.title}",
            update_interval=timedelta(hours=24),  # safe default; overridden in interval mode
        )
        self.client = client
        self.entry = entry

    def set_interval_minutes(self, minutes: int | None):
        """Set/clear periodic polling interval."""
        if minutes is None:
            self.update_interval = timedelta(hours=24)
            _LOGGER.debug("Coordinator update_interval disabled (set to 24h fallback).")
        else:
            self.update_interval = timedelta(minutes=minutes)
            _LOGGER.info("Coordinator update_interval set to %d minutes.", minutes)

    async def _async_update_data(self):
        _LOGGER.debug("Coordinator update started: %s", self.name)
        try:
            data = await asyncio.create_task(self.client.async_fetch_all())
            _LOGGER.debug("Coordinator update completed; students=%d", len(data.get("students", [])))
            return data
        except MashovAuthError as exc:
            _LOGGER.error("Authentication error during data update: %s", exc)
            raise UpdateFailed(f"Auth error: {exc}") from exc
        except MashovError as exc:
            _LOGGER.error("Mashov error during data update: %s", exc)
            raise UpdateFailed(f"Mashov error: {exc}") from exc
        except Exception as exc:
            _LOGGER.error("Unexpected error during data update: %s", exc)
            raise UpdateFailed(f"Unexpected error: {exc}") from exc
