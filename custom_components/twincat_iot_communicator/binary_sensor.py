"""Binary sensor platform for TwinCAT IoT Communicator.

Provides:
- Per-device hub status (connectivity)
- Motion widget sensors (motion detected, output active)
- Read-only companion binary sensor for BOOL datatype widgets
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DATATYPE_BOOL,
    META_ICON,
    META_MOTION_ACTIVE_VISIBLE,
    META_MOTION_STATUS_VISIBLE,
    VAL_DATATYPE_VALUE,
    VAL_MOTION_ACTIVE,
    VAL_MOTION_MOTION,
    WIDGET_TYPE_MOTION,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotDeviceEntity, TcIotEntity
from .icon_helper import normalize_icon_name, resolve_icon
from .models import DeviceContext, WidgetData, metadata_bool

PARALLEL_UPDATES = 0

# Keys are normalized icon names (see icon_helper.normalize_icon_name):
# app icon names and Google Material Symbols ("md:...").
ICON_BINARY_SENSOR_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "Door_Closed": BinarySensorDeviceClass.DOOR,
    "Door_Open": BinarySensorDeviceClass.DOOR,
    "Garage": BinarySensorDeviceClass.GARAGE_DOOR,
    "Gate": BinarySensorDeviceClass.OPENING,
    "Lock": BinarySensorDeviceClass.LOCK,
    "Unlock": BinarySensorDeviceClass.LOCK,
    "Motion": BinarySensorDeviceClass.MOTION,
    "Plug": BinarySensorDeviceClass.PLUG,
    "Window_Closed": BinarySensorDeviceClass.WINDOW,
    "Window_Open": BinarySensorDeviceClass.WINDOW,
    # Google Material Symbols ("md:" + Google name)
    "md:door_front": BinarySensorDeviceClass.DOOR,
    "md:door_back": BinarySensorDeviceClass.DOOR,
    "md:door_sliding": BinarySensorDeviceClass.DOOR,
    "md:sensor_door": BinarySensorDeviceClass.DOOR,
    "md:garage_door": BinarySensorDeviceClass.GARAGE_DOOR,
    "md:garage_door_open": BinarySensorDeviceClass.GARAGE_DOOR,
    "md:window": BinarySensorDeviceClass.WINDOW,
    "md:sensor_window": BinarySensorDeviceClass.WINDOW,
    "md:motion_sensor_active": BinarySensorDeviceClass.MOTION,
    "md:motion_sensor_idle": BinarySensorDeviceClass.MOTION,
    "md:motion_sensor_alert": BinarySensorDeviceClass.MOTION,
    "md:motion_sensor_urgent": BinarySensorDeviceClass.MOTION,
    "md:sensor_occupied": BinarySensorDeviceClass.OCCUPANCY,
    "md:detector_smoke": BinarySensorDeviceClass.SMOKE,
    "md:detector_co": BinarySensorDeviceClass.CO,
    "md:water_damage": BinarySensorDeviceClass.MOISTURE,
    "md:flood": BinarySensorDeviceClass.MOISTURE,
    "md:outlet": BinarySensorDeviceClass.PLUG,
    "md:battery_alert": BinarySensorDeviceClass.BATTERY,
    "md:battery_very_low": BinarySensorDeviceClass.BATTERY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT binary sensors (hub status + widget sensors)."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []

    for device in coordinator.devices.values():
        entities.append(TcIotHubStatus(coordinator, device))

    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(
                _create_widget_binary_sensors(coordinator, device_name, widget)
            )

    if entities:
        async_add_entities(entities)

    def _on_new_device(device: DeviceContext) -> None:
        async_add_entities([TcIotHubStatus(coordinator, device)])

    coordinator.register_new_device_callback(_on_new_device)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[BinarySensorEntity] = []
        for widget in widgets:
            new.extend(
                _create_widget_binary_sensors(coordinator, device_name, widget)
            )
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(
        Platform.BINARY_SENSOR, _on_new_widgets,
    )


def _create_widget_binary_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[BinarySensorEntity]:
    """Create binary sensor entities for a widget based on its type."""
    wt = widget.metadata.widget_type
    if wt == WIDGET_TYPE_MOTION:
        return _create_motion_binary_sensors(coordinator, device_name, widget)
    if wt == DATATYPE_BOOL:
        return [TcIotDatatypeBinarySensor(coordinator, device_name, widget)]
    return []


def _create_motion_binary_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[BinarySensorEntity]:
    """Create binary sensor entities for a Motion widget."""
    raw = widget.metadata.raw
    entities: list[BinarySensorEntity] = []

    if metadata_bool(raw.get(META_MOTION_STATUS_VISIBLE, "")):
        entities.append(TcIotMotionSensor(coordinator, device_name, widget))

    if metadata_bool(raw.get(META_MOTION_ACTIVE_VISIBLE, "")):
        entities.append(TcIotMotionActiveSensor(coordinator, device_name, widget))

    return entities


class TcIotHubStatus(TcIotDeviceEntity, BinarySensorEntity):
    """Binary sensor representing a TcIoT device's online status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the hub status binary sensor."""
        super().__init__(coordinator, device, "hub_status")
        self._attr_translation_key = "hub_status"

    @property
    def is_on(self) -> bool:
        """Return True if the MQTT broker is connected and the device is online."""
        return self.coordinator.connected and self._dev.online

    @property
    def available(self) -> bool:
        """Always available: the connection state is this sensor's payload.

        Inheriting the device availability would make the sensor unavailable
        exactly when it should report ``off``.
        """
        return True

    @property
    def icon(self) -> str | None:
        """Return an MDI icon based on the device's configured icon name."""
        return (
            resolve_icon(self._dev.icon_name, self.coordinator.icon_mode)
            or "mdi:lan-connect"
        )


# ── Motion widget binary sensors ─────────────────────────────────────


class TcIotMotionSensor(TcIotEntity, BinarySensorEntity):
    """Motion sensor status (bMotion) — movement detected by the sensor."""

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the motion sensor binary sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_motion"
        self._attr_translation_key = "motion"

    @property
    def is_on(self) -> bool | None:
        """Return True if motion is currently detected."""
        value = self.widget.values.get(VAL_MOTION_MOTION)
        if value is None:
            return None
        return bool(value)


class TcIotMotionActiveSensor(TcIotEntity, BinarySensorEntity):
    """Motion output active (bActive) — PLC-evaluated output state."""

    _attr_device_class = None

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the motion active binary sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_active"
        self._attr_translation_key = "motion_active"

    @property
    def is_on(self) -> bool | None:
        """Return True if the PLC output is active."""
        value = self.widget.values.get(VAL_MOTION_ACTIVE)
        if value is None:
            return None
        return bool(value)


# ── Scalar BOOL datatype companion binary sensor ─────────────────────


class TcIotDatatypeBinarySensor(TcIotEntity, BinarySensorEntity):
    """Read-only binary sensor companion for PLC BOOL datatype widgets."""

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the datatype companion binary sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_binary_sensor"
        self._attr_translation_key = "dt_binary_sensor"
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        icon_key = normalize_icon_name(self.widget.metadata.raw.get(META_ICON))
        self._attr_device_class = (
            ICON_BINARY_SENSOR_CLASS_MAP.get(icon_key) if icon_key else None
        )

    @property
    def is_on(self) -> bool | None:
        """Return the current PLC BOOL value."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        return bool(value)
