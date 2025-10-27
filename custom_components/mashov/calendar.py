from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
)
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


class MashovHolidaysCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar entity for Mashov holidays."""

    _attr_icon = HOLIDAY_ICON

    def __init__(self, coordinator, entry_id: str):
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = "Mashov Holidays Calendar"
        self._attr_unique_id = f"mashov_{entry_id}_holidays_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        data = self.coordinator.data or {}
        items = data.get("holidays") or []

        now = dt_util.now()
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

                start_dt = dt_util.start_of_local_day(datetime.combine(start_date, datetime.min.time()))
                end_dt = dt_util.start_of_local_day(datetime.combine(end_date, datetime.min.time())) + timedelta(days=1)

                if start_dt <= now < end_dt:
                    return CalendarEvent(
                        start=start_date,
                        end=end_date + timedelta(days=1),
                        summary=name,
                    )

                if start_dt > now and current_or_next is None or start_dt < current_or_next[0]:
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
        """Return calendar events within a datetime range."""
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
        """Return device information."""
        return create_holidays_device_info(DOMAIN, self._entry_id, DEVICE_MANUFACTURER, DEVICE_MODEL)
