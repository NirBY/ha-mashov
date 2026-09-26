"""Shared cache visibility and student device metadata."""

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class MashovEntity(CoordinatorEntity):
    """Keep last known data visible, explicitly marked stale after a failure."""

    _attr_has_entity_name = True

    @property
    def available(self):
        return bool(self.coordinator.data)

    @property
    def data_stale(self):
        return bool(getattr(self.coordinator, "data_stale", False)) or not self.coordinator.last_update_success


class MashovStudentEntity(MashovEntity):
    @property
    def available(self):
        data = self.coordinator.data or {}
        return super().available and (
            "students" not in data or any(student.get("id") == self._student_id for student in data["students"])
        )

    @property
    def student_name(self):
        return next(
            (
                s.get("name", self._student_name)
                for s in (self.coordinator.data or {}).get("students", [])
                if s.get("id") == self._student_id
            ),
            self._student_name,
        )

    @callback
    def _handle_coordinator_update(self):
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, str(self._student_id))})
        if device and device.name != f"Mashov – {self.student_name}":
            registry.async_update_device(device.id, name=f"Mashov – {self.student_name}")
        super()._handle_coordinator_update()
