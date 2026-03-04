"""Select platform for TwinCAT IoT Communicator (General widget modes)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_GENERAL_MODE1_CHANGEABLE,
    META_GENERAL_MODE1_VISIBLE,
    META_GENERAL_MODE2_CHANGEABLE,
    META_GENERAL_MODE2_VISIBLE,
    META_GENERAL_MODE3_CHANGEABLE,
    META_GENERAL_MODE3_VISIBLE,
    VAL_GENERAL_MODE1,
    VAL_GENERAL_MODE2,
    VAL_GENERAL_MODE3,
    VAL_GENERAL_MODES1,
    VAL_GENERAL_MODES2,
    VAL_GENERAL_MODES3,
    WIDGET_TYPE_GENERAL,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_MODE_SLOTS = (
    (META_GENERAL_MODE1_VISIBLE, META_GENERAL_MODE1_CHANGEABLE,
     VAL_GENERAL_MODE1, VAL_GENERAL_MODES1, "_mode1", "Mode 1"),
    (META_GENERAL_MODE2_VISIBLE, META_GENERAL_MODE2_CHANGEABLE,
     VAL_GENERAL_MODE2, VAL_GENERAL_MODES2, "_mode2", "Mode 2"),
    (META_GENERAL_MODE3_VISIBLE, META_GENERAL_MODE3_CHANGEABLE,
     VAL_GENERAL_MODE3, VAL_GENERAL_MODES3, "_mode3", "Mode 3"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT select entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[SelectEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_selects(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[SelectEntity] = []
        for widget in widgets:
            new.extend(_create_selects(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.SELECT, _on_new_widgets)


def _create_selects(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SelectEntity]:
    """Create select entities for visible General widget mode slots."""
    if widget.metadata.widget_type != WIDGET_TYPE_GENERAL:
        return []

    raw = widget.metadata.raw
    entities: list[SelectEntity] = []

    for vis_key, chg_key, val_key, opts_key, suffix, label in _MODE_SLOTS:
        if raw.get(vis_key, "").lower() != "true":
            continue
        modes_raw = widget.values.get(opts_key, [])
        options = [m for m in modes_raw if m] if isinstance(modes_raw, list) else []
        if not options:
            continue
        entities.append(TcIotGeneralSelect(
            coordinator, device_name, widget,
            value_key=val_key,
            options_key=opts_key,
            chg_key=chg_key,
            suffix=suffix,
            label=label,
        ))

    return entities


class TcIotGeneralSelect(TcIotEntity, SelectEntity):
    """A General widget mode (sMode1-3) exposed as select entity."""

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        value_key: str,
        options_key: str,
        chg_key: str,
        suffix: str,
        label: str,
    ) -> None:
        """Initialize from a General widget mode slot."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._options_key = options_key
        self._chg_key = chg_key
        self._changeable: bool = False

        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        base_name = (
            widget.friendly_path
            or widget.metadata.display_name
            or widget.widget_id
        )
        self._attr_name = f"{base_name} {label}"
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read changeable flag and options from live widget."""
        self._changeable = (
            self.widget.metadata.raw.get(self._chg_key, "").lower() == "true"
        )
        modes_raw = self.widget.values.get(self._options_key, [])
        self._attr_options = (
            [m for m in modes_raw if m] if isinstance(modes_raw, list) else []
        )

    @property
    def current_option(self) -> str | None:
        """Return the currently selected mode."""
        return self.widget.values.get(self._value_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose changeable flag alongside the standard read_only."""
        attrs = super().extra_state_attributes
        attrs["changeable"] = self._changeable
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Send the selected mode to the PLC."""
        self._check_read_only()
        if not self._changeable:
            _LOGGER.warning(
                "Mode %s is not changeable for %s", self._value_key, self.name,
            )
            return
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{self._value_key}": option},
        )
