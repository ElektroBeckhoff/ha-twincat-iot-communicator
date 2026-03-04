"""Base entities for TwinCAT IoT Communicator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
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


def _build_device_info(coordinator: TcIotCoordinator, device_name: str) -> DeviceInfo:
    """Build the shared DeviceInfo for a TcIoT device."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{device_name}")},
        name=f"TcIoT {device_name}",
        manufacturer="Beckhoff",
        model="TwinCAT IoT Communicator",
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
        self._attr_device_info = _build_device_info(coordinator, dev.device_name)

    @property
    def available(self) -> bool:
        """Return True if the MQTT connection is active."""
        return self.coordinator.connected


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

        self._attr_unique_id = (
            f"{coordinator.hostname}_{coordinator.main_topic}_"
            f"{device_name}_{widget.path}"
        )
        self._attr_name = widget.friendly_path or widget.effective_display_name()
        self._attr_device_info = _build_device_info(coordinator, device_name)

        icon_name = widget.metadata.raw.get(META_ICON, "")
        if icon_name:
            mapped = TCIOT_ICON_MAP.get(icon_name)
            if mapped:
                self._attr_icon = mapped

    # ── lifecycle ────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register the widget update listener when the entity is added."""
        self._unregister_listener = self.coordinator.register_listener(
            self.widget.path, self._on_widget_update
        )
        if not self._try_assign_area():
            self._unregister_areas = self.coordinator.on_areas_ready(
                self._try_assign_area,
            )

    @callback
    def _try_assign_area(self) -> bool:
        """Assign this entity to its HA area. Returns True on success."""
        area_id = self.coordinator.get_area_for_widget(
            self.device_name, self.widget.path
        )
        if area_id and self.registry_entry and not self.registry_entry.area_id:
            ent_reg = er.async_get(self.hass)
            ent_reg.async_update_entity(self.entity_id, area_id=area_id)
            return True
        return False

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
        self._attr_name = widget.friendly_path or widget.effective_display_name()
        self._sync_metadata()
        self.async_write_ha_state()

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
                translation_placeholders={"name": self.name or ""},
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
