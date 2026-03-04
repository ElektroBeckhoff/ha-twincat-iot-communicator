"""Binary sensor platform for TwinCAT IoT Communicator.

Provides per-device hub status (connectivity).

NOTE: PLC BOOL datatypes are mapped to Switch (not BinarySensor),
because the read_only flag can change at runtime.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import TCIOT_ICON_MAP
from .coordinator import TcIotCoordinator
from .entity import TcIotDeviceEntity
from .models import DeviceContext

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT binary sensors (hub status only)."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []

    for device in coordinator.devices.values():
        entities.append(TcIotHubStatus(coordinator, device))

    if entities:
        async_add_entities(entities)

    def _on_new_device(device: DeviceContext) -> None:
        async_add_entities([TcIotHubStatus(coordinator, device)])

    coordinator.register_new_device_callback(_on_new_device)


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
