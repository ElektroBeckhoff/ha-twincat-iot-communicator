"""Switch platform for TwinCAT IoT Communicator.

Provides:
- Plug widget switches (bOn)
- PLC BOOL datatype switches (value)
- General widget switches (bValue1)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DATATYPE_BOOL,
    META_GENERAL_VALUE1_SWITCH_VISIBLE,
    VAL_DATATYPE_VALUE,
    VAL_GENERAL_VALUE1,
    VAL_MODE,
    VAL_PLUG_ON,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_PLUG,
)
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
    """Set up TcIoT switch entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[SwitchEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_switches(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[SwitchEntity] = []
        for widget in widgets:
            new.extend(_create_switches(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.SWITCH, _on_new_widgets)


def _create_switches(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SwitchEntity]:
    """Create switch entities for a widget based on its type."""
    widget_type = widget.metadata.widget_type
    if widget_type == WIDGET_TYPE_PLUG:
        return [TcIotPlugSwitch(coordinator, device_name, widget)]
    if widget_type == DATATYPE_BOOL:
        return [TcIotDatatypeSwitch(coordinator, device_name, widget)]
    if widget_type == WIDGET_TYPE_GENERAL:
        raw = widget.metadata.raw
        if raw.get(META_GENERAL_VALUE1_SWITCH_VISIBLE, "").lower() == "true":
            return [TcIotGeneralSwitch(coordinator, device_name, widget)]
    return []


class TcIotPlugSwitch(TcIotEntity, SwitchEntity):
    """A TcIoT Plug widget exposed as HA switch entity."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        """Return whether the plug is on."""
        value = self.widget.values.get(VAL_PLUG_ON)
        if value is None:
            return None
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose widget metadata as state attributes."""
        attrs: dict[str, Any] = {"read_only": self.widget.metadata.read_only}
        mode = self.widget.values.get(VAL_MODE)
        if mode is not None:
            attrs["mode"] = mode
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the plug."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_PLUG_ON}": True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the plug."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_PLUG_ON}": False},
        )


class TcIotDatatypeSwitch(TcIotEntity, SwitchEntity):
    """A PLC BOOL exposed as switch.

    Intentionally not a BinarySensor: the PLC's ReadOnly flag can change
    at runtime via metadata updates, so the entity type must always be
    the controllable variant.  Commands are blocked dynamically by
    _check_read_only().
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        """Return whether the BOOL value is True."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the BOOL to True."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name, {self.widget.path: True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the BOOL to False."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name, {self.widget.path: False},
        )


class TcIotGeneralSwitch(TcIotEntity, SwitchEntity):
    """A General widget bValue1 exposed as switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        """Return whether bValue1 is True."""
        value = self.widget.values.get(VAL_GENERAL_VALUE1)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set bValue1 to True."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_GENERAL_VALUE1}": True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set bValue1 to False."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_GENERAL_VALUE1}": False},
        )
