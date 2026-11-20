"""School-data access must remain scoped, authenticated and consent aware."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
import pytest

from custom_components.mashov.approvals import PARENT_APPROVALS
from custom_components.mashov.data_schedule import SHARED_DATA
from custom_components.mashov.data_selection import DATA_KEYS
from custom_components.mashov.llm_api import MashovCatalogTool, MashovDataAPI, MashovReadTool

from .const import TEST_PENDING_RECORD


def setup_api(hass):
    entry = SimpleNamespace(
        entry_id="account", title="School", options={"mcp_enabled": True, "enabled_data": list(DATA_KEYS)}
    )
    student = {"id": "child", "name": "Child", "slug": "child", "year": 2026}
    coordinator = SimpleNamespace(
        entry=entry,
        data_stale=False,
        last_update_success=True,
        data={
            "students": [student],
            "by_slug": {
                "child": {
                    "source_status": dict.fromkeys(DATA_KEYS, "ok"),
                    **{key: [{"value": 1}] for key in DATA_KEYS if key not in SHARED_DATA},
                }
            },
            "holidays": [{"name": "Holiday"}],
            "holidays_status": "ok",
            "mailbox": {"items": [{"subject": "Hello", "messages": [{"body": "secret"}]}], "status": "ok"},
        },
    )
    hass.data["mashov"] = {"account": {"coordinator": coordinator}}
    context = llm.LLMContext(
        platform="mcp_server", context=Context(user_id="admin"), language="he", assistant="mcp_server", device_id=None
    )
    hass.auth.async_get_user = AsyncMock(return_value=SimpleNamespace(is_admin=True))
    return entry, coordinator, context


def unwrap(result):
    return result.data if hasattr(result, "data") else result


async def test_merged_hubs_have_short_unique_stable_tool_names(hass):
    entry, _, context = setup_api(hass)
    entry.title = "שם בית ספר ארוך מאוד " * 12
    first = MashovDataAPI(hass, entry)
    second_id = "01" + "a" * 24
    second_entry = SimpleNamespace(entry_id=second_id, title=entry.title)
    hass.data["mashov"][second_id] = hass.data["mashov"]["account"]
    second = MashovDataAPI(hass, second_entry)
    merged = await llm.MergedAPI([first, second]).async_get_api_instance(context)
    assert len({tool.name for tool in merged.tools}) == 4
    assert all(len(tool.name) <= 64 and tool.name.isascii() for tool in merged.tools)
    entry.title = "Renamed account"
    assert MashovDataAPI(hass, entry).name == first.name
    assert first.id == "mashov_account"


async def test_optional_resource_timestamp_and_failed_child_scope(hass):
    _, coordinator, context = setup_api(hass)
    group = coordinator.data["by_slug"]["child"]
    group["additional_data"] = {"message_board": {"status": "ok", "items": [{"text": "notice"}]}}
    group["source_last_update"] = {"message_board": 1234567}
    coordinator.failed_datasets = {("child", "message_board")}
    tool = MashovReadTool("account")
    request = llm.ToolInput(tool_name=tool.name, tool_args={"dataset": "message_board", "student_id": "child"})
    result = unwrap(await tool.async_call(hass, request, context))
    assert result["last_update"] == 1234567
    assert result["data_stale"] is True
    coordinator.failed_datasets = {("another_child", "message_board")}
    result = unwrap(await tool.async_call(hass, request, context))
    assert result["data_stale"] is False


@pytest.mark.parametrize("dataset", DATA_KEYS)
async def test_read_all_selected_datasets(hass, dataset):
    _, coordinator, context = setup_api(hass)
    coordinator.data[PARENT_APPROVALS] = {
        "status": "ok",
        "forms_status": {"consent": "ok", "general": "ok"},
        "by_student": {"child": [TEST_PENDING_RECORD]},
    }
    result = unwrap(
        await MashovReadTool("account").async_call(
            hass,
            llm.ToolInput(tool_name="mashov__read", tool_args={"dataset": dataset, "student_id": "child"}),
            context,
        )
    )
    assert result["total"] == 1
    assert result["status"] == "ok"
    assert result["next_offset"] is None


async def test_healthy_parent_approvals_are_not_a_partial_failure(hass):
    """forms_status is a dict of kinds, not the string "ok"."""
    _, coordinator, context = setup_api(hass)
    coordinator.data[PARENT_APPROVALS] = {
        "status": "ok",
        "answers_failures": 0,
        "forms_status": {"consent": "ok", "general": "ok"},
        "by_student": {},
        "last_update": 123456,
    }
    tool = MashovReadTool("account")
    request = llm.ToolInput(tool_name=tool.name, tool_args={"dataset": PARENT_APPROVALS})
    result = unwrap(await tool.async_call(hass, request, context))
    assert result["status"] == "ok"
    assert result["data_stale"] is False

    coordinator.data[PARENT_APPROVALS]["forms_status"] = {"consent": "ok", "general": "http_503"}
    result = unwrap(await tool.async_call(hass, request, context))
    assert result["status"] == "partial_failure"
    assert result["data_stale"] is True


async def test_permission_revocation_wrong_child_and_pagination(hass):
    entry, coordinator, context = setup_api(hass)
    api = await MashovDataAPI(hass, entry).async_get_api_instance(context)
    assert len(api.tools) == 2
    tool = MashovReadTool("account")
    args = {"dataset": "homework", "student_id": "child", "limit": 1}
    coordinator.data["by_slug"]["child"]["homework"] *= 3
    result = unwrap(await tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args=args), context))
    assert result["next_offset"] == 1
    with pytest.raises(HomeAssistantError, match="student_id"):
        await tool.async_call(
            hass, llm.ToolInput(tool_name=tool.name, tool_args={**args, "student_id": "other"}), context
        )
    entry.options["enabled_data"] = []
    with pytest.raises(HomeAssistantError, match="not enabled"):
        await tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args=args), context)
    entry.options["mcp_enabled"] = False
    with pytest.raises(HomeAssistantError, match="disabled"):
        await api.tools[0].async_call(hass, llm.ToolInput(tool_name="mashov__catalog", tool_args={}), context)


async def test_no_anonymous_or_non_admin_access(hass):
    _, _, context = setup_api(hass)
    tool = MashovCatalogTool("account")
    hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
    with pytest.raises(HomeAssistantError, match="administrator"):
        await tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args={}), context)
    context.context = None
    with pytest.raises(HomeAssistantError, match="administrator"):
        await tool.async_call(hass, llm.ToolInput(tool_name=tool.name, tool_args={}), context)


async def test_mailbox_content_consent_and_staleness(hass):
    entry, coordinator, context = setup_api(hass)
    tool = MashovReadTool("account")
    request = llm.ToolInput(tool_name=tool.name, tool_args={"dataset": "mailbox"})
    result = unwrap(await tool.async_call(hass, request, context))
    assert "secret" not in str(result)
    entry.options["mailbox_full_content"] = True
    coordinator.data_stale = True
    result = unwrap(await tool.async_call(hass, request, context))
    assert "secret" in str(result)
    assert result["data_stale"] is True


async def test_api_registration_is_opt_in_and_unloaded(hass, hass_admin_user, mock_config_entry, mock_mashov_client):
    mock_config_entry.add_to_hass(hass)
    api_id = f"mashov_{mock_config_entry.entry_id}"
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert api_id not in {api.id for api in llm.async_get_apis(hass)}

    await hass.services.async_call(
        "mashov",
        "set_options",
        {"entry_id": mock_config_entry.entry_id, "mcp_enabled": True},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert api_id in {api.id for api in llm.async_get_apis(hass)}
    # Unload/retry keeps the API registered so agents that selected it keep working
    # (it offers no tools while the hub is not loaded); removing the hub unregisters it.
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert api_id in {api.id for api in llm.async_get_apis(hass)}
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    assert api_id not in {api.id for api in llm.async_get_apis(hass)}


async def test_mcp_option_is_present_in_grouped_configure_form(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    schema = result["data_schema"]
    advanced = next(value for key, value in schema.schema.items() if str(key) == "advanced")
    assert "mcp_enabled" in {str(key) for key in advanced.schema.schema}
    assert schema({"advanced": {"mcp_enabled": True}})["mcp_enabled"] is True


async def test_unauthorized_session_gets_no_tools_instead_of_an_error(hass):
    """Non-admins, voice satellites (no user) and a disabled API must not break merged Assist sessions."""
    entry, coordinator, context = setup_api(hass)
    hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
    api = await MashovDataAPI(hass, entry).async_get_api_instance(context)
    assert api.tools == []
    assert "not available" in api.api_prompt
    context.context = None
    assert (await MashovDataAPI(hass, entry).async_get_api_instance(context)).tools == []
    hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=True)
    context.context = Context(user_id="admin")
    entry.options["mcp_enabled"] = False
    assert (await MashovDataAPI(hass, entry).async_get_api_instance(context)).tools == []


async def test_set_options_requires_an_administrator(hass, hass_read_only_user, mock_config_entry, mock_mashov_client):
    """A non-admin user cannot redirect api_base (where the stored password is sent)."""
    from homeassistant.exceptions import Unauthorized

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "mashov",
            "set_options",
            {"entry_id": mock_config_entry.entry_id, "api_base": "https://attacker.invalid/"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert "api_base" not in mock_config_entry.options
    # Automations and scripts (no user) keep working.
    await hass.services.async_call(
        "mashov", "set_options", {"entry_id": mock_config_entry.entry_id, "homework_days_back": 3}, blocking=True
    )
    assert mock_config_entry.options["homework_days_back"] == 3
