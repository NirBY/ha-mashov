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
from .entity import MashovStudentEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Create one picture entity per student, for students who join later too."""
    if "picture" not in enabled_data(entry.options):
        return
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known: set[str] = set()

    @callback
    def sync_students() -> None:
        new = [stu for stu in (coord.data or {}).get("students", []) if str(stu["id"]) not in known]
        if not new:
            return
        known.update(str(stu["id"]) for stu in new)
        async_add_entities(
            [MashovStudentPicture(coord, stu["id"], stu["slug"], stu["name"], entry.entry_id) for stu in new]
        )

    sync_students()
    entry.async_on_unload(coord.async_add_listener(sync_students))


class MashovStudentPicture(MashovStudentEntity, ImageEntity):
    """A student's Mashov profile picture; unavailable as an image when Mashov has none."""

    _attr_translation_key = "picture"
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, student_id: Any, slug: str, name: str, entry_id: str) -> None:
        MashovStudentEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._student_id = str(student_id)
        self._slug = slug
        self._student_name = name
        self._entry_id = entry_id
        self._attr_unique_id = f"mashov_{entry_id}_{self._student_id}_picture"

    @property
    def _stored(self):
        return self.coordinator.client.pictures.get(self._student_id)

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
        status = (
            ((self.coordinator.data or {}).get("picture") or {})
            .get("by_student", {})
            .get(self._student_id, "not_fetched")
        )
        return {"student_name": self.student_name, "source_status": status}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._student_id)},
            "name": f"Mashov – {self.student_name}",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }
