"""Tests for TwinCAT IoT Communicator number platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    DATATYPE_NUMBER,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.components.twincat_iot_communicator.number import (
    TcIotDatatypeNumber,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


def _make_number(
    hass,
    entry: MockConfigEntry,
    *,
    widget_id: str = "stSensor.fREAL",
    value: float = 21.5,
    min_val: float = 0.0,
    max_val: float = 100.0,
    unit: str = "°C",
    precision: str = "1",
) -> tuple[TcIotDatatypeNumber, MagicMock]:
    """Create a TcIotDatatypeNumber with configurable parameters."""
    raw = {}
    if precision:
        raw["iot.DecimalPrecision"] = precision
    meta = WidgetMetaData(
        display_name="Test Number",
        widget_type=DATATYPE_NUMBER,
        unit=unit,
        min_value=min_val,
        max_value=max_val,
        raw=raw,
    )
    widget = WidgetData(
        widget_id=widget_id,
        path=widget_id,
        metadata=meta,
        values={"value": value},
        friendly_path="Test Number",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets[widget_id] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotDatatypeNumber(coordinator, MOCK_DEVICE_NAME, widget)
    return entity, coordinator


class TestNumberSetup:
    """Tests for number entity initialization."""

    def test_min_max_unit(self, hass, mock_config_entry) -> None:
        """Test min/max/unit from metadata."""
        entity, _ = _make_number(hass, mock_config_entry)
        assert entity.native_min_value == 0.0
        assert entity.native_max_value == 100.0
        assert entity.native_unit_of_measurement == "°C"

    def test_native_value_float(self, hass, mock_config_entry) -> None:
        """Test native value returned as float for REAL."""
        entity, _ = _make_number(hass, mock_config_entry)
        assert entity.native_value == 21.5

    def test_native_value_int(self, hass, mock_config_entry) -> None:
        """Test native value returned as int for INT type."""
        entity, _ = _make_number(
            hass,
            mock_config_entry,
            widget_id="stDataTypes.nINT",
            value=42,
            precision="0",
        )
        assert entity.native_value == 42
        assert isinstance(entity.native_value, int)

    def test_step_float(self, hass, mock_config_entry) -> None:
        """Test step is 0.1 for precision=1 on float field."""
        entity, _ = _make_number(hass, mock_config_entry, precision="1")
        assert entity.native_step == 0.1

    def test_step_int_default(self, hass, mock_config_entry) -> None:
        """Test default step is 1.0 for integer field without precision."""
        entity, _ = _make_number(
            hass, mock_config_entry, widget_id="stDataTypes.nINT", precision=""
        )
        assert entity.native_step == 1.0


class TestNumberCommands:
    """Tests for number commands."""

    def test_set_value(self, hass, mock_config_entry) -> None:
        """Test set_native_value sends correct command."""
        entity, coord = _make_number(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_native_value(25.0))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] == 25.0

    def test_set_value_int(self, hass, mock_config_entry) -> None:
        """Test set_native_value sends int for integer field."""
        entity, coord = _make_number(
            hass, mock_config_entry, widget_id="stDataTypes.nINT"
        )
        hass.loop.run_until_complete(entity.async_set_native_value(42.0))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] == 42
        assert isinstance(cmd[entity.widget.path], int)

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test set_native_value raises for read-only widget."""
        entity, _ = _make_number(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_native_value(10.0))
