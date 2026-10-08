"""Shared cache visibility and student device metadata."""

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .data_schedule import CONF_DATA_SCHEDULES, CONF_STUDENT_SCHEDULES, effective_schedule
from .data_selection import DATA_KEYS, enabled_data


@callback
def sync_selected_entities(hass, entry):
    """Disable deselected entities without deleting IDs, customizations or history."""
    selected = set(enabled_data(entry.options))
    registry = er.async_get(hass)
    prefix = f"mashov_{entry.entry_id}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform != DOMAIN or not entity.unique_id.startswith(prefix):
            continue
        tail = entity.unique_id[len(prefix) :]
        key = (
            "holidays"
            if tail == "holidays_calendar"
            else next(
                (key for key in sorted(DATA_KEYS, key=len, reverse=True) if tail == key or tail.endswith(f"_{key}")),
                None,
            )
        )
        if key is None:
            continue
        if key not in selected and entity.disabled_by is None:
            registry.async_update_entity(entity.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
        elif key in selected and entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity.entity_id, disabled_by=None)


class MashovEntity(CoordinatorEntity):
    """Keep last known data visible, explicitly marked stale after a failure."""

    _attr_has_entity_name = True

    @property
    def available(self):
        """Available whenever any data exists (fresh or cached).

        Unlike the CoordinatorEntity default, a failed refresh does not make the
        entity unavailable; staleness is reported via data_stale instead.
        """
        return bool(self.coordinator.data)

    @property
    def data_stale(self):
        """True when the shown data did not come from the latest refresh attempt.

        The coordinator sets data_stale when it keeps serving cached data (e.g. auth
        failure or password change required); last_update_success covers refreshes
        that raised UpdateFailed.
        """
        key = getattr(self, "_data_key", getattr(self, "_key", getattr(self, "_attr_translation_key", None)))
        failed = getattr(self.coordinator, "failed_datasets", None)
        if isinstance(failed, set) and key in DATA_KEYS:
            return key in failed or (getattr(self, "_student_id", None), key) in failed
        return bool(getattr(self.coordinator, "data_stale", False)) or not self.coordinator.last_update_success

    def schedule_attributes(self, key):
        """Expose the effective resource schedule on every kind of sensor."""
        options = dict(getattr(getattr(self.coordinator, "entry", None), "options", {}))
        hass = getattr(self.coordinator, "hass", None)
        if hass is not None:
            options.update(hass.data.get(DOMAIN, {}).get("yaml_options", {}) or {})
        student_id = getattr(self, "_student_id", None)
        schedule = effective_schedule(options, key, student_id)
        student_schedule = options.get(CONF_STUDENT_SCHEDULES, {}).get(student_id, {})
        return {
            "schedule_type": schedule["schedule_type"],
            "schedule_time": schedule["schedule_time"],
            "schedule_days": schedule["schedule_days"],
            "schedule_interval_minutes": schedule["schedule_interval"],
            "schedule_scope": "student_custom"
            if key in student_schedule.get("overrides", {})
            else "student_general"
            if student_schedule.get("general")
            else "custom"
            if key in options.get(CONF_DATA_SCHEDULES, {})
            else "shared",
        }


class MashovStudentEntity(MashovEntity):
    """Base for per-student entities; subclasses set _student_id and _student_name."""

    @property
    def available(self):
        """Unavailable once the student disappears from a loaded roster.

        Data without a "students" key (e.g. partial/legacy payloads) does not
        hide the entity.
        """
        data = self.coordinator.data or {}
        return super().available and (
            "students" not in data or any(student.get("id") == self._student_id for student in data["students"])
        )

    @property
    def student_name(self):
        """Current name from the roster, falling back to the name known at creation."""
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
        """Keep the student's device name in sync with the roster before updating state.

        Only writes to the registry when the name actually changed. A rename made
        in the UI is stored in name_by_user and is therefore preserved.
        """
        registry = dr.async_get(self.hass)
        registered = self.registry_entry
        device = registry.async_get(registered.device_id) if registered and registered.device_id else None
        if device and device.name != f"Mashov – {self.student_name}":
            registry.async_update_device(device.id, name=f"Mashov – {self.student_name}")
        super()._handle_coordinator_update()
