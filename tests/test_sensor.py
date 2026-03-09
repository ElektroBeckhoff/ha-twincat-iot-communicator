"""Tests for TwinCAT IoT Communicator sensor platform."""

from __future__ import annotations

import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.twincat_iot_communicator.const import (
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
    TcIotChargingTimeSensor,
    TcIotDescTimestamp,
    TcIotEnergyFieldSensor,
    TcIotEnergyPhaseSensor,
    TcIotHeartbeatInterval,
    TcIotLastMessage,
    TcIotLastMessageType,
    TcIotMessageCount,
    UNIT_DEVICE_CLASS_MAP,
    _create_charging_station_sensors,
    _create_energy_monitoring_sensors,
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


class TestEnergyMonitoringSensors:
    """Tests for the EnergyMonitoring widget sensors."""

    def test_sensor_count_3_phases(self, hass, mock_config_entry) -> None:
        """Test 3-phase EnergyMonitoring creates expected number of sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/energy_monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 4 scalar + 3 phases * 3 per-phase = 13
        assert len(sensors) == 13

    def test_power_sensor(self, hass, mock_config_entry) -> None:
        """Test power sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/energy_monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        power_sensor = next(s for s in sensors if s.translation_key == "power")
        assert power_sensor.device_class == SensorDeviceClass.POWER
        assert power_sensor.native_value == 11.5

    def test_energy_sensor(self, hass, mock_config_entry) -> None:
        """Test energy sensor has correct state class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/energy_monitoring.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_energy_monitoring_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        energy_sensor = next(s for s in sensors if s.translation_key == "energy")
        assert energy_sensor.state_class == SensorStateClass.TOTAL_INCREASING
        assert energy_sensor.native_value == 210.2

    def test_phase_sensor_value(self, hass, mock_config_entry) -> None:
        """Test phase sensors read from array values."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/energy_monitoring.json"])
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

    def test_sensor_count_3_phases(self, hass, mock_config_entry) -> None:
        """Test 3-phase ChargingStation creates expected number of sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 5 scalar (status, battery, power, energy, time)
        # + 3 phases * 4 per-phase (power, max power, voltage, current) = 17
        assert len(sensors) == 17

    def test_status_sensor(self, hass, mock_config_entry) -> None:
        """Test status sensor returns string value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        status = next(s for s in sensors if s.translation_key == "status")
        assert status.native_value == "Charging"

    def test_battery_sensor(self, hass, mock_config_entry) -> None:
        """Test battery sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        battery = next(s for s in sensors if s.translation_key == "battery")
        assert battery.device_class == SensorDeviceClass.BATTERY
        assert battery.native_value == 67

    def test_power_sensor(self, hass, mock_config_entry) -> None:
        """Test power sensor has correct device class and value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        power = next(s for s in sensors if s.translation_key == "power")
        assert power.device_class == SensorDeviceClass.POWER
        assert power.native_value == 7.5

    def test_energy_sensor(self, hass, mock_config_entry) -> None:
        """Test energy sensor has TOTAL_INCREASING state class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        energy = next(s for s in sensors if s.translation_key == "energy")
        assert energy.state_class == SensorStateClass.TOTAL_INCREASING
        assert energy.native_value == 10.4

    def test_charging_time_sensor(self, hass, mock_config_entry) -> None:
        """Test charging time sensor has duration device class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        time_sensor = next(s for s in sensors if isinstance(s, TcIotChargingTimeSensor))
        assert time_sensor.device_class == SensorDeviceClass.DURATION
        assert time_sensor.native_value == 2068

    def test_phase_sensor_values(self, hass, mock_config_entry) -> None:
        """Test phase sensors read correct values from arrays."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        l1_power = next(s for s in sensors if s.translation_key == "l1_power")
        assert l1_power.native_value == 4.8

    def test_1_phase_only(self, hass, mock_config_entry) -> None:
        """Test 1-phase ChargingStation creates fewer sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/charging_station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.ChargingStationPhase2Visible"] = "false"
        widget.metadata.raw["iot.ChargingStationPhase3Visible"] = "false"

        sensors = _create_charging_station_sensors(coordinator, MOCK_DEVICE_NAME, widget)
        # 5 scalar + 1 phase * 4 = 9
        assert len(sensors) == 9


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
