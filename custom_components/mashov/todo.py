"""Per-student homework checklists; completion is local and never sent to Mashov."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN
from .data_selection import enabled_data
from .entity import MashovStudentEntity, sync_selected_entities
from .holidays_utils import parse_iso_date_to_date

PARALLEL_UPDATES = 0


class HomeworkCompletionStore:
    """Serialize writes across children so simultaneous checkboxes cannot lose data."""

    def __init__(self, hass, entry_id):
        self.store = Store(hass, 1, f"mashov.{entry_id}.homework_completion")
        self.completed = {}
        self.lock = asyncio.Lock()

    async def load(self):
        self.completed = (await self.store.async_load() or {}).get("students", {})

    async def update(self, student_id, uid, completed):
        async with self.lock:
            students = {key: list(value) for key, value in self.completed.items()}
            markers = set(students.get(student_id, []))
            if completed:
                markers.add(uid)
            else:
                markers.discard(uid)
            students[student_id] = sorted(markers)
            await self.store.async_save({"students": students})
            self.completed = students


def homework_uid(item, year):
    """Stable across ordering/refresh; changed assignment text reopens the task."""
    identity = [
        year,
        *(item.get(key) for key in ("lesson_id", "group_id", "lesson_date", "lesson", "subject_name", "homework")),
    ]
    return sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def async_setup_entry(hass, entry, async_add_entities):
    """Discover checklists without issuing additional portal requests."""
    sync_selected_entities(hass, entry)
    if "homework" not in enabled_data(entry.options):
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    completion = HomeworkCompletionStore(hass, entry.entry_id)
    await completion.load()
    known = set()

    @callback
    def discover():
        entities = []
        for student in (coordinator.data or {}).get("students", []):
            if student["id"] not in known:
                known.add(student["id"])
                entities.append(MashovHomeworkTodo(coordinator, entry.entry_id, student, completion))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class MashovHomeworkTodo(MashovStudentEntity, TodoListEntity):
    """A child's assignments, with independent durable completion markers."""

    _attr_translation_key = "homework_checklist"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM
    _attr_icon = "mdi:clipboard-check-outline"
    _data_key = "homework"

    def __init__(self, coordinator, entry_id, student, completion):
        super().__init__(coordinator)
        self._student_id = student["id"]
        self._student_name = student["name"]
        self._slug = student["slug"]
        self._year = student.get("year")
        self._attr_unique_id = f"mashov_{entry_id}_{self._student_id}_checklist_homework"
        self._completion = completion
        self._lock = asyncio.Lock()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._student_id))},
            "name": f"Mashov – {self.student_name}",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }

    @property
    def todo_items(self):
        data = self.coordinator.data or {}
        student = next((s for s in data.get("students", []) if s["id"] == self._student_id), {})
        resource = data.get("by_slug", {}).get(student.get("slug", self._slug), {})
        if resource.get("source_status", {}).get("homework", "ok") != "ok":
            return None
        items = {}
        for item in resource.get("homework", []):
            text = (item.get("homework") or "").strip()
            if not text:
                continue
            uid = homework_uid(item, student.get("year", self._year))
            subject = item.get("subject_name") or ""
            items[uid] = TodoItem(
                uid=uid,
                summary=f"{subject}: {text}" if subject else text,
                status=TodoItemStatus.COMPLETED
                if uid in self._completion.completed.get(self._student_id, [])
                else TodoItemStatus.NEEDS_ACTION,
                description=" · ".join(
                    filter(None, [str(parse_iso_date_to_date(item.get("lesson_date")) or ""), item.get("remark")])
                ),
            )
        return sorted(items.values(), key=lambda item: (str(item.due or ""), item.summary))

    @property
    def extra_state_attributes(self):
        return {"student_id": self._student_id, "student_name": self.student_name, "data_stale": self.data_stale}

    async def async_update_todo_item(self, item):
        """Only completion may change; reject assignment edits rather than losing them."""
        async with self._lock:
            current = next((task for task in self.todo_items or [] if task.uid == item.uid), None)
            if current is None:
                raise HomeAssistantError("Homework assignment is no longer available")
            if (item.summary, item.due, item.description) != (current.summary, current.due, current.description):
                raise HomeAssistantError("Mashov assignments are read-only; only completion can be changed")
            if item.status not in (TodoItemStatus.COMPLETED, TodoItemStatus.NEEDS_ACTION):
                raise HomeAssistantError("Invalid homework completion status")
            await self._completion.update(self._student_id, item.uid, item.status == TodoItemStatus.COMPLETED)
            self.async_write_ha_state()
