"""Tests for TwinCAT IoT Communicator switch platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_PLUG_ON,
    VAL_TIMESWITCH_MONDAY,
    VAL_TIMESWITCH_ON,
    VAL_TIMESWITCH_YEARLY,
)
from homeassistant.components.twincat_iot_communicator.switch import (
    TcIotDatatypeArraySwitch,
    TcIotDatatypeSwitch,
    TcIotPlugSwitch,
    TcIotTimeSwitchBoolSwitch,
    _create_array_switches,
    _create_timeswitch_switches,
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


class TestTimeSwitchSwitches:
    """Tests for TimeSwitch boolean switches."""

    def _make_ts_switches(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[list[TcIotTimeSwitchBoolSwitch], MagicMock]:
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
        coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        entities = _create_timeswitch_switches(coordinator, DEVICE_NAME, widget)
        return entities, coordinator

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test factory creates power + yearly + 7 days = 9 switches."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        assert len(entities) == 9

    def test_power_switch_name(self, hass, mock_config_entry) -> None:
        """Test power switch has correct name."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        power = entities[0]
        assert power.name == "Power"

    def test_power_is_on(self, hass, mock_config_entry) -> None:
        """Test power switch reflects bOn value."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        power = entities[0]
        assert power.is_on is False

    def test_power_turn_on(self, hass, mock_config_entry) -> None:
        """Test power turn_on sends correct command."""
        entities, coord = self._make_ts_switches(hass, mock_config_entry)
        power = entities[0]
        hass.loop.run_until_complete(power.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{power.widget.path}.{VAL_TIMESWITCH_ON}"] is True

    def test_yearly_switch_name(self, hass, mock_config_entry) -> None:
        """Test yearly switch has correct name."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        yearly = next(e for e in entities if e.name == "Yearly")
        assert yearly is not None

    def test_day_switches_names(self, hass, mock_config_entry) -> None:
        """Test all 7 weekday switches are created with correct names."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        names = {e.name for e in entities}
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"):
            assert day in names

    def test_monday_turn_on(self, hass, mock_config_entry) -> None:
        """Test Monday switch sends correct command."""
        entities, coord = self._make_ts_switches(hass, mock_config_entry)
        monday = next(e for e in entities if e.name == "Monday")
        hass.loop.run_until_complete(monday.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{monday.widget.path}.{VAL_TIMESWITCH_MONDAY}"] is True

    def test_unique_ids_all_differ(self, hass, mock_config_entry) -> None:
        """Test all TimeSwitch switches have distinct unique IDs."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == len(entities)

    def test_days_hidden_reduces_count(self, hass, mock_config_entry) -> None:
        """Test hiding days reduces to power + yearly = 2."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchDaysVisible"] = "false"
        entities = _create_timeswitch_switches(coordinator, DEVICE_NAME, widget)
        assert len(entities) == 2

    def test_yearly_hidden_reduces_count(self, hass, mock_config_entry) -> None:
        """Test hiding yearly reduces to power + 7 days = 8."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchDateYearlyVisible"] = "false"
        entities = _create_timeswitch_switches(coordinator, DEVICE_NAME, widget)
        assert len(entities) == 8

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only TimeSwitch."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        power = entities[0]
        power.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(power.async_turn_on())


# ── Array switch tests ────────────────────────────────────────────


def _make_array_switches(
    hass,
    entry: MockConfigEntry,
    *,
    values: list[bool] | None = None,
) -> tuple[list[TcIotDatatypeArraySwitch], MagicMock]:
    """Create array switch entities from the array_bool fixture."""
    dev = build_device_with_widgets(
        DEVICE_NAME, ["datatypes/array_bool.json"]
    )
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    if values is not None:
        widget.values["value"] = values
    entities = _create_array_switches(coordinator, DEVICE_NAME, widget)
    return entities, coordinator


class TestDatatypeArraySwitch:
    """Tests for PLC BOOL array switch entities."""

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test one entity per array element."""
        entities, _ = _make_array_switches(hass, mock_config_entry)
        assert len(entities) == 4

    def test_naming(self, hass, mock_config_entry) -> None:
        """Test entity names are bracket-indexed."""
        entities, _ = _make_array_switches(hass, mock_config_entry)
        assert [e.name for e in entities] == ["[0]", "[1]", "[2]", "[3]"]

    def test_is_on(self, hass, mock_config_entry) -> None:
        """Test is_on reflects array values."""
        entities, _ = _make_array_switches(hass, mock_config_entry)
        assert entities[0].is_on is True
        assert entities[1].is_on is False
        assert entities[2].is_on is True
        assert entities[3].is_on is False

    def test_bounds_check(self, hass, mock_config_entry) -> None:
        """Test out-of-bounds index returns None."""
        entities, _ = _make_array_switches(hass, mock_config_entry, values=[True])
        entity = entities[0]
        entity.widget.values["value"] = []
        assert entity.is_on is None

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all unique IDs are distinct."""
        entities, _ = _make_array_switches(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 4

    def test_none_element_returns_none(self, hass, mock_config_entry) -> None:
        """Test that a None element in the array returns None."""
        entities, _ = _make_array_switches(
            hass, mock_config_entry, values=[True, None, False]
        )
        assert entities[0].is_on is True
        assert entities[1].is_on is None
        assert entities[2].is_on is False

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test writes are always blocked."""
        entities, _ = _make_array_switches(hass, mock_config_entry)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entities[0].async_turn_on())
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entities[0].async_turn_off())
