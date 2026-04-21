"""Tests for TwinCAT IoT Communicator repair flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.twincat_iot_communicator.const import DOMAIN
from homeassistant.components.twincat_iot_communicator.repairs import (
    StaleDevicesRepairFlow,
    async_create_fix_flow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import (
    MOCK_DEVICE_NAME,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry."""
    from .conftest import MOCK_ENTRY_DATA
    return MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA,
        unique_id="test",
        title="Test",
        version=2,
        minor_version=4,
    )


async def _setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> AsyncMock:
    """Set up a config entry with a mocked coordinator."""
    coordinator = create_mock_coordinator(
        hass,
        entry,
        {MOCK_DEVICE_NAME: build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lighting.json"])},
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.twincat_iot_communicator.TcIotCoordinator",
        return_value=coordinator,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return coordinator


async def test_async_create_fix_flow_stale_devices(hass: HomeAssistant) -> None:
    """Test that async_create_fix_flow returns StaleDevicesRepairFlow for stale_devices."""
    flow = await async_create_fix_flow(hass, "stale_devices", None)
    assert isinstance(flow, StaleDevicesRepairFlow)


async def test_async_create_fix_flow_unknown_raises(hass: HomeAssistant) -> None:
    """Test that async_create_fix_flow raises for unknown issue_id."""
    with pytest.raises(ValueError, match="Unknown issue_id"):
        await async_create_fix_flow(hass, "unknown_issue", None)


async def test_stale_devices_repair_flow_removes_widgets_only(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the repair flow removes only stale widgets, not Hub Devices."""
    coordinator = await _setup_entry(hass, mock_config_entry)
    coordinator.get_stale_widget_info.return_value = [
        (MOCK_DEVICE_NAME, "stPlug"),
    ]

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    widget = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stPlug")},
        name="Steckdose",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )
    hub_id = hub.id

    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": mock_config_entry.entry_id}

    with patch(
        "homeassistant.components.twincat_iot_communicator.repairs.ir"
    ) as mock_ir:
        result = await flow.async_step_confirm(user_input={})

    coordinator.async_remove_widget.assert_awaited_once_with(MOCK_DEVICE_NAME, "stPlug")
    coordinator.async_remove_device.assert_not_awaited()
    mock_ir.async_delete_issue.assert_called_once_with(
        hass, DOMAIN, "stale_devices",
    )
    assert result["type"] == "create_entry"
    assert dev_reg.async_get(hub_id) is not None


async def test_stale_devices_repair_flow_cleans_widget_registry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the repair flow removes stale widgets from the HA device registry."""
    coordinator = await _setup_entry(hass, mock_config_entry)
    coordinator.get_stale_widget_info.return_value = [
        (MOCK_DEVICE_NAME, "stPlug"),
    ]

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    widget = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stPlug")},
        name="Steckdose",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )
    hub_id = hub.id
    widget_id = widget.id

    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": mock_config_entry.entry_id}

    with patch(
        "homeassistant.components.twincat_iot_communicator.repairs.ir"
    ):
        await flow.async_step_confirm(user_input={})

    assert dev_reg.async_get(widget_id) is None
    assert dev_reg.async_get(hub_id) is not None


async def test_repair_flow_shows_confirmation_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the repair flow shows a confirmation form before cleanup."""
    await _setup_entry(hass, mock_config_entry)

    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": mock_config_entry.entry_id}

    result = await flow.async_step_init(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"


async def test_repair_flow_noop_without_entry(
    hass: HomeAssistant,
) -> None:
    """Test that the repair flow aborts when entry_id is missing."""
    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {}

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_repair_flow_entry_not_found(
    hass: HomeAssistant,
) -> None:
    """Test that the repair flow aborts when entry_id is valid but entry is unloaded."""
    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": "nonexistent_entry_id"}

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_repair_flow_coordinator_none(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that the repair flow aborts when entry exists but runtime_data is None."""
    mock_config_entry.add_to_hass(hass)

    flow = StaleDevicesRepairFlow()
    flow.hass = hass
    flow.data = {"entry_id": mock_config_entry.entry_id}

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"
