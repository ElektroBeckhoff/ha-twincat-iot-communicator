"""Date platform for TwinCAT IoT Communicator (TimeSwitch widget)."""

from __future__ import annotations

import datetime
from homeassistant.components.date import DateEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_TIMESWITCH_END_DATE_VISIBLE,
    META_TIMESWITCH_START_DATE_VISIBLE,
    VAL_TIMESWITCH_END_DATE,
    VAL_TIMESWITCH_START_DATE,
    WIDGET_TYPE_TIME_SWITCH,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

PARALLEL_UPDATES = 0

_DATE_SLOTS = (
    (META_TIMESWITCH_START_DATE_VISIBLE, VAL_TIMESWITCH_START_DATE,
     "_start_date", "start_date"),
    (META_TIMESWITCH_END_DATE_VISIBLE, VAL_TIMESWITCH_END_DATE,
     "_end_date", "end_date"),
)

_EPOCH = datetime.date(1970, 1, 1)


def _epoch_seconds_to_date(seconds: int) -> datetime.date:
    """Convert TwinCAT DATE (seconds since 1970-01-01) to datetime.date."""
    return _EPOCH + datetime.timedelta(seconds=seconds)


def _date_to_epoch_seconds(d: datetime.date) -> int:
    """Convert datetime.date to TwinCAT DATE (seconds since 1970-01-01)."""
    return int(datetime.datetime.combine(d, datetime.time(), datetime.timezone.utc).timestamp())


def _date_to_iso(d: datetime.date) -> str:
    """Convert datetime.date to the ISO format expected by the PLC Rx channel."""
    return f"{d.isoformat()}T00:00:00"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT date entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[DateEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_date_entities(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[DateEntity] = []
        for widget in widgets:
            new.extend(_create_date_entities(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.DATE, _on_new_widgets)


def _create_date_entities(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[DateEntity]:
    """Create date entities for a TimeSwitch widget."""
    if widget.metadata.widget_type != WIDGET_TYPE_TIME_SWITCH:
        return []

    raw = widget.metadata.raw
    entities: list[DateEntity] = []

    for vis_key, val_key, suffix, tkey in _DATE_SLOTS:
        if raw.get(vis_key, "false").lower() != "true":
            continue
        entities.append(
            TcIotTimeSwitchDate(
                coordinator, device_name, widget,
                value_key=val_key, suffix=suffix, translation_key=tkey,
            )
        )

    return entities


class TcIotTimeSwitchDate(TcIotEntity, DateEntity):
    """A TimeSwitch start/end date exposed as HA date entity."""

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
        """Initialize from a TimeSwitch date slot."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        self._attr_translation_key = translation_key

    @property
    def native_value(self) -> datetime.date | None:
        """Return the current date value."""
        val = self.widget.values.get(self._value_key)
        if val is None:
            return None
        try:
            return _epoch_seconds_to_date(int(val))
        except (ValueError, TypeError, OSError):
            return None

    async def async_set_value(self, value: datetime.date) -> None:
        """Send the new date to the PLC."""
        self._check_read_only()
        await self._send_optimistic(
            {f"{self.widget.path}.{self._value_key}": _date_to_iso(value)},
        )
