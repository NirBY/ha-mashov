"""Password-change and authentication failures: detection, notifications and data retention.

Protects that a ChangePass login response raises a dedicated error, that notifications
include the Mashov login link, and that the coordinator keeps the last good data
(raising UpdateFailed only when there is none).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

import custom_components.mashov as mashov_integration
from custom_components.mashov.mashov_client import MashovAuthError, MashovClient, MashovPasswordChangeRequiredError


@pytest.fixture
def enable_custom_integrations():
    """Provide a local no-op fixture for plugin-light test runs."""
    yield


class _FakeResponse:
    """Minimal aiohttp response stand-in exposing ``status``, ``headers`` and ``text()``."""

    def __init__(self, status: int, headers: dict[str, str] | None = None, text: str = "") -> None:
        self.status = status
        self.headers = headers or {}
        self._text = text

    async def text(self) -> str:
        return self._text


class _FakeRequestContext:
    """Async context manager returned by ``session.post(...)``, yielding the fake response."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    """Session stand-in whose every POST (the login call) returns the same response."""

    def __init__(self, response: _FakeResponse) -> None:
        self.closed = False
        self._response = response

    def post(self, *args, **kwargs) -> _FakeRequestContext:
        return _FakeRequestContext(self._response)


def _make_coordinator(existing_data, side_effect):
    """Build a MashovCoordinator without running ``__init__`` (no hass/scheduler needed).

    Only the attributes ``_async_update_data`` reads are set; ``async_fetch_all``
    raises ``side_effect`` and ``data`` holds the previously fetched snapshot.
    """
    coordinator = mashov_integration.MashovCoordinator.__new__(mashov_integration.MashovCoordinator)
    coordinator.name = "MashovCoordinator:Test"
    coordinator.hass = MagicMock()
    coordinator.entry = SimpleNamespace(entry_id="entry-1", title="Test School (123456)")
    coordinator.client = SimpleNamespace(
        async_fetch_all=AsyncMock(side_effect=side_effect), login_page_url="https://web.mashov.info/students/login"
    )
    coordinator.data = existing_data
    return coordinator


def test_client_raises_password_change_required_on_login_response() -> None:
    """A 403 login response with ``reason: ChangePass`` raises MashovPasswordChangeRequiredError with the login URL."""
    client = MashovClient(
        school_id="123456",
        year=2026,
        username="test_user",
        password="secret",
    )
    client._session = _FakeSession(
        _FakeResponse(
            403,
            headers={"reason": "ChangePass"},
            text='{"message":"Please change password before authenticating."}',
        )
    )

    with pytest.raises(MashovPasswordChangeRequiredError) as exc_info:
        asyncio.run(client.async_init(None))

    assert "Please change password before authenticating." in str(exc_info.value)
    assert exc_info.value.login_url == "https://web.mashov.info/students/login"


def test_password_change_notification_contains_login_link_and_cache_message() -> None:
    """The password-change notification links to the Mashov login page and says cached data is kept."""
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="entry-1", title="Test School (123456)")
    exc = MashovPasswordChangeRequiredError(
        "Please change password before authenticating.",
        "https://web.mashov.info/students/login",
    )

    with patch.object(mashov_integration.persistent_notification, "async_create") as mock_create:
        mashov_integration._async_show_password_change_notification(hass, entry, exc)

    mock_create.assert_called_once()
    args, kwargs = mock_create.call_args
    assert args[0] is hass
    assert "keep the last successful data" in args[1]
    assert exc.login_url in args[1]
    assert kwargs["title"] == "Mashov password change required"


def test_coordinator_keeps_existing_data_when_password_change_is_required() -> None:
    """With cached data, a password-change error notifies and returns the existing data unchanged."""
    existing_data = {"students": [{"id": "student-1"}], "by_slug": {}, "holidays": []}
    exc = MashovPasswordChangeRequiredError(
        "Please change password before authenticating.",
        "https://web.mashov.info/students/login",
    )
    coordinator = _make_coordinator(existing_data, exc)

    with (
        patch.object(mashov_integration, "_async_show_password_change_notification") as mock_notify,
        patch.object(mashov_integration, "_async_clear_issue_notification") as mock_clear,
    ):
        result = asyncio.run(mashov_integration.MashovCoordinator._async_update_data(coordinator))

    assert result is existing_data
    mock_notify.assert_called_once_with(coordinator.hass, coordinator.entry, exc)
    mock_clear.assert_not_called()


def test_coordinator_raises_without_existing_data_when_password_change_is_required() -> None:
    """Without cached data, a password-change error notifies and raises UpdateFailed."""
    exc = MashovPasswordChangeRequiredError(
        "Please change password before authenticating.",
        "https://web.mashov.info/students/login",
    )
    coordinator = _make_coordinator(None, exc)

    with (
        patch.object(mashov_integration, "_async_show_password_change_notification") as mock_notify,
        pytest.raises(UpdateFailed, match="Password change required"),
    ):
        asyncio.run(mashov_integration.MashovCoordinator._async_update_data(coordinator))

    mock_notify.assert_called_once_with(coordinator.hass, coordinator.entry, exc)


def test_auth_notification_contains_configure_hint_and_login_link() -> None:
    """The auth-failure notification points to the Configure dialog and the Mashov login page."""
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="entry-1", title="Test School (123456)")

    with patch.object(mashov_integration.persistent_notification, "async_create") as mock_create:
        mashov_integration._async_show_auth_notification(
            hass,
            entry,
            "Authentication failed.",
            "https://web.mashov.info/students/login",
        )

    mock_create.assert_called_once()
    args, kwargs = mock_create.call_args
    assert args[0] is hass
    assert "keep the last successful data" in args[1]
    assert "Settings -> Devices & Services -> Mashov -> Configure" in args[1]
    assert "https://web.mashov.info/students/login" in args[1]
    assert kwargs["title"] == "Mashov authentication failed"


def test_coordinator_keeps_existing_data_when_authentication_fails() -> None:
    """With cached data, an auth error notifies (with the login URL) and returns the existing data."""
    existing_data = {"students": [{"id": "student-1"}], "by_slug": {}, "holidays": []}
    exc = MashovAuthError("Authentication failed. Please check your credentials, school ID, and year.")
    coordinator = _make_coordinator(existing_data, exc)

    with (
        patch.object(mashov_integration, "_async_show_auth_notification") as mock_notify,
        patch.object(mashov_integration, "_async_clear_issue_notification") as mock_clear,
    ):
        result = asyncio.run(mashov_integration.MashovCoordinator._async_update_data(coordinator))

    assert result is existing_data
    mock_notify.assert_called_once_with(
        coordinator.hass,
        coordinator.entry,
        exc,
        coordinator.client.login_page_url,
    )
    mock_clear.assert_not_called()


def test_coordinator_raises_without_existing_data_when_authentication_fails() -> None:
    """Without cached data, an auth error notifies and raises UpdateFailed."""
    exc = MashovAuthError("Authentication failed. Please check your credentials, school ID, and year.")
    coordinator = _make_coordinator(None, exc)

    with (
        patch.object(mashov_integration, "_async_show_auth_notification") as mock_notify,
        pytest.raises(UpdateFailed, match="Auth error"),
    ):
        asyncio.run(mashov_integration.MashovCoordinator._async_update_data(coordinator))

    mock_notify.assert_called_once_with(
        coordinator.hass,
        coordinator.entry,
        exc,
        coordinator.client.login_page_url,
    )
