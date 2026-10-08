"""Async HTTP client for the Mashov student portal (unofficial API).

Handles login (with a cached-session fast path), school lookup, per-student data
fetching and normalization of the raw API payloads into the snake_case dicts the
sensors consume. It never submits forms or downloads attachments. The optional
mailbox full-content GET marks conversations read and requires explicit opt-in.

Failure isolation is deliberate: a school that disables a feature (HTTP 403/404)
only blanks that one resource for that one student, with a cooldown so we do not
hammer the endpoint, and a holidays failure never discards student data.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date, timedelta
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import aiohttp  # type: ignore[import]

from .additional_data import STUDENT_RESOURCES
from .const import CONF_YEAR
from .data_selection import (
    CONF_ADDITIONAL_DATA,
    CONF_ENABLED_DATA,
    DEFAULT_MAILBOX_LIMIT,
    enabled_data as resolve_enabled_data,
)
from .mailbox import fetch_mailbox

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant  # type: ignore[import]  # pyright: ignore[reportMissingImports]
else:
    HomeAssistant = Any

_LOGGER = logging.getLogger(__name__)


def _trace(msg: str, *args):
    # Use DEBUG for portability; can toggle in logger config
    _LOGGER.debug(msg, *args)


API_BASE = "https://web.mashov.info/api/"  # default; can be overridden

# Escalating cooldowns for core student endpoints that answer HTTP 403 (feature disabled by the school).
CORE_RESOURCE_BACKOFF_STEPS = (3600, 21600, 86400)  # 1h -> 6h -> 24h


class MashovError(Exception):
    """Base error for Mashov API, network and data problems."""

    pass


class MashovAuthError(MashovError):
    """Raised when Mashov rejects the credentials (re-auth is required)."""

    pass


class MashovPasswordChangeRequiredError(MashovAuthError):
    """Raised when Mashov requires a password change before login."""

    def __init__(self, message: str, login_url: str) -> None:
        super().__init__(message)
        self.login_url = login_url


def _slugify(text: str) -> str:
    """Build an entity-safe slug; non-Latin letters (Hebrew) are kept, punctuation dropped."""
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("_")
    s = "".join(out).strip("_")
    return s or "student"


def _default_mashov_year(today: date | None = None) -> int:
    """Return the Mashov school year, named after the calendar year it ends in.

    The year rolls over on September 1st, e.g. 2025-09-01 .. 2026-08-31 is year 2026.
    """
    d = today or date.today()
    return d.year + 1 if d.month >= 9 else d.year


def configured_school_year(data: dict, options: dict | None) -> int | None:
    """Return None while the automatic year is on. Otherwise keep the stored year, or freeze today's."""
    options = options or {}
    # Legacy entries without the option are automatic unless a year was stored at setup.
    if options.get("automatic_school_year", not data.get(CONF_YEAR)):
        return None
    stored = data.get(CONF_YEAR)
    return int(stored) if stored else _default_mashov_year()


class MashovClient:
    """Client for one Mashov parent/student account, covering all of its children.

    One login returns every child on the account; data is then fetched per child
    and keyed by the child's slug. Session state (cookies + CSRF token) can be
    exported via ``auth_data`` and passed back as ``saved_auth`` to skip a login
    on the next Home Assistant start.
    """

    def __init__(
        self,
        school_id: int | str,
        year: int | None,
        username: str,
        password: str,
        homework_days_back: int = 7,
        homework_days_forward: int = 21,
        api_base: str | None = None,
        saved_auth: dict[str, Any] | None = None,
        additional_data: list[str] | None = None,
        enabled_data: list[str] | None = None,
        mailbox_full_content: bool = False,
        mailbox_limit: int = DEFAULT_MAILBOX_LIMIT,
    ) -> None:
        # school may be semel int or name string (resolved in async_init)
        self.school_id = int(school_id) if str(school_id).isdigit() else None
        self.school_name = None if str(school_id).isdigit() else str(school_id)

        # An explicit year is pinned; otherwise follow the Mashov school year (rolls over on September 1st).
        self._configured_year = int(year) if year else None
        self._session_year: int | None = None
        self.username = username
        self.password = password
        self.homework_days_back = homework_days_back
        self.homework_days_forward = homework_days_forward
        selection = {CONF_ADDITIONAL_DATA: additional_data or []}
        if enabled_data is not None:
            selection[CONF_ENABLED_DATA] = enabled_data
        self.enabled_data = resolve_enabled_data(selection)
        self.additional_data = tuple(key for key in STUDENT_RESOURCES if key in self.enabled_data)
        self.mailbox_full_content = bool(mailbox_full_content and "mailbox" in self.enabled_data)
        self.mailbox_limit = max(1, min(50, int(mailbox_limit)))
        # Optional resources: (student_id, resource_key) -> (retry_after_monotonic, last_status)
        self._resource_retry_after: dict[tuple[str, str], tuple[float, str]] = {}
        # Core resources: (student_id, url_key) -> (retry_after_monotonic, consecutive_403_count)
        self._endpoint_cooldown: dict[tuple[str, str], tuple[float, int]] = {}

        self._session: aiohttp.ClientSession | None = None
        self._headers: dict[str, str] = {}
        # Instance-level endpoints (fix race condition)
        self._login_endpoint = ""
        self._login_page_url = ""
        self._endpoints: dict[str, str] = {}

        self._api_base = (api_base or API_BASE).rstrip("/") + "/"
        self._resolve_endpoints()

        # store all students
        self._students: list[dict[str, Any]] = []  # [{id, name, slug}]
        self._auth_data: dict[str, Any] = {}  # Store authentication response data
        # Only keep cached auth that can actually authenticate; it is consumed once in async_init.
        self._saved_auth = (
            saved_auth if saved_auth and (saved_auth.get("csrf_token") or saved_auth.get("cookies")) else None
        )
        # Set once a real login (not a session restore) has reloaded the children list.
        self.roster_refreshed = False

        # Concurrency control
        self._login_lock = asyncio.Lock()
        self._last_login_timestamp = 0.0

    @property
    def year(self) -> int:
        """Return the configured year, or the current Mashov school year."""
        return self._configured_year or _default_mashov_year()

    def _resolve_endpoints(self):
        """Build the login and core resource URL templates from the API base."""
        self._login_endpoint = self._api_base + "login"
        self._login_page_url = self._build_login_page_url()
        self._endpoints = {
            "homework": self._api_base + "students/{student_id}/homework?from={start}&to={end}&year={year}",
            "behavior": self._api_base + "students/{student_id}/behave?from={start}&to={end}&year={year}",
            "weekly_plan": self._api_base + "students/{student_id}/lessons/plans",
            "timetable": self._api_base + "students/{student_id}/timetable",
            "holidays": self._api_base + "holidays",
            "lessons_history": self._api_base + "students/{student_id}/lessons/history",
            "grades": self._api_base + "students/{student_id}/grades",
        }

    def _build_login_page_url(self) -> str:
        """Return the browser login URL that matches the configured API base."""
        parsed = urlsplit(self._api_base)
        path = parsed.path.rstrip("/")
        if path.endswith("/api"):
            path = path[: -len("/api")]
        return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/students/login", "", ""))

    @property
    def login_page_url(self) -> str:
        """Return the Mashov login page URL for user-facing notifications."""
        return self._login_page_url

    @property
    def auth_data(self) -> dict[str, Any]:
        """Return authentication data for persistence."""
        # Export cookies from jar if session is open
        cookies = {}
        if self._session and self._session.cookie_jar:
            for cookie in self._session.cookie_jar:
                cookies[cookie.key] = cookie.value.value if hasattr(cookie.value, "value") else cookie.value

        return {
            "local_auth": self._auth_data,
            "session_year": self._session_year,
            "csrf_token": self._headers.get("X-Csrf-Token"),
            "cookies": cookies,
        }

    async def _ensure_valid_session(self):
        """Ensure session is valid, re-logging in if necessary, with concurrency protection.

        Called after an HTTP 401. Parallel requests that all hit 401 share one
        re-login: the first takes the lock and logs in, the rest see a login
        younger than 10 seconds and return immediately to retry their request.
        """
        # Fast check without lock first
        if time.time() - self._last_login_timestamp < 10:
            return

        async with self._login_lock:
            # Double-check inside lock
            if time.time() - self._last_login_timestamp < 10:
                return

            _LOGGER.debug("Ensuring valid session (under lock)")
            await self.async_init(None)
            self._last_login_timestamp = time.time()

    async def async_open_session(self) -> None:
        """Create the aiohttp session if missing or closed (e.g. after a reload)."""
        if self._session is None or self._session.closed:
            _trace("Opening new Mashov client session")
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60, connect=30),
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
            )

    async def async_close(self):
        """Close the session; errors are swallowed so unload never fails."""
        if self._session and not self._session.closed:
            _LOGGER.debug("Closing Mashov client session")
            try:
                # Wait for any pending requests to complete
                await asyncio.sleep(0.1)
                await self._session.close()
                await asyncio.sleep(0.25)  # Wait for cleanup
            except Exception as e:
                _LOGGER.debug("Error closing session: %s", e)
            finally:
                self._session = None

    async def async_fetch_schools_catalog(self, year: int | None = None) -> list[dict[str, Any]]:
        """Fetch a full list of schools for dropdown; best-effort across deployments."""
        await self.async_open_session()
        yr = year or self.year
        _LOGGER.debug("Fetching schools catalog for year %s", yr)

        # Deployments expose the list under different routes; merge whatever answers.
        candidates = [
            (self._api_base + f"schools?{urlencode({'year': yr})}", None),
            (self._api_base + "schools", None),
            (self._api_base + "institutions", None),
        ]

        all_items: list[dict[str, Any]] = []
        for url, hdrs in candidates:
            try:
                _trace("Trying schools catalog endpoint: %s", url)
                async with self._session.get(url, headers=hdrs or self._headers) as resp:
                    if resp.status >= 400:
                        _LOGGER.debug("Schools catalog endpoint failed with status %s: %s", resp.status, url)
                        continue
                    data = await resp.json(content_type=None)
                    items = self._normalize_schools_list(data)
                    if items:
                        _LOGGER.debug("Found %d schools from catalog endpoint: %s", len(items), url)
                        all_items.extend(items)
            except Exception as e:
                _LOGGER.debug("Schools catalog endpoint error: %s - %s", url, e)
                continue

        dedup = {}
        for it in all_items:
            semel = it.get("semel")
            if semel and semel not in dedup:
                dedup[semel] = it
        result = sorted(dedup.values(), key=lambda x: (x.get("name") or "").lower())
        _LOGGER.debug("Schools catalog completed: %d unique schools found", len(result))
        return result

    async def async_search_schools(self, query: str, year: int | None = None) -> list[dict[str, Any]]:
        """Search schools by name or city.

        Tries server-side search routes first, then full lists filtered locally;
        returns the first non-empty result.
        """
        if not self._session:
            await self.async_open_session()
        q = query.strip()
        yr = year or self.year
        _LOGGER.debug("Searching for schools matching '%s' for year %s", q, yr)
        candidates = [
            (self._api_base + f"schools?{urlencode({'year': yr, 'search': q})}", None),
            (self._api_base + f"schools?{urlencode({'search': q})}", None),
            (self._api_base + "schools", None),
            (self._api_base + f"institutions?{urlencode({'search': q})}", None),
            (self._api_base + "institutions", None),
        ]
        for url, hdrs in candidates:
            try:
                _trace("Trying school search endpoint: %s", url)
                async with self._session.get(url, headers=hdrs or self._headers) as resp:
                    if resp.status >= 400:
                        _LOGGER.debug("School search endpoint failed with status %s: %s", resp.status, url)
                        continue
                    data = await resp.json(content_type=None)
                    items = self._normalize_schools_list(data, query=q)
                    if items:
                        _LOGGER.debug("Found %d schools from search endpoint: %s", len(items), url)
                        return items
            except Exception as e:
                _LOGGER.debug("School search endpoint error: %s - %s", url, e)
                continue
        _LOGGER.warning("No schools found for query '%s'", q)
        return []

    def _normalize_schools_list(self, raw, query: str | None = None) -> list[dict[str, Any]]:
        """Map any known school-list shape to ``{semel, name, city}`` dicts, deduplicated by semel.

        Accepts a bare list or a dict wrapping it; field names vary between
        deployments (semel/id/schoolCode, name/schoolName/institutionName).
        Entries without a numeric semel or a name are skipped.
        """
        items: list[dict[str, Any]] = []

        def add(semel, name, city=None):
            try:
                semel = int(semel)
                if name:
                    # Do not attempt to derive a city; keep the name exactly as given by API
                    items.append({"semel": semel, "name": name, "city": city})
            except Exception:
                pass

        if isinstance(raw, list):
            for x in raw:
                add(
                    x.get("semel") or x.get("id") or x.get("schoolCode"),
                    x.get("name") or x.get("schoolName") or x.get("institutionName"),
                    x.get("city") or x.get("cityName"),
                )
        elif isinstance(raw, dict):
            for key in ("schools", "items", "results", "data"):
                lst = raw.get(key)
                if isinstance(lst, list):
                    for x in lst:
                        add(
                            x.get("semel") or x.get("id") or x.get("schoolCode"),
                            x.get("name") or x.get("schoolName") or x.get("institutionName"),
                            x.get("city") or x.get("cityName"),
                        )
        if query:
            ql = query.lower()
            items = [i for i in items if ql in (i["name"] or "").lower() or ql in (i["city"] or "").lower()]
        dedup = {}
        for i in items:
            dedup[i["semel"]] = i
        return list(dedup.values())

    async def async_init(self, hass: HomeAssistant):
        """Authenticate and load the account's children.

        Steps: resolve a school name to its semel if needed, try to restore the
        cached session, and otherwise perform a full login with retries.
        ``hass`` is unused; callers pass ``None`` for re-logins.

        Raises:
            MashovPasswordChangeRequiredError: Mashov demands a password change.
            MashovAuthError: credentials, school or year were rejected (no retry).
            MashovError: network/server failure after all retries.
        """
        _LOGGER.info("=== MASHOV CLIENT INIT START ===")
        _LOGGER.info("Initializing Mashov client")
        _LOGGER.info("API Base URL: %s", self._api_base)
        await self.async_open_session()

        # Login retries cover transient server/network failures only; 401/403 fail fast.
        max_retries = 3
        retry_delay = 2

        # --- School resolution: legacy configs may store a school name instead of a semel.
        if self.school_id is None and self.school_name:
            _LOGGER.debug("Resolving school name '%s' to semel", self.school_name)
            matches = await self.async_search_schools(self.school_name, self.year)
            if not matches:
                _LOGGER.error("No schools found matching '%s'", self.school_name)
                raise MashovError(f"No schools match '{self.school_name}'")
            best = next((m for m in matches if m.get("name") == self.school_name), matches[0])
            self.school_id = int(best.get("semel") or best.get("id"))
            _LOGGER.info("Resolved school '%s' to semel %s", best.get("name"), self.school_id)

        # --- Session restore: reuse cached cookies/CSRF token to avoid a login on every
        # HA start. A session is bound to the school year it was opened for, so a
        # cache from before the September rollover is discarded.
        if (
            self._saved_auth
            and self._saved_auth.get("session_year") is not None
            and str(self._saved_auth["session_year"]) != str(self.year)
        ):
            _LOGGER.info("Cached session belongs to a different school year - logging in again")
            self._saved_auth = None
        if self._saved_auth and not self._session.closed:
            _LOGGER.info("Attempting to restore session from cached auth data")
            saved_auth = self._saved_auth
            self._saved_auth = None  # Never restore the same stale session on later retries.
            try:
                # Restore cookies
                saved_cookies = saved_auth.get("cookies", {})
                if saved_cookies:
                    self._session.cookie_jar.update_cookies(saved_cookies)
                    _LOGGER.debug("Restored %d cookies from cache", len(saved_cookies))

                # Restore headers
                csrf = saved_auth.get("csrf_token")
                if csrf:
                    self._headers["X-Csrf-Token"] = csrf
                    self._headers["Accept"] = "application/json"
                    _LOGGER.debug("Restored CSRF token from cache")

                # Restore internal auth data
                self._auth_data = saved_auth.get("local_auth", {})

                # The old /me route returns 404. Probe a known authenticated,
                # read-only student endpoint instead of forcing a new login.
                try:
                    children = self._auth_data.get("accessToken", {}).get("children", [])
                    if not children or not children[0].get("childGuid"):
                        raise MashovError("Cached session has no student metadata")
                    if "timetable" not in self.enabled_data:
                        # Do not query a deselected dataset just to validate a cookie.
                        # The first selected request handles a stale session via 401.
                        await self._extract_students()
                        self._last_login_timestamp = 0
                        return
                    student_id = quote(str(children[0]["childGuid"]), safe="")
                    probe_url = self._endpoints["timetable"].format(student_id=student_id)
                    async with self._session.get(probe_url, headers=self._headers) as resp:
                        if resp.status == 200:
                            _LOGGER.info("Session restored successfully")
                            # We can skip login. roster_refreshed is not set here: the
                            # children list comes from the cache, not a fresh login.
                            await self._extract_students()
                            return
                        _LOGGER.warning("Restored session unavailable (HTTP %s) - proceeding to login", resp.status)
                except Exception as e:
                    _LOGGER.warning("Error verifying restored session: %s", e)
                # Do not carry the rejected cookies/CSRF token into the fresh login.
                self._headers = {}
                self._auth_data = {}
                self._session.cookie_jar.clear()

            except Exception as e:
                _LOGGER.warning("Failed to restore session: %s", e)
                # clear potentially bad state
                self._headers = {}
                self._session.cookie_jar.clear()

        # --- Full login. The payload and headers mimic the official web client
        # (app name/version and device fields), as the portal expects.
        payload = {
            "semel": int(self.school_id),
            "year": int(self.year),
            "username": self.username,
            "password": self.password,
            "IsBiometric": False,
            "appName": "info.mashov.students",
            "apiVersion": "4.20250101",
            "appVersion": "4.20250101",
            "appBuild": "4.20250101",
            "deviceUuid": "chrome-ha",
            "devicePlatform": "chrome",
            "deviceManufacturer": "homeassistant",
            "deviceModel": "integration",
            "deviceVersion": "1.0.5",
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://web.mashov.info",
            "Referer": "https://web.mashov.info/students/login",
            "User-Agent": "Mozilla/5.0 (HomeAssistant) Mashov/1.0.5",
        }
        # Try login with retry mechanism
        for attempt in range(max_retries):
            _LOGGER.info("=== LOGIN ATTEMPT %d/%d ===", attempt + 1, max_retries)
            _LOGGER.info("Starting login request")
            _LOGGER.info("Login endpoint: %s", self._login_endpoint)
            try:
                async with self._session.post(self._login_endpoint, json=payload, headers=headers) as resp:
                    _LOGGER.info("Login response status: %s", resp.status)
                    _LOGGER.info("Login response received")

                    if resp.status in (401, 403):
                        # Rejected credentials are final; retrying cannot fix them.
                        # A forced password change is signalled by a "reason: changepass"
                        # header or by the message text, and gets its own error so the
                        # user can be sent to the Mashov login page.
                        txt = await resp.text()
                        message = txt
                        try:
                            parsed = json.loads(txt)
                            if isinstance(parsed, dict) and parsed.get("message"):
                                message = str(parsed["message"])
                        except Exception:
                            pass
                        reason = (resp.headers.get("reason") or "").strip().lower()
                        if reason == "changepass" or "change password" in message.lower():
                            _LOGGER.warning("Mashov requires a password change")
                            raise MashovPasswordChangeRequiredError(
                                "Please change password before authenticating.", self.login_page_url
                            )
                        _LOGGER.error("Authentication failed; check credentials, school and year")
                        raise MashovAuthError(
                            "Authentication failed. Please check your credentials, school ID, and year."
                        )
                    if resp.status >= 400:
                        txt = await resp.text()
                        _LOGGER.error("Login request failed")
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying login in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            continue
                        raise MashovError(f"Login failed HTTP {resp.status}")

                    # Try to parse response
                    try:
                        data = await resp.json(content_type=None)
                        _LOGGER.info(
                            "Login response data keys: %s",
                            list(data.keys()) if isinstance(data, dict) else "not a dict",
                        )
                        _LOGGER.info("Login response parsed")
                    except Exception as e:
                        _LOGGER.error("Failed to parse login response as JSON: %s", e)
                        txt = await resp.text()
                        _LOGGER.error("Invalid login response")
                        data = {}

                    # Fresh headers for this session; data requests are authorized by the
                    # session cookies plus the CSRF token echoed in a header.
                    self._headers = {"Accept": "application/json"}

                    # Extract CSRF token from response headers
                    csrf_token = resp.headers.get("x-csrf-token") or resp.headers.get("X-Csrf-Token")
                    if csrf_token:
                        _LOGGER.debug("CSRF token received")
                        self._headers["X-Csrf-Token"] = csrf_token
                    else:
                        _LOGGER.warning("No CSRF token found in response headers")

                    # If we have accessToken data (even if it's a dict), we can proceed
                    _LOGGER.debug("Checking authentication data...")
                    _LOGGER.debug("Has accessToken: %s", bool(data.get("accessToken")))
                    _LOGGER.debug("Has credential: %s", bool(data.get("credential")))

                    # Log the type of accessToken to help debug
                    access_token = data.get("accessToken")
                    if access_token:
                        _LOGGER.debug("accessToken type: %s", type(access_token))
                        if isinstance(access_token, dict):
                            _LOGGER.info("accessToken is dict with keys: %s", list(access_token.keys()))
                        elif isinstance(access_token, str):
                            _LOGGER.info("accessToken is string, length: %d", len(access_token))

                    # Check for authentication success - either accessToken or credential
                    has_auth = bool(data.get("accessToken")) or bool(data.get("credential"))
                    if has_auth:
                        _LOGGER.info("=== AUTHENTICATION SUCCESSFUL ===")
                        _LOGGER.info("Authentication successful - accessToken/credential received")
                        # Store the full response data for later use
                        self._auth_data = data
                        break  # Success, exit retry loop
                    _LOGGER.error("=== AUTHENTICATION FAILED ===")
                    _LOGGER.error(
                        "No authentication data received. Available data keys: %s, headers: %s",
                        list(data.keys()) if isinstance(data, dict) else "not a dict",
                        list(resp.headers.keys()),
                    )
                    _LOGGER.error("Authentication data missing")
                    if attempt < max_retries - 1:
                        _LOGGER.info("Retrying login in %d seconds...", retry_delay)
                        await asyncio.sleep(retry_delay)
                        continue
                    raise MashovError("No authentication data received after multiple attempts")

            except TimeoutError:
                _LOGGER.warning("Login timeout on attempt %d/%d", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                _LOGGER.error("Login timeout - Mashov server is not responding")
                raise MashovError("Login timeout - Mashov server is not responding") from None
            except aiohttp.ClientError as e:
                _LOGGER.warning("Network error on attempt %d/%d: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                _LOGGER.error("Network error during login: %s", e)
                raise MashovError(f"Network error during login: {e}") from e

        # --- Students. Reaching here means the loop hit `break`; every failure path
        # above either retries or raises.
        await self._extract_students()
        self.roster_refreshed = True

    async def _extract_students(self):
        """Build ``self._students`` from ``accessToken.children`` in the login response.

        The childGuid is the stable student ID used in every student URL and in
        device/entity identifiers. Also records the school year the session
        belongs to and stamps the login time used by ``_ensure_valid_session``.
        Student names and IDs are deliberately not logged (privacy).
        """
        _LOGGER.info("=== EXTRACTING STUDENTS FROM AUTH RESPONSE ===")

        # Get children from the authentication response
        children = self._auth_data.get("accessToken", {}).get("children", [])
        _LOGGER.info("Found %d children in auth response", len(children))

        if not children:
            _LOGGER.error("No children found in authentication response")
            raise MashovError("No children found in authentication response")

        students: list[dict[str, Any]] = []
        for child in children:
            # Extract child information
            child_guid = child.get("childGuid")
            family_name = child.get("familyName", "")
            private_name = child.get("privateName", "")
            class_code = child.get("classCode", "")
            class_num = child.get("classNum", "")
            groups = child.get("groups", [])

            # Create display name
            name = f"{private_name} {family_name}"
            if class_code and class_num:
                name += f" ({class_code}{class_num})"

            # Use childGuid directly as the student ID
            if not child_guid:
                _LOGGER.warning("Skipping student without an identifier")
                continue

            _LOGGER.info("Student group metadata loaded")

            students.append(
                {
                    "id": child_guid,  # Use childGuid directly as ID
                    "name": name,
                    "slug": _slugify(name) or f"student_{child_guid}",
                    "child_guid": child_guid,
                    "class_code": class_code,
                    "class_num": class_num,
                    "groups": groups,
                }
            )

        self._students = students
        self._session_year = self.year
        _LOGGER.info("=== STUDENTS PROCESSING COMPLETE ===")
        _LOGGER.info("Student metadata loaded")

        # Keep session open for future use - don't close it here
        self._last_login_timestamp = time.time()
        _LOGGER.info("=== MASHOV CLIENT INIT COMPLETE ===")

    def _register_endpoint_forbidden(self, cooldown_key: tuple[str, str]) -> None:
        """Back off a core endpoint that answered HTTP 403, escalating per consecutive failure.

        The key is (student_id, resource), so one child's disabled feature does not
        affect siblings. Delays follow CORE_RESOURCE_BACKOFF_STEPS and stay at the
        last step; the counter resets on the next successful fetch.
        """
        _retry_after, count = self._endpoint_cooldown.get(cooldown_key, (0.0, 0))
        count += 1
        delay = CORE_RESOURCE_BACKOFF_STEPS[min(count, len(CORE_RESOURCE_BACKOFF_STEPS)) - 1]
        self._endpoint_cooldown[cooldown_key] = (time.monotonic() + delay, count)
        _LOGGER.warning(
            "Student resource %s forbidden (HTTP 403); feature may be disabled - retrying in %d hours",
            cooldown_key[1],
            delay // 3600,
        )

    async def _fetch_student_resource(self, sid: str, key: str, start: str, end: str) -> dict[str, Any]:
        """Fetch metadata only; never download files, mark mail read, or submit forms.

        Used for the opt-in ``additional_data`` resources. Never raises for API
        errors (except a required password change): the result is always
        ``{"items": [...], "status": ...}`` so one failing resource cannot break
        the refresh. HTTP 403/404 park the resource for 24 hours per student;
        while parked, the last status is returned without a request.
        """
        cache_key = (sid, key)
        retry_after, previous_status = self._resource_retry_after.get(cache_key, (0, "not_fetched"))
        if time.monotonic() < retry_after:
            return {"items": [], "status": previous_status}
        resource = STUDENT_RESOURCES[key]
        url = f"{self._api_base}students/{sid}/{resource.path}"
        if resource.dated:
            url += "?" + urlencode({"start": start, "end": end})
        try:
            # One re-login retry on 401, then give up for this cycle.
            for attempt in range(2):
                async with self._session.get(url, headers=self._headers) as response:
                    if response.status == 401:
                        if attempt == 0:
                            await self._ensure_valid_session()
                            continue
                        return {"items": [], "status": "unauthorized"}
                    if response.status == 403:
                        # A forced password change also surfaces as 403 on data routes.
                        body = await response.text()
                        if (
                            response.headers.get("reason") or ""
                        ).lower() == "changepass" or "change password" in body.lower():
                            raise MashovPasswordChangeRequiredError(
                                "Please change password before authenticating.", self.login_page_url
                            )
                    if response.status in (403, 404):
                        status = "forbidden" if response.status == 403 else "unsupported"
                        # School permissions differ. Retry tomorrow, independently per student/resource.
                        _LOGGER.warning(
                            "Optional student resource %s %s (HTTP %s); retrying in 24 hours",
                            key,
                            status,
                            response.status,
                        )
                        self._resource_retry_after[cache_key] = (time.monotonic() + 86400, status)
                        return {"items": [], "status": status}
                    if response.status >= 400:
                        return {"items": [], "status": f"http_{response.status}"}
                    payload = await response.json()
                    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                        return {"items": [], "status": "invalid_response"}
                    self._resource_retry_after.pop(cache_key, None)
                    return {"items": payload, "status": "ok"}
        except MashovPasswordChangeRequiredError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError):
            _LOGGER.warning("Unable to fetch optional Mashov resource %s", key)
            return {"items": [], "status": "fetch_failed"}

    async def async_fetch_all(self, selected_data=None, student_data=None) -> dict[str, Any]:
        """Fetch and normalize data for every student plus school holidays.

        Returns ``{"students", "by_slug", "holidays", "holidays_status"}``.
        ``by_slug[slug]`` holds the normalized core resources, the optional
        ``additional_data`` and a ``source_status`` map (ok/forbidden/unsupported/
        http_400) so the UI can explain empty sensors.

        Auth errors and password-change errors propagate; per-resource 400/403/404
        and holiday failures are absorbed so partial data is still returned.
        """
        selected = set(self.enabled_data) if selected_data is None else set(selected_data) & set(self.enabled_data)
        _LOGGER.info("Fetching %d selected data sources", len(selected))
        # --- Session / login. Ensure session and authentication are available (lazy login)
        if not self._session or self._session.closed:
            await self.async_open_session()
        if not self._students or "X-Csrf-Token" not in self._headers:
            _LOGGER.debug("No students/csrf in memory – performing lazy login")
            await self.async_init(None)
        elif self._session_year is not None and self._session_year != self.year:
            # School-year rollover (automatic year crossed September 1st): the old
            # session is bound to the previous year, and 403/404 cooldowns earned
            # last year may not apply to the new one.
            _LOGGER.info("Mashov school year changed to %s - logging in again", self.year)
            self._endpoint_cooldown.clear()
            self._resource_retry_after.clear()
            await self.async_init(None)

        # Ensure we have CSRF token in headers (after lazy login should exist)
        if "X-Csrf-Token" not in self._headers:
            _LOGGER.warning("No CSRF token found in headers for data fetching")

        # Freeze the roster for this refresh. A 401 mid-refresh triggers a re-login that
        # replaces self._students; results must stay paired with the roster they were
        # fetched for, or one child's data could be shown under another (or an added child
        # would cause an IndexError). A changed roster takes effect on the next refresh.
        students = list(self._students)

        # --- Date window for the dated resources (homework, behavior, optional resources).
        today = date.today()
        from_dt = (today - timedelta(days=self.homework_days_back)).isoformat()
        to_dt = (today + timedelta(days=self.homework_days_forward)).isoformat()
        today.isoformat()  # Result unused (leftover); harmless.

        _LOGGER.info("Fetching data for %d students from %s to %s", len(students), from_dt, to_dt)

        # No pre-flight session check (this block is intentionally a no-op).
        # A stale session is handled reactively: if parallel requests all get 401,
        # the first one re-logs in under _login_lock, the others wait on the lock,
        # see the fresh login and retry once.
        if students:
            with contextlib.suppress(Exception):
                pass

        # --- Per-student fetch: the six core resources in parallel, then optional ones.
        async def fetch_for_student(stu):
            sid = stu["id"]
            student_selected = selected if student_data is None else set(student_data.get(sid, ())) & selected
            source_status = {}

            urls = {
                "homework": self._endpoints["homework"].format(
                    student_id=sid, start=from_dt, end=to_dt, year=self.year
                ),
                "behavior": self._endpoints["behavior"].format(
                    student_id=sid, start=from_dt, end=to_dt, year=self.year
                ),
                "weekly_plan": self._endpoints["weekly_plan"].format(student_id=sid),
                "timetable": self._endpoints["timetable"].format(student_id=sid),
                "lessons_history": self._endpoints["lessons_history"].format(student_id=sid),
                "grades": self._endpoints["grades"].format(student_id=sid),
            }

            async def fetch(url_key: str, attempt: int = 0):
                """Fetch one core resource, recording its outcome in ``source_status``.

                401 -> one shared re-login and retry; 400/404 -> empty result;
                403 -> password-change check, else escalating cooldown; other
                errors raise MashovError and fail the whole refresh.
                """
                if url_key not in self.enabled_data:
                    source_status[url_key] = "disabled"
                    return []
                if url_key not in student_selected:
                    source_status[url_key] = "not_fetched"
                    return []
                url = urls[url_key]
                cooldown_key = (sid, url_key)
                retry_after, _count = self._endpoint_cooldown.get(cooldown_key, (0.0, 0))
                if time.monotonic() < retry_after:
                    _LOGGER.debug("Skipping %s: endpoint forbidden, in cooldown", url_key)
                    source_status[url_key] = "forbidden"
                    return []
                _LOGGER.debug("Fetching student resource")
                try:
                    async with self._session.get(url, headers=self._headers) as resp:
                        _LOGGER.debug("Student resource response received")
                        if resp.status == 401:
                            if attempt == 0:
                                _LOGGER.warning("Student resource unauthorized; retrying login")
                                await self._ensure_valid_session()  # Thread-safe re-login
                                return await fetch(url_key, attempt=1)
                            _LOGGER.warning("Student resource unauthorized after retry")
                            raise MashovAuthError("Authentication failed after one retry")
                        if resp.status == 404:
                            _LOGGER.warning("Student resource not available (HTTP 404)")
                            source_status[url_key] = "unsupported"
                            return []
                        if resp.status == 400:
                            txt = await resp.text()
                            _LOGGER.warning("Student resource rejected (HTTP 400)")
                            source_status[url_key] = "http_400"
                            return []
                        if resp.status == 403:
                            txt = await resp.text()
                            reason = (resp.headers.get("reason") or "").strip().lower()
                            if reason == "changepass" or "change password" in txt.lower():
                                raise MashovPasswordChangeRequiredError(
                                    "Please change password before authenticating.", self.login_page_url
                                )
                            source_status[url_key] = "forbidden"
                            self._register_endpoint_forbidden(cooldown_key)
                            return []
                        if resp.status >= 400:
                            raise MashovError(f"HTTP {resp.status} fetching {url_key}")
                        try:
                            data = await resp.json()
                            _LOGGER.debug("Student resource loaded")
                            source_status[url_key] = "ok"
                            # Success resets the 403 escalation for this student/resource.
                            self._endpoint_cooldown.pop(cooldown_key, None)
                            return data
                        except (ValueError, aiohttp.ClientError) as e:
                            raise MashovError(f"Invalid JSON fetching {url_key}") from e
                except MashovError:
                    raise
                except (aiohttp.ClientError, OSError) as e:
                    raise MashovError(f"Request failed fetching {url_key}") from e
                except RuntimeError as e:
                    # aiohttp raises this when the session was closed during a reload. It is not a code defect.
                    if getattr(self._session, "closed", False):
                        raise MashovError(f"Request failed fetching {url_key}") from e
                    raise

            homework, behavior, weekly_plan, timetable, lessons_history, grades = await asyncio.gather(
                fetch("homework"),
                fetch("behavior"),
                fetch("weekly_plan"),
                fetch("timetable"),
                fetch("lessons_history"),
                fetch("grades"),
            )
            # Sequential optional requests bound the extra load for each student.
            additional = {}
            for key in self.additional_data:
                if key not in student_selected:
                    continue
                additional[key] = await self._fetch_student_resource(sid, key, from_dt, to_dt)
            return {
                "homework": self._normalize_homework(homework),
                "behavior": self._normalize_behavior(behavior),
                "weekly_plan": self._normalize_weekly_plan(weekly_plan),
                "timetable": self._normalize_timetable(timetable),
                "lessons_history": self._normalize_lessons_history(lessons_history),
                "grades": self._normalize_grades(grades),
                "additional_data": additional,
                "source_status": source_status,
            }

        _LOGGER.debug("Fetching data for all students in parallel")
        # Use asyncio.gather for parallel execution
        results = await asyncio.gather(*(fetch_for_student(s) for s in students))

        # --- Holidays (school-wide, not per student). A holiday failure must not
        # discard successfully fetched student data; only auth errors propagate.
        holidays_raw = []
        holidays_status = "not_fetched" if "holidays" in self.enabled_data else "disabled"
        try:
            url = self._endpoints.get("holidays")
            if url and "holidays" in selected:
                for attempt in range(2):
                    async with self._session.get(url, headers=self._headers) as resp:
                        if resp.status == 401 and attempt == 0:
                            await self._ensure_valid_session()
                            continue
                        if resp.status >= 400:
                            holidays_status = f"http_{resp.status}"
                            break
                        holidays_raw = await resp.json(content_type=None)
                        if not isinstance(holidays_raw, list):
                            holidays_raw = []
                            holidays_status = "invalid_response"
                        else:
                            holidays_status = "ok"
                        break
        except (MashovAuthError, MashovPasswordChangeRequiredError):
            raise
        except Exception:
            holidays_status = "fetch_failed"
        if "holidays" in selected and holidays_status not in ("ok", "disabled"):
            _LOGGER.warning("Holidays refresh failed (%s); student data is retained", holidays_status)

        holidays = self._normalize_holidays(holidays_raw)
        by_slug = {student["slug"]: data for student, data in zip(students, results, strict=True)}
        if [s["id"] for s in self._students] != [s["id"] for s in students]:
            _LOGGER.info("Student list changed during a re-login; the update applies on the next refresh")

        result = {
            "students": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "slug": s["slug"],
                    "year": self.year,
                    "school_id": self.school_id,
                }
                for s in students
            ],
            "by_slug": by_slug,
            "holidays": holidays,
            "holidays_status": holidays_status,
            "enabled_data": list(self.enabled_data),
            "mailbox_full_content": self.mailbox_full_content,
            "mailbox_limit": self.mailbox_limit,
        }

        if "mailbox" in selected:
            result["mailbox"] = await fetch_mailbox(
                self._fetch_account_json, full_content=self.mailbox_full_content, limit=self.mailbox_limit
            )

        _LOGGER.debug("Data fetch completed for %d students", len(students))
        return result

    async def _fetch_account_json(self, path, key, expected_type):
        """Fetch a known account route; isolate failures and back off forbidden features."""
        cache_key = ("account", path if key == "mail_content" else key)
        retry_after, previous = self._resource_retry_after.get(cache_key, (0, "not_fetched"))
        if time.monotonic() < retry_after:
            return previous, None
        try:
            for attempt in range(2):
                async with self._session.get(self._api_base + path, headers=self._headers) as response:
                    if response.status == 401:
                        if attempt == 0:
                            await self._ensure_valid_session()
                            continue
                        return "unauthorized", None
                    if response.status == 403:
                        body = await response.text()
                        if (
                            response.headers.get("reason") or ""
                        ).lower() == "changepass" or "change password" in body.lower():
                            raise MashovPasswordChangeRequiredError(
                                "Please change password before authenticating.", self.login_page_url
                            )
                    if response.status in (403, 404):
                        status = "forbidden" if response.status == 403 else "unsupported"
                        # A single removed conversation (404) must not block other details.
                        if key != "mail_content" or response.status == 403:
                            self._resource_retry_after[cache_key] = (time.monotonic() + 86400, status)
                        return status, None
                    if response.status >= 400:
                        return f"http_{response.status}", None
                    payload = await response.json()
                    if not isinstance(payload, expected_type):
                        return "invalid_response", None
                    self._resource_retry_after.pop(cache_key, None)
                    return "ok", payload
        except MashovPasswordChangeRequiredError:
            raise
        except RuntimeError:
            if not getattr(self._session, "closed", False):
                raise
            _LOGGER.warning("Mashov session closed while fetching account resource %s", key)
            return "fetch_failed", None
        except (aiohttp.ClientError, TimeoutError, ValueError):
            _LOGGER.warning("Unable to fetch Mashov account resource %s", key)
            return "fetch_failed", None

    # Normalizers: map Mashov's camelCase (sometimes lowercase) API fields to the
    # snake_case keys the sensors use. They never raise; a malformed payload
    # yields whatever was parsed before the error (logged at debug level).
    def _normalize_weekly_plan(self, raw):
        """Weekly plan items; note this API uses all-lowercase keys (groupid, lessondate)."""
        items = []
        try:
            for plan in raw or []:
                items.append(
                    {
                        "group_id": plan.get("groupid"),
                        "lesson_date": plan.get("lessondate"),
                        "lesson": plan.get("lesson"),
                        "plan": plan.get("plan"),
                    }
                )
        except Exception as e:
            _LOGGER.debug("normalize weekly plan failed: %s", e)
        return items

    def _normalize_timetable(self, raw):
        """Keep timetable structure (timeTable/groupDetails) mostly intact for UI formatting."""
        items = []
        try:
            if isinstance(raw, list):
                for it in raw:
                    # Ensure keys exist with sane defaults
                    items.append(
                        {
                            "timeTable": (it or {}).get("timeTable") or {},
                            "groupDetails": (it or {}).get("groupDetails") or {},
                        }
                    )
            elif isinstance(raw, dict):
                # Some deployments may wrap data
                data_list = raw.get("items") or raw.get("data") or []
                for it in data_list:
                    items.append(
                        {
                            "timeTable": (it or {}).get("timeTable") or {},
                            "groupDetails": (it or {}).get("groupDetails") or {},
                        }
                    )
        except Exception as e:
            _LOGGER.debug("normalize timetable failed: %s", e)
        return items

    def _normalize_homework(self, raw):
        """Homework assignments within the configured days-back/forward window."""
        items = []
        try:
            for hw in raw or []:
                items.append(
                    {
                        "lesson_id": hw.get("lessonId"),
                        "lesson_date": hw.get("lessonDate"),
                        "lesson": hw.get("lesson"),
                        "homework": hw.get("homework"),
                        "group_id": hw.get("groupId"),
                        "remark": hw.get("remark"),
                        "student_guid": hw.get("studentGuid"),
                        "subject_name": hw.get("subjectName"),
                    }
                )
        except Exception as e:
            _LOGGER.debug("normalize homework failed: %s", e)
        return items

    def _normalize_behavior(self, raw):
        """Behavior events (absences, lateness, praise...).

        ``achva*`` fields describe Mashov's event type (code, display name and
        ``achvaAval``) and are passed through unchanged.
        """
        items = []
        try:
            for ev in raw or []:
                items.append(
                    {
                        "student_guid": ev.get("studentGuid"),
                        "event_code": ev.get("eventCode"),
                        "justified": ev.get("justified"),
                        "lesson_id": ev.get("lessonId"),
                        "reporter_guid": ev.get("reporterGuid"),
                        "timestamp": ev.get("timestamp"),
                        "group_id": ev.get("groupId"),
                        "lesson_type": ev.get("lessonType"),
                        "lesson": ev.get("lesson"),
                        "lesson_date": ev.get("lessonDate"),
                        "lesson_reporter": ev.get("lessonReporter"),
                        "achva_code": ev.get("achvaCode"),
                        "achva_name": ev.get("achvaName"),
                        "achva_aval": ev.get("achvaAval"),
                        "justification_id": ev.get("justificationId"),
                        "justification": ev.get("justification"),
                        "reporter": ev.get("reporter"),
                        "subject": ev.get("subject"),
                    }
                )
        except Exception as e:
            _LOGGER.debug("normalize behavior failed: %s", e)
        return items

    def _normalize_holidays(self, raw):
        """School holidays; the API spells the name field ``hollyDayName`` (typo kept upstream)."""
        items = []
        try:
            for h in raw or []:
                items.append(
                    {
                        "id": h.get("id"),
                        "name": h.get("hollyDayName") or h.get("holidayName") or h.get("name"),
                        "start": h.get("startDate"),
                        "end": h.get("endDate"),
                    }
                )
        except Exception as e:
            _LOGGER.debug("normalize holidays failed: %s", e)
        return items

    def _normalize_lessons_history(self, raw):
        """Past lessons: lesson fields live under ``lessonLog``; group/subject names on the outer item."""
        items = []
        try:
            for r in raw or []:
                log = r.get("lessonLog") or {}
                items.append(
                    {
                        "lesson_id": log.get("lessonID"),
                        "group_id": log.get("groupId"),
                        "lesson_date": log.get("lessonDate"),
                        "lesson": log.get("lesson"),
                        "took_place": log.get("tookPlace"),
                        "remark": log.get("remark"),
                        "homework": log.get("homeWork"),
                        "lessontype": log.get("lessontype"),
                        "reporter_guid": log.get("reporterGuid"),
                        "group_name": r.get("groupName"),
                        "subject_name": r.get("subjectName"),
                    }
                )
        except Exception as e:
            _LOGGER.debug("normalize lessons history failed: %s", e)
        return items

    def _normalize_grades(self, raw):
        """Normalize grades data."""
        if not raw or not isinstance(raw, list):
            return []
        # Grades come already normalized from the API
        return raw
