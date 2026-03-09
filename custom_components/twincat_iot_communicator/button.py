"""Button platform for TwinCAT IoT Communicator.

Provides:
- ChargingStation start/stop charging buttons
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_CHARGING_STATION_RESERVE_VISIBLE,
    VAL_CHARGING_RESERVE,
    VAL_CHARGING_START,
    VAL_CHARGING_STOP,
    WIDGET_TYPE_CHARGING_STATION,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT button entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[ButtonEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_buttons(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[ButtonEntity] = []
        for widget in widgets:
            new.extend(_create_buttons(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.BUTTON, _on_new_widgets)


def _create_buttons(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[ButtonEntity]:
    """Create button entities for a widget based on its type."""
    if widget.metadata.widget_type == WIDGET_TYPE_CHARGING_STATION:
        buttons: list[ButtonEntity] = [
            TcIotChargingStartButton(coordinator, device_name, widget),
            TcIotChargingStopButton(coordinator, device_name, widget),
        ]
        raw = widget.metadata.raw
        if raw.get(META_CHARGING_STATION_RESERVE_VISIBLE, "false").lower() == "true":
            buttons.append(
                TcIotChargingReserveButton(coordinator, device_name, widget)
            )
        return buttons
    return []


class TcIotChargingStartButton(TcIotEntity, ButtonEntity):
    """Button to start charging on a ChargingStation widget."""

    _attr_translation_key = "charging_start"

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the start charging button."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_start"

    async def async_press(self) -> None:
        """Send the start charging command to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_CHARGING_START}": True},
        )


class TcIotChargingStopButton(TcIotEntity, ButtonEntity):
    """Button to stop charging on a ChargingStation widget."""

    _attr_translation_key = "charging_stop"

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the stop charging button."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_stop"

    async def async_press(self) -> None:
        """Send the stop charging command to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_CHARGING_STOP}": True},
        )


class TcIotChargingReserveButton(TcIotEntity, ButtonEntity):
    """Button to reserve charging on a ChargingStation widget."""

    _attr_translation_key = "charging_reserve"

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the reserve charging button."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_reserve"

    async def async_press(self) -> None:
        """Send the reserve charging command to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_CHARGING_RESERVE}": True},
        )
