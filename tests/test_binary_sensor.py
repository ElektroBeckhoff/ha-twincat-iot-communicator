"""Tests for TwinCAT IoT Communicator binary sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.twincat_iot_communicator.binary_sensor import (
    ICON_BINARY_SENSOR_CLASS_MAP,
    TcIotDatatypeBinarySensor,
    TcIotHubStatus,
    TcIotMotionActiveSensor,
    TcIotMotionSensor,
    _create_motion_binary_sensors,
    _create_widget_binary_sensors,
)
from homeassistant.components.twincat_iot_communicator.const import (
    DATATYPE_ARRAY_BOOL,
    DATATYPE_BOOL,
    VAL_MOTION_ACTIVE,
    VAL_MOTION_MOTION,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.const import EntityCategory

from .conftest import (
    MOCK_DEVICE_NAME,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry


class TestHubStatus:
    """Tests for the hub connectivity binary sensor."""

    def test_is_on_connected_online(self, hass, mock_config_entry) -> None:
        """Test is_on is True when connected and online."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is True

    def test_is_on_disconnected(self, hass, mock_config_entry) -> None:
        """Test is_on is False when coordinator is disconnected."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        coordinator.connected = False
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is False

    def test_is_on_offline_device(self, hass, mock_config_entry) -> None:
        """Test is_on is False when device is offline."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = False
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.is_on is False

    def test_device_class(self, hass, mock_config_entry) -> None:
        """Test hub status has connectivity device class."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.device_class == BinarySensorDeviceClass.CONNECTIVITY
        assert entity.entity_category == EntityCategory.DIAGNOSTIC

    def test_icon_mapped(self, hass, mock_config_entry) -> None:
        """Test icon mapping from device icon name."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.icon_name = "Lightbulb"
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.icon == "mdi:lightbulb"

    def test_icon_default(self, hass, mock_config_entry) -> None:
        """Test default icon when no icon name is set."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        assert entity.icon == "mdi:lan-connect"


# ── Motion binary sensor tests ───────────────────────────────────────


class TestMotionBinarySensors:
    """Tests for Motion widget binary sensors."""

    def _make_motion_sensors(
        self, hass, entry: MockConfigEntry,
    ) -> tuple[list, MagicMock]:
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/motion.json"])
        coordinator = create_mock_coordinator(
            hass, entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_motion_binary_sensors(
            coordinator, MOCK_DEVICE_NAME, widget,
        )
        return entities, coordinator

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test factory creates 2 sensors (motion + active) when both visible."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        assert len(entities) == 2

    def test_motion_sensor_device_class(self, hass, mock_config_entry) -> None:
        """Test motion sensor has MOTION device class."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        motion = next(e for e in entities if isinstance(e, TcIotMotionSensor))
        assert motion.device_class == BinarySensorDeviceClass.MOTION

    def test_active_sensor_device_class(self, hass, mock_config_entry) -> None:
        """Test active sensor has OCCUPANCY device class."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        active = next(e for e in entities if isinstance(e, TcIotMotionActiveSensor))
        assert active.device_class == BinarySensorDeviceClass.OCCUPANCY

    def test_motion_is_on(self, hass, mock_config_entry) -> None:
        """Test motion sensor reflects bMotion value."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        motion = next(e for e in entities if isinstance(e, TcIotMotionSensor))
        assert motion.is_on is True

    def test_active_is_on(self, hass, mock_config_entry) -> None:
        """Test active sensor reflects bActive value."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        active = next(e for e in entities if isinstance(e, TcIotMotionActiveSensor))
        assert active.is_on is True

    def test_motion_none_value(self, hass, mock_config_entry) -> None:
        """Test is_on returns None when bMotion is missing."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        motion = next(e for e in entities if isinstance(e, TcIotMotionSensor))
        del motion.widget.values[VAL_MOTION_MOTION]
        assert motion.is_on is None

    def test_hidden_status_reduces_count(self, hass, mock_config_entry) -> None:
        """Test hiding MotionStatusVisible creates only 1 sensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.MotionStatusVisible"] = "false"
        entities = _create_motion_binary_sensors(
            coordinator, MOCK_DEVICE_NAME, widget,
        )
        assert len(entities) == 1
        assert isinstance(entities[0], TcIotMotionActiveSensor)

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all unique IDs are distinct."""
        entities, _ = self._make_motion_sensors(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 2


class TestHubStatusCallbackCleanup:
    """Tests for hub status callback deregistration."""

    @pytest.mark.asyncio
    async def test_remove_calls_unsub_hub(self, hass, mock_config_entry) -> None:
        """async_will_remove_from_hass calls the unregister callable."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entity = TcIotHubStatus(coordinator, dev)
        await entity.async_added_to_hass()

        unsub = coordinator.register_hub_status_callback.return_value
        assert entity._unsub_hub is unsub

        await entity.async_will_remove_from_hass()
        unsub.assert_called_once()
        assert entity._unsub_hub is None


# ── Datatype BOOL companion binary sensor tests ─────────────────────


class TestDatatypeBinarySensors:
    """Tests for companion binary sensor entities on BOOL PLC datatype widgets."""

    def test_bool_creates_binary_sensor(self, hass, mock_config_entry) -> None:
        """Test BOOL datatype creates a TcIotDatatypeBinarySensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_widget_binary_sensors(
            coordinator, MOCK_DEVICE_NAME, widget,
        )
        assert len(entities) == 1
        assert isinstance(entities[0], TcIotDatatypeBinarySensor)

    def test_is_on_reflects_value(self, hass, mock_config_entry) -> None:
        """Test is_on reflects the PLC BOOL value."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.is_on is False

    def test_icon_maps_to_device_class(self, hass, mock_config_entry) -> None:
        """Test iot.Icon = Door_Open resolves to BinarySensorDeviceClass.DOOR."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.Icon"] = "Door_Open"
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == BinarySensorDeviceClass.DOOR

    def test_window_icon(self, hass, mock_config_entry) -> None:
        """Test iot.Icon = Window_Closed resolves to WINDOW."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.Icon"] = "Window_Closed"
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == BinarySensorDeviceClass.WINDOW

    def test_unmapped_icon_no_device_class(self, hass, mock_config_entry) -> None:
        """Test unmapped icon results in no device_class."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        # bool.json has iot.Icon = "Light" which is NOT in the map
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class is None

    def test_unique_id_has_binary_sensor_suffix(self, hass, mock_config_entry) -> None:
        """Test companion binary sensor unique_id ends with _binary_sensor."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.unique_id.endswith("_binary_sensor")

    def test_array_bool_no_binary_sensor(self, hass, mock_config_entry) -> None:
        """Test array BOOL datatypes do NOT create companion binary sensors."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["datatypes/array_bool.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        assert widget.metadata.widget_type == DATATYPE_ARRAY_BOOL
        entities = _create_widget_binary_sensors(
            coordinator, MOCK_DEVICE_NAME, widget,
        )
        assert len(entities) == 0
