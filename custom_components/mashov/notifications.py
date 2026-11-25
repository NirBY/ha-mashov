"""Opt-in refresh when Mashov lists a new notification (read-only polling).

Mashov offers Home Assistant no push channel: its pushes go through the app's own
Firebase project (see docs/mashov-api-reference.md). But every account has a bell list
of its newest notifications at ``GET user/notifications``. With this option, a hub reads
that list every few minutes and refreshes only the data types that new notifications
are about. The regular schedule keeps running, because some data types never produce
a notification (the noticeboard, for example).

The check is a single read: the app and website mark notifications read with a
separate ``PUT user/notifications/...`` when the list is opened, which is never sent
here. Notification text is never logged or stored. Only short one-way digests of the
notifications already seen are kept on disk, so a restart does not refresh the same
data again but still notices what arrived while Home Assistant was down.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import hashlib
import json
import logging

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.helpers.event import async_track_time_interval  # type: ignore
from homeassistant.helpers.storage import Store  # type: ignore

from .const import DOMAIN
from .data_selection import enabled_data
from .mashov_client import MashovAuthError, MashovError, MashovNotificationsUnavailable

_LOGGER = logging.getLogger(__name__)

CONF_NOTIFICATION_REFRESH = "notification_refresh"
CONF_NOTIFICATION_INTERVAL = "notification_interval"
DEFAULT_NOTIFICATION_INTERVAL = 15
MIN_NOTIFICATION_INTERVAL = 5
# Mashov ends a session after about 60 idle minutes; checking at least this often keeps
# it alive, so a hub that opted in rarely needs to log in again.
MAX_NOTIFICATION_INTERVAL = 60
# The newest notifications read per check: the same seven the app's bell list shows.
NOTIFICATION_TAKE = 7
# Digests remembered across checks and restarts (bounded; a check lists at most seven).
SEEN_LIMIT = 50
# The fields that identify a notification. The read state is left out: reading a
# notification in the app must not count as a new one.
_IDENTITY_FIELDS = ("id", "eventType", "eventTime", "addTime", "eventKey", "eventData", "eventText", "eventUserId")
# Mashov also lists generated entries with an id of 0 or less (for example "unread
# conversations", type 16) whose times are those of the request itself. Only their
# content identifies them, so they count as new only when it changes.
_REQUEST_TIME_FIELDS = ("eventTime", "addTime")

# Mashov eventType (from the app's bundle) -> data types such a notification changes.
# Types not listed (general text, staff exports, Bagrut grades, school tests) concern
# nothing this integration fetches.
EVENT_DATA_TYPES: dict[int, tuple[str, ...]] = {
    16: ("mailbox",),  # unread conversations
    101: ("behavior", "daily_behavior", "attendance_counts"),  # attendance or behaviour event
    102: ("homework", "lessons_history"),  # homework
    105: ("outside_behavior",),  # behaviour outside lessons
    106: ("behavior", "daily_behavior", "attendance_counts"),  # entered by the class educator
    111: ("grades",),  # grade
    121: ("follow_up",),  # follow-up note (maakav)
    131: ("parent_approvals",),  # form answer
    141: ("parent_approvals",),  # form answer viewed
    151: ("parent_approvals",),  # school activity (trip) answer
    201: ("parent_approvals",),  # parents' consent answer
    211: ("parent_approvals",),  # parents' consent shared access
    221: ("timetable", "weekly_plan", "lesson_cancellations"),  # timetable change
    231: ("picture",),  # student picture
}
ALL_NOTIFIED_DATA = frozenset(key for keys in EVENT_DATA_TYPES.values() for key in keys)


def notification_interval(options) -> int:
    """Minutes between checks, clamped to the allowed range."""
    try:
        minutes = int(options.get(CONF_NOTIFICATION_INTERVAL, DEFAULT_NOTIFICATION_INTERVAL))
    except (TypeError, ValueError):
        return DEFAULT_NOTIFICATION_INTERVAL
    return max(MIN_NOTIFICATION_INTERVAL, min(MAX_NOTIFICATION_INTERVAL, minutes))


def notification_digest(item: dict) -> str:
    """A short one-way digest of a notification, without its read state."""
    item_id = item.get("id")
    stored = isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0
    fields = _IDENTITY_FIELDS if stored else tuple(f for f in _IDENTITY_FIELDS if f not in _REQUEST_TIME_FIELDS)
    identity = {field: item.get(field) for field in fields}
    raw = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def data_types_for(item: dict) -> set[str]:
    """The data types a notification is about; empty for types the hub does not fetch."""
    try:
        event_type = int(item.get("eventType"))
    except (TypeError, ValueError):
        return set()
    return set(EVENT_DATA_TYPES.get(event_type, ()))


def notifications_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Digests of the notifications a hub has seen; removed with the hub."""
    return Store(hass, 1, f"{DOMAIN}.{entry_id}.notifications")


class NotificationWatcher:
    """Check one hub's bell list and refresh the data types of new notifications.

    The first check for a hub only records what is already listed. A failed check
    changes nothing and is tried again at the next interval. A refused list (the
    account may not read it) stops the checks until the hub reloads, and a rejected
    login pauses them until a refresh succeeds, so they never cause repeated logins.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._store = notifications_store(hass, entry.entry_id)
        self._seen: list[str] | None = None  # None: nothing recorded yet
        self._loaded = False
        self._busy = False
        self._unavailable = False
        self._auth_paused_at: object = None
        self._paused = False

    def async_start(self, options) -> Callable[[], None]:
        """Check every configured interval; returns the unsubscribe for the timer."""
        minutes = notification_interval(options)
        _LOGGER.info("Checking Mashov notifications for %s every %d minutes", self._entry.title, minutes)
        return async_track_time_interval(
            self._hass,
            self.async_check,
            timedelta(minutes=minutes),
            name=f"Mashov notifications {self._entry.entry_id}",
            cancel_on_shutdown=True,
        )

    async def async_check(self, _now=None) -> None:
        """Timer callback: one check at a time, skipped while paused."""
        coordinator = self._coordinator
        if self._busy or self._unavailable or getattr(coordinator, "_stopped", False):
            return
        if getattr(coordinator, "auth_failed", False):
            return  # a refresh was refused for credentials; the user must act first
        if self._paused and coordinator.last_successful_update == self._auth_paused_at:
            return
        self._paused = False
        self._busy = True
        try:
            keys = await self._async_new_data()
            if keys:
                _LOGGER.info(
                    "New Mashov notifications for %s; refreshing %s", self._entry.title, ", ".join(sorted(keys))
                )
                await coordinator.async_refresh_datasets(keys)
        finally:
            self._busy = False

    async def _async_new_data(self) -> set[str]:
        """Read the list once (in the refresh queue); return the data types to refresh."""
        coordinator = self._coordinator
        title = self._entry.title
        # The same queue as refreshes: a check never overlaps a refresh or another hub's login.
        async with coordinator._refresh_slot():
            if coordinator._stopped:
                return set()
            try:
                items = await coordinator.client.async_fetch_notifications(NOTIFICATION_TAKE)
            except MashovNotificationsUnavailable as err:
                self._unavailable = True
                _LOGGER.warning("%s for %s; notification checks are off until the hub reloads", err, title)
                return set()
            except MashovAuthError as err:
                self._paused = True
                self._auth_paused_at = coordinator.last_successful_update
                _LOGGER.warning(
                    "Mashov login failed while checking notifications for %s (%s); "
                    "checks resume after the next successful refresh",
                    title,
                    type(err).__name__,
                )
                return set()
            except MashovError as err:
                _LOGGER.debug("Could not check Mashov notifications for %s: %s", title, err)
                return set()
            except Exception as err:  # keep the timer alive; never log response content
                _LOGGER.warning("Unexpected error while checking Mashov notifications for %s: %r", title, type(err))
                return set()
        return await self._async_compare(items)

    async def _async_compare(self, items: list[dict]) -> set[str]:
        """Record the listed notifications; return the enabled data types new ones concern."""
        if not self._loaded:
            stored = await self._store.async_load()
            seen = stored.get("seen") if isinstance(stored, dict) else None
            self._seen = [str(digest) for digest in seen] if isinstance(seen, list) else None
            self._loaded = True
        digests = [notification_digest(item) for item in items]
        before = self._seen
        new_items = (
            []
            if before is None
            else [item for item, digest in zip(items, digests, strict=True) if digest not in before]
        )
        seen = list(dict.fromkeys(digests + (before or [])))[:SEEN_LIMIT]
        if seen != before:
            self._seen = seen
            await self._store.async_save({"seen": seen})
        _LOGGER.debug(
            "Checked Mashov notifications for %s: %d listed, %d new%s",
            self._entry.title,
            len(items),
            len(new_items),
            " (first check)" if before is None else "",
        )
        if not new_items:
            return set()
        if before and len(items) >= NOTIFICATION_TAKE and len(new_items) == len(items):
            # Everything listed is new, so older notifications may have scrolled past
            # unseen: refresh every data type that notifications can be about.
            keys = set(ALL_NOTIFIED_DATA)
        else:
            keys = set().union(*(data_types_for(item) for item in new_items))
        return keys & set(enabled_data(self._entry.options))
