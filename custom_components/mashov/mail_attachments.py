"""Opt-in mailbox attachment files under the config folder.

Files live at <config>/mashov_files/<entry_id>/<conversationId>/<messageId>/<fileId>-<name>.
That directory is on the config volume, so it survives a container recreate and is part of
a config backup. Home Assistant's media browser only serves image, audio and video, so
documents are downloaded from an authenticated view instead. Every file operation runs in
the executor, and nothing outside the entry folder is removed.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
import shutil
import unicodedata
from urllib.parse import quote

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

_LOGGER = logging.getLogger(__name__)

STORAGE_FOLDER = "mashov_files"
LEGACY_MEDIA_FOLDER = "mashov"
DOWNLOAD_URL = "/api/mashov/attachment/{entry_id}/{conversation_id}/{message_id}/{file_id}"
# Keeps "<fileId>-<name>.part" well under the 255-byte file-name limit, even
# for Hebrew names (two bytes per letter in UTF-8).
MAX_NAME_LENGTH = 100
FALLBACK_NAME = "attachment"
DEFAULT_MIME_TYPE = "application/octet-stream"
_UNSAFE_CHARACTERS = frozenset('/\\:*?"<>|')
# encodeURIComponent leaves these unescaped; the web client builds the URL with it.
_URI_COMPONENT_SAFE = "!~*'()"
# Home Assistant's media view serves image/video/audio types from the local media folder
# on its own origin. SVG is an image type that can run script there (stored XSS from any
# sender), so it is stored inert with a .txt suffix: kept on disk, never served as an image.
ACTIVE_MIME_TYPES = frozenset({"image/svg+xml"})
INERT_SUFFIX = ".txt"
# Ceiling for all stored attachments of one hub; files that would exceed it are skipped.
MAX_ENTRY_BYTES = 500 * 1024 * 1024
# Statuses that will not change on retry within this run; such files are not downloaded again.
_PERMANENT_STATUSES = frozenset({"too_large"})


def safe_file_name(name: str) -> str:
    """Return a single path component: no separators, '..', controls or leading dots."""
    cleaned = "".join(
        "_" if char in _UNSAFE_CHARACTERS or unicodedata.category(char).startswith("C") else char
        for char in unicodedata.normalize("NFC", str(name))
    )
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.strip().lstrip(".").strip()
    stem, extension = os.path.splitext(cleaned)
    if len(extension) >= MAX_NAME_LENGTH:
        stem, extension = cleaned, ""
    return (stem[: MAX_NAME_LENGTH - len(extension)].rstrip() + extension) or FALLBACK_NAME


def _is_safe_component(value) -> bool:
    return isinstance(value, str) and bool(value) and safe_file_name(value) == value


def media_dir(hass) -> Path:
    """Attachment root on the config volume, not the container media mount."""
    return Path(hass.config.path(STORAGE_FOLDER))


def entry_media_dir(hass, entry_id: str) -> Path:
    return media_dir(hass) / entry_id


def legacy_entry_media_dir(hass, entry_id: str) -> Path:
    """Earlier builds stored files in the local media source, which Docker keeps outside config."""
    base = Path(hass.config.media_dirs.get("local") or hass.config.path("media"))
    return base / LEGACY_MEDIA_FOLDER / entry_id


def download_url(entry_id: str, conversation_id: str, message_id: str, file_id: str) -> str:
    return DOWNLOAD_URL.format(
        entry_id=quote(entry_id, safe=""),
        conversation_id=quote(conversation_id, safe=""),
        message_id=quote(message_id, safe=""),
        file_id=quote(file_id, safe=""),
    )


def _inside(path: Path, container: Path) -> bool:
    """True when path resolves strictly below container (symlinks followed)."""
    return container.resolve() in path.resolve().parents


def _remove_tree(path: Path, container: Path) -> None:
    if not os.path.lexists(path):
        return
    if not _inside(path, container):
        _LOGGER.warning("Refusing to remove a Mashov media folder outside its entry folder")
        return
    shutil.rmtree(path)


def stored_file_name(name: str) -> tuple[str, bool]:
    """Sanitized on-disk name; active types get an inert suffix. Returns (name, neutralized)."""
    cleaned = safe_file_name(name)
    if mimetypes.guess_type(cleaned)[0] in ACTIVE_MIME_TYPES:
        return cleaned + INERT_SUFFIX, True
    return cleaned, False


def _folder_size(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink())


def _retain(root: Path, keep: set[str]) -> None:
    if root.is_dir():
        for child in root.iterdir():
            if child.name not in keep:
                _remove_tree(child, root)


def _open_partial(root: Path, target: Path, partial: Path):
    if not _inside(target, root):
        raise ValueError("attachment path escapes the entry folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    return partial.open("wb")


def _finish(handle, partial: Path, target: Path, keep: bool) -> None:
    handle.close()
    if keep:
        os.replace(partial, target)
    else:
        partial.unlink(missing_ok=True)


async def _async_remove_entry_dir(hass, root: Path) -> None:
    try:
        if root.exists():
            await hass.async_add_executor_job(_remove_tree, root, root.parent)
    except OSError as err:
        _LOGGER.warning("Could not remove stored Mashov attachments (%s)", type(err).__name__)


async def async_clear_legacy_entry_media(hass, entry_id: str) -> None:
    """Remove this hub's files from the old media folder once they live under config."""
    legacy = legacy_entry_media_dir(hass, entry_id)
    if legacy != entry_media_dir(hass, entry_id):
        await _async_remove_entry_dir(hass, legacy)


async def async_clear_entry_media(hass, entry_id: str) -> None:
    """Delete every stored attachment of one hub, including files left in the old media folder."""
    await _async_remove_entry_dir(hass, entry_media_dir(hass, entry_id))
    legacy = legacy_entry_media_dir(hass, entry_id)
    if legacy != entry_media_dir(hass, entry_id):
        await _async_remove_entry_dir(hass, legacy)


class AttachmentStore:
    """Download each attachment once and expose media-source metadata for it."""

    def __init__(self, hass, entry_id: str, max_bytes: int) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self.max_bytes = max_bytes
        self.root = entry_media_dir(hass, entry_id)
        # target path -> permanent status (e.g. too_large): skip re-downloading every refresh.
        self._permanent: dict[Path, str] = {}
        self._used_bytes = 0

    def _run(self, func, *args):
        return self._hass.async_add_executor_job(func, *args)

    async def async_sync(self, mailbox: dict, download) -> None:
        """Store attachments of fully fetched conversations, then apply retention.

        download(path, max_bytes, write) streams one file and returns
        (status, content_type). A failure only affects that attachment.
        """
        # Retention first, so space freed by conversations that left the window counts
        # toward the per-hub ceiling for this run's new downloads.
        if mailbox.get("status") == "ok":
            keep = {item["conversationId"] for item in mailbox.get("items", [])}
            try:
                await self._run(_retain, self.root, keep)
            except OSError as err:
                _LOGGER.warning("Could not remove old Mashov attachments (%s)", type(err).__name__)
        try:
            self._used_bytes = await self._run(_folder_size, self.root)
        except OSError:
            self._used_bytes = MAX_ENTRY_BYTES  # Unknown usage: do not grow the folder.
        for item in mailbox.get("items", []):
            if item.get("content_status") != "ok":
                continue
            for message in item.get("messages", []):
                for attachment in message.get("attachments", []):
                    attachment.update(
                        await self._async_save(download, item["conversationId"], message.get("messageId"), attachment)
                    )

    async def _async_save(self, download, conversation_id: str, message_id, attachment: dict) -> dict:
        file_id, name = attachment["fileId"], attachment["fileName"]
        if not all(_is_safe_component(part) for part in (conversation_id, message_id, file_id)):
            return self._metadata(None, "error", None, name)
        stored_name, neutralized = stored_file_name(name)
        target = self.root / conversation_id / message_id / f"{file_id}-{stored_name}"
        path = "mail/messages/{}/files/{}/download/{}".format(
            *(quote(part, safe=_URI_COMPONENT_SAFE) for part in (message_id, file_id, name))
        )
        try:
            status, content_type = await self._async_fetch_once(download, path, target)
            size = await self._run(os.path.getsize, target) if status == "ok" else None
        except Exception as err:  # One attachment must never fail the refresh.
            _LOGGER.warning("Could not store a Mashov mailbox attachment (%s)", type(err).__name__)
            status, content_type, size = "error", None, None
        metadata = self._metadata(
            target if status == "ok" else None,
            status,
            content_type,
            name,
            size,
            conversation_id,
            message_id,
            file_id,
        )
        if neutralized:
            metadata["neutralized"] = True
        return metadata

    async def _async_fetch_once(self, download, path: str, target: Path):
        if await self._run(target.is_file):
            return "ok", None
        if target in self._permanent:
            return self._permanent[target], None
        budget = MAX_ENTRY_BYTES - self._used_bytes
        if budget <= 0:
            return "quota_exceeded", None
        limit = min(self.max_bytes, budget)
        partial = target.with_name(f".{target.name}.part")
        handle = await self._run(_open_partial, self.root, target, partial)
        status, content_type = "error", None
        try:
            status, content_type = await download(path, limit, lambda chunk: self._run(handle.write, chunk))
        finally:
            await self._run(_finish, handle, partial, target, status == "ok")
        if status == "too_large" and limit < self.max_bytes:
            # Within the per-file limit but over the remaining hub budget.
            return "quota_exceeded", None
        if status in _PERMANENT_STATUSES:
            self._permanent[target] = status
        if status == "ok":
            self._used_bytes += await self._run(os.path.getsize, target)
        return status, content_type

    def _metadata(
        self, target, status, content_type, name, size=None, conversation_id=None, message_id=None, file_id=None
    ) -> dict:
        mime_type = (content_type or "").split(";")[0].strip().lower()
        if not mime_type or mime_type == DEFAULT_MIME_TYPE:
            mime_type = mimetypes.guess_type(name)[0] or DEFAULT_MIME_TYPE
        # The local media source cannot serve documents, and must never serve active content.
        url = None
        if target is not None and conversation_id and message_id and file_id:
            url = download_url(self._entry_id, conversation_id, message_id, file_id)
        return {"mime_type": mime_type, "size": size, "status": status, "download_url": url}


def _matching_files(folder: Path, file_id: str) -> list[Path]:
    if not folder.is_dir():
        return []
    prefix = f"{file_id}-"
    return [
        path for path in folder.iterdir() if path.is_file() and not path.is_symlink() and path.name.startswith(prefix)
    ]


class MashovAttachmentView(HomeAssistantView):
    """Serve one stored attachment as a download. Documents are not in the media browser.

    Active types (SVG) are stored with a .txt suffix and served as plain text, always as an
    attachment, so a script in a school file cannot run on Home Assistant's origin.
    """

    url = "/api/mashov/attachment/{entry_id}/{conversation_id}/{message_id}/{file_id}"
    name = "api:mashov:attachment"
    requires_auth = True

    async def get(self, request, entry_id, conversation_id, message_id, file_id):
        hass = request.app["hass"]
        if not all(_is_safe_component(part) for part in (entry_id, conversation_id, message_id, file_id)):
            return web.Response(status=404)
        root = entry_media_dir(hass, entry_id)
        folder = root / conversation_id / message_id
        if not _inside(folder, root):
            return web.Response(status=404)
        matches = await hass.async_add_executor_job(_matching_files, folder, file_id)
        if len(matches) != 1 or not _inside(matches[0], root):
            return web.Response(status=404)
        path = matches[0]
        mime_type = mimetypes.guess_type(path.name)[0] or DEFAULT_MIME_TYPE
        if mime_type in ACTIVE_MIME_TYPES or path.name.endswith(INERT_SUFFIX):
            mime_type = "text/plain"
        filename = path.name[len(file_id) + 1 :] if path.name.startswith(f"{file_id}-") else path.name
        response = web.FileResponse(path)
        response.content_type = mime_type
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response
