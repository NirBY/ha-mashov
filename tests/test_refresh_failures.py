"""A broken refresh must not replace real data with successful empty lists."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mashov.mashov_client import MashovAuthError, MashovClient, MashovError


async def test_schedule_change_cancels_old_poll(hass, mock_config_entry):
    from custom_components.mashov import MashovCoordinator

    coordinator = MashovCoordinator(hass, MagicMock(), mock_config_entry)
    cancel = MagicMock()
    coordinator._unsub_refresh = cancel
    coordinator.set_interval_minutes(None)
    cancel.assert_called_once()
    assert coordinator.update_interval is None
    assert coordinator._unsub_refresh is None
    await coordinator.async_shutdown()


@pytest.mark.parametrize("status,error", [(401, MashovAuthError), (500, MashovError)])
async def test_core_errors_propagate(status, error):
    client = MashovClient("123", 2027, "test", "test")
    client._students = [{"id": "synthetic", "slug": "synthetic", "name": "Example"}]
    client._headers["X-Csrf-Token"] = "synthetic"
    client._ensure_valid_session = AsyncMock()
    response = MagicMock(status=status, headers={})
    response.text = AsyncMock(return_value="private server text")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client._session = MagicMock(closed=False)
    client._session.get.return_value = context
    with pytest.raises(error) as exc:
        await client.async_fetch_all()
    assert "private server text" not in str(exc.value)
    assert client._session.get.call_count <= 12
