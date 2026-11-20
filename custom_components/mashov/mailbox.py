"""Bounded inbox retrieval. Unread conversations are never opened."""

from html.parser import HTMLParser
import re
from urllib.parse import quote
from uuid import UUID


class _PlainText(HTMLParser):
    """Extract text without executing HTML or loading remote images/attachments."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif not self.hidden and tag in ("br", "p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ("p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_body(value):
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return "\n".join(line for part in re.split(r"[\r\n]+", "".join(parser.parts)) if (line := part.strip()))


def _attachments(value):
    """Keep well-formed {fileId, fileName} entries; a bad entry never drops its message.

    Only parsed from detail GETs (full content), and only when attachments are enabled.
    """
    result = []
    for entry in value if isinstance(value, list) else []:
        file_id = entry.get("fileId") if isinstance(entry, dict) else None
        name = entry.get("fileName") if isinstance(entry, dict) else None
        if isinstance(file_id, bool) or not isinstance(file_id, (int, str)) or not str(file_id).strip():
            continue
        if isinstance(name, str) and name.strip():
            result.append({"fileId": str(file_id), "fileName": name})
    return result


def _messages(value, include_body=False, include_files=False):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        return None
    result = []
    for message in value:
        item = {
            key: message[key]
            for key in ("messageId", "subject", "senderName", "sendTime", "lastUpdate", "isNew")
            if isinstance(message.get(key), (str, bool))
        }
        if include_body:
            if not isinstance(message.get("body"), str):
                return None
            item["body"] = plain_body(message["body"])
        if include_files:
            item["attachments"] = _attachments(message.get("files"))
        result.append(item)
    return result


def _count(counts, key):
    value = counts.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


async def fetch_mailbox(get_json, *, full_content=False, limit=20, attachments=False):
    """Fetch at most limit inbox conversations once per account, never per student.

    get_json returns (status, payload) and handles authentication/backoff. Detail
    URLs are requested only for conversations the parent has already read: Mashov
    marks a conversation read when its detail is fetched, so an unread thread is
    left as headers until the parent opens it.
    """
    result = {"status": "not_fetched", "items": [], "full_content": full_content, "limit": limit}
    counts_status, counts = await get_json("mail/counts", "mail_counts", dict)
    if counts_status == "ok":
        result["unread_count"] = _count(counts, "unreadConversations")
        result["inbox_count"] = _count(counts, "inboxConversations")
    result["counts_status"] = counts_status
    if counts_status == "ok" and result.get("unread_count") is None:
        result["counts_status"] = "invalid_response"
    status, inbox = await get_json(f"mail/inbox/conversations?skip=0&take={limit}", "mailbox", list)
    result["status"] = status
    if status != "ok":
        return result
    if any(not isinstance(item, dict) for item in inbox):
        result["status"] = "invalid_response"
        return result
    for conversation in inbox[:limit]:
        try:
            conversation_id = str(UUID(conversation.get("conversationId", "")))
        except (ValueError, TypeError, AttributeError):
            result["status"] = "invalid_response"
            continue
        messages = _messages(conversation.get("messages"))
        if messages is None:
            result["status"] = "invalid_response"
            continue
        item = {
            key: conversation[key]
            for key in ("subject", "sendTime", "isNew", "hasAttachments")
            if isinstance(conversation.get(key), (str, bool))
        }
        item.update(conversationId=conversation_id, messages=messages)
        result["items"].append(item)

    if full_content:
        opened = [item for item in result["items"] if item.get("isNew") is False]
        for item in opened:
            status, detail = await get_json(
                "mail/conversations/" + quote(item["conversationId"], safe=""),
                "mail_content",
                dict,
            )
            if status == "ok":
                # A malformed/mismatched response must not attach another thread's body.
                messages = _messages(detail.get("messages"), include_body=True, include_files=attachments)
                if detail.get("conversationId") != item["conversationId"] or messages is None:
                    status = "invalid_response"
                else:
                    item["messages"] = messages
                    # A successful detail GET has read side effects regardless of a
                    # possibly stale isNew value in the detail response itself.
                    item["isNew"] = False
                    for message in item["messages"]:
                        message["isNew"] = False
            item["content_status"] = status
        # Opened threads were already read, so the unread count from the first
        # counts request remains accurate; no second counts request is needed.
    return result
