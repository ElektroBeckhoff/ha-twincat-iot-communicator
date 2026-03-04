"""Tests for TwinCAT IoT Communicator switch platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.components.twincat_iot_communicator.const import VAL_PLUG_ON
from homeassistant.components.twincat_iot_communicator.switch import (
    TcIotDatatypeSwitch,
    TcIotPlugSwitch,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


DEVICE_NAME = "TestDevice"


def _make_plug(hass, entry: MockConfigEntry) -> tuple[TcIotPlugSwitch, MagicMock]:
    """Create a TcIotPlugSwitch from the Plug fixture."""
    dev = build_device_with_widgets(DEVICE_NAME, ["widgets/plug.json"])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotPlugSwitch(coordinator, DEVICE_NAME, widget)
    return entity, coordinator


def _make_dt_switch(hass, entry: MockConfigEntry) -> tuple[TcIotDatatypeSwitch, MagicMock]:
    """Create a TcIotDatatypeSwitch from a writable BOOL fixture."""
    # Build a writable BOOL manually
    from homeassistant.components.twincat_iot_communicator.models import WidgetData, WidgetMetaData
    from homeassistant.components.twincat_iot_communicator.const import DATATYPE_BOOL

    meta = WidgetMetaData(display_name="Test Bool", widget_type=DATATYPE_BOOL)
    widget = WidgetData(
        widget_id="stSwitch.bBOOL",
        path="stSwitch.bBOOL",
        metadata=meta,
        values={"value": True},
        friendly_path="Test Bool",
    )
    from homeassistant.components.twincat_iot_communicator.models import DeviceContext

    dev = DeviceContext(device_name=DEVICE_NAME)
    dev.online = True
    dev.widgets["stSwitch.bBOOL"] = widget
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    entity = TcIotDatatypeSwitch(coordinator, DEVICE_NAME, widget)
    return entity, coordinator


class TestPlugSwitch:
    """Tests for the Plug widget switch."""

    def test_setup(self, hass, mock_config_entry) -> None:
        """Test Plug switch has outlet device class and correct is_on."""
        entity, _ = _make_plug(hass, mock_config_entry)
        assert entity.device_class == SwitchDeviceClass.OUTLET
        assert entity.is_on is False

    def test_turn_on(self, hass, mock_config_entry) -> None:
        """Test turn_on sends bOn=True."""
        entity, coord = _make_plug(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_PLUG_ON}"] is True

    def test_turn_off(self, hass, mock_config_entry) -> None:
        """Test turn_off sends bOn=False."""
        entity, coord = _make_plug(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_PLUG_ON}"] is False


class TestDatatypeSwitch:
    """Tests for the writable BOOL datatype switch."""

    def test_setup(self, hass, mock_config_entry) -> None:
        """Test datatype switch has switch device class."""
        entity, _ = _make_dt_switch(hass, mock_config_entry)
        assert entity.device_class == SwitchDeviceClass.SWITCH
        assert entity.is_on is True

    def test_turn_on(self, hass, mock_config_entry) -> None:
        """Test turn_on sends path: True."""
        entity, coord = _make_dt_switch(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] is True

    def test_turn_off(self, hass, mock_config_entry) -> None:
        """Test turn_off sends path: False."""
        entity, coord = _make_dt_switch(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] is False

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only switch."""
        entity, _ = _make_dt_switch(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_turn_on())
