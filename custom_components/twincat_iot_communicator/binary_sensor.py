"""Binary sensor platform for TwinCAT IoT Communicator.

Provides:
- Per-device hub status (connectivity)
- Motion widget sensors (motion detected, output active)
- Read-only companion binary sensor for BOOL datatype widgets
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DATATYPE_BOOL,
    META_ICON,
    META_MOTION_ACTIVE_VISIBLE,
    META_MOTION_STATUS_VISIBLE,
    TCIOT_ICON_MAP,
    VAL_DATATYPE_VALUE,
    VAL_MOTION_ACTIVE,
    VAL_MOTION_MOTION,
    WIDGET_TYPE_MOTION,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotDeviceEntity, TcIotEntity
from .models import DeviceContext, WidgetData

PARALLEL_UPDATES = 0

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

    if raw.get(META_MOTION_STATUS_VISIBLE, "").lower() == "true":
        entities.append(TcIotMotionSensor(coordinator, device_name, widget))

    if raw.get(META_MOTION_ACTIVE_VISIBLE, "").lower() == "true":
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
        self._unsub_hub: Callable[[], None] | None = None
        self._attr_translation_key = "hub_status"

    @property
    def is_on(self) -> bool:
        """Return True if the MQTT broker is connected and the device is online."""
        return self.coordinator.connected and self._dev.online

    @property
    def icon(self) -> str | None:
        """Return an MDI icon based on the device's configured icon name."""
        name = self._dev.icon_name
        if name:
            return TCIOT_ICON_MAP.get(name, "mdi:lan-connect")
        return "mdi:lan-connect"

    async def async_added_to_hass(self) -> None:
        """Register the hub status callback when the entity is added."""
        self._unsub_hub = self.coordinator.register_hub_status_callback(
            self._dev.device_name, self._on_update,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the hub status callback when the entity is removed."""
        if self._unsub_hub:
            self._unsub_hub()
            self._unsub_hub = None

    @callback
    def _on_update(self) -> None:
        """Handle a hub status update from the coordinator."""
        self.async_write_ha_state()


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

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

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
        icon_name = self.widget.metadata.raw.get(META_ICON, "")
        self._attr_device_class = ICON_BINARY_SENSOR_CLASS_MAP.get(icon_name)

    @property
    def is_on(self) -> bool | None:
        """Return the current PLC BOOL value."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        return bool(value)
