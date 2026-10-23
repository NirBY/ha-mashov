"""Checklist isolation, durable markers, changing content and source failures."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.components.todo import TodoItemStatus
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.mashov.todo import HomeworkCompletionStore, MashovHomeworkTodo


def make_entity(hass, completion, sid="one"):
    student = {"id": sid, "name": sid, "slug": sid, "year": 2026}
    item = {"lesson_id": 42, "lesson_date": "2026-10-23", "subject_name": "Math", "homework": "Page 8"}
    coordinator = SimpleNamespace(hass=hass, data={"students": [student], "by_slug": {sid: {"homework": [item]}}})
    entity = MashovHomeworkTodo(coordinator, "account", student, completion)
    entity.async_write_ha_state = lambda: None
    return entity, item


async def test_persist_isolate_and_reopen_changed_homework(hass):
    completion = HomeworkCompletionStore(hass, "account")
    completion.store.async_save = AsyncMock()
    first, raw = make_entity(hass, completion)
    second, _ = make_entity(hass, completion, "two")
    task = first.todo_items[0]
    await first.async_update_todo_item(replace(task, status=TodoItemStatus.COMPLETED))
    assert first.todo_items[0].status == TodoItemStatus.COMPLETED
    assert second.todo_items[0].status == TodoItemStatus.NEEDS_ACTION
    saved = completion.store.async_save.call_args.args[0]
    restored = HomeworkCompletionStore(hass, "account")
    restored.store.async_load = AsyncMock(return_value=saved)
    await restored.load()
    restarted, _ = make_entity(hass, restored)
    assert restarted.todo_items[0].status == TodoItemStatus.COMPLETED
    raw["homework"] = "Page 9"
    assert first.todo_items[0].status == TodoItemStatus.NEEDS_ACTION
    # Portal lesson date is not promised to be a submission deadline.
    assert task.due is None


async def test_duplicate_order_status_and_read_only(hass):
    completion = HomeworkCompletionStore(hass, "account")
    completion.store.async_save = AsyncMock()
    entity, item = make_entity(hass, completion)
    resource = entity.coordinator.data["by_slug"]["one"]
    resource["homework"].extend([dict(item), {"homework": " "}])
    assert len(entity.todo_items) == 1
    with pytest.raises(HomeAssistantError, match="read-only"):
        await entity.async_update_todo_item(replace(entity.todo_items[0], summary="changed"))
    resource["source_status"] = {"homework": "error"}
    assert entity.todo_items is None


async def test_failed_save_does_not_claim_completion(hass):
    completion = HomeworkCompletionStore(hass, "account")
    completion.store.async_save = AsyncMock(side_effect=OSError("disk error"))
    entity, _ = make_entity(hass, completion)
    with pytest.raises(OSError):
        await entity.async_update_todo_item(replace(entity.todo_items[0], status=TodoItemStatus.COMPLETED))
    assert entity.todo_items[0].status == TodoItemStatus.NEEDS_ACTION


async def test_platform_setup_and_service(hass, mock_config_entry, mock_mashov_client):
    mock_config_entry.add_to_hass(hass)
    mock_mashov_client.async_fetch_all.return_value["by_slug"]["student-123"]["homework"] = [
        {"lesson_id": 1, "homework": "Read", "subject_name": "English"}
    ]
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    lists = hass.states.async_all("todo")
    assert len(lists) == 1
    assert lists[0].state == "1"
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": lists[0].entity_id, "item": "English: Read", "status": "completed"},
        blocking=True,
    )
    assert hass.states.get(lists[0].entity_id).state == "0"


async def test_no_checklist_when_homework_deselected(hass, mock_config_entry, mock_mashov_client):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["timetable"]})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.states.async_all("todo")
