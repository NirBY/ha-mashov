"""Mailbox attachments: opt-in gating, safe storage, size cap, statuses and retention.

No network: downloads are fakes or mocked aiohttp responses. File-system effects
are confined to pytest's tmp_path, which stands in for Home Assistant's media folder.
"""

from copy import deepcopy
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import llm
from homeassistant.helpers.json import json_bytes
import pytest
import voluptuous as vol

import custom_components.mashov as integration
from custom_components.mashov.const import DOMAIN
from custom_components.mashov.data_selection import (
    filter_cached_data,
    mailbox_option_errors,
    merge_selection_options,
)
from custom_components.mashov.llm_api import MashovReadTool
from custom_components.mashov.mail_attachments import (
    FALLBACK_NAME,
    MAX_NAME_LENGTH,
    AttachmentStore,
    _remove_tree,
    async_clear_entry_media,
    safe_file_name,
)
from custom_components.mashov.mailbox import fetch_mailbox
from custom_components.mashov.mashov_client import MashovClient
from custom_components.mashov.sensor import MashovMailboxSensor

from .const import (
    TEST_CONVERSATION_ID,
    TEST_ENTRY_ID,
    TEST_FILE_BYTES,
    TEST_FILE_CONTENT_TYPE,
    TEST_FILE_ID,
    TEST_FILE_NAME,
    TEST_MESSAGE_ID,
    TEST_OTHER_CONVERSATION_ID,
)
from .test_llm_api import setup_api, unwrap
from .test_setup_resilience import DATA, _patch_cache, _patch_client


def _attachment():
    return {"fileId": TEST_FILE_ID, "fileName": TEST_FILE_NAME}


def _getter(files):
    """Account JSON fake: one unread conversation whose detail lists ``files``."""
    message = {"messageId": TEST_MESSAGE_ID, "subject": "Subject", "isNew": True}

    async def get(path, key, expected):
        if key == "mail_counts":
            return "ok", {"unreadConversations": 1, "inboxConversations": 1}
        if key == "mailbox":
            return "ok", [{"conversationId": TEST_CONVERSATION_ID, "hasAttachments": True, "messages": [message]}]
        detail = {**message, "body": "<p>Body</p>", "files": deepcopy(files)}
        return "ok", {"conversationId": TEST_CONVERSATION_ID, "messages": [detail]}

    return AsyncMock(side_effect=get)


def _mailbox(*conversation_ids, status="ok"):
    """A fetched mailbox whose conversations each carry one attachment."""
    return {
        "status": status,
        "items": [
            {
                "conversationId": conversation_id,
                "content_status": "ok",
                "messages": [{"messageId": TEST_MESSAGE_ID, "attachments": [_attachment()]}],
            }
            for conversation_id in conversation_ids or (TEST_CONVERSATION_ID,)
        ],
    }


def _download(status="ok", chunks=(TEST_FILE_BYTES,)):
    """Fake client download: writes ``chunks`` and returns ``status``."""

    async def download(path, max_bytes, write):
        for chunk in chunks:
            await write(chunk)
        return status, TEST_FILE_CONTENT_TYPE if status == "ok" else None

    return AsyncMock(side_effect=download)


def _stream_response(status=200, chunks=(TEST_FILE_BYTES,), content_length=None):
    """aiohttp-like context manager streaming ``chunks``."""

    async def iter_any():
        for chunk in chunks:
            yield chunk

    response = MagicMock(status=status, headers={"Content-Type": TEST_FILE_CONTENT_TYPE}, content_length=content_length)
    response.content.iter_any = iter_any
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@pytest.fixture(name="media")
def media_fixture(hass, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path)}
    return tmp_path


def _stored_files(media):
    return sorted(path for path in media.rglob("*") if path.is_file())


def _first(mailbox):
    return mailbox["items"][0]["messages"][0]["attachments"][0]


# --- Parsing ---


async def test_detail_files_are_parsed_defensively():
    files = [
        _attachment(),
        {},
        "not a dict",
        {"fileId": True, "fileName": "flag.png"},
        {"fileId": 7, "fileName": ""},
        {"fileId": None, "fileName": "missing.png"},
        {"fileId": 8, "fileName": "דף עבודה.pdf"},
    ]
    result = await fetch_mailbox(_getter(files), full_content=True, attachments=True)
    item = result["items"][0]
    assert item["content_status"] == "ok"
    assert item["messages"][0]["attachments"] == [_attachment(), {"fileId": "8", "fileName": "דף עבודה.pdf"}]


@pytest.mark.parametrize("files", [None, "bad", {"fileId": 1}])
async def test_malformed_files_field_keeps_the_conversation(files):
    result = await fetch_mailbox(_getter(files), full_content=True, attachments=True)
    assert result["status"] == "ok"
    assert result["items"][0]["content_status"] == "ok"
    assert result["items"][0]["messages"][0]["attachments"] == []


async def test_attachment_metadata_needs_its_own_opt_in():
    result = await fetch_mailbox(_getter([_attachment()]), full_content=True)
    assert "attachments" not in result["items"][0]["messages"][0]


async def test_full_content_off_never_requests_details():
    get = _getter([_attachment()])
    result = await fetch_mailbox(get, attachments=True)
    assert "attachments" not in result["items"][0]["messages"][0]
    assert [call.args[1] for call in get.await_args_list] == ["mail_counts", "mailbox"]


# --- Option dependencies ---


@pytest.mark.parametrize(
    "submitted,current,errors",
    [
        (
            {"enabled_data": ["mailbox"], "mailbox_attachments": True},
            {},
            {"mailbox_attachments": "full_content_required"},
        ),
        (
            {"mailbox_attachments": True},
            {"enabled_data": ["homework"], "mailbox_full_content": False},
            {"mailbox_attachments": "full_content_required"},
        ),
        ({"enabled_data": ["mailbox"], "mailbox_full_content": True, "mailbox_attachments": True}, {}, {}),
        ({"mailbox_attachments": True}, {"enabled_data": ["mailbox"], "mailbox_full_content": True}, {}),
    ],
)
def test_attachments_require_mailbox_and_full_content(submitted, current, errors):
    assert mailbox_option_errors(submitted, current)[1] == errors


def test_removing_a_prerequisite_resets_attachments():
    current = {"enabled_data": ["mailbox"], "mailbox_full_content": True, "mailbox_attachments": True}
    for change in ({"mailbox_full_content": False}, {"enabled_data": ["homework"]}):
        assert merge_selection_options(current, change)["mailbox_attachments"] is False
        submitted, errors = mailbox_option_errors({**current, **change}, current, reset_removed=True)
        assert errors == {}
        assert submitted["mailbox_attachments"] is False


async def test_options_flow_rejects_attachments_without_full_content(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["mailbox"]})
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"enabled_data": ["mailbox"], "mailbox_full_content": False, "mailbox_attachments": True}
    )
    assert result["errors"]["data"]["mailbox_attachments"] == "full_content_required"
    assert not mock_config_entry.options.get("mailbox_attachments")


async def test_options_flow_turning_off_full_content_resets_attachments(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    options = {"enabled_data": ["mailbox"], "mailbox_full_content": True, "mailbox_attachments": True}
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**options, "mailbox_full_content": False}
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.options["mailbox_attachments"] is False


async def test_initial_flow_rejects_attachments_without_full_content(hass):
    with patch("custom_components.mashov.config_flow.ConfigFlow._load_schools_catalog", return_value=[]):
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "username": "test",
                "password": "test",
                "school_name": "123",
                "enabled_data": ["mailbox"],
                "mailbox_attachments": True,
            },
        )
    assert result["errors"]["data"]["mailbox_attachments"] == "full_content_required"


async def test_set_options_validates_attachment_dependency_and_size(hass, mock_config_entry):
    from custom_components.mashov import async_setup

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={"enabled_data": ["mailbox"]})
    await async_setup(hass, {})
    target = {"entry_id": mock_config_entry.entry_id}
    with pytest.raises(ServiceValidationError, match="full content"):
        await hass.services.async_call(DOMAIN, "set_options", {**target, "mailbox_attachments": True}, blocking=True)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_options", {**target, "mailbox_attachment_max_mb": 101}, blocking=True
        )
    enable = {"mailbox_full_content": True, "mailbox_attachments": True, "mailbox_attachment_max_mb": 5}
    await hass.services.async_call(DOMAIN, "set_options", {**target, **enable}, blocking=True)
    assert mock_config_entry.options["mailbox_attachments"] is True
    assert mock_config_entry.options["mailbox_attachment_max_mb"] == 5
    await hass.services.async_call(DOMAIN, "set_options", {**target, "mailbox_full_content": False}, blocking=True)
    assert mock_config_entry.options["mailbox_attachments"] is False


def test_cache_drops_attachment_metadata_without_consent():
    data = {"enabled_data": ["mailbox"], "mailbox_attachments": True, "mailbox": _mailbox()}
    options = {"enabled_data": ["mailbox"], "mailbox_full_content": True, "mailbox_attachments": True}
    assert _first(filter_cached_data(data, options)["mailbox"]) == _attachment()
    for revoked in ({"mailbox_attachments": False}, {"mailbox_full_content": False}):
        filtered = filter_cached_data(data, {**options, **revoked})
        assert "attachments" not in filtered["mailbox"]["items"][0]["messages"][0]
        assert filtered["mailbox_attachments"] is False


# --- Name sanitization ---


@pytest.mark.parametrize(
    "name,expected",
    [
        ("../../etc/passwd", "_._etc_passwd"),
        ("..", FALLBACK_NAME),
        ("", FALLBACK_NAME),
        (".hidden.txt", "hidden.txt"),
        ("a\\b/c\x00d\n.pdf", "a_b_c_d_.pdf"),
        ("סיכום שיעור.docx", "סיכום שיעור.docx"),
    ],
)
def test_file_names_are_single_safe_components(name, expected):
    assert safe_file_name(name) == expected


def test_long_names_are_bounded_and_keep_the_extension():
    name = safe_file_name("א" * (MAX_NAME_LENGTH * 3) + ".jpeg")
    assert len(name) == MAX_NAME_LENGTH
    assert name.endswith(".jpeg")


# --- Storage ---


async def test_download_writes_file_and_exposes_media_metadata(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    download = _download()
    mailbox = _mailbox()
    await store.async_sync(mailbox, download)
    stored = (
        media / "mashov" / TEST_ENTRY_ID / TEST_CONVERSATION_ID / TEST_MESSAGE_ID / f"{TEST_FILE_ID}-{TEST_FILE_NAME}"
    )
    assert _stored_files(media) == [stored]
    assert stored.read_bytes() == TEST_FILE_BYTES
    assert _first(mailbox) == {
        **_attachment(),
        "mime_type": "image/png",
        "size": len(TEST_FILE_BYTES),
        "status": "ok",
        "media_content_id": "media-source://media_source/local/" + stored.relative_to(media).as_posix(),
    }
    path = download.await_args.args[0]
    assert path.startswith(f"mail/messages/{TEST_MESSAGE_ID}/files/{TEST_FILE_ID}/download/")
    assert " " not in path and "/" not in path.rsplit("/", 1)[1]


async def test_existing_file_is_not_downloaded_again(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    await store.async_sync(_mailbox(), _download())
    download = _download()
    mailbox = _mailbox()
    await store.async_sync(mailbox, download)
    download.assert_not_awaited()
    assert _first(mailbox)["status"] == "ok"
    assert _first(mailbox)["size"] == len(TEST_FILE_BYTES)
    assert _first(mailbox)["mime_type"] == "image/png"


@pytest.mark.parametrize("status", ["too_large", "http_401", "http_403", "http_500", "error"])
async def test_failed_download_leaves_no_file_and_a_status(hass, media, status):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    mailbox = _mailbox()
    await store.async_sync(mailbox, _download(status))
    assert _stored_files(media) == []
    assert _first(mailbox)["status"] == status
    assert _first(mailbox)["media_content_id"] is None


async def test_unexpected_error_is_scoped_to_one_attachment(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    mailbox = _mailbox()
    await store.async_sync(mailbox, AsyncMock(side_effect=OSError("disk full")))
    assert _first(mailbox)["status"] == "error"
    assert _stored_files(media) == []


async def test_unsafe_message_id_is_never_used_as_a_path(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    mailbox = _mailbox()
    mailbox["items"][0]["messages"][0]["messageId"] = "../../escape"
    download = _download()
    await store.async_sync(mailbox, download)
    download.assert_not_awaited()
    assert _first(mailbox)["status"] == "error"
    assert _stored_files(media) == []


# --- Retention ---


async def test_retention_removes_conversations_outside_the_window(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    await store.async_sync(_mailbox(TEST_CONVERSATION_ID, TEST_OTHER_CONVERSATION_ID), _download())
    await store.async_sync(_mailbox(TEST_CONVERSATION_ID, status="invalid_response"), _download())
    assert (store.root / TEST_OTHER_CONVERSATION_ID).is_dir()
    await store.async_sync(_mailbox(TEST_CONVERSATION_ID), _download())
    assert not (store.root / TEST_OTHER_CONVERSATION_ID).exists()
    assert (store.root / TEST_CONVERSATION_ID).is_dir()


async def test_cleanup_never_escapes_the_entry_folder(hass, media, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "keep.txt").write_bytes(TEST_FILE_BYTES)
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    store.root.mkdir(parents=True)
    os.symlink(outside, store.root / TEST_OTHER_CONVERSATION_ID)
    await store.async_sync(_mailbox(TEST_CONVERSATION_ID), _download())
    _remove_tree(outside, store.root)
    _remove_tree(store.root, store.root)
    assert (outside / "keep.txt").read_bytes() == TEST_FILE_BYTES
    assert store.root.is_dir()


async def test_clearing_one_hub_keeps_other_hubs(hass, media):
    for entry_id in (TEST_ENTRY_ID, "other"):
        await AttachmentStore(hass, entry_id, len(TEST_FILE_BYTES)).async_sync(_mailbox(), _download())
    await async_clear_entry_media(hass, TEST_ENTRY_ID)
    assert not (media / "mashov" / TEST_ENTRY_ID).exists()
    assert (media / "mashov" / "other").is_dir()


async def test_removing_the_entry_deletes_its_files(hass, media, mock_config_entry):
    from custom_components.mashov import async_remove_entry

    await AttachmentStore(hass, mock_config_entry.entry_id, len(TEST_FILE_BYTES)).async_sync(_mailbox(), _download())
    await async_remove_entry(hass, mock_config_entry)
    assert _stored_files(media) == []


@pytest.mark.parametrize("enabled", [False, True])
async def test_setup_builds_store_only_when_enabled_and_clears_otherwise(hass, media, mock_config_entry, enabled):
    mock_config_entry.add_to_hass(hass)
    options = {"enabled_data": ["mailbox"], "mailbox_full_content": True, "mailbox_attachments": enabled}
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    await AttachmentStore(hass, mock_config_entry.entry_id, len(TEST_FILE_BYTES)).async_sync(_mailbox(), _download())
    patcher, _client = _patch_client()
    try:
        with _patch_cache({"data": deepcopy(DATA)}):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        store = integration.MashovClient.call_args.kwargs["attachment_store"]
        assert bool(_stored_files(media)) is enabled
        assert (store.max_bytes if store else None) == (25 * 1024 * 1024 if enabled else None)
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()


# --- Client download and gating ---


def _client(**kwargs):
    client = MashovClient("123", 2027, "test", "test", enabled_data=["mailbox"], **kwargs)
    client._students = [{"id": "a", "slug": "a", "name": "A"}]
    client._headers = {"X-Csrf-Token": "synthetic"}
    client._session = MagicMock(closed=False)
    client._ensure_valid_session = AsyncMock()
    return client


@pytest.mark.parametrize(
    "response,expected",
    [
        (_stream_response(content_length=len(TEST_FILE_BYTES) + 1), "too_large"),
        (_stream_response(chunks=(TEST_FILE_BYTES, b"x")), "too_large"),
        (_stream_response(status=401), "http_401"),
        (_stream_response(status=403), "http_403"),
        (_stream_response(status=404), "http_404"),
    ],
)
async def test_client_download_statuses_never_relogin(response, expected):
    client = _client()
    client._session.get.return_value = response
    write = AsyncMock()
    assert await client._download_account_file("path", len(TEST_FILE_BYTES), write) == (expected, None)
    if expected == "too_large" and response.__aenter__.return_value.content_length:
        write.assert_not_awaited()
    client._ensure_valid_session.assert_not_awaited()
    assert client._resource_retry_after == {}


async def test_client_download_network_error_is_a_file_status():
    client = _client()
    client._session.get.side_effect = aiohttp.ClientError()
    assert await client._download_account_file("path", 1, AsyncMock()) == ("error", None)


async def test_client_streams_attachment_into_store(hass, media):
    store = AttachmentStore(hass, TEST_ENTRY_ID, len(TEST_FILE_BYTES))
    client = _client(mailbox_full_content=True, attachment_store=store)
    client._fetch_account_json = _getter([_attachment()])
    client._session.get.return_value = _stream_response(chunks=(TEST_FILE_BYTES[:3], TEST_FILE_BYTES[3:]))
    result = await client.async_fetch_all()
    assert result["mailbox_attachments"] is True
    assert _first(result["mailbox"])["status"] == "ok"
    assert [path.read_bytes() for path in _stored_files(media)] == [TEST_FILE_BYTES]
    assert client._session.get.call_args.kwargs["headers"] == client._headers


async def test_option_off_means_zero_download_calls():
    client = _client(mailbox_full_content=True)
    client._fetch_account_json = _getter([_attachment()])
    client._download_account_file = AsyncMock()
    result = await client.async_fetch_all()
    client._download_account_file.assert_not_awaited()
    client._session.get.assert_not_called()
    assert "attachments" not in result["mailbox"]["items"][0]["messages"][0]


async def test_full_content_off_means_no_detail_or_download_calls():
    store = MagicMock(async_sync=AsyncMock())
    client = _client(attachment_store=store)
    client._fetch_account_json = _getter([_attachment()])
    result = await client.async_fetch_all()
    assert client.attachment_store is None
    assert result["mailbox_attachments"] is False
    store.async_sync.assert_not_awaited()
    client._session.get.assert_not_called()
    assert [call.args[1] for call in client._fetch_account_json.await_args_list] == ["mail_counts", "mailbox"]


# --- Sensor ---


def _sensor(items):
    data = {"mailbox": {"status": "ok", "counts_status": "ok", "unread_count": 0, "full_content": True, "items": items}}
    coordinator = SimpleNamespace(
        data=data, entry=SimpleNamespace(title="Test", options={}), last_update_success=True, data_stale=False
    )
    return MashovMailboxSensor(coordinator, TEST_ENTRY_ID)


def test_sensor_exposes_attachment_metadata_and_count():
    mailbox = _mailbox()
    _first(mailbox).update(status="ok", mime_type="image/png", size=1, media_content_id="media-source://x")
    attrs = _sensor(mailbox["items"]).extra_state_attributes
    assert attrs["attachment_count"] == 1
    assert _first(attrs)["media_content_id"] == "media-source://x"


def test_sensor_attachment_metadata_respects_the_attribute_budget():
    mailbox = _mailbox()
    message = mailbox["items"][0]["messages"][0]
    message["attachments"] = [{"fileId": str(index), "fileName": "קובץ" * 40} for index in range(200)]
    attrs = _sensor(mailbox["items"]).extra_state_attributes
    assert len(json_bytes(attrs)) <= 14 * 1024
    assert attrs["attachment_count"] == 200
    assert attrs["content_truncated"] is True
    assert attrs["stored_conversations"] == len(attrs["items"])


# --- LLM API ---


async def test_llm_read_exposes_attachment_metadata_only_with_consent(hass):
    entry, coordinator, context = setup_api(hass)
    coordinator.data["mailbox"] = _mailbox()
    tool = MashovReadTool("account")
    request = llm.ToolInput(tool_name=tool.name, tool_args={"dataset": "mailbox"})
    entry.options["mailbox_full_content"] = True
    assert "attachments" not in unwrap(await tool.async_call(hass, request, context))["items"][0]["messages"][0]
    entry.options["mailbox_attachments"] = True
    result = unwrap(await tool.async_call(hass, request, context))
    assert result["items"][0]["messages"][0]["attachments"] == [_attachment()]
