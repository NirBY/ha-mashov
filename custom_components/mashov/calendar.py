"""Holidays calendar for a Mashov config entry.

Exposes the school's holiday/vacation list (fetched by the coordinator) as
all-day calendar events. One calendar per config entry, attached to the shared
per-school holidays device.

Portal holidays have an inclusive end date, while Home Assistant all-day events
use an exclusive end date, so every event's end is shifted by one day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)
from .entity import MashovEntity
from .holidays_utils import (
    HOLIDAY_DEFAULT_NAME,
    HOLIDAY_ICON,
    create_holidays_device_info,
    parse_iso_date_to_date,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Mashov calendar entities."""
    _LOGGER.debug("Setting up calendar for entry: %s", entry.title)
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data["coordinator"]

    entities = [MashovHolidaysCalendar(coord, entry.entry_id)]

    _LOGGER.info("Adding %d Mashov calendar entities", len(entities))
    async_add_entities(entities)


class MashovHolidaysCalendar(MashovEntity, CalendarEntity):
    """Calendar entity for Mashov holidays."""

    _attr_icon = HOLIDAY_ICON

    def __init__(self, coordinator, entry_id: str):
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_translation_key = "holidays"
        self._attr_unique_id = f"mashov_{entry_id}_holidays_calendar"

    @property
    def extra_state_attributes(self):
        """Expose the holidays fetch status; stale if the refresh or that fetch failed."""
        data = self.coordinator.data or {}
        return {
            "source_status": data.get("holidays_status", "ok"),
            "data_stale": self.data_stale or data.get("holidays_status", "ok") != "ok",
        }

    @property
    def event(self) -> CalendarEvent | None:
        """Return the holiday in progress, otherwise the nearest upcoming one.

        A holiday in progress is returned immediately; for future ones the
        earliest start wins regardless of the order the portal lists them in.
        """
        data = self.coordinator.data or {}
        items = data.get("holidays") or []

        now = dt_util.now()
        # (start_dt, start_date, end_date, name) of the earliest future holiday seen so far.
        current_or_next = None

        for holiday in items:
            start_str = holiday.get("start")
            end_str = holiday.get("end")
            name = holiday.get("name") or HOLIDAY_DEFAULT_NAME

            if not start_str or not end_str:
                continue

            try:
                start_date = parse_iso_date_to_date(start_str)
                end_date = parse_iso_date_to_date(end_str)

                if not start_date or not end_date:
                    continue

                # Local-midnight bounds; end_dt is midnight after the last holiday day (exclusive).
                start_dt = dt_util.start_of_local_day(datetime.combine(start_date, datetime.min.time()))
                end_dt = dt_util.start_of_local_day(datetime.combine(end_date, datetime.min.time())) + timedelta(days=1)

                if start_dt <= now < end_dt:
                    # Passing dates (not datetimes) makes HA treat these as all-day events.
                    return CalendarEvent(
                        start=start_date,
                        end=end_date + timedelta(days=1),
                        summary=name,
                    )

                if start_dt > now and (current_or_next is None or start_dt < current_or_next[0]):
                    current_or_next = (start_dt, start_date, end_date, name)

            except Exception as e:
                _LOGGER.debug("Error parsing holiday event: %s", e)
                continue

        if current_or_next:
            _, start_date, end_date, name = current_or_next
            return CalendarEvent(
                start=start_date,
                end=end_date + timedelta(days=1),
                summary=name,
            )

        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return holidays overlapping the requested range, sorted by start date.

        A holiday is included when any part of it falls inside [start_date, end_date),
        so multi-day vacations that began before the visible range still show up.
        """
        data = self.coordinator.data or {}
        items = data.get("holidays") or []

        events = []

        for holiday in items:
            start_str = holiday.get("start")
            end_str = holiday.get("end")
            name = holiday.get("name") or HOLIDAY_DEFAULT_NAME

            if not start_str or not end_str:
                continue

            try:
                h_start = parse_iso_date_to_date(start_str)
                h_end = parse_iso_date_to_date(end_str)

                if not h_start or not h_end:
                    continue

                h_start_dt = dt_util.start_of_local_day(datetime.combine(h_start, datetime.min.time()))
                h_end_dt = dt_util.start_of_local_day(datetime.combine(h_end, datetime.min.time())) + timedelta(days=1)

                # Standard interval-overlap test on half-open ranges.
                if h_end_dt > start_date and h_start_dt < end_date:
                    events.append(
                        CalendarEvent(
                            start=h_start,
                            end=h_end + timedelta(days=1),
                            summary=name,
                        )
                    )

            except Exception as e:
                _LOGGER.debug("Error parsing holiday for range query: %s", e)
                continue

        events.sort(key=lambda e: (e.start, e.summary))
        return events

    @property
    def device_info(self):
        """Attach to the per-entry holidays device, named after the school (entry title)."""
        return create_holidays_device_info(
            DOMAIN,
            self._entry_id,
            DEVICE_MANUFACTURER,
            DEVICE_MODEL,
            getattr(getattr(self.coordinator, "entry", None), "title", ""),
        )
