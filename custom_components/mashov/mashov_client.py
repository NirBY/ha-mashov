from __future__ import annotations

import asyncio
from datetime import date, timedelta
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import aiohttp  # type: ignore[import]

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant  # type: ignore[import]  # pyright: ignore[reportMissingImports]
else:
    HomeAssistant = Any

_LOGGER = logging.getLogger(__name__)


def _trace(msg: str, *args):
    # Use DEBUG for portability; can toggle in logger config
    _LOGGER.debug(msg, *args)


API_BASE = "https://web.mashov.info/api/"  # default; can be overridden

# API_BASE = "https://web.mashov.info/api/"  # default; can be overridden


class MashovError(Exception):
    pass


class MashovAuthError(MashovError):
    pass


def _slugify(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("_")
    s = "".join(out).strip("_")
    return s or "student"


def _default_mashov_year(today: date | None = None) -> int:
    d = today or date.today()
    return d.year + 1 if d.month >= 9 else d.year


class MashovClient:
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
    ) -> None:
        # school may be semel int or name string (resolved in async_init)
        self.school_id = int(school_id) if str(school_id).isdigit() else None
        self.school_name = None if str(school_id).isdigit() else str(school_id)

        self.year = int(year) if year else _default_mashov_year()
        self.username = username
        self.password = password
        self.homework_days_back = homework_days_back
        self.homework_days_forward = homework_days_forward

        self._session: aiohttp.ClientSession | None = None
        self._headers: dict[str, str] = {}
        self._api_base = (api_base or API_BASE).rstrip("/") + "/"
        self._resolve_endpoints()

        # store all students
        self._students: list[dict[str, Any]] = []  # [{id, name, slug}]
        self._auth_data: dict[str, Any] = {}  # Store authentication response data
        self._saved_auth = saved_auth  # Data restored from cache

        # Instance-level endpoints (fix race condition)
        self._login_endpoint = ""
        self._me_endpoint = ""
        self._endpoints: dict[str, str] = {}

    def _resolve_endpoints(self):
        self._login_endpoint = self._api_base + "login"
        self._me_endpoint = self._api_base + "me"
        self._endpoints = {
            "homework": self._api_base + "students/{student_id}/homework?from={start}&to={end}&year={year}",
            "behavior": self._api_base + "students/{student_id}/behave?from={start}&to={end}&year={year}",
            "weekly_plan": self._api_base + "students/{student_id}/lessons/plans",
            "timetable": self._api_base + "students/{student_id}/timetable",
            "holidays": self._api_base + "holidays",
            "lessons_history": self._api_base + "students/{student_id}/lessons/history",
            "grades": self._api_base + "students/{student_id}/grades",
        }

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
            "csrf_token": self._headers.get("X-Csrf-Token"),
            "cookies": cookies,
        }

    async def async_open_session(self) -> None:
        if self._session is None or self._session.closed:
            _trace("Opening new Mashov client session")
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60, connect=30),
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
            )

    async def async_close(self):
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
        _LOGGER.info("=== MASHOV CLIENT INIT START ===")
        _LOGGER.info(
            "Initializing Mashov client for school=%s, year=%s, user=%s",
            self.school_id or self.school_name,
            self.year,
            self.username,
        )
        _LOGGER.info("API Base URL: %s", self._api_base)
        await self.async_open_session()

        # Add retry mechanism for login
        max_retries = 3
        retry_delay = 2

        if self.school_id is None and self.school_name:
            _LOGGER.debug("Resolving school name '%s' to semel", self.school_name)
            matches = await self.async_search_schools(self.school_name, self.year)
            if not matches:
                _LOGGER.error("No schools found matching '%s'", self.school_name)
                raise MashovError(f"No schools match '{self.school_name}'")
            best = next((m for m in matches if m.get("name") == self.school_name), matches[0])
            self.school_id = int(best.get("semel") or best.get("id"))
            _LOGGER.info("Resolved school '%s' to semel %s", best.get("name"), self.school_id)

        # Attempt to restore session
        if self._saved_auth and not self._session.closed:
            _LOGGER.info("Attempting to restore session from cached auth data")
            try:
                # Restore cookies
                saved_cookies = self._saved_auth.get("cookies", {})
                if saved_cookies:
                    self._session.cookie_jar.update_cookies(saved_cookies)
                    _LOGGER.debug("Restored %d cookies from cache", len(saved_cookies))

                # Restore headers
                csrf = self._saved_auth.get("csrf_token")
                if csrf:
                    self._headers["X-Csrf-Token"] = csrf
                    self._headers["Accept"] = "application/json"
                    _LOGGER.debug("Restored CSRF token from cache")

                # Restore internal auth data
                self._auth_data = self._saved_auth.get("local_auth", {})

                # Verify session validity with a lightweight call (ME endpoint)
                try:
                    async with self._session.get(self._me_endpoint, headers=self._headers) as resp:
                        if resp.status == 200:
                            _LOGGER.info("Session restored successfully (Me endpoint returned 200)")
                            # We can skip login
                            await self._extract_students()
                            return
                        else:
                            _LOGGER.warning("Restored session invalid (Me endpoint returned %s) - proceeding to login", resp.status)
                except Exception as e:
                    _LOGGER.warning("Error verifying restored session: %s", e)

            except Exception as e:
                _LOGGER.warning("Failed to restore session: %s", e)
                # clear potentially bad state
                self._headers = {}
                self._session.cookie_jar.clear()

        # Login
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
            "deviceVersion": "1.0.0",
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://web.mashov.info",
            "Referer": "https://web.mashov.info/students/login",
            "User-Agent": "Mozilla/5.0 (HomeAssistant) Mashov/0.5",
        }
        # Try login with retry mechanism
        for attempt in range(max_retries):
            _LOGGER.info("=== LOGIN ATTEMPT %d/%d ===", attempt + 1, max_retries)
            _LOGGER.info(
                "Login attempt %d/%d (semel=%s, year=%s, user=%s)",
                attempt + 1,
                max_retries,
                self.school_id,
                self.year,
                self.username,
            )
            _LOGGER.info("Login endpoint: %s", self._login_endpoint)
            try:
                async with self._session.post(self._login_endpoint, json=payload, headers=headers) as resp:
                    _LOGGER.info("Login response status: %s", resp.status)
                    _LOGGER.info("Login response headers: %s", dict(resp.headers))

                    if resp.status in (401, 403):
                        txt = await resp.text()
                        _LOGGER.error(
                            "Authentication failed for school=%s, year=%s, user=%s. Response: %s",
                            self.school_id,
                            self.year,
                            self.username,
                            txt,
                        )
                        raise MashovAuthError(
                            "Authentication failed. Please check your credentials, school ID, and year."
                        )
                    if resp.status >= 400:
                        txt = await resp.text()
                        _LOGGER.error("Login failed HTTP %s: %s", resp.status, txt)
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying login in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            continue
                        raise MashovError(f"Login failed HTTP {resp.status}: {txt}")

                    # Try to parse response
                    try:
                        data = await resp.json(content_type=None)
                        _LOGGER.info(
                            "Login response data keys: %s",
                            list(data.keys()) if isinstance(data, dict) else "not a dict",
                        )
                        _LOGGER.info("Login response data: %s", data)
                    except Exception as e:
                        _LOGGER.error("Failed to parse login response as JSON: %s", e)
                        txt = await resp.text()
                        _LOGGER.error("Login response text: %s", txt)
                        data = {}

                    # Check if we have authentication data

                    self._headers = {"Accept": "application/json"}

                    # Extract CSRF token from response headers
                    csrf_token = resp.headers.get("x-csrf-token") or resp.headers.get("X-Csrf-Token")
                    if csrf_token:
                        _LOGGER.debug("Found CSRF token: %s", csrf_token)
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
                    _LOGGER.error("Full response data: %s", data)
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

        # Extract students from authentication response
        await self._extract_students()

    async def _extract_students(self):
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
                _LOGGER.warning("Child without GUID found: %s", child)
                continue

            _LOGGER.info("Student %s has groups: %s", name, groups)

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
        _LOGGER.info("=== STUDENTS PROCESSING COMPLETE ===")
        _LOGGER.info("Mashov: found %d student(s): %s", len(students), ", ".join([s["name"] for s in students]))

        # Keep session open for future use - don't close it here
        _LOGGER.info("=== MASHOV CLIENT INIT COMPLETE ===")

    async def async_fetch_all(self) -> dict[str, Any]:
        _LOGGER.info("=== FETCHING ALL DATA ===")
        # Ensure session and authentication are available (lazy login)
        if not self._session or self._session.closed:
            await self.async_open_session()
        if not self._students or "X-Csrf-Token" not in self._headers:
            _LOGGER.debug("No students/csrf in memory – performing lazy login")
            await self.async_init(None)

        # Ensure we have CSRF token in headers (after lazy login should exist)
        if "X-Csrf-Token" not in self._headers:
            _LOGGER.warning("No CSRF token found in headers for data fetching")

        today = date.today()
        from_dt = (today - timedelta(days=self.homework_days_back)).isoformat()
        to_dt = (today + timedelta(days=self.homework_days_forward)).isoformat()
        today.isoformat()

        _LOGGER.info("Fetching data for %d students from %s to %s", len(self._students), from_dt, to_dt)

        async def fetch_for_student(stu):
            sid = stu["id"]

            urls = {
                "homework": self._endpoints["homework"].format(student_id=sid, start=from_dt, end=to_dt, year=self.year),
                "behavior": self._endpoints["behavior"].format(student_id=sid, start=from_dt, end=to_dt, year=self.year),
                "weekly_plan": self._endpoints["weekly_plan"].format(student_id=sid),
                "timetable": self._endpoints["timetable"].format(student_id=sid),
                "lessons_history": self._endpoints["lessons_history"].format(student_id=sid),
                "grades": self._endpoints["grades"].format(student_id=sid),
            }

            async def fetch(url_key: str):
                url = urls[url_key]
                _LOGGER.debug("Fetching %s for student %s from: %s", url_key, sid, url)
                try:
                    async with self._session.get(url, headers=self._headers) as resp:
                        _LOGGER.debug("%s response status for student %s: %s", url_key, sid, resp.status)
                        if resp.status == 401:
                            _LOGGER.warning("401 on %s for student %s, attempting re-login...", url_key, sid)
                            await self.async_init(None)  # re-login
                            return await fetch(url_key)
                        if resp.status == 404:
                            _LOGGER.warning("HTTP 404 for %s (student %s) - endpoint not available", url_key, sid)
                            return []  # Return empty list for 404 errors
                        if resp.status == 400:
                            txt = await resp.text()
                            _LOGGER.warning("HTTP 400 for %s (student %s): %s - skipping", url_key, sid, txt)
                            return []  # Return empty list for 400 errors
                        if resp.status >= 400:
                            txt = await resp.text()
                            _LOGGER.error("HTTP %s for %s (student %s): %s", resp.status, url_key, sid, txt)
                            return []  # Return empty list for other errors instead of raising
                        try:
                            data = await resp.json()
                            _LOGGER.debug(
                                "%s returned %d items for student %s",
                                url_key,
                                len(data) if isinstance(data, list) else 1,
                                sid,
                            )
                            return data
                        except Exception as e:
                            _LOGGER.debug("Failed to parse %s as JSON for student %s: %s", url_key, sid, e)
                            return await resp.text()
                except Exception as e:
                    _LOGGER.warning("Exception fetching %s for student %s: %s", url_key, sid, e)
                    return []  # Return empty list on exception

            homework, behavior, weekly_plan, timetable, lessons_history, grades = await asyncio.gather(
                fetch("homework"),
                fetch("behavior"),
                fetch("weekly_plan"),
                fetch("timetable"),
                fetch("lessons_history"),
                fetch("grades"),
            )
            return {
                "homework": self._normalize_homework(homework),
                "behavior": self._normalize_behavior(behavior),
                "weekly_plan": self._normalize_weekly_plan(weekly_plan),
                "timetable": self._normalize_timetable(timetable),
                "lessons_history": self._normalize_lessons_history(lessons_history),
                "grades": self._normalize_grades(grades),
            }

        _LOGGER.debug("Fetching data for all students in parallel")
        # Use asyncio.gather for parallel execution
        results = await asyncio.gather(*(fetch_for_student(s) for s in self._students))

        # Fetch holidays once (not per student)
        holidays_raw = []
        try:
            url = self._endpoints.get("holidays")
            if url:
                _LOGGER.debug("Fetching holidays from: %s", url)
                async with self._session.get(url, headers=self._headers) as resp:
                    if resp.status >= 400:
                        _LOGGER.warning("Holidays endpoint returned %s", resp.status)
                        holidays_raw = []
                    else:
                        holidays_raw = await resp.json(content_type=None)
        except Exception as e:
            _LOGGER.debug("Failed fetching holidays: %s", e)
            holidays_raw = []

        holidays = self._normalize_holidays(holidays_raw)
        by_slug = {self._students[i]["slug"]: results[i] for i in range(len(self._students))}

        result = {
            "students": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "slug": s["slug"],
                    "year": self.year,
                    "school_id": self.school_id,
                }
                for s in self._students
            ],
            "by_slug": by_slug,
            "holidays": holidays,
        }

        _LOGGER.debug("Data fetch completed for %d students", len(self._students))
        return result

    # Normalizers
    def _normalize_weekly_plan(self, raw):
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
