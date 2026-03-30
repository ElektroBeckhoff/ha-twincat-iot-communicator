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
    TcIotGeneralNumber,
    _create_array_numbers,
    _create_general_numbers,
    _create_motion_numbers,
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

    def test_read_only_disabled_by_default(self, hass, mock_config_entry) -> None:
        """Test read-only number is disabled in the entity registry by default."""
        entity, _ = _make_number(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        ro_entity = TcIotDatatypeNumber(entity.coordinator, MOCK_DEVICE_NAME, entity.widget)
        assert ro_entity.entity_registry_enabled_default is False

    def test_writable_enabled_by_default(self, hass, mock_config_entry) -> None:
        """Test writable number is enabled by default."""
        entity, _ = _make_number(hass, mock_config_entry)
        assert entity.entity_registry_enabled_default is True


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

    def test_decimal_precision_from_metadata(self, hass, mock_config_entry) -> None:
        """Test array_real with DecimalPrecision sets step and display precision."""
        dev = build_device_with_widgets(
            MOCK_DEVICE_NAME, ["datatypes/array_real.json"]
        )
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_array_numbers(coordinator, MOCK_DEVICE_NAME, widget)
        assert entities[0].native_step == 0.1
        assert entities[0].suggested_display_precision == 1

    def test_no_precision_for_int_array(self, hass, mock_config_entry) -> None:
        """Test int array without DecimalPrecision has no step/precision override."""
        entities, _ = _make_array_numbers(hass, mock_config_entry)
        assert not hasattr(entities[0], '_attr_suggested_display_precision') or \
            getattr(entities[0], '_attr_suggested_display_precision', None) is None


# ── Motion number tests ─────────────────────────────────────────────


class TestMotionNumbers:
    """Tests for Motion widget number entities."""

    def _make_motion_numbers(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[list, MagicMock]:
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/motion.json"])
        coordinator = create_mock_coordinator(
            hass, entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_motion_numbers(coordinator, MOCK_DEVICE_NAME, widget)
        return entities, coordinator

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test factory creates 4 numbers (all visible in fixture)."""
        entities, _ = self._make_motion_numbers(hass, mock_config_entry)
        assert len(entities) == 4

    def test_hold_time_value(self, hass, mock_config_entry) -> None:
        """Test hold time number has correct value."""
        entities, _ = self._make_motion_numbers(hass, mock_config_entry)
        hold = next(e for e in entities if e.translation_key == "motion_hold_time")
        assert hold.native_value == 300

    def test_hidden_field_reduces_count(self, hass, mock_config_entry) -> None:
        """Test hiding a field skips its entity."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.MotionHoldTimeVisible"] = "false"
        entities = _create_motion_numbers(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 3

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all unique IDs are distinct."""
        entities, _ = self._make_motion_numbers(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 4

    def test_reuses_general_number(self, hass, mock_config_entry) -> None:
        """Test all Motion numbers are TcIotGeneralNumber instances."""
        entities, _ = self._make_motion_numbers(hass, mock_config_entry)
        for e in entities:
            assert isinstance(e, TcIotGeneralNumber)


# ── General widget number tests ──────────────────────────────────────


class TestGeneralNumbers:
    """Tests for General widget number entities (gated by SliderVisible)."""

    def _make_general(self, hass, entry, **meta_overrides):
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/general.json"])
        coordinator = create_mock_coordinator(
            hass, entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        for k, v in meta_overrides.items():
            widget.metadata.raw[k] = v
        entities = _create_general_numbers(coordinator, MOCK_DEVICE_NAME, widget)
        return entities, coordinator

    def test_no_numbers_when_slider_hidden(self, hass, mock_config_entry) -> None:
        """Test no numbers when SliderVisible is false (fixture default)."""
        entities, _ = self._make_general(hass, mock_config_entry)
        assert len(entities) == 0

    def test_visible_not_slider_creates_no_number(self, hass, mock_config_entry) -> None:
        """Test Value2Visible=true alone does NOT create a number."""
        entities, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2Visible": "true"},
        )
        assert len(entities) == 0

    def test_slider_visible_creates_number(self, hass, mock_config_entry) -> None:
        """Test SliderVisible=true creates a number entity."""
        entities, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2SliderVisible": "true"},
        )
        assert len(entities) == 1
        assert isinstance(entities[0], TcIotGeneralNumber)

    def test_both_sliders_visible(self, hass, mock_config_entry) -> None:
        """Test both value2 and value3 slider visible creates 2 numbers."""
        entities, _ = self._make_general(
            hass, mock_config_entry,
            **{
                "iot.GeneralValue2SliderVisible": "true",
                "iot.GeneralValue3SliderVisible": "true",
            },
        )
        assert len(entities) == 2
        ids = {e.unique_id for e in entities}
        assert len(ids) == 2

    def test_slider_reads_field_metadata_unit(self, hass, mock_config_entry) -> None:
        """Test number reads unit from field_metadata."""
        entities, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2SliderVisible": "true"},
        )
        assert entities[0].native_unit_of_measurement == "%"
        assert entities[0].native_min_value == 0.0
        assert entities[0].native_max_value == 100.0

    def test_int_precision_default(self, hass, mock_config_entry) -> None:
        """Test General number defaults to step=1 / precision=0 (INT)."""
        entities, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2SliderVisible": "true"},
        )
        assert entities[0].native_step == 1.0
        assert entities[0].suggested_display_precision == 0

    def test_sends_int_command(self, hass, mock_config_entry) -> None:
        """Test set_native_value sends int when step >= 1."""
        entities, coord = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2SliderVisible": "true"},
        )
        hass.loop.run_until_complete(entities[0].async_set_native_value(50.0))
        cmd = coord.async_send_command.call_args[0][1]
        sent = list(cmd.values())[0]
        assert isinstance(sent, int)
        assert sent == 50
