"""Student removal must preserve current students, shared devices and history.

Covers the manual "delete device" check against the live or cached roster, refusing
removal when no roster is known, and automatic cleanup that detaches a departed
student's device only after an authoritative, non-stale refresh.
"""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mashov import async_remove_config_entry_device
from custom_components.mashov.const import DOMAIN

from .test_setup_resilience import DATA, _patch_cache, _patch_client


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("identifier,allowed", [("departed", True), ("student-123", False), ("holidays_hub", False)])
async def test_manual_removal_checks_roster(hass, mock_config_entry, cached, identifier, allowed):
    """Only a device for a student absent from the roster (live or cached) may be deleted manually."""
    device = MagicMock(identifiers={(DOMAIN, identifier)})
    # Without a loaded coordinator the check must fall back to the Store cache.
    if not cached:
        hass.data[DOMAIN] = {mock_config_entry.entry_id: {"coordinator": MagicMock(data=deepcopy(DATA))}}
    with patch("custom_components.mashov.Store") as store:
        store.return_value.async_load = AsyncMock(return_value={"data": deepcopy(DATA)})
        assert await async_remove_config_entry_device(hass, mock_config_entry, device) is allowed
        store.return_value.async_remove.assert_not_called()
        store.return_value.async_save.assert_not_called()


@pytest.mark.parametrize("data", [None, {}, {"data": {}}, {"data": {"students": None}}])
async def test_missing_roster_cannot_approve_removal(hass, mock_config_entry, data):
    """Without a usable cached roster, manual device removal is refused."""
    with patch("custom_components.mashov.Store") as store:
        store.return_value.async_load = AsyncMock(return_value=data)
        assert not await async_remove_config_entry_device(
            hass, mock_config_entry, MagicMock(identifiers={(DOMAIN, "departed")})
        )


@pytest.mark.parametrize(
    "authoritative,stale,shared",
    [(False, False, False), (True, True, False), (True, False, False), (True, False, True)],
)
async def test_automatic_cleanup_detaches_only_confirmed_departed_device(
    hass, mock_config_entry, authoritative, stale, shared
):
    """A departed device is detached only after a fresh, non-stale roster; other entries' devices remain."""
    mock_config_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    departed = devices.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, "departed")}
    )
    old = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        f"mashov_{mock_config_entry.entry_id}_departed_homework",
        config_entry=mock_config_entry,
        device_id=departed.id,
    )
    if shared:
        other = MockConfigEntry(domain=DOMAIN, data={})
        other.add_to_hass(hass)
        # Single-owner device registries need a separate device per entry;
        # otherwise the other entry is attached to the same device.
        if hasattr(departed, "config_entry_id"):
            other_device = devices.async_get_or_create(
                config_entry_id=other.entry_id, identifiers={(DOMAIN, "departed")}
            )
        else:
            other_device = devices.async_update_device(departed.id, add_config_entry_id=other.entry_id)
        retained = entities.async_get_or_create(
            "sensor",
            DOMAIN,
            f"mashov_{other.entry_id}_departed_homework",
            config_entry=other,
            device_id=other_device.id,
        )
    patcher, client = _patch_client()
    # Setup itself must not clean up; the roster/stale flags are applied to the next update.
    client.roster_refreshed = False
    try:
        with _patch_cache(None):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]["coordinator"]
        client.roster_refreshed = authoritative
        coordinator.data_stale = stale
        coordinator.async_set_updated_data(deepcopy(DATA))
        await hass.async_block_till_done()
        removed = authoritative and not stale
        assert (entities.async_get(old.entity_id) is None) == removed
        remaining = devices.async_get(departed.id)
        if removed:
            assert remaining is None or mock_config_entry.entry_id not in remaining.config_entries
        else:
            assert mock_config_entry.entry_id in remaining.config_entries
        if shared:
            assert devices.async_get(other_device.id) is not None
            assert entities.async_get(retained.entity_id) is not None
        current_entities = er.async_entries_for_config_entry(entities, mock_config_entry.entry_id)
        assert any("student-123" in entity.unique_id for entity in current_entities)
        assert any("holidays" in entity.unique_id for entity in current_entities)
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        patcher.stop()
