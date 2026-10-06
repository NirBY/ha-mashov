"""Mashov (Israeli school portal) integration: setup, services, scheduling and coordinator.

Each config entry is a "hub" (one Mashov login at one school) that may expose several
students. Data is cached on disk so entities come back immediately after a restart,
and refreshes run on a user-chosen schedule (daily, weekly or fixed interval).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
import logging
import time

from homeassistant.components import persistent_notification  # type: ignore
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback  # type: ignore
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, ServiceValidationError  # type: ignore
from homeassistant.helpers import (
    config_validation as cv,  # type: ignore
    device_registry as dr,
)
from homeassistant.helpers.event import async_track_time_change  # type: ignore
from homeassistant.helpers.service import async_register_admin_service  # type: ignore
from homeassistant.helpers.storage import Store  # type: ignore
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # type: ignore
from homeassistant.loader import async_get_integration  # type: ignore
from homeassistant.util import dt as dt_util  # type: ignore
import voluptuous as vol  # type: ignore

from .additional_data import CONF_ADDITIONAL_DATA, STUDENT_RESOURCES
from .const import (
    CONF_API_BASE,
    CONF_HOMEWORK_DAYS_BACK,
    CONF_HOMEWORK_DAYS_FORWARD,
    CONF_MAX_ITEMS_IN_ATTRIBUTES,
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
from .data_selection import (
    CONF_ENABLED_DATA,
    CONF_MAILBOX_FULL_CONTENT,
    CONF_MAILBOX_LIMIT,
    DATA_KEYS,
    DEFAULT_MAILBOX_LIMIT,
    cached_selection,
    enabled_data,
    filter_cached_data,
    merge_selection_options,
)
from .live_dashboard import DEFAULT_DASHBOARD, STUDENT_ENTITY_KEYS, async_save_live_dashboard
from .mashov_client import (
    MashovAuthError,
    MashovClient,
    MashovError,
    MashovPasswordChangeRequiredError,
    configured_school_year,
)
from .reporting import is_internal_error, issue_report_url, technical_log

_LOGGER = logging.getLogger(__name__)

# Notification policy
# -------------------
# Every hub has a single persistent notification slot (same notification_id), so a
# newer problem replaces the older one and a successful refresh dismisses it.
# Bug-report links are only offered for internal (programming) errors, never for
# normal account, network or Mashov API failures (see reporting.is_internal_error).
_ISSUE_NOTIFICATION_KEY = "issue"


def _issue_notification_id(entry: ConfigEntry) -> str:
    """Return the per-hub notification id shared by all issue notifications."""
    return f"{DOMAIN}_{entry.entry_id}_{_ISSUE_NOTIFICATION_KEY}"


def _async_show_issue_notification(
    hass: HomeAssistant, entry: ConfigEntry, title: str, message: str, *, error=None
) -> None:
    """Create/replace the hub's notification; append report links for internal errors.

    For internal errors a sanitized technical log is recorded (last 20 per hub, kept
    in memory and exported via diagnostics) and embedded in a prefilled GitHub issue
    link. The user must review and submit manually; nothing is sent automatically.
    """
    if is_internal_error(error):
        logs = hass.data.setdefault(DOMAIN, {}).setdefault("report_logs", {}).setdefault(entry.entry_id, [])
        logs.append(technical_log(error, title))
        del logs[:-20]  # bound memory and URL length: keep only the 20 most recent entries
        message += (
            "\n\nAn unexpected internal error was detected."
            f"\n\n[Review a bug report on GitHub]({issue_report_url(title)})"
            f"\n\n[Review a bug report with technical logs]({issue_report_url(title, logs)})"
            "\n\nTechnical logs include error types, timestamps and integration code locations only; "
            "exception text, credentials, student data and raw HA logs are excluded. "
            "For an attachment, open [Mashov settings](/config/integrations/integration/mashov), "
            "choose the affected hub, download diagnostics from its menu and attach the file to GitHub. "
            "Review the report and attachments before submitting. Nothing is submitted automatically."
        )
    persistent_notification.async_create(
        hass,
        message,
        title=title,
        notification_id=_issue_notification_id(entry),
    )


def _async_show_password_change_notification(
    hass: HomeAssistant, entry: ConfigEntry, exc: MashovPasswordChangeRequiredError
) -> None:
    """Tell the user to change the password on the Mashov site (not a bug; no report links)."""
    message = (
        f"Mashov requires a password change before it can log in for **{entry.title}**.\n\n"
        "The integration will keep the last successful data until this is resolved.\n\n"
        f"[Open Mashov login page]({exc.login_url})"
    )
    _async_show_issue_notification(hass, entry, "Mashov password change required", message)


def _async_show_error_notification(hass: HomeAssistant, entry: ConfigEntry, title: str, error: Exception | str) -> None:
    """Show a refresh failure: internal errors get report links, transient ones a retry hint.

    Callers decide *when* to notify (first failure without cache, third consecutive
    failure, or once per internal error); this only chooses the wording.
    """
    if is_internal_error(error):
        message = "Mashov encountered an unexpected internal error while processing data. Cached data is retained when available."
    else:
        message = f"Mashov could not refresh **{entry.title}**. Check connectivity and Mashov availability; a later refresh will retry."
    _async_show_issue_notification(hass, entry, title, message, error=error)


def _async_show_auth_notification(
    hass: HomeAssistant,
    entry: ConfigEntry,
    error: Exception | str,
    login_url: str | None = None,
) -> None:
    """Ask the user to fix the hub credentials; shown on every auth failure (not a bug)."""
    message = (
        f"Mashov could not authenticate for **{entry.title}**.\n\n"
        "The integration will keep the last successful data until this is resolved, if cached data is available.\n\n"
        f"Error: `{error}`\n\n"
        "Update the hub credentials in **Settings -> Devices & Services -> Mashov -> Configure**."
    )
    if login_url:
        message += f"\n\n[Open Mashov login page]({login_url})"
    _async_show_issue_notification(hass, entry, "Mashov authentication failed", message)


def _async_clear_issue_notification(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Dismiss the hub's issue notification (after a successful refresh or hub removal)."""
    persistent_notification.async_dismiss(hass, _issue_notification_id(entry))


# Optional YAML block (`mashov:` in configuration.yaml). Values here override the UI
# options for every hub (see _async_setup_scheduler); ALLOW_EXTRA lets HA's full
# config pass through this top-level schema.
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
    """Store optional YAML options and register domain-wide services.

    Services are registered here (once per HA start), not per entry, so they exist
    even when no hub has loaded yet.
    """
    hass.data.setdefault(DOMAIN, {})
    yaml_conf = config.get(DOMAIN) or {}
    hass.data[DOMAIN]["yaml_options"] = yaml_conf
    if yaml_conf:
        _LOGGER.info("Loaded YAML options for Mashov: %s", {k: yaml_conf.get(k) for k in yaml_conf})
    else:
        _LOGGER.debug("No YAML options provided for Mashov")
    _async_register_services(hass)
    return True


def _int_in(lo: int, hi: int):
    """Validator: coerce to int (service UIs may send strings) and check the range."""
    return vol.All(vol.Coerce(int), vol.Range(min=lo, max=hi))


# --- Service schemas ---
# refresh_now: without entry_id every loaded hub is refreshed.
REFRESH_NOW_SCHEMA = vol.Schema({vol.Optional("entry_id"): cv.string})
# set_options: same ranges as the Configure UI. REMOVE_EXTRA silently drops unknown
# keys (e.g. from older automations) instead of failing the call or storing them.
# schedule_days is deduplicated and sorted; legacy schedule_day is still accepted.
SET_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("automatic_school_year"): cv.boolean,
        vol.Optional(CONF_MAX_ITEMS_IN_ATTRIBUTES): _int_in(10, 500),
        vol.Optional(CONF_ADDITIONAL_DATA): vol.All(cv.ensure_list, [vol.In(STUDENT_RESOURCES)]),
        vol.Optional(CONF_ENABLED_DATA): vol.All(cv.ensure_list, [vol.In(DATA_KEYS)]),
        vol.Optional(CONF_MAILBOX_FULL_CONTENT): cv.boolean,
        vol.Optional(CONF_MAILBOX_LIMIT): _int_in(1, 50),
        vol.Optional(CONF_SCHEDULE_TYPE): vol.In(["daily", "weekly", "interval"]),
        vol.Optional(CONF_SCHEDULE_TIME): vol.Match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$"),
        vol.Optional(CONF_SCHEDULE_DAY): _int_in(0, 6),
        vol.Optional(CONF_SCHEDULE_DAYS): vol.All(
            cv.ensure_list, [_int_in(0, 6)], vol.Length(min=1), lambda days: sorted(set(days))
        ),
        vol.Optional(CONF_SCHEDULE_INTERVAL): _int_in(5, 1440),
        vol.Optional(CONF_HOMEWORK_DAYS_BACK): _int_in(0, 60),
        vol.Optional(CONF_HOMEWORK_DAYS_FORWARD): _int_in(1, 120),
        vol.Optional(CONF_API_BASE): vol.Match(r"^https?://"),
    },
    extra=vol.REMOVE_EXTRA,
)

# create_live_dashboard: per-student overrides. Empty/None values mean "use the
# auto-detected entity"; unknown keys are dropped. Entity slots come from
# live_dashboard.STUDENT_ENTITY_KEYS so both stay in sync.
_OPTIONAL_ENTITY = vol.Any(None, "", cv.entity_id)
LIVE_STUDENT_SCHEMA = vol.Schema(
    {
        vol.Optional("name"): vol.Any(None, cv.string),
        vol.Optional("emoji"): vol.Any(None, cv.string),
        vol.Optional("label"): vol.Any(None, cv.string),
        vol.Optional("person"): _OPTIONAL_ENTITY,
        vol.Optional("viewers"): vol.Any(None, vol.All(cv.ensure_list, [cv.entity_id])),
        # "#RRGGBB" or [r, g, b]; values are fully validated later in live_dashboard._accent.
        vol.Optional("accent"): vol.Any(None, cv.string, vol.All(list, vol.Length(min=3, max=3))),
        **{vol.Optional(key): _OPTIONAL_ENTITY for key in STUDENT_ENTITY_KEYS},
    },
    extra=vol.REMOVE_EXTRA,
)
CREATE_LIVE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional("dashboard", default=DEFAULT_DASHBOARD): cv.string,
        vol.Optional("title"): vol.Any(None, cv.string),
        vol.Optional("family"): vol.Any(None, vol.All(cv.ensure_list, [cv.entity_id])),
        vol.Optional("overwrite", default=False): cv.boolean,
        vol.Optional("students"): vol.Any(None, vol.All(cv.ensure_list, [LIVE_STUDENT_SCHEMA])),
    }
)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once; handlers resolve entries at call time."""

    async def _handle_refresh(call: ServiceCall):
        """Refresh one hub or all loaded hubs; an unknown/unloaded entry_id is a no-op."""
        entry_id = call.data.get("entry_id")
        tasks = []
        if entry_id:
            ce = hass.data[DOMAIN].get(entry_id)
            if isinstance(ce, dict) and "coordinator" in ce:
                tasks.append(ce["coordinator"].async_request_refresh())
        else:
            # hass.data[DOMAIN] also holds non-entry keys (yaml_options, report_logs).
            for maybe_entry in hass.data.get(DOMAIN, {}).values():
                if isinstance(maybe_entry, dict) and "coordinator" in maybe_entry:
                    tasks.append(maybe_entry["coordinator"].async_request_refresh())
        if tasks:
            await asyncio.gather(*tasks)

    # Service: set_options - allows updating options without Configure UI
    async def _handle_set_options(call: ServiceCall):
        """Merge the given options into a hub; the update listener then reloads or reschedules.

        Unlike refresh_now, the entry does not need to be loaded when entry_id is given.
        """
        payload = dict(call.data or {})
        entry_id = payload.pop("entry_id", None)
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                raise ServiceValidationError(f"Unknown Mashov entry_id: {entry_id}")
        else:
            entries = hass.config_entries.async_entries(DOMAIN)
            if not entries:
                raise ServiceValidationError("No Mashov hub is configured")
            if len(entries) > 1:
                _LOGGER.warning(
                    "set_options without entry_id targets the first loaded hub; specify entry_id with multiple hubs"
                )
            # Legacy calls target the first loaded hub. Explicit entry_id selects any hub.
            # Iterating hass.data[DOMAIN] keys (insertion order = load order) picks the
            # first *loaded* entry; fall back to the first configured one if none loaded.
            entry = next(
                (candidate for key in hass.data.get(DOMAIN, {}) for candidate in entries if candidate.entry_id == key),
                entries[0],
            )
        if payload.get(CONF_MAILBOX_FULL_CONTENT) and "mailbox" not in payload.get(
            CONF_ENABLED_DATA, enabled_data(entry.options)
        ):
            raise ServiceValidationError("Select mailbox before enabling full content (which marks messages read)")
        opts = merge_selection_options(entry.options, payload)
        # Legacy schedule_day is promoted to a one-element schedule_days, and the old
        # key is never stored alongside the list (mirrors the setup-time migration).
        if CONF_SCHEDULE_DAY in payload and CONF_SCHEDULE_DAYS not in payload:
            opts[CONF_SCHEDULE_DAYS] = [payload[CONF_SCHEDULE_DAY]]
        if CONF_SCHEDULE_DAYS in opts:
            opts.pop(CONF_SCHEDULE_DAY, None)
        hass.config_entries.async_update_entry(entry, options=opts)
        _LOGGER.info("Options updated via service for entry %s: %s", entry.title, list(payload.keys()))

    async def _handle_create_live_dashboard(call: ServiceCall) -> ServiceResponse:
        """Write the generated Lovelace dashboard; returns a summary when a response is requested."""
        return await async_save_live_dashboard(hass, dict(call.data))

    hass.services.async_register(DOMAIN, "refresh_now", _handle_refresh, schema=REFRESH_NOW_SCHEMA)
    hass.services.async_register(DOMAIN, "set_options", _handle_set_options, schema=SET_OPTIONS_SCHEMA)
    # Admin-only: it creates/overwrites a dashboard in HA's Lovelace storage, which
    # non-admin users must not be able to do. Response is optional so it also works
    # from automations/scripts that do not ask for one.
    async_register_admin_service(
        hass,
        DOMAIN,
        "create_live_dashboard",
        _handle_create_live_dashboard,
        schema=CREATE_LIVE_DASHBOARD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _frozen_school_year(hass: HomeAssistant, entry: ConfigEntry):
    """Keep a turned-off automatic year from following the calendar on hubs that never stored one.

    Returns None while the automatic school year is on (the client then picks the
    current Mashov year). When it is off and no year was stored, today's year is
    persisted once so the hub stays on it after the calendar rolls over.
    """
    data = dict(entry.data)
    year = configured_school_year(data, entry.options)
    if year is not None and not data.get(CONF_YEAR):
        data[CONF_YEAR] = year
        hass.config_entries.async_update_entry(entry, data=data)
    return year


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up one hub: restore cache, build client/coordinator, maybe refresh, schedule.

    Setup error mapping (only when there is no cached data to fall back on):
    - auth / password-change errors raised by the login (client.async_init)
      -> ConfigEntryError (no retry loop; the user must act)
    - anything else, including coordinator UpdateFailed (which HA already turns into
      ConfigEntryNotReady) -> ConfigEntryNotReady (HA retries setup with backoff)
    With cached data, setup always succeeds and entities show the cache marked stale.
    """
    # Use the manifest metadata Home Assistant already loaded; no file I/O in the event loop.
    try:
        version = (await async_get_integration(hass, DOMAIN)).version
    except Exception as e:
        _LOGGER.debug("Version discovery failed: %s", e)
        version = None
    if version:
        _LOGGER.info("Setting up Mashov integration v%s for entry: %s", version, entry.title)
    else:
        _LOGGER.info("Setting up Mashov integration for entry: %s", entry.title)

    hass.data.setdefault(DOMAIN, {})

    # Preserve exactly what older hubs (including v1.0.7+) fetched. New sources
    # are never added to the frozen historical default during an upgrade.
    if CONF_ENABLED_DATA not in entry.options:
        hass.config_entries.async_update_entry(entry, options=merge_selection_options(entry.options, {}))

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

    # Set up simple cache store per entry to avoid immediate API calls on startup.
    # Layout: {"last_refresh_ts": epoch seconds, "data": coordinator data,
    #          "auth": client session (cookies/CSRF token/session_year)}.
    # Removed in async_remove_entry since it holds session cookies and student data.
    store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.cache")
    cached: dict | None = None
    try:
        cached = await store.async_load()
        if isinstance(cached, dict) and cached.get("data"):
            _LOGGER.debug("Loaded cached data for entry %s (ts=%s)", entry.entry_id, cached.get("last_refresh_ts"))
    except Exception as e:
        _LOGGER.debug("No cache available for entry %s: %s", entry.entry_id, e)

    # Apply opt-outs on disk before authentication or network requests. A failed
    # refresh must never leave disabled records or message bodies in our cache.
    # Keep the snapshot's original selection metadata until a successful fetch,
    # so adding data still forces a refresh after a failed attempt/restart.
    if isinstance(cached, dict) and cached.get("data"):
        filtered = filter_cached_data(cached["data"], entry.options)
        if filtered != cached["data"]:
            cached = {**cached, "data": filtered}
            try:
                await store.async_save(cached)
            except Exception as err:
                raise ConfigEntryNotReady("Could not remove disabled data from the Mashov cache") from err

    # Restore the saved Mashov session so a restart does not force a new login.
    # The client needs to know which school year a session was opened for, so it
    # does not reuse a session from a different year.
    saved_auth = cached.get("auth") if isinstance(cached, dict) else None
    if (
        isinstance(saved_auth, dict)
        and (saved_auth.get("csrf_token") or saved_auth.get("cookies"))
        and "session_year" not in saved_auth
    ):
        # Back-compat: older caches stored the school year alongside students, not in auth.
        cached_students = (cached.get("data") or {}).get("students") or []
        if cached_students and cached_students[0].get("year"):
            saved_auth = {**saved_auth, "session_year": cached_students[0]["year"]}

    client = MashovClient(
        school_id=data[CONF_SCHOOL_ID],
        year=_frozen_school_year(hass, entry),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        homework_days_back=entry.options.get(CONF_HOMEWORK_DAYS_BACK, DEFAULT_HOMEWORK_DAYS_BACK),
        homework_days_forward=entry.options.get(CONF_HOMEWORK_DAYS_FORWARD, DEFAULT_HOMEWORK_DAYS_FORWARD),
        api_base=entry.options.get(CONF_API_BASE, DEFAULT_API_BASE),
        saved_auth=saved_auth,
        additional_data=entry.options.get(CONF_ADDITIONAL_DATA, []),
        enabled_data=list(enabled_data(entry.options)),
        mailbox_full_content=entry.options.get(CONF_MAILBOX_FULL_CONTENT, False),
        mailbox_limit=entry.options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT),
    )

    coordinator = MashovCoordinator(hass, client, entry)

    # Inject cached data into coordinator if available, so platforms create entities
    # from the cache even when no startup refresh runs.
    if isinstance(cached, dict) and cached.get("data"):
        coordinator.data = cached["data"]
        coordinator.last_successful_update = cached.get("last_refresh_ts")

    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "unsub_daily": None,  # list of time-trigger unsubscribers set by _async_setup_scheduler
    }

    # Decide whether to perform initial refresh now
    # Merge options + YAML to find schedule type
    yaml_opts = hass.data.get(DOMAIN, {}).get("yaml_options", {}) or {}
    merged_opts = dict(entry.options)

    # Migration: normalize schedule_days and drop legacy schedule_day.
    # Runs on UI options only (before YAML is merged) so YAML values are never persisted.
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

    # Determine if to perform startup refresh at all:
    # - no cached students (first boot / empty cache): always refresh, any schedule type
    # - daily/weekly with cache: skip; the next timer or refresh_now updates the data
    # - interval with cache: refresh, unless the cache is younger than the cooldown,
    #   so frequent HA restarts do not hammer the Mashov servers
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

    # Newly selected data must be fetched immediately after Configure, even when
    # the daily schedule or restart cooldown would otherwise defer the refresh.
    cached_data = (cached or {}).get("data") or {}
    if cached_data and (
        cached_selection(cached_data) != set(enabled_data(entry.options))
        or bool(cached_data.get(CONF_MAILBOX_FULL_CONTENT, False))
        != bool(entry.options.get(CONF_MAILBOX_FULL_CONTENT, False))
        or cached_data.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)
        != entry.options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT)
    ):
        do_startup_refresh = True

    # Failure handling below: always mark data stale and notify; keep the cache when
    # there is one, otherwise close the client and fail setup (see docstring).
    if do_startup_refresh:
        try:
            await asyncio.create_task(client.async_init(hass))
            await coordinator.async_config_entry_first_refresh()
        except MashovPasswordChangeRequiredError as e:
            coordinator.data_stale = True
            _async_show_password_change_notification(hass, entry, e)
            if coordinator.data:
                _LOGGER.warning(
                    "Mashov requires a password change for %s; keeping cached data until the issue is resolved",
                    entry.title,
                )
            else:
                _LOGGER.error("Failed to perform startup refresh: %s", e)
                await client.async_close()
                raise ConfigEntryError(str(e)) from e
        except MashovAuthError as e:
            coordinator.data_stale = True
            _async_show_auth_notification(hass, entry, e, getattr(client, "login_page_url", None))
            if coordinator.data:
                _LOGGER.warning("Mashov authentication failed for %s; keeping cached data", entry.title)
            else:
                # Do not retry bad credentials in a loop; the user must update them.
                _LOGGER.error("Failed to perform startup refresh: %s", e)
                await client.async_close()
                raise ConfigEntryError(str(e)) from e
        except Exception as e:
            coordinator.data_stale = True
            # Notify when setup is about to fail (no cache) or for an internal error, but
            # at most once per internal error streak (the flag is reset on success).
            # Transient failures with a cache stay silent here; the coordinator's
            # third-consecutive-failure rule handles them later.
            if (not coordinator.data or is_internal_error(e)) and not coordinator._internal_error_notified:
                _async_show_error_notification(hass, entry, "Mashov startup refresh failed", e)
                coordinator._internal_error_notified = is_internal_error(e)
            if coordinator.data:
                # Scheduled/polled refreshes will retry; keep serving the cache meanwhile.
                _LOGGER.warning("Startup refresh failed for %s; keeping cached data: %s", entry.title, e)
            else:
                _LOGGER.error("Failed to perform startup refresh: %s", e)
                await client.async_close()
                if isinstance(e, ConfigEntryNotReady):
                    raise
                # Transient (network/server) failure: let Home Assistant retry the setup.
                raise ConfigEntryNotReady(str(e)) from e

    # Configure scheduler per options/YAML (also ensures timers; interval mode sets polling)
    await _async_setup_scheduler(hass, entry)

    # Reconfigure when options change
    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        """Reload only when the client must be rebuilt; otherwise just reschedule.

        Anything baked into MashovClient (year, credentials, extra resources,
        homework window, API base) needs a full reload. Schedule-only changes (and
        attribute limits, read live by sensors) are applied without a reload.
        Title/data updates made by this module also trigger the listener; they
        compare equal here and only cause a harmless reschedule.
        """
        data = updated_entry.data
        options = updated_entry.options
        credentials_changed = data.get(CONF_USERNAME) != client.username or data.get(CONF_PASSWORD) != client.password
        client_changed = (
            str(configured_school_year(data, options)) != str(client._configured_year)
            or data.get(CONF_USERNAME) != client.username
            or data.get(CONF_PASSWORD) != client.password
            or set(enabled_data(options)) != set(client.enabled_data)
            or bool(options.get(CONF_MAILBOX_FULL_CONTENT, False)) != client.mailbox_full_content
            or options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT) != client.mailbox_limit
            or options.get(CONF_HOMEWORK_DAYS_BACK, DEFAULT_HOMEWORK_DAYS_BACK) != client.homework_days_back
            or options.get(CONF_HOMEWORK_DAYS_FORWARD, DEFAULT_HOMEWORK_DAYS_FORWARD) != client.homework_days_forward
            or (options.get(CONF_API_BASE, DEFAULT_API_BASE).rstrip("/") + "/") != client._api_base
        )
        if client_changed:
            if credentials_changed:
                # A valid old cookie must not bypass newly supplied credentials.
                # Stop scheduled coordinator refreshes first, then clear the cached
                # session so the reloaded client logs in with the new credentials.
                await coordinator.async_shutdown()
                cached_entry = await store.async_load()
                if isinstance(cached_entry, dict):
                    cached_entry["auth"] = {}
                    await store.async_save(cached_entry)
            _LOGGER.info("Configuration/options updated for entry %s requiring reload", updated_entry.title)
            await hass.config_entries.async_reload(updated_entry.entry_id)
            return
        _LOGGER.info("Options updated for entry %s; reconfiguring scheduler", updated_entry.title)
        await _async_setup_scheduler(hass, updated_entry)

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload platforms, cancel schedule timers and close the HTTP session.

    The on-disk cache is kept so the next load (or a reload) starts from it.
    """
    _LOGGER.info("Unloading Mashov integration: %s", entry.title)
    # Check if DOMAIN exists in hass.data (it won't if setup failed or was mocked)
    if DOMAIN not in hass.data:
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
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
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Remove credentials and cached school data when a hub is deleted."""
    # The cache holds session cookies and student data; the entry itself (with the
    # password) is deleted by HA.
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.cache").async_remove()
    hass.data.get(DOMAIN, {}).get("report_logs", {}).pop(entry.entry_id, None)
    _async_clear_issue_notification(hass, entry)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow explicit removal of a departed student, including after a cached startup.

    HA detaches only this config entry and its entities. Recorder history is not
    purged. A student still in the roster would be recreated on the next refresh.

    Rules: the per-school holidays device can never be removed; a student device can
    be removed only if none of its identifiers is in the current roster. The roster
    comes from the coordinator, or from the disk cache when the hub is not loaded.
    Without any roster data removal is refused, to avoid deleting active students.
    """
    identifiers = {value for domain, value in device_entry.identifiers if domain == DOMAIN}
    if not identifiers or any(value.startswith(("holidays_", "mailbox_")) for value in identifiers):
        return False
    coordinator = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {}).get("coordinator")
    data = coordinator.data if coordinator else None
    if data is None:
        cached = await Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.cache").async_load()
        data = (cached or {}).get("data")
    if not isinstance(data, dict) or not isinstance(data.get("students"), list):
        return False
    active = {str(student["id"]) for student in data["students"]}
    return identifiers.isdisjoint(active)


def async_get_options_flow(config_entry: ConfigEntry):
    """Return the options flow (Configure button); imported lazily to keep startup light."""
    with contextlib.suppress(Exception):
        _LOGGER.debug(
            "async_get_options_flow requested (entry_id=%s, title='%s')",
            getattr(config_entry, "entry_id", ""),
            getattr(config_entry, "title", ""),
        )
    from .config_flow import OptionsFlowHandler

    return OptionsFlowHandler(config_entry)


async def _async_setup_scheduler(hass: HomeAssistant, entry: ConfigEntry):
    """Apply merged (YAML-overriding-UI) options and configure polling/timers.

    - interval: coordinator polling only (update_interval), no time triggers
    - daily: polling off, one time trigger per day at schedule_time
    - weekly: polling off, a daily trigger that only refreshes on schedule_days
    Invalid values fall back to defaults instead of failing. Safe to call repeatedly:
    previous triggers are cancelled first.
    """
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
        """Parse an int within [lo, hi], or return default."""
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
        """Normalize "HH:MM" or "HH:MM:SS" to "HH:MM:SS", or return default."""
        try:
            s = str(val)
            parts = s.split(":")
            if len(parts) not in (2, 3):
                raise ValueError
            hh, mm = parts[:2]
            H = _as_int(hh, None, 0, 23)
            M = _as_int(mm, None, 0, 59)
            S = _as_int(parts[2], None, 0, 59) if len(parts) == 3 else 0
            if H is None or M is None or S is None:
                raise ValueError
            return f"{H:02d}:{M:02d}:{S:02d}"
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
        # Fall back to the legacy single-day option (or its default).
        days = [schedule_day_single]
    interval_minutes = _as_int(
        merged.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL), DEFAULT_SCHEDULE_INTERVAL, 5, 1440
    )

    # Rewire coordinator polling vs. timers
    coordinator: MashovCoordinator = data["coordinator"]
    unsubs = []

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
            parts = [int(x) for x in schedule_time.split(":")]
            hh, mm = parts[:2]
            ss = parts[2] if len(parts) > 2 else 0
        except Exception:
            # Unreachable in practice (_as_hhmm already normalized the value); last-resort fallback.
            hh, mm, ss = 2, 30, 0

        if schedule_type == "daily":
            _LOGGER.info("Daily mode: refresh at %02d:%02d", hh, mm)
            unsubs.append(async_track_time_change(hass, _refresh_data, hour=hh, minute=mm, second=ss))

        elif schedule_type == "weekly":
            _LOGGER.info("Weekly mode: days=%s at %02d:%02d", days, hh, mm)

            async def _maybe_refresh_weekly(now=None):
                try:
                    # HA local time; weekday() uses 0=Monday, matching schedule_days.
                    today_idx = dt_util.now().weekday()
                except Exception:
                    today_idx = -1
                if today_idx in days:
                    await _refresh_data(now)
                else:
                    _LOGGER.debug("Weekly mode: skipping refresh (today=%s not in %s)", today_idx, days)

            # Schedule once daily at the specified time; gate by weekday inside the callback
            unsubs.append(async_track_time_change(hass, _maybe_refresh_weekly, hour=hh, minute=mm, second=ss))

    hass.data[DOMAIN][entry.entry_id]["unsub_daily"] = unsubs


class MashovCoordinator(DataUpdateCoordinator):
    """Coordinator for Mashov, supporting dynamic interval changes.

    Stale-data model: on auth / password-change failures the last good data is
    returned (entities stay available, data_stale=True). Other failures raise
    UpdateFailed; HA then keeps the previous data but last_update_success is False,
    which entities also report as stale.
    """

    def __init__(self, hass: HomeAssistant, client: MashovClient, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=f"MashovCoordinator:{entry.title}",
            update_interval=timedelta(hours=24),  # safe default; overridden in interval mode
            config_entry=entry,
        )
        self.client = client
        self.entry = entry
        self.data_stale = False
        self.last_successful_update = None  # epoch seconds; restored from the cache on setup
        # Transient failures notify only on the 3rd in a row (when cached data exists).
        self._consecutive_failures = 0
        # Internal errors notify once per failure streak; reset on the next success.
        self._internal_error_notified = False

    def set_interval_minutes(self, minutes: int | None):
        """Set/clear periodic polling interval.

        The pending refresh is cancelled and only rescheduled when entities already
        listen; otherwise HA schedules it when the first listener subscribes.
        """
        self._async_unsub_refresh()
        if minutes is None:
            self.update_interval = None
            _LOGGER.debug("Coordinator polling disabled; using configured schedule.")
        else:
            self.update_interval = timedelta(minutes=minutes)
            _LOGGER.info("Coordinator update_interval set to %d minutes.", minutes)
            if self._listeners:
                self._schedule_refresh()

    async def _async_update_data(self):
        """Fetch everything, merge cached holidays if needed, persist the cache, notify on failure."""
        _LOGGER.debug("Coordinator update started: %s", self.name)
        try:
            data = await asyncio.create_task(self.client.async_fetch_all())
            # Options may change while a request is in flight. Never reintroduce
            # opted-out data if that old request completes during the reload.
            data = filter_cached_data(data, self.entry.options)
            self.data_stale = False
            self._consecutive_failures = 0
            self._internal_error_notified = False
            previous_update = self.last_successful_update
            self.last_successful_update = time.time()
            # Holidays come from a separate endpoint that may fail on its own. If it
            # failed, keep the previous holidays (fresh or already cached) and flag
            # them as cached, preserving when they were last actually fetched.
            if data.get("holidays_status", "ok") == "ok":
                data["holidays_last_update"] = self.last_successful_update
            elif (
                self.data
                and data.get("holidays_status") != "disabled"
                and "holidays" in self.data
                and (self.data.get("holidays_status", "ok") == "ok" or self.data.get("holidays_cached"))
            ):
                data["holidays"] = self.data["holidays"]
                data["holidays_cached"] = True
                data["holidays_last_update"] = self.data.get("holidays_last_update", previous_update)
            _async_clear_issue_notification(self.hass, self.entry)
            _LOGGER.debug("Coordinator update completed; students=%d", len(data.get("students", [])))
            # Persist cache after every successful data update (interval, daily, or manual refresh)
            try:
                store = Store(self.hass, 1, f"{DOMAIN}.{self.entry.entry_id}.cache")
                await store.async_save(
                    {
                        "last_refresh_ts": time.time(),
                        "data": data,
                        "auth": getattr(self.client, "auth_data", {}),
                    }
                )
            except Exception as e:
                _LOGGER.debug("Failed saving cache after coordinator update: %s", e)
            return data
        # Auth problems need user action, so they notify every time and, with cached
        # data, return it instead of failing (entities stay available, marked stale).
        except MashovPasswordChangeRequiredError as exc:
            self.data_stale = True
            _async_show_password_change_notification(self.hass, self.entry, exc)
            if self.data:
                _LOGGER.warning(
                    "Mashov requires a password change for %s; keeping the last successful data",
                    self.entry.title,
                )
                return self.data
            _LOGGER.error("Authentication error during data update: %s", exc)
            raise UpdateFailed(f"Password change required: {exc}") from exc
        except MashovAuthError as exc:
            self.data_stale = True
            _async_show_auth_notification(
                self.hass,
                self.entry,
                exc,
                getattr(self.client, "login_page_url", None),
            )
            if self.data:
                _LOGGER.warning(
                    "Mashov authentication failed for %s; keeping the last successful data",
                    self.entry.title,
                )
                return self.data
            _LOGGER.error("Authentication error during data update: %s", exc)
            raise UpdateFailed(f"Auth error: {exc}") from exc
        except MashovError as exc:
            # Portal/API errors are usually transient: notify immediately only when
            # there is nothing cached, otherwise on exactly the 3rd consecutive failure
            # (not on every later one) to avoid notification spam.
            self.data_stale = True
            self._consecutive_failures += 1
            if not self.data or self._consecutive_failures == 3:
                _async_show_error_notification(self.hass, self.entry, "Mashov refresh failed", exc)
            _LOGGER.error("Mashov error during data update: %s", exc)
            raise UpdateFailed(f"Mashov error: {exc}") from exc
        except Exception as exc:
            self.data_stale = True
            self._consecutive_failures += 1
            # Internal (programming) errors: notify once with report links.
            # Other unexpected errors (network, timeouts): same rule as MashovError.
            reportable = is_internal_error(exc)
            if (reportable and not self._internal_error_notified) or (
                not reportable and (not self.data or self._consecutive_failures == 3)
            ):
                _async_show_error_notification(self.hass, self.entry, "Mashov refresh failed", exc)
                self._internal_error_notified |= reportable
            _LOGGER.error("Unexpected error during data update: %s", exc)
            raise UpdateFailed(f"Unexpected error: {exc}") from exc
