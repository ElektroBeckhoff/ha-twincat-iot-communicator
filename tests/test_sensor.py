"""Tests for TwinCAT IoT Communicator sensor platform."""

from __future__ import annotations

from unittest.mock import patch as _patch

import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.twincat_iot_communicator.const import (
    DATATYPE_ARRAY_BOOL,
    VAL_AC_MODE,
    VAL_CHARGING_BATTERY_LEVEL,
    VAL_CHARGING_CURRENT_POWER,
    VAL_CHARGING_ENERGY,
    VAL_CHARGING_STATUS,
    VAL_CHARGING_TIME,
    VAL_ENERGY_CURRENT_POWER,
    VAL_ENERGY_STATUS,
    VAL_ENERGY_VALUE,
    WIDGET_TYPE_ENERGY_MONITORING,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    TcIotMessage,
)
from homeassistant.components.twincat_iot_communicator.sensor import (
    AC_MODE_MAP,
    AC_MODE_OPTIONS,
    TcIotAcModeSensor,
    TcIotChargingTimeSensor,
    TcIotDatatypeSensor,
    TcIotDescTimestamp,
    TcIotEnergyFieldSensor,
    TcIotEnergyPhaseSensor,
    TcIotHeartbeatInterval,
    TcIotLastMessage,
    TcIotLastMessageType,
    TcIotMessageCount,
    UNIT_DEVICE_CLASS_MAP,
    _create_ac_sensors,
    _create_charging_station_sensors,
    _create_energy_monitoring_sensors,
    _create_general_sensors,
    _create_lock_sensors,
    _create_motion_sensors,
    _create_widget_sensors,
)
from homeassistant.const import EntityCategory

from .conftest import build_device_with_widgets, create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


def _make_device_context(
    device_name: str = MOCK_DEVICE_NAME,
) -> DeviceContext:
    """Create a DeviceContext with typical state for sensor tests."""
    dev = DeviceContext(device_name=device_name)
    dev.online = True
    dev.registered = True
    dev.desc_timestamp = "2026-02-19T08:46:23.247"
    dev.messages = {
        "msg1": TcIotMessage(
            message_id="msg1",
            timestamp="2026-02-19T08:46:23.247",
            text="Test message",
            message_type="Warning",
        ),
        "msg2": TcIotMessage(
            message_id="msg2",
            timestamp="2026-02-19T08:47:00.000",
            text="Another message",
            message_type="Error",
            acknowledged=True,
        ),
    }
    return dev


class TestDescTimestamp:
    """Tests for the Desc timestamp diagnostic sensor."""

    def test_native_value(self, hass, mock_config_entry) -> None:
        """Test timestamp sensor returns parsed datetime."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotDescTimestamp(coordinator, dev)
        assert entity.native_value is not None
        assert entity.native_value.year == 2026

    def test_category(self, hass, mock_config_entry) -> None:
        """Test timestamp sensor is diagnostic category."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotDescTimestamp(coordinator, dev)
        assert entity.entity_category == EntityCategory.DIAGNOSTIC

    def test_none_timestamp(self, hass, mock_config_entry) -> None:
        """Test returns None when no timestamp is set."""
        dev = _make_device_context()
        dev.desc_timestamp = None
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotDescTimestamp(coordinator, dev)
        assert entity.native_value is None


class TestHeartbeatInterval:
    """Tests for the heartbeat interval diagnostic sensor."""

    def test_none_before_calibration(self, hass, mock_config_entry) -> None:
        """Test returns None when no interval has been measured yet."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHeartbeatInterval(coordinator, dev)
        assert entity.native_value is None

    def test_returns_measured_interval(self, hass, mock_config_entry) -> None:
        """Test returns the measured desc_interval in seconds."""
        dev = _make_device_context()
        dev.desc_interval = 10.5
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHeartbeatInterval(coordinator, dev)
        assert entity.native_value == 10.5

    def test_device_class_and_unit(self, hass, mock_config_entry) -> None:
        """Test sensor has duration device class and seconds unit."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHeartbeatInterval(coordinator, dev)
        assert entity.device_class == SensorDeviceClass.DURATION
        assert entity.native_unit_of_measurement == "s"
        assert entity.entity_category == EntityCategory.DIAGNOSTIC


class TestMessageCount:
    """Tests for the message count sensor."""

    def test_counts_unacknowledged(self, hass, mock_config_entry) -> None:
        """Test counts only unacknowledged messages."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotMessageCount(coordinator, dev)
        assert entity.native_value == 1  # msg1 unack, msg2 ack


class TestLastMessage:
    """Tests for the last message sensor."""

    def test_initially_none(self, hass, mock_config_entry) -> None:
        """Test native value is None initially."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotLastMessage(coordinator, dev)
        assert entity.native_value is None

    def test_after_message(self, hass, mock_config_entry) -> None:
        """Test native value updates after receiving a message callback."""
        from unittest.mock import patch as _patch

        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotLastMessage(coordinator, dev)
        msg = dev.messages["msg1"]
        with _patch.object(entity, "async_write_ha_state"):
            entity._on_message("received", msg)
        assert entity.native_value == "Test message"
        assert entity.extra_state_attributes["message_id"] == "msg1"


class TestLastMessageType:
    """Tests for the last message type sensor."""

    def test_initially_none(self, hass, mock_config_entry) -> None:
        """Test native value is None initially."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotLastMessageType(coordinator, dev)
        assert entity.native_value is None

    def test_native_value_after_message(self, hass, mock_config_entry) -> None:
        """Test native_value returns message_type after _on_message fires."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotLastMessageType(coordinator, dev)
        entity.hass = hass
        entity.entity_id = "sensor.test_last_msg_type"
        entity._attr_name = "Test"

        msg = TcIotMessage(
            message_id="msg99",
            timestamp="2026-04-12T10:00:00.000",
            text="Temperature warning",
            message_type="Critical",
        )
        with _patch.object(entity, "async_write_ha_state"):
            entity._on_message("received", msg)
        assert entity.native_value == "Critical"

    def test_non_received_event_ignored(self, hass, mock_config_entry) -> None:
        """Test that non-'received' event types do not update native_value."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotLastMessageType(coordinator, dev)

        msg = TcIotMessage(
            message_id="msg99",
            timestamp="2026-04-12T10:00:00.000",
            text="whatever",
            message_type="Info",
        )
        entity._on_message("deleted", msg)
        assert entity.native_value is None


class TestEnergyMonitoringSensors:
    """Tests for the EnergyMonitoring widget sensors."""

    def test_sensor_count_energy_3_phases(self, hass, mock_config_entry) -> None:
        """Test 3-phase EnergyMonitoring creates expected number of sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-energy-monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 4 scalar + 3 phases * 3 per-phase = 13
        assert len(sensors) == 13

    def test_power_sensor(self, hass, mock_config_entry) -> None:
        """Test power sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-energy-monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        power_sensor = next(s for s in sensors if s.translation_key == "power")
        assert power_sensor.device_class == SensorDeviceClass.POWER
        assert power_sensor.native_value == 11.5

    def test_energy_sensor(self, hass, mock_config_entry) -> None:
        """Test energy sensor has correct state class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-energy-monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        energy_sensor = next(s for s in sensors if s.translation_key == "energy")
        assert energy_sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert energy_sensor.native_value == 210.2

    def test_phase_sensor_value(self, hass, mock_config_entry) -> None:
        """Test phase sensors read from array values."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-energy-monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        l1_power = next(s for s in sensors if s.translation_key == "l1_power")
        assert l1_power.native_value == 4.8


class TestDescTimestampCallbackCleanup:
    """Tests for DescTimestamp hub callback deregistration."""

    @pytest.mark.asyncio
    async def test_remove_calls_unsub_hub(self, hass, mock_config_entry) -> None:
        """async_will_remove_from_hass calls the unregister callable."""
        dev = _make_device_context()
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotDescTimestamp(coordinator, dev)
        await entity.async_added_to_hass()

        unsub = coordinator.register_hub_status_callback.return_value
        assert entity._unsub_hub is unsub

        await entity.async_will_remove_from_hass()
        unsub.assert_called_once()
        assert entity._unsub_hub is None


class TestChargingStationSensors:
    """Tests for the ChargingStation widget sensors."""

    def test_sensor_count_charging_3_phases(self, hass, mock_config_entry) -> None:
        """Test 3-phase ChargingStation creates expected number of sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 5 scalar (status, battery, power, energy, time)
        # + 3 phases * 4 per-phase (power, max power, voltage, current) = 17
        assert len(sensors) == 17

    def test_status_sensor(self, hass, mock_config_entry) -> None:
        """Test status sensor returns string value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        status = next(s for s in sensors if s.translation_key == "status")
        assert status.native_value == "Charging"

    def test_battery_sensor(self, hass, mock_config_entry) -> None:
        """Test battery sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        battery = next(s for s in sensors if s.translation_key == "battery")
        assert battery.device_class == SensorDeviceClass.BATTERY
        assert battery.native_value == 67

    def test_power_sensor(self, hass, mock_config_entry) -> None:
        """Test power sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        power = next(s for s in sensors if s.translation_key == "power")
        assert power.device_class == SensorDeviceClass.POWER
        assert power.native_value == 7.5

    def test_energy_sensor(self, hass, mock_config_entry) -> None:
        """Test energy sensor has TOTAL_INCREASING state class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        energy = next(s for s in sensors if s.translation_key == "energy")
        assert energy.state_class == SensorStateClass.TOTAL_INCREASING
        assert energy.native_value == 10.4

    def test_charging_time_sensor(self, hass, mock_config_entry) -> None:
        """Test charging time sensor has duration device class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        time_sensor = next(s for s in sensors if isinstance(s, TcIotChargingTimeSensor))
        assert time_sensor.device_class == SensorDeviceClass.DURATION
        assert time_sensor.native_value == 2068

    def test_phase_sensor_values(self, hass, mock_config_entry) -> None:
        """Test phase sensors read correct values from arrays."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        l1_power = next(s for s in sensors if s.translation_key == "l1_power")
        assert l1_power.native_value == 4.8

    def test_1_phase_only(self, hass, mock_config_entry) -> None:
        """Test 1-phase ChargingStation creates fewer sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.ChargingStationPhase2Visible"] = "false"
        widget.metadata.raw["iot.ChargingStationPhase3Visible"] = "false"

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 5 scalar + 1 phase * 4 = 9
        assert len(sensors) == 9


class TestLockSensors:
    """Tests for Lock widget state sensor."""

    def test_creates_state_sensor(self, hass, mock_config_entry) -> None:
        """Test lock state sensor is created when visible."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_lock_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        assert sensors[0].translation_key == "lock_state"
        assert sensors[0].native_value == "Locked"

    def test_hidden_state_no_sensors(self, hass, mock_config_entry) -> None:
        """Test no sensor created when LockStateVisible is false."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.LockStateVisible"] = "false"
        sensors = _create_lock_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 0


class TestMotionSensors:
    """Tests for Motion widget battery sensor."""

    def test_battery_hidden(self, hass, mock_config_entry) -> None:
        """Test no sensor when MotionBatteryVisible=false."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/variants/widget-motion-battery-hidden.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_motion_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 0

    def test_battery_visible(self, hass, mock_config_entry) -> None:
        """Test battery sensor created when MotionBatteryVisible is true (fixture default)."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_motion_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        assert sensors[0].translation_key == "motion_battery"
        assert sensors[0].device_class == SensorDeviceClass.BATTERY
        assert sensors[0].native_value == 87


class TestAcModeSensor:
    """Tests for the AC widget mode sensor."""

    def test_creates_sensor(self, hass, mock_config_entry) -> None:
        """Test AC widget creates exactly one mode sensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_ac_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        assert isinstance(sensors[0], TcIotAcModeSensor)

    def test_device_class_is_enum(self, hass, mock_config_entry) -> None:
        """Test sensor uses ENUM device class with correct options."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotAcModeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == SensorDeviceClass.ENUM
        assert sensor.options == AC_MODE_OPTIONS

    def test_value_none_for_mode_0(self, hass, mock_config_entry) -> None:
        """Test nAcMode=0 maps to 'none'."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotAcModeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.native_value == "none"

    @pytest.mark.parametrize(
        ("mode_int", "expected"),
        [
            (1, "cooling"),
            (2, "ventilation"),
            (3, "heating"),
            (4, "cooling_off"),
            (5, "ventilation_off"),
            (6, "heating_off"),
        ],
    )
    def test_mode_mapping(
        self, hass, mock_config_entry, mode_int, expected,
    ) -> None:
        """Test each E_IoT_AcMode value maps to the correct string."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.values[VAL_AC_MODE] = mode_int
        sensor = TcIotAcModeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.native_value == expected

    def test_unknown_mode_falls_back(self, hass, mock_config_entry) -> None:
        """Test unknown nAcMode value falls back to 'none'."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.values[VAL_AC_MODE] = 99
        sensor = TcIotAcModeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.native_value == "none"

    def test_unique_id_suffix(self, hass, mock_config_entry) -> None:
        """Test unique_id ends with the AC mode field key."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotAcModeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.unique_id.endswith(f"_{VAL_AC_MODE}")

    def test_widget_sensors_dispatches_ac(self, hass, mock_config_entry) -> None:
        """Test _create_widget_sensors routes AC widgets to AC sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-ac.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        assert isinstance(sensors[0], TcIotAcModeSensor)


class TestUnitDeviceClassMap:
    """Tests for the unit to device class mapping."""

    def test_known_units(self) -> None:
        """Test common units map to expected device classes."""
        assert UNIT_DEVICE_CLASS_MAP["°C"] == SensorDeviceClass.TEMPERATURE
        assert UNIT_DEVICE_CLASS_MAP["W"] == SensorDeviceClass.POWER
        assert UNIT_DEVICE_CLASS_MAP["V"] == SensorDeviceClass.VOLTAGE
        assert UNIT_DEVICE_CLASS_MAP["A"] == SensorDeviceClass.CURRENT
        assert UNIT_DEVICE_CLASS_MAP["kWh"] == SensorDeviceClass.ENERGY
        assert UNIT_DEVICE_CLASS_MAP["ppm"] == SensorDeviceClass.CO2


class TestDatatypeSensors:
    """Tests for companion sensor entities on scalar PLC datatype widgets."""

    def test_bool_no_sensor_companion(self, hass, mock_config_entry) -> None:
        """Test BOOL datatype does NOT create a companion Sensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 0

    def test_number_sensor_unit_fallback(self, hass, mock_config_entry) -> None:
        """Test NUMBER datatype resolves device_class from iot.Unit fallback."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-lreal.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        sensor = sensors[0]
        # "Gear" icon is not mapped; "%" unit falls back to HUMIDITY
        assert sensor.device_class == SensorDeviceClass.HUMIDITY
        assert sensor.state_class == SensorStateClass.MEASUREMENT
        assert sensor.native_unit_of_measurement == "%"

    def test_string_sensor_no_device_class(self, hass, mock_config_entry) -> None:
        """Test STRING datatype with unmapped icon and no unit has no device_class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-string.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 1
        sensor = sensors[0]
        assert sensor.device_class is None
        assert sensor.state_class is None
        assert sensor.native_value == "Szene 1"

    def test_icon_maps_to_device_class(self, hass, mock_config_entry) -> None:
        """Test iot.Icon = Temperature resolves to SensorDeviceClass.TEMPERATURE."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-lreal.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.Icon"] = "Temperature"
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == SensorDeviceClass.TEMPERATURE

    def test_icon_takes_priority_over_unit(self, hass, mock_config_entry) -> None:
        """Test iot.Icon takes priority over iot.Unit for device_class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-lreal.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        # Droplet → HUMIDITY, but unit "°C" would give TEMPERATURE
        widget.metadata.raw["iot.Icon"] = "Droplet"
        widget.metadata.unit = "°C"
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == SensorDeviceClass.HUMIDITY

    def test_unique_id_has_sensor_suffix(self, hass, mock_config_entry) -> None:
        """Test companion sensor unique_id ends with _sensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-lreal.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.unique_id.endswith("_sensor")

    def test_array_type_no_sensor(self, hass, mock_config_entry) -> None:
        """Test array datatypes do NOT create companion sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/variants/datatype-bool-array.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        assert widget.metadata.widget_type == DATATYPE_ARRAY_BOOL
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(sensors) == 0

    def test_decimal_precision_from_metadata(self, hass, mock_config_entry) -> None:
        """Test REAL sensor reads DecimalPrecision for display precision."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-real.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.suggested_display_precision == 1

    def test_no_precision_without_metadata(self, hass, mock_config_entry) -> None:
        """Test INT sensor has no display precision when DecimalPrecision absent."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/base/datatype-int.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert getattr(sensor, '_attr_suggested_display_precision', None) is None


# ── General widget value sensors ─────────────────────────────────────


class TestGeneralValueSensors:
    """Tests for General widget nValue2/nValue3 read-only sensors."""

    def _make_general(self, hass, entry, **meta_overrides):
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(
            hass, entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        for k, v in meta_overrides.items():
            widget.metadata.raw[k] = v
        entities = _create_general_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        return entities, coordinator, widget

    def test_no_sensors_when_hidden(self, hass, mock_config_entry) -> None:
        """Test no sensors when Value2Visible/Value3Visible are false."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{
                "iot.GeneralValue2Visible": "false",
                "iot.GeneralValue3Visible": "false",
            },
        )
        assert len(entities) == 0

    def test_value2_visible_creates_sensor(self, hass, mock_config_entry) -> None:
        """Test only Value2Visible=true creates a single sensor for nValue2."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue3Visible": "false"},
        )
        assert len(entities) == 1
        assert isinstance(entities[0], TcIotEnergyFieldSensor)

    def test_both_visible_creates_two(self, hass, mock_config_entry) -> None:
        """Test both Value2Visible and Value3Visible create 2 sensors."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{
                "iot.GeneralValue2Visible": "true",
                "iot.GeneralValue3Visible": "true",
            },
        )
        assert len(entities) == 2
        ids = {e.unique_id for e in entities}
        assert len(ids) == 2

    def test_unit_from_field_metadata(self, hass, mock_config_entry) -> None:
        """Test sensor gets unit from field_metadata."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2Visible": "true"},
        )
        assert entities[0].native_unit_of_measurement == "%"

    def test_no_device_class_for_general(self, hass, mock_config_entry) -> None:
        """Test General sensors never guess device_class from unit."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2Visible": "true"},
        )
        assert entities[0].device_class is None
        assert entities[0].state_class is None

    def test_native_value_reads_nvalue2(self, hass, mock_config_entry) -> None:
        """Test native_value returns the current nValue2."""
        entities, _, widget = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2Visible": "true"},
        )
        widget.values["nValue2"] = 42.5
        assert entities[0].native_value == 42.5

    def test_unique_id_suffix(self, hass, mock_config_entry) -> None:
        """Test sensor unique_id ends with _nValue2 (from field_key)."""
        entities, _, _ = self._make_general(
            hass, mock_config_entry,
            **{"iot.GeneralValue2Visible": "true"},
        )
        assert entities[0].unique_id.endswith("_nValue2")

    def test_dispatch_via_create_widget_sensors(self, hass, mock_config_entry) -> None:
        """Test _create_widget_sensors dispatches General to general sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.GeneralValue2Visible"] = "true"
        sensors = _create_widget_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        assert any(e.unique_id.endswith("_nValue2") for e in sensors)
