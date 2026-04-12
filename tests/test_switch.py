"""Tests for TwinCAT IoT Communicator switch platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_MOTION_ON,
    VAL_PLUG_ON,
    VAL_TIMESWITCH_MONDAY,
    VAL_TIMESWITCH_ON,
    VAL_TIMESWITCH_YEARLY,
)
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_GENERAL_VALUE1,
    WIDGET_TYPE_GENERAL,
)
from homeassistant.components.twincat_iot_communicator.switch import (
    TcIotDatatypeArraySwitch,
    TcIotDatatypeSwitch,
    TcIotGeneralSwitch,
    TcIotMotionSwitch,
    TcIotPlugSwitch,
    TcIotTimeSwitchBoolSwitch,
    _create_array_switches,
    _create_motion_switches,
    _create_switches,
    _create_timeswitch_switches,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import (
    attach_entity_to_hass,
    MOCK_DEVICE_NAME,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry




def _make_plug(hass, entry: MockConfigEntry) -> tuple[TcIotPlugSwitch, MagicMock]:
    """Create a TcIotPlugSwitch from the Plug fixture."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-plug.json"])
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotPlugSwitch(coordinator, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "switch")
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

    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets["stSwitch.bBOOL"] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotDatatypeSwitch(coordinator, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "switch")
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

    def test_read_only_disabled_by_default(self, hass, mock_config_entry) -> None:
        """Test read-only BOOL switch is disabled in entity registry by default."""
        entity, _ = _make_dt_switch(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        ro = TcIotDatatypeSwitch(entity.coordinator, MOCK_DEVICE_NAME, entity.widget)
        assert ro.entity_registry_enabled_default is False

    def test_writable_enabled_by_default(self, hass, mock_config_entry) -> None:
        """Test writable BOOL switch is enabled by default."""
        entity, _ = _make_dt_switch(hass, mock_config_entry)
        assert entity.entity_registry_enabled_default is True


class TestTimeSwitchSwitches:
    """Tests for TimeSwitch boolean switches."""

    def _make_ts_switches(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[list[TcIotTimeSwitchBoolSwitch], MagicMock]:
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-time-switch.json"])
        coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        entities = _create_timeswitch_switches(coordinator, MOCK_DEVICE_NAME, widget)
        for ent in entities:
            attach_entity_to_hass(hass, ent, "switch")
        return entities, coordinator

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test factory creates power + yearly + 7 days = 9 switches."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        assert len(entities) == 9

    def test_power_switch_name(self, hass, mock_config_entry) -> None:
        """Test power switch has correct name."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        power = entities[0]
        assert power.translation_key == "ts_power"

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
        yearly = next(e for e in entities if e.translation_key == "ts_yearly")
        assert yearly is not None

    def test_day_switches_names(self, hass, mock_config_entry) -> None:
        """Test all 7 weekday switches are created with correct names."""
        entities, _ = self._make_ts_switches(hass, mock_config_entry)
        keys = {e.translation_key for e in entities}
        for day in ("ts_monday", "ts_tuesday", "ts_wednesday", "ts_thursday",
                     "ts_friday", "ts_saturday", "ts_sunday"):
            assert day in keys

    def test_monday_turn_on(self, hass, mock_config_entry) -> None:
        """Test Monday switch sends correct command."""
        entities, coord = self._make_ts_switches(hass, mock_config_entry)
        monday = next(e for e in entities if e.translation_key == "ts_monday")
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
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-time-switch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchDaysVisible"] = "false"
        entities = _create_timeswitch_switches(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 2

    def test_yearly_hidden_reduces_count(self, hass, mock_config_entry) -> None:
        """Test hiding yearly reduces to power + 7 days = 8."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-time-switch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchDateYearlyVisible"] = "false"
        entities = _create_timeswitch_switches(coordinator, MOCK_DEVICE_NAME, widget)
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
        MOCK_DEVICE_NAME, ["datatypes/variants/datatype-bool-array.json"]
    )
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    if values is not None:
        widget.values["value"] = values
    entities = _create_array_switches(coordinator, MOCK_DEVICE_NAME, widget)
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
        assert [e.__dict__["__attr_name"] for e in entities] == ["[0]", "[1]", "[2]", "[3]"]

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


# ── Motion switch tests ─────────────────────────────────────────────


class TestMotionSwitch:
    """Tests for the Motion widget bOn switch."""

    def _make_motion_switch(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[TcIotMotionSwitch, MagicMock]:
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_motion_switches(coordinator, MOCK_DEVICE_NAME, widget)
        attach_entity_to_hass(hass, entities[0], "switch")
        return entities[0], coordinator

    def test_creates_one_switch(self, hass, mock_config_entry) -> None:
        """Test factory creates exactly one switch."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_motion_switches(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1

    def test_is_on_false(self, hass, mock_config_entry) -> None:
        """Test is_on reflects bOn value (fixture has False)."""
        entity, _ = self._make_motion_switch(hass, mock_config_entry)
        assert entity.is_on is False

    def test_turn_on(self, hass, mock_config_entry) -> None:
        """Test turn_on sends bOn=True."""
        entity, coord = self._make_motion_switch(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MOTION_ON}"] is True

    def test_turn_off(self, hass, mock_config_entry) -> None:
        """Test turn_off sends bOn=False."""
        entity, coord = self._make_motion_switch(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MOTION_ON}"] is False

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only widget."""
        entity, _ = self._make_motion_switch(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_turn_on())

    def test_hidden_switch_no_entities(self, hass, mock_config_entry) -> None:
        """Test no switch is created when MotionOnSwitchVisible is false."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.MotionOnSwitchVisible"] = "false"
        entities = _create_motion_switches(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 0


# ── General switch tests ─────────────────────────────────────────────


class TestGeneralSwitch:
    """Tests for the General widget bValue1 switch."""

    def _make_general(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[TcIotGeneralSwitch, MagicMock]:
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        entity = TcIotGeneralSwitch(coordinator, MOCK_DEVICE_NAME, widget)
        attach_entity_to_hass(hass, entity, "switch")
        return entity, coordinator

    def test_factory_creates_general_switch(self, hass, mock_config_entry) -> None:
        """Test _create_switches routes General widget to TcIotGeneralSwitch."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_switches(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1
        assert isinstance(entities[0], TcIotGeneralSwitch)

    def test_factory_skips_when_not_visible(self, hass, mock_config_entry) -> None:
        """Test no switch is created when GeneralValue1SwitchVisible is false."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.GeneralValue1SwitchVisible"] = "false"
        entities = _create_switches(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 0

    def test_device_class(self, hass, mock_config_entry) -> None:
        """Test general switch has SWITCH device class."""
        entity, _ = self._make_general(hass, mock_config_entry)
        assert entity.device_class == SwitchDeviceClass.SWITCH

    def test_is_on_false(self, hass, mock_config_entry) -> None:
        """Test is_on reflects bValue1 (fixture has False)."""
        entity, _ = self._make_general(hass, mock_config_entry)
        assert entity.is_on is False

    def test_is_on_true(self, hass, mock_config_entry) -> None:
        """Test is_on returns True when bValue1 is True."""
        entity, _ = self._make_general(hass, mock_config_entry)
        entity.widget.values[VAL_GENERAL_VALUE1] = True
        assert entity.is_on is True

    def test_is_on_none(self, hass, mock_config_entry) -> None:
        """Test is_on returns None when bValue1 is missing."""
        entity, _ = self._make_general(hass, mock_config_entry)
        entity.widget.values.pop(VAL_GENERAL_VALUE1, None)
        assert entity.is_on is None

    def test_turn_on(self, hass, mock_config_entry) -> None:
        """Test turn_on sends bValue1=True."""
        entity, coord = self._make_general(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_GENERAL_VALUE1}"] is True

    def test_turn_off(self, hass, mock_config_entry) -> None:
        """Test turn_off sends bValue1=False."""
        entity, coord = self._make_general(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_GENERAL_VALUE1}"] is False

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only general widget."""
        entity, _ = self._make_general(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_turn_on())
