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
    TcIotDatatypeArrayNumber,
    TcIotDatatypeNumber,
    _create_array_numbers,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator, MOCK_DEVICE_NAME

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
            hass, mock_config_entry, value=42, precision=""
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
            hass, mock_config_entry, value=42, precision=""
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


# ── Array number tests ───────────────────────────────────────────


def _make_array_numbers(
    hass,
    entry: MockConfigEntry,
    *,
    values: list[int | float] | None = None,
    unit: str | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
) -> tuple[list[TcIotDatatypeArrayNumber], MagicMock]:
    """Create array number entities from the array_int fixture."""
    dev = build_device_with_widgets(
        MOCK_DEVICE_NAME, ["datatypes/array_int.json"]
    )
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    if values is not None:
        widget.values["value"] = values
    if unit is not None:
        widget.metadata.unit = unit
    if min_val is not None:
        widget.metadata.min_value = min_val
    if max_val is not None:
        widget.metadata.max_value = max_val
    entities = _create_array_numbers(coordinator, MOCK_DEVICE_NAME, widget)
    return entities, coordinator


class TestDatatypeArrayNumber:
    """Tests for PLC numeric array entities."""

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test one entity per array element."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        assert len(entities) == 5

    def test_naming(self, hass, mock_config_entry) -> None:
        """Test entity names are bracket-indexed."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        names = [e.name for e in entities]
        assert names == ["[0]", "[1]", "[2]", "[3]", "[4]"]

    def test_native_value(self, hass, mock_config_entry) -> None:
        """Test first element has the correct value."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        assert entities[0].native_value == 55
        assert entities[1].native_value == 0

    def test_bounds_check(self, hass, mock_config_entry) -> None:
        """Test out-of-bounds index returns None."""
        entities, _ = _make_array_numbers(hass, mock_config_entry, values=[10])
        entity = entities[0]
        entity.widget.values["value"] = []
        assert entity.native_value is None

    def test_unit_from_metadata(self, hass, mock_config_entry) -> None:
        """Test unit is read from widget metadata."""
        entities, _ = _make_array_numbers(hass, mock_config_entry, unit="°C")
        assert entities[0].native_unit_of_measurement == "°C"

    def test_min_max_from_metadata(self, hass, mock_config_entry) -> None:
        """Test min/max are read from widget metadata."""
        entities, _ = _make_array_numbers(
            hass, mock_config_entry, min_val=10.0, max_val=200.0
        )
        assert entities[0].native_min_value == 10.0
        assert entities[0].native_max_value == 200.0

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all unique IDs are distinct."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 5

    def test_none_element_returns_none(self, hass, mock_config_entry) -> None:
        """Test that a None element in the array returns None."""
        entities, _ = _make_array_numbers(
            hass, mock_config_entry, values=[55, None, 0]
        )
        assert entities[0].native_value == 55
        assert entities[1].native_value is None
        assert entities[2].native_value == 0

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test writes are always blocked."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entities[0].async_set_native_value(42.0))
