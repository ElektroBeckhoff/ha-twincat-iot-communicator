"""Tests for TwinCAT IoT Communicator event platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.components.twincat_iot_communicator.event import TcIotMessageEvent
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    TcIotMessage,
)

from .conftest import create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


class TestMessageEvent:
    """Tests for the PLC message event entity."""

    def test_event_types(self, hass, mock_config_entry) -> None:
        """Test event entity has 'message' event type."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotMessageEvent(coordinator, dev)
        assert entity.event_types == ["message"]

    def test_message_fires(self, hass, mock_config_entry) -> None:
        """Test _on_message triggers event with correct data."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotMessageEvent(coordinator, dev)

        msg = TcIotMessage(
            message_id="msg42",
            timestamp="2026-02-19T08:46:23.247",
            text="Fire alarm!",
            message_type="Critical",
        )

        with patch.object(entity, "_trigger_event") as mock_trigger, \
             patch.object(entity, "async_write_ha_state"):
            entity._on_message("received", msg)
            mock_trigger.assert_called_once_with(
                "message",
                {
                    "message_id": "msg42",
                    "text": "Fire alarm!",
                    "type": "Critical",
                    "timestamp": "2026-02-19T08:46:23.247",
                },
            )

    def test_non_received_ignored(self, hass, mock_config_entry) -> None:
        """Test non-received event types are ignored."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotMessageEvent(coordinator, dev)

        with patch.object(entity, "_trigger_event") as mock_trigger:
            entity._on_message("deleted", None)
            mock_trigger.assert_not_called()

    def test_none_message_ignored(self, hass, mock_config_entry) -> None:
        """Test None message is ignored even with 'received' event type."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotMessageEvent(coordinator, dev)

        with patch.object(entity, "_trigger_event") as mock_trigger:
            entity._on_message("received", None)
            mock_trigger.assert_not_called()
