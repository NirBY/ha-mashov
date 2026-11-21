"""Opt-in student profile pictures as read-only image entities.

Pictures are downloaded during the refresh that selected "picture" and kept in
memory only (never written to the cache or the recorder).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN
from .data_selection import enabled_data
from .entity import MashovStudentEntity, sync_selected_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Create one picture entity per student, for students who join later too."""
    sync_selected_entities(hass, entry)
    if "picture" not in enabled_data(entry.options):
        return
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known: set[Any] = set()

    @callback
    def sync_students() -> None:
        students = (coord.data or {}).get("students", [])
        # Same rule as the sensors and todo lists: only a freshly verified roster proves a
        # departure. Forget departed students so a returning child gets an entity again.
        if (
            students
            and getattr(coord.client, "roster_refreshed", False) is True
            and not coord.data_stale
            and coord.last_update_success
        ):
            known.intersection_update(stu["id"] for stu in students)
        new = [stu for stu in students if stu["id"] not in known]
        if not new:
            return
        known.update(stu["id"] for stu in new)
        async_add_entities(
            [MashovStudentPicture(coord, stu["id"], stu["slug"], stu["name"], entry.entry_id) for stu in new]
        )

    sync_students()
    entry.async_on_unload(coord.async_add_listener(sync_students))


class MashovStudentPicture(MashovStudentEntity, ImageEntity):
    """A student's Mashov profile picture; unavailable while no picture is held."""

    _attr_translation_key = "picture"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, student_id: Any, slug: str, name: str, entry_id: str) -> None:
        MashovStudentEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        # Keep the roster's own id type for lookups; only identifiers are text.
        self._student_id = student_id
        self._slug = slug
        self._student_name = name
        self._entry_id = entry_id
        self._attr_unique_id = f"mashov_{entry_id}_{student_id}_picture"

    @property
    def _stored(self):
        return self.coordinator.client.pictures.get(self._student_id)

    @property
    def available(self) -> bool:
        """Pictures live in memory only, so the entity is unavailable until one was fetched."""
        return super().available and self._stored is not None

    @property
    def content_type(self) -> str:
        stored = self._stored
        return stored[1] if stored else self._attr_content_type

    @property
    def image_last_updated(self) -> datetime | None:
        stored = self._stored
        return datetime.fromtimestamp(stored[2], tz=UTC) if stored else None

    async def async_image(self) -> bytes | None:
        stored = self._stored
        return stored[0] if stored else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = ((self.coordinator.data or {}).get("picture") or {}).get("by_student", {}).get(self._student_id)
        if status is None:
            status = "not_fetched"
        elif status == "ok" and self._stored is None:
            # The cache never holds pictures, so after a restart an "ok" status is not a picture.
            status = "not_fetched"
        return {
            "student_name": self.student_name,
            "source_status": status,
            "data_stale": self.data_stale or status != "ok",
            **self.schedule_attributes("picture"),
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._student_id))},
            "name": f"Mashov – {self.student_name}",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }
