"""Select platform for TwinCAT IoT Communicator (General + TimeSwitch modes)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DOMAIN,
    META_GENERAL_MODE1_CHANGEABLE,
    META_GENERAL_MODE1_VISIBLE,
    META_GENERAL_MODE2_CHANGEABLE,
    META_GENERAL_MODE2_VISIBLE,
    META_GENERAL_MODE3_CHANGEABLE,
    META_GENERAL_MODE3_VISIBLE,
    META_TIMESWITCH_MODE_CHANGEABLE,
    META_TIMESWITCH_MODE_VISIBLE,
    VAL_GENERAL_MODE1,
    VAL_GENERAL_MODE2,
    VAL_GENERAL_MODE3,
    VAL_GENERAL_MODES1,
    VAL_GENERAL_MODES2,
    VAL_GENERAL_MODES3,
    VAL_MODE,
    VAL_MODES,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_TIME_SWITCH,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_MODE_SLOTS = (
    (META_GENERAL_MODE1_VISIBLE, META_GENERAL_MODE1_CHANGEABLE,
     VAL_GENERAL_MODE1, VAL_GENERAL_MODES1, "_mode1", "mode_1"),
    (META_GENERAL_MODE2_VISIBLE, META_GENERAL_MODE2_CHANGEABLE,
     VAL_GENERAL_MODE2, VAL_GENERAL_MODES2, "_mode2", "mode_2"),
    (META_GENERAL_MODE3_VISIBLE, META_GENERAL_MODE3_CHANGEABLE,
     VAL_GENERAL_MODE3, VAL_GENERAL_MODES3, "_mode3", "mode_3"),
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
    """Create select entities for visible widget mode slots."""
    wtype = widget.metadata.widget_type
    if wtype == WIDGET_TYPE_GENERAL:
        return _create_general_selects(coordinator, device_name, widget)
    if wtype == WIDGET_TYPE_TIME_SWITCH:
        return _create_timeswitch_selects(coordinator, device_name, widget)
    return []


def _create_general_selects(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SelectEntity]:
    """Create select entities for visible General widget mode slots."""
    raw = widget.metadata.raw
    entities: list[SelectEntity] = []

    for vis_key, chg_key, val_key, opts_key, suffix, tkey in _MODE_SLOTS:
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
            translation_key=tkey,
        ))

    return entities


def _create_timeswitch_selects(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SelectEntity]:
    """Create a select entity for the TimeSwitch mode if visible."""
    raw = widget.metadata.raw
    if raw.get(META_TIMESWITCH_MODE_VISIBLE, "false").lower() != "true":
        return []
    modes_raw = widget.values.get(VAL_MODES, [])
    options = [m for m in modes_raw if m] if isinstance(modes_raw, list) else []
    if not options:
        return []
    return [
        TcIotGeneralSelect(
            coordinator, device_name, widget,
            value_key=VAL_MODE,
            options_key=VAL_MODES,
            chg_key=META_TIMESWITCH_MODE_CHANGEABLE,
            suffix="_mode",
            translation_key="mode",
        )
    ]


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
        translation_key: str,
    ) -> None:
        """Initialize from a General widget mode slot."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._options_key = options_key
        self._chg_key = chg_key
        self._changeable: bool = False

        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        self._attr_translation_key = translation_key
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
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{self._value_key}": option},
        )
