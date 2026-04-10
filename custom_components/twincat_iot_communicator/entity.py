"""Base entities for TwinCAT IoT Communicator."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    META_ICON,
    META_VALUE_TEXT_COLOR,
    META_VALUE_TEXT_COLOR_DARK,
    TCIOT_ICON_MAP,
)
from .coordinator import TcIotCoordinator
from .models import DeviceContext, WidgetData


def _build_hub_device_info(
    coordinator: TcIotCoordinator, device_name: str,
) -> DeviceInfo:
    """Build the DeviceInfo for the PLC hub device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{device_name}")},
        name=f"TcIoT {device_name}",
        manufacturer="Beckhoff",
        model="TwinCAT IoT Communicator",
    )


_WIDGET_MODEL_MAP: dict[str, str] = {
    "_dt_bool": "PLC BOOL",
    "_dt_number": "PLC Numeric",
    "_dt_string": "PLC STRING",
    "_dt_array_bool": "PLC BOOL Array",
    "_dt_array_number": "PLC Numeric Array",
    "_dt_array_string": "PLC STRING Array",
}


def _build_widget_device_info(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> DeviceInfo:
    """Build the DeviceInfo for a widget sub-device."""
    wtype = widget.metadata.widget_type
    model = _WIDGET_MODEL_MAP.get(wtype, wtype) or "PLC Value"
    return DeviceInfo(
        identifiers={
            (DOMAIN, f"{coordinator.entry.entry_id}_{device_name}_{widget.path}")
        },
        name=widget.friendly_path or widget.effective_display_name(),
        manufacturer="Beckhoff",
        model=model,
        via_device=(DOMAIN, f"{coordinator.entry.entry_id}_{device_name}"),
    )


class TcIotDeviceEntity:
    """Base for device-level (non-widget) entities like sensors and binary sensors.

    Provides shared DeviceInfo, unique_id, coordinator reference, and availability.
    Designed as a first-parent in the MRO before the HA entity class:
        class MyEntity(TcIotDeviceEntity, SensorEntity): ...
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: TcIotCoordinator, dev: DeviceContext, key: str) -> None:
        """Initialize the device-level entity base."""
        self.coordinator = coordinator
        self._dev = dev
        self._attr_unique_id = (
            f"{coordinator.hostname}_{coordinator.main_topic}_"
            f"{dev.device_name}_{key}"
        )
        self._attr_device_info = _build_hub_device_info(coordinator, dev.device_name)

    @property
    def available(self) -> bool:
        """Return True if the MQTT connection is active."""
        return self.coordinator.connected


_OPTIMISTIC_HOLD = 2.0


class TcIotEntity(Entity):
    """Base entity for widget-based entities (lights, covers, etc.)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the base TcIoT entity."""
        self.coordinator = coordinator
        self.device_name = device_name
        self.widget = widget
        self._unregister_listener: Callable[[], None] | None = None
        self._unregister_areas: Callable[[], None] | None = None
        self._optimistic_values: dict[str, Any] = {}
        self._optimistic_until: float = 0.0

        self._attr_unique_id = (
            f"{coordinator.hostname}_{coordinator.main_topic}_"
            f"{device_name}_{widget.path}"
        )
        self._attr_device_info = _build_widget_device_info(
            coordinator, device_name, widget,
        )

        icon_name = widget.metadata.raw.get(META_ICON, "")
        if icon_name:
            mapped = TCIOT_ICON_MAP.get(icon_name)
            if mapped:
                self._attr_icon = mapped

    # ── lifecycle ────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register the widget update listener when the entity is added."""
        self._unregister_listener = self.coordinator.register_listener(
            self.device_name, self.widget.path, self._on_widget_update
        )
        if (
            self.coordinator._create_areas
            and self.coordinator._assign_devices_to_areas
            and not self._try_assign_area()
        ):
            self._unregister_areas = self.coordinator.on_areas_ready(
                self._try_assign_area,
            )

    @callback
    def _try_assign_area(self) -> bool:
        """Assign the widget device to its HA area. Returns True on success."""
        area_id = self.coordinator.get_area_for_widget(
            self.device_name, self.widget.path
        )
        if not area_id:
            return False
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            identifiers={
                (
                    DOMAIN,
                    f"{self.coordinator.entry.entry_id}_"
                    f"{self.device_name}_{self.widget.path}",
                )
            },
        )
        if not device:
            return False
        if not device.area_id:
            dev_reg.async_update_device(device.id, area_id=area_id)
        return True

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when the entity is removed."""
        if self._unregister_listener:
            self._unregister_listener()
            self._unregister_listener = None
        if self._unregister_areas:
            self._unregister_areas()
            self._unregister_areas = None

    @callback
    def _on_widget_update(self, widget: WidgetData) -> None:
        """Handle an updated widget from the coordinator."""
        self.widget = widget
        if self._optimistic_values and time.monotonic() < self._optimistic_until:
            for key, val in self._optimistic_values.items():
                self.widget.values[key] = val
        else:
            self._optimistic_values = {}
        self._sync_device_name()
        self._sync_metadata()
        self.async_write_ha_state()

    async def _send_optimistic(
        self,
        commands: dict[str, Any],
        *,
        optimistic_extra: dict[str, Any] | None = None,
    ) -> None:
        """Apply optimistic values, write state, THEN send to PLC.

        Values are applied BEFORE the await so that any coordinator push
        during the MQTT round-trip is already protected by the cooldown.

        *optimistic_extra* contains derived widget field values that are NOT
        sent to the PLC but must be set optimistically so that all HA
        properties return consistent data (e.g. nHueValue when only nRed/
        nGreen/nBlue are sent).
        """
        path = self.widget.path
        prefix = f"{path}."
        applied: dict[str, Any] = {}
        previous: dict[str, Any] = {}
        for cmd_key, cmd_val in commands.items():
            if cmd_key == path:
                previous["value"] = self.widget.values.get("value")
                self.widget.values["value"] = cmd_val
                applied["value"] = cmd_val
            elif cmd_key.startswith(prefix):
                field = cmd_key.removeprefix(prefix)
                previous[field] = self.widget.values.get(field)
                self.widget.values[field] = cmd_val
                applied[field] = cmd_val
        if optimistic_extra:
            for field, val in optimistic_extra.items():
                previous.setdefault(field, self.widget.values.get(field))
                self.widget.values[field] = val
                applied[field] = val
        if applied:
            self._optimistic_values = applied
            self._optimistic_until = time.monotonic() + _OPTIMISTIC_HOLD
        self.async_write_ha_state()
        try:
            await self.coordinator.async_send_command(self.device_name, commands)
        except HomeAssistantError:
            for field, old_val in previous.items():
                if old_val is None:
                    self.widget.values.pop(field, None)
                else:
                    self.widget.values[field] = old_val
            self._optimistic_values = {}
            self._optimistic_until = 0.0
            self.async_write_ha_state()
            raise

    @callback
    def _sync_device_name(self) -> None:
        """Update the widget device name when the PLC display name changes."""
        new_name = (
            self.widget.friendly_path or self.widget.effective_display_name()
        )
        if not new_name:
            return
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            identifiers={
                (
                    DOMAIN,
                    f"{self.coordinator.entry.entry_id}_"
                    f"{self.device_name}_{self.widget.path}",
                )
            },
        )
        if device and device.name != new_name:
            dev_reg.async_update_device(device.id, name=new_name)

    def _sync_metadata(self) -> None:
        """Re-read metadata-dependent attributes from the live widget.

        Called from __init__ and on every widget update. Subclasses override
        to keep _attr_* values in sync with runtime metadata changes (e.g.
        Visible, Changeable, Min/Max, Unit flags sent via ForceUpdate).
        """

    # ── read-only guard ─────────────────────────────────────────

    def _check_read_only(self) -> None:
        """Raise if the widget is marked read-only by the PLC."""
        if self.widget.metadata.read_only:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="read_only_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose widget metadata as state attributes."""
        attrs: dict[str, Any] = {"read_only": self.widget.metadata.read_only}
        raw = self.widget.metadata.raw
        color = raw.get(META_VALUE_TEXT_COLOR)
        if color:
            attrs["value_text_color"] = color
        color_dark = raw.get(META_VALUE_TEXT_COLOR_DARK)
        if color_dark:
            attrs["value_text_color_dark"] = color_dark
        return attrs

    @property
    def available(self) -> bool:
        """Return True if the device is online and the widget is not stale."""
        dev: DeviceContext | None = self.coordinator.get_device(self.device_name)
        if dev is None or not self.coordinator.connected or not dev.online:
            return False
        if self.widget.path in dev.stale_widget_paths:
            return False
        return bool(self.widget.values)
