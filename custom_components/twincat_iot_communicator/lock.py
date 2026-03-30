"""Lock platform for TwinCAT IoT Communicator.

Provides lock entities for Lock widgets (doors, access control, latches).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_LOCK_JAMMED_VISIBLE,
    META_LOCK_OPEN_VISIBLE,
    VAL_LOCK_JAMMED,
    VAL_LOCK_LOCK,
    VAL_LOCK_LOCKED,
    VAL_LOCK_OPEN,
    VAL_LOCK_OPENED,
    VAL_LOCK_STATE,
    VAL_LOCK_UNLOCK,
    WIDGET_TYPE_LOCK,
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
    """Set up TcIoT lock entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[LockEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_locks(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[LockEntity] = []
        for widget in widgets:
            new.extend(_create_locks(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.LOCK, _on_new_widgets)


def _create_locks(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[LockEntity]:
    """Create lock entities for a widget based on its type."""
    if widget.metadata.widget_type != WIDGET_TYPE_LOCK:
        return []
    return [TcIotLock(coordinator, device_name, widget)]


class TcIotLock(TcIotEntity, LockEntity):
    """A TcIoT Lock widget exposed as HA lock entity."""

    _attr_translation_key = "lock"

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator, device_name, widget)
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read feature flags from live widget metadata."""
        raw = self.widget.metadata.raw
        features = LockEntityFeature(0)
        if raw.get(META_LOCK_OPEN_VISIBLE, "").lower() == "true":
            features |= LockEntityFeature.OPEN
        self._attr_supported_features = features

    @property
    def is_locked(self) -> bool | None:
        """Return whether the lock is locked."""
        value = self.widget.values.get(VAL_LOCK_LOCKED)
        if value is None:
            return None
        return bool(value)

    @property
    def is_jammed(self) -> bool:
        """Return whether the lock is jammed."""
        raw = self.widget.metadata.raw
        if raw.get(META_LOCK_JAMMED_VISIBLE, "").lower() != "true":
            return False
        return bool(self.widget.values.get(VAL_LOCK_JAMMED, False))

    @property
    def is_open(self) -> bool | None:
        """Return whether the door is physically open."""
        raw = self.widget.metadata.raw
        if raw.get(META_LOCK_OPEN_VISIBLE, "").lower() != "true":
            return None
        value = self.widget.values.get(VAL_LOCK_OPENED)
        if value is None:
            return None
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose lock state string and metadata."""
        attrs = super().extra_state_attributes
        state = self.widget.values.get(VAL_LOCK_STATE)
        if state is not None:
            attrs["lock_state"] = state
        return attrs

    async def async_lock(self, **kwargs: Any) -> None:
        """Send the lock command to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_LOCK_LOCK}": True},
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Send the unlock command to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_LOCK_UNLOCK}": True},
        )

    async def async_open(self, **kwargs: Any) -> None:
        """Send the open command (electric strike / buzzer) to the PLC."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_LOCK_OPEN}": True},
        )
