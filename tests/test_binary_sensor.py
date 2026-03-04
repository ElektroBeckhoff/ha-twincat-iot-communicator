"""Tests for TwinCAT IoT Communicator binary sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.twincat_iot_communicator.binary_sensor import (
    TcIotHubStatus,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.const import EntityCategory

from .conftest import (
    MOCK_DEVICE_NAME,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry


class TestHubStatus:
    """Tests for the hub connectivity binary sensor."""

    def test_is_on_connected_online(self, hass, mock_config_entry) -> None:
        """Test is_on is True when connected and online."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is True

    def test_is_on_disconnected(self, hass, mock_config_entry) -> None:
        """Test is_on is False when coordinator is disconnected."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        coordinator.connected = False
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is False

    def test_is_on_offline_device(self, hass, mock_config_entry) -> None:
        """Test is_on is False when device is offline."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = False
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is False

    def test_device_class(self, hass, mock_config_entry) -> None:
        """Test hub status has connectivity device class."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.device_class == BinarySensorDeviceClass.CONNECTIVITY
        assert entity.entity_category == EntityCategory.DIAGNOSTIC

    def test_icon_mapped(self, hass, mock_config_entry) -> None:
        """Test icon mapping from device icon name."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.icon_name = "Lightbulb"
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.icon == "mdi:lightbulb"

    def test_icon_default(self, hass, mock_config_entry) -> None:
        """Test default icon when no icon name is set."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.icon == "mdi:lan-connect"


class TestHubStatusCallbackCleanup:
    """Tests for hub status callback deregistration."""

    @pytest.mark.asyncio
    async def test_remove_calls_unsub_hub(self, hass, mock_config_entry) -> None:
        """async_will_remove_from_hass calls the unregister callable."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        await entity.async_added_to_hass()

        unsub = coordinator.register_hub_status_callback.return_value
        assert entity._unsub_hub is unsub

        await entity.async_will_remove_from_hass()
        unsub.assert_called_once()
        assert entity._unsub_hub is None
