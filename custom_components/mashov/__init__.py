from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, ServiceCall, callback  # type: ignore
from homeassistant.helpers.event import async_track_time_change  # type: ignore
from homeassistant.helpers.storage import Store  # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # type: ignore
import voluptuous as vol  # type: ignore

from .const import (
    CONF_API_BASE,
    CONF_HOMEWORK_DAYS_BACK,
    CONF_HOMEWORK_DAYS_FORWARD,
    CONF_PASSWORD,
    CONF_SCHEDULE_DAY,
    CONF_SCHEDULE_DAYS,
    CONF_SCHEDULE_INTERVAL,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_USERNAME,
    CONF_YEAR,
    DEFAULT_API_BASE,
    DEFAULT_HOMEWORK_DAYS_BACK,
    DEFAULT_HOMEWORK_DAYS_FORWARD,
    DEFAULT_SCHEDULE_DAY,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_TYPE,
    DOMAIN,
    PLATFORMS,
)
from .mashov_client import MashovAuthError, MashovClient, MashovError

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
        _LOGGER.info("Loaded YAML options for Mashov: %s", {k: yaml_conf.get(k) for k in yaml_conf})
    else:
        _LOGGER.debug("No YAML options provided for Mashov")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Try to log version info (best effort)
    try:
        import json
        import os

        current_dir = os.path.dirname(os.path.abspath(__file__))
        version_file = os.path.abspath(os.path.join(current_dir, "..", "..", "VERSION"))
        if not os.path.exists(version_file):
            alt = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "VERSION"))
            if os.path.exists(alt):
                version_file = alt
        if os.path.exists(version_file):
            with open(version_file, encoding="utf-8") as f:
                version = f.read().strip()
            _LOGGER.info("Setting up Mashov integration v%s for entry: %s", version, entry.title)
        else:
            manifest_file = os.path.join(current_dir, "manifest.json")
            if os.path.exists(manifest_file):
                with open(manifest_file, encoding="utf-8") as f:
                    version = json.load(f).get("version", "unknown")
                _LOGGER.info("Setting up Mashov integration v%s for entry: %s (from manifest)", version, entry.title)
            else:
                _LOGGER.info("Setting up Mashov integration for entry: %s", entry.title)
    except Exception as e:
        _LOGGER.warning("Version discovery failed: %s", e)
        _LOGGER.info("Setting up Mashov integration for entry: %s", entry.title)

    hass.data.setdefault(DOMAIN, {})

    # Extra diagnostics to understand why Configure button may not appear
    try:
        yaml_present = bool(hass.data.get(DOMAIN, {}).get("yaml_options"))
        _LOGGER.debug(
            "ConfigEntry meta: id=%s title='%s' source=%s domain=%s supports_options=%s yaml_present=%s",
            getattr(entry, "entry_id", ""),
            getattr(entry, "title", ""),
            getattr(entry, "source", ""),
            getattr(entry, "domain", ""),
            getattr(entry, "supports_options", None),
            yaml_present,
        )
        import sys  # local import to avoid unused-import when stripped by HA

        has_options_flow = hasattr(sys.modules[__name__], "async_get_options_flow")
        _LOGGER.debug("Module has async_get_options_flow: %s", has_options_flow)
        # Always log a concise INFO so it's visible even without DEBUG
        _LOGGER.info(
            "Mashov entry meta: source=%s, has_options_flow=%s, yaml_present=%s",
            getattr(entry, "source", ""),
            has_options_flow,
            yaml_present,
        )
    except Exception as e:
        _LOGGER.debug("Failed to log ConfigEntry diagnostics: %s", e)

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
        saved_auth=cached.get("auth") if isinstance(cached, dict) else None,
    )

    coordinator = MashovCoordinator(hass, client, entry)

    # Set up simple cache store per entry to avoid immediate API calls on startup
    store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.cache")
    cached: dict | None = None
    try:
        cached = await store.async_load()
        if isinstance(cached, dict) and cached.get("data"):
            coordinator.data = cached.get("data")
            _LOGGER.debug("Loaded cached data for entry %s (ts=%s)", entry.entry_id, cached.get("last_refresh_ts"))
    except Exception as e:
        _LOGGER.debug("No cache available for entry %s: %s", entry.entry_id, e)

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "unsub_daily": None,
    }

    # Decide whether to perform initial refresh now
    # Merge options + YAML to find schedule type
    yaml_opts = hass.data.get(DOMAIN, {}).get("yaml_options", {}) or {}
    merged_opts = dict(entry.options)

    # Migration: normalize schedule_days and drop legacy schedule_day
    try:
        migrated = False
        # If only legacy single day exists, promote to list
        if CONF_SCHEDULE_DAYS not in merged_opts and CONF_SCHEDULE_DAY in merged_opts:
            try:
                single = int(merged_opts.get(CONF_SCHEDULE_DAY))
            except Exception:
                single = DEFAULT_SCHEDULE_DAY
            merged_opts[CONF_SCHEDULE_DAYS] = [max(0, min(6, single))]
            migrated = True
        # If schedule_days exists with strings, cast to ints and clamp 0..6
        if CONF_SCHEDULE_DAYS in merged_opts and isinstance(merged_opts.get(CONF_SCHEDULE_DAYS), list):
            casted = []
            for v in merged_opts.get(CONF_SCHEDULE_DAYS) or []:
                with contextlib.suppress(Exception):
                    casted.append(max(0, min(6, int(v))))
            if casted:
                merged_opts[CONF_SCHEDULE_DAYS] = sorted(set(casted))
                migrated = True
        # Remove legacy key if we have schedule_days
        if CONF_SCHEDULE_DAYS in merged_opts and CONF_SCHEDULE_DAY in merged_opts:
            merged_opts.pop(CONF_SCHEDULE_DAY, None)
            migrated = True
        if migrated:
            hass.config_entries.async_update_entry(entry, options=merged_opts)
            _LOGGER.info(
                "Migrated options: normalized schedule_days and dropped legacy schedule_day for entry %s", entry.title
            )
    except Exception as e:
        _LOGGER.debug("Options migration skipped: %s", e)
    if yaml_opts:
        merged_opts.update({k: v for k, v in yaml_opts.items() if v is not None})

    schedule_type = str(merged_opts.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE))
    if schedule_type not in ("daily", "weekly", "interval"):
        schedule_type = DEFAULT_SCHEDULE_TYPE

    # Determine if to perform startup refresh at all
    # For daily/weekly schedules we avoid any startup refresh (defer to timers or manual service)
    # For interval we do a startup refresh to warm up data
    cooldown_seconds = 6 * 60 * 60  # used only for interval
    last_ts = None
    try:
        last_ts = (
            float(cached.get("last_refresh_ts")) if isinstance(cached, dict) and cached.get("last_refresh_ts") else None
        )
    except Exception:
        last_ts = None

    has_students = bool(getattr(coordinator, "data", None) and len((coordinator.data or {}).get("students", [])) > 0)
    # Refresh on startup if using interval OR if no students cached yet (first boot)
    do_startup_refresh = (schedule_type == "interval") or (not has_students)
    if (
        schedule_type == "interval"
        and last_ts is not None
        and (time.time() - last_ts) < cooldown_seconds
        and has_students
    ):
        do_startup_refresh = False
        _LOGGER.info(
            "Skipping startup refresh in interval mode due to cooldown (last=%s)",
            datetime.fromtimestamp(last_ts).isoformat(timespec="seconds"),
        )
    if schedule_type in ("daily", "weekly"):
        if not has_students:
            _LOGGER.info("Startup refresh enabled to warm up students (no cache present) [type=%s]", schedule_type)
        else:
            _LOGGER.info(
                "Startup refresh disabled for schedule_type=%s (defer to timers or manual service)", schedule_type
            )

    if do_startup_refresh:
        try:
            await asyncio.create_task(client.async_init(hass))
            await coordinator.async_config_entry_first_refresh()
            # Save cache after successful refresh
            try:
                await store.async_save(
                    {
                        "last_refresh_ts": time.time(),
                        "data": coordinator.data,
                        "auth": client.auth_data,
                    }
                )
            except Exception as e:
                _LOGGER.debug("Failed saving cache: %s", e)
        except Exception as e:
            _LOGGER.error("Failed to perform startup refresh: %s", e)
            await client.async_close()
            raise

    # Configure scheduler per options/YAML (also ensures timers; interval mode sets polling)
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

        # Service: set_options – allows updating options without Configure UI
        async def _handle_set_options(call: ServiceCall):
            opts = dict(entry.options)
            payload = dict(call.data or {})
            # Keep only known option keys
            known_keys = {
                CONF_HOMEWORK_DAYS_BACK,
                CONF_HOMEWORK_DAYS_FORWARD,
                CONF_API_BASE,
                CONF_SCHEDULE_TYPE,
                CONF_SCHEDULE_TIME,
                CONF_SCHEDULE_DAY,
                CONF_SCHEDULE_DAYS,
                CONF_SCHEDULE_INTERVAL,
            }
            for k, _v in list(payload.items()):
                if k not in known_keys:
                    payload.pop(k, None)
            opts.update(payload)
            hass.config_entries.async_update_entry(entry, options=opts)
            _LOGGER.info("Options updated via service for entry %s: %s", entry.title, list(payload.keys()))

        hass.services.async_register(DOMAIN, "set_options", _handle_set_options)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.info("Unloading Mashov integration: %s", entry.title)
    # Check if DOMAIN exists in hass.data (it won't if setup failed or was mocked)
    if DOMAIN not in hass.data:
        return True
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
    with contextlib.suppress(Exception):
        _LOGGER.debug(
            "async_get_options_flow requested (entry_id=%s, title='%s')",
            getattr(config_entry, "entry_id", ""),
            getattr(config_entry, "title", ""),
        )
    from .config_flow import OptionsFlowHandler

    return OptionsFlowHandler(config_entry)


async def _async_setup_scheduler(hass: HomeAssistant, entry: ConfigEntry):
    """Apply merged (YAML-overriding-UI) options and configure polling/timers."""
    from .const import (
        CONF_SCHEDULE_DAY,
        CONF_SCHEDULE_DAYS,
        CONF_SCHEDULE_INTERVAL,
        CONF_SCHEDULE_TIME,
        CONF_SCHEDULE_TYPE,
        DEFAULT_SCHEDULE_DAY,
        DEFAULT_SCHEDULE_TYPE,
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
    interval_minutes = _as_int(
        merged.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL), DEFAULT_SCHEDULE_INTERVAL, 5, 1440
    )

    # Rewire coordinator polling vs. timers
    coordinator: MashovCoordinator = data["coordinator"]
    unsubs = []

    @callback
    async def _refresh_data(now=None):
        _LOGGER.debug("Scheduled refresh fired at %s", now)
        await coordinator.async_request_refresh()
        # Persist cache after each scheduled refresh
        try:
            store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.cache")
            await store.async_save(
                {
                    "last_refresh_ts": time.time(),
                    "data": coordinator.data,
                    "auth": coordinator.client.auth_data,
                }
            )
        except Exception as e:
            _LOGGER.debug("Failed saving cache after refresh: %s", e)

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

            @callback
            async def _maybe_refresh_weekly(now=None):
                try:
                    today_idx = datetime.now().weekday()
                except Exception:
                    try:
                        # Fallback to UTC if needed
                        today_idx = datetime.utcnow().weekday()  # type: ignore[attr-defined]
                    except Exception:
                        today_idx = -1
                if today_idx in days:
                    await _refresh_data(now)
                else:
                    _LOGGER.debug("Weekly mode: skipping refresh (today=%s not in %s)", today_idx, days)

            # Schedule once daily at the specified time; gate by weekday inside the callback
            unsubs.append(async_track_time_change(hass, _maybe_refresh_weekly, hour=hh, minute=mm, second=0))

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
