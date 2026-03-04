"""Text platform for TwinCAT IoT Communicator (PLC STRING datatypes)."""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import DATATYPE_STRING, VAL_DATATYPE_VALUE
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT text entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TcIotDatatypeText] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            if widget.metadata.widget_type == DATATYPE_STRING:
                entities.append(
                    TcIotDatatypeText(coordinator, device_name, widget)
                )
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new = [
            TcIotDatatypeText(coordinator, device_name, widget)
            for widget in widgets
            if widget.metadata.widget_type == DATATYPE_STRING
        ]
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.TEXT, _on_new_widgets)


class TcIotDatatypeText(TcIotEntity, TextEntity):
    """A PLC STRING exposed as text entity.

    Intentionally not a Sensor: the PLC's ReadOnly flag can change at
    runtime via metadata updates, so the entity type must always be the
    controllable variant.  Commands are blocked dynamically by
    _check_read_only().
    """

    _attr_native_max = 255

    @property
    def native_value(self) -> str | None:
        """Return the current string value from the PLC."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        return str(value)

    async def async_set_value(self, value: str) -> None:
        """Write a new string value to the PLC."""
        self._check_read_only()
        value = value[: self._attr_native_max]
        await self.coordinator.async_send_command(
            self.device_name, {self.widget.path: value},
        )
