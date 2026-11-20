"""A broken refresh must not replace real data with successful empty lists."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.mashov_client import MashovAuthError, MashovClient


async def test_schedule_change_cancels_old_poll(hass, mock_config_entry):
    """Switching to a non-interval schedule cancels the pending poll and clears ``update_interval``."""
    from custom_components.mashov import MashovCoordinator

    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    cancel = MagicMock()
    coordinator._unsub_refresh = cancel
    coordinator.set_interval_minutes(None)
    cancel.assert_called_once()
    assert coordinator.update_interval is None
    assert coordinator._unsub_refresh is None
    await coordinator.async_shutdown()


def _core_client(status):
    client = MashovClient("123", 2027, "test", "test")
    client._students = [{"id": "synthetic", "slug": "synthetic", "name": "Example"}]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._ensure_valid_session = AsyncMock()
    response = MagicMock(status=status, headers={})
    response.text = AsyncMock(return_value="private server text")
    # session.get() is used as an async context manager yielding the response.
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False)
    client._session.get.return_value = context
    return client


async def test_core_auth_error_propagates_without_server_text():
    """A core 401 that survives the single re-login raises (without server text) instead of returning empty lists."""
    client = _core_client(401)
    with pytest.raises(MashovAuthError) as exc:
        await client.async_fetch_all()
    assert "private server text" not in str(exc.value)
    # The failure aborts the refresh early instead of hitting every endpoint.
    assert client._session.get.call_count <= 12


async def test_core_server_error_is_scoped_to_its_resource():
    """A core 5xx marks only that resource as failed; the rest of the refresh completes without server text."""
    client = _core_client(500)
    result = await client.async_fetch_all()
    student = result["by_slug"]["synthetic"]
    assert student["source_status"]["homework"] == "http_500"
    assert student["homework"] == []
    assert "private server text" not in json.dumps(result, default=str)
    assert result["holidays_status"] == "http_500"
