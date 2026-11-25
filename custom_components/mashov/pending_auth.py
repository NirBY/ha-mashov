"""Hand a credential check's login over to the hub that is set up or reloaded next.

Every Mashov password login registers a new device and emails the parent. The check
in the add-hub and Configure flows already logs in as HA's private device, so the
hub reuses that session and remembered device instead of logging in a second time.
The login is kept in memory only, used once, and only for the same school and username.
"""

from __future__ import annotations

import time
from typing import Any

from .const import DOMAIN

PENDING_AUTH = "pending_auth"
# A check whose flow was abandoned is not reused after this long.
PENDING_AUTH_MAX_AGE = 3600


def _key(school_id, username) -> tuple[str, str]:
    return (str(school_id), str(username))


def hand_over_auth(hass, school_id, username, auth) -> None:
    """Keep a successful check's session and remembered device for this account's hub."""
    if isinstance(auth, dict) and (auth.get("csrf_token") or auth.get("device_auth")):
        pending = hass.data.setdefault(DOMAIN, {}).setdefault(PENDING_AUTH, {})
        pending[_key(school_id, username)] = (time.monotonic(), auth)


def take_pending_auth(hass, school_id, username) -> dict[str, Any] | None:
    """Return this account's handed-over login once, if it is recent enough."""
    pending = hass.data.get(DOMAIN, {}).get(PENDING_AUTH, {}).pop(_key(school_id, username), None)
    if pending and time.monotonic() - pending[0] < PENDING_AUTH_MAX_AGE:
        return pending[1]
    return None
