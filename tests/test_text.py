"""Tests for TwinCAT IoT Communicator text platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import DATATYPE_STRING
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.components.twincat_iot_communicator.text import TcIotDatatypeText
from homeassistant.exceptions import ServiceValidationError

from .conftest import create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


def _make_text(
    hass, entry: MockConfigEntry
) -> tuple[TcIotDatatypeText, MagicMock]:
    """Create a TcIotDatatypeText for testing."""
    meta = WidgetMetaData(display_name="Test Text", widget_type=DATATYPE_STRING)
    widget = WidgetData(
        widget_id="stScenes.sSTRING",
        path="stScenes.sSTRING",
        metadata=meta,
        values={"value": "Hello"},
        friendly_path="Test Text",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets["stScenes.sSTRING"] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotDatatypeText(coordinator, MOCK_DEVICE_NAME, widget)
    return entity, coordinator


class TestTextEntity:
    """Tests for the text entity."""

    def test_native_value(self, hass, mock_config_entry) -> None:
        """Test native value reads from widget values."""
        entity, _ = _make_text(hass, mock_config_entry)
        assert entity.native_value == "Hello"

    def test_set_value(self, hass, mock_config_entry) -> None:
        """Test set_value sends correct command."""
        entity, coord = _make_text(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_value("World"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] == "World"

    def test_set_value_truncated(self, hass, mock_config_entry) -> None:
        """Test value longer than 255 chars is truncated."""
        entity, coord = _make_text(hass, mock_config_entry)
        long_value = "A" * 300
        hass.loop.run_until_complete(entity.async_set_value(long_value))
        cmd = coord.async_send_command.call_args[0][1]
        assert len(cmd[entity.widget.path]) == 255

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test set_value raises for read-only widget."""
        entity, _ = _make_text(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_value("test"))
