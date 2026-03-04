"""Event platform for TwinCAT IoT Communicator – PLC message events."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .coordinator import TcIotCoordinator
from .entity import TcIotDeviceEntity
from .models import DeviceContext, TcIotMessage

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT message event entities (one per discovered device)."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TcIotMessageEvent] = []
    for device in coordinator.devices.values():
        entities.append(TcIotMessageEvent(coordinator, device))
    if entities:
        async_add_entities(entities)

    def _on_new_device(device: DeviceContext) -> None:
        async_add_entities([TcIotMessageEvent(coordinator, device)])

    coordinator.register_new_device_callback(_on_new_device)


class TcIotMessageEvent(TcIotDeviceEntity, EventEntity):
    """Event entity that fires when a PLC push message arrives."""

    _attr_event_types = ["message"]
    _attr_icon = "mdi:message-text"
    _attr_translation_key = "plc_message"

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the PLC message event entity."""
        super().__init__(coordinator, device, "messages")
        self._unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Register the message callback when the entity is added."""
        self._unsub = self.coordinator.register_message_callback(
            self._dev.device_name, self._on_message,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the message callback when the entity is removed."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_message(
        self, event_type: str, message: TcIotMessage | None,
    ) -> None:
        """Handle a message event from the coordinator."""
        if event_type != "received" or message is None:
            return
        self._trigger_event(
            "message",
            {
                "message_id": message.message_id,
                "text": message.text,
                "type": message.message_type,
                "timestamp": message.timestamp,
            },
        )
        self.async_write_ha_state()
