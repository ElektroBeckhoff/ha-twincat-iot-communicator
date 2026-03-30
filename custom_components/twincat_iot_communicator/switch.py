"""Switch platform for TwinCAT IoT Communicator.

Provides:
- Plug widget switches (bOn)
- PLC BOOL datatype switches (value)
- General widget switches (bValue1)
- TimeSwitch widget switches (power, yearly, weekdays)
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
    DATATYPE_ARRAY_BOOL,
    DATATYPE_BOOL,
    META_GENERAL_VALUE1_SWITCH_VISIBLE,
    META_MOTION_ON_SWITCH_VISIBLE,
    META_TIMESWITCH_DATE_YEARLY_VISIBLE,
    META_TIMESWITCH_DAYS_VISIBLE,
    VAL_DATATYPE_VALUE,
    VAL_GENERAL_VALUE1,
    VAL_MODE,
    VAL_MOTION_ON,
    VAL_PLUG_ON,
    VAL_TIMESWITCH_FRIDAY,
    VAL_TIMESWITCH_MONDAY,
    VAL_TIMESWITCH_ON,
    VAL_TIMESWITCH_SATURDAY,
    VAL_TIMESWITCH_SUNDAY,
    VAL_TIMESWITCH_THURSDAY,
    VAL_TIMESWITCH_TUESDAY,
    VAL_TIMESWITCH_WEDNESDAY,
    VAL_TIMESWITCH_YEARLY,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_MOTION,
    WIDGET_TYPE_PLUG,
    WIDGET_TYPE_TIME_SWITCH,
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
    if widget_type == DATATYPE_ARRAY_BOOL:
        return _create_array_switches(coordinator, device_name, widget)
    if widget_type == WIDGET_TYPE_GENERAL:
        raw = widget.metadata.raw
        if raw.get(META_GENERAL_VALUE1_SWITCH_VISIBLE, "").lower() == "true":
            return [TcIotGeneralSwitch(coordinator, device_name, widget)]
    if widget_type == WIDGET_TYPE_TIME_SWITCH:
        return _create_timeswitch_switches(coordinator, device_name, widget)
    if widget_type == WIDGET_TYPE_MOTION:
        return _create_motion_switches(coordinator, device_name, widget)
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
    _attr_translation_key = "general_switch"

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


# ── TimeSwitch switches ──────────────────────────────────────────────

_DAY_SLOTS = (
    (VAL_TIMESWITCH_MONDAY, "_monday", "ts_monday"),
    (VAL_TIMESWITCH_TUESDAY, "_tuesday", "ts_tuesday"),
    (VAL_TIMESWITCH_WEDNESDAY, "_wednesday", "ts_wednesday"),
    (VAL_TIMESWITCH_THURSDAY, "_thursday", "ts_thursday"),
    (VAL_TIMESWITCH_FRIDAY, "_friday", "ts_friday"),
    (VAL_TIMESWITCH_SATURDAY, "_saturday", "ts_saturday"),
    (VAL_TIMESWITCH_SUNDAY, "_sunday", "ts_sunday"),
)


def _create_timeswitch_switches(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SwitchEntity]:
    """Create switch entities for a TimeSwitch widget."""
    raw = widget.metadata.raw
    entities: list[SwitchEntity] = [
        TcIotTimeSwitchBoolSwitch(
            coordinator, device_name, widget,
            value_key=VAL_TIMESWITCH_ON, suffix="_power",
            translation_key="ts_power",
        ),
    ]

    if raw.get(META_TIMESWITCH_DATE_YEARLY_VISIBLE, "false").lower() == "true":
        entities.append(
            TcIotTimeSwitchBoolSwitch(
                coordinator, device_name, widget,
                value_key=VAL_TIMESWITCH_YEARLY, suffix="_yearly",
                translation_key="ts_yearly",
            )
        )

    if raw.get(META_TIMESWITCH_DAYS_VISIBLE, "false").lower() == "true":
        for val_key, suffix, tkey in _DAY_SLOTS:
            entities.append(
                TcIotTimeSwitchBoolSwitch(
                    coordinator, device_name, widget,
                    value_key=val_key, suffix=suffix, translation_key=tkey,
                )
            )

    return entities


class TcIotTimeSwitchBoolSwitch(TcIotEntity, SwitchEntity):
    """A boolean field from a TimeSwitch widget exposed as HA switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        value_key: str,
        suffix: str,
        translation_key: str,
    ) -> None:
        """Initialize from a TimeSwitch boolean field."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        self._attr_translation_key = translation_key

    @property
    def is_on(self) -> bool | None:
        """Return the current boolean state."""
        value = self.widget.values.get(self._value_key)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the boolean to True."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{self._value_key}": True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the boolean to False."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{self._value_key}": False},
        )


# ── Motion switches ───────────────────────────────────────────────


def _create_motion_switches(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SwitchEntity]:
    """Create switch entities for a Motion widget."""
    raw = widget.metadata.raw
    if raw.get(META_MOTION_ON_SWITCH_VISIBLE, "").lower() != "true":
        return []
    return [TcIotMotionSwitch(coordinator, device_name, widget)]


class TcIotMotionSwitch(TcIotEntity, SwitchEntity):
    """A Motion widget bOn (enable/override) exposed as switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "motion_on"

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the motion on/off switch."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_on"

    @property
    def is_on(self) -> bool | None:
        """Return whether bOn is True."""
        value = self.widget.values.get(VAL_MOTION_ON)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set bOn to True."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MOTION_ON}": True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set bOn to False."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MOTION_ON}": False},
        )


# ── PLC Array of BOOL values ─────────────────────────────────────


def _create_array_switches(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SwitchEntity]:
    """Create one switch entity per element in a PLC BOOL array."""
    arr = widget.values.get("value", [])
    if not isinstance(arr, list):
        return []
    return [
        TcIotDatatypeArraySwitch(coordinator, device_name, widget, index=i)
        for i in range(len(arr))
    ]


class TcIotDatatypeArraySwitch(TcIotEntity, SwitchEntity):
    """A single element of a PLC BOOL array.

    Arrays are always read-only; write commands are blocked.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        index: int,
    ) -> None:
        """Initialize from an array widget and element index."""
        super().__init__(coordinator, device_name, widget)
        self._index = index
        self._attr_unique_id = f"{self._attr_unique_id}_arr{index}"
        self._attr_name = f"[{index}]"

    @property
    def is_on(self) -> bool | None:
        """Return the boolean value of this array element."""
        arr = self.widget.values.get("value")
        if not isinstance(arr, list) or self._index >= len(arr):
            return None
        val = arr[self._index]
        if val is None:
            return None
        return bool(val)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Block writes — PLC arrays are read-only."""
        self._check_read_only()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Block writes — PLC arrays are read-only."""
        self._check_read_only()
