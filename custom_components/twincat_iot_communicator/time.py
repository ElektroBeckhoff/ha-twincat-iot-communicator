"""Time platform for TwinCAT IoT Communicator (TimeSwitch widget)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_TIMESWITCH_END_TIME_VISIBLE,
    META_TIMESWITCH_START_TIME_VISIBLE,
    VAL_TIMESWITCH_END_TIME,
    VAL_TIMESWITCH_START_TIME,
    WIDGET_TYPE_TIME_SWITCH,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData, metadata_bool

PARALLEL_UPDATES = 0

_TIME_SLOTS = (
    (META_TIMESWITCH_START_TIME_VISIBLE, VAL_TIMESWITCH_START_TIME,
     "_start_time", "start_time"),
    (META_TIMESWITCH_END_TIME_VISIBLE, VAL_TIMESWITCH_END_TIME,
     "_end_time", "end_time"),
)


def _ms_to_time(ms: int) -> time:
    """Convert TwinCAT TIME_OF_DAY (ms since midnight) to datetime.time."""
    total_s = (ms // 1000) % 86400
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return time(h, m, s)


def parse_time_of_day(value: Any) -> time | None:
    """Parse a TIME_OF_DAY value from a Tx/Data payload.

    Accepts the numeric encoding (milliseconds since midnight) as well as
    textual forms: ``HH:MM[:SS[.fff]]``, an ISO 8601 date-time, or an IEC
    literal such as ``TOD#15:30:00``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _ms_to_time(int(value))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "#" in text:
        text = text.split("#", 1)[1]
    if text.isdigit():
        return _ms_to_time(int(text))
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).time().replace(
                microsecond=0,
            )
        return time.fromisoformat(text).replace(microsecond=0, tzinfo=None)
    except ValueError:
        return None


def _time_to_ms(t: time) -> int:
    """Convert datetime.time to TwinCAT TIME_OF_DAY (ms since midnight)."""
    return (t.hour * 3600 + t.minute * 60 + t.second) * 1000


def _time_to_iso(t: time) -> str:
    """Convert datetime.time to the ISO format expected by the PLC Rx channel."""
    return f"1970-01-01T{t.hour:02d}:{t.minute:02d}:{t.second:02d}Z"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT time entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TimeEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_time_entities(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[TimeEntity] = []
        for widget in widgets:
            new.extend(_create_time_entities(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.TIME, _on_new_widgets)


def _create_time_entities(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[TimeEntity]:
    """Create time entities for a TimeSwitch widget."""
    if widget.metadata.widget_type != WIDGET_TYPE_TIME_SWITCH:
        return []

    raw = widget.metadata.raw
    entities: list[TimeEntity] = []

    for vis_key, val_key, suffix, tkey in _TIME_SLOTS:
        if not metadata_bool(raw.get(vis_key, "false")):
            continue
        entities.append(
            TcIotTimeSwitchTime(
                coordinator, device_name, widget,
                value_key=val_key, suffix=suffix, translation_key=tkey,
            )
        )

    return entities


class TcIotTimeSwitchTime(TcIotEntity, TimeEntity):
    """A TimeSwitch start/end time exposed as HA time entity."""

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
        """Initialize from a TimeSwitch time slot."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        self._attr_translation_key = translation_key

    @property
    def native_value(self) -> time | None:
        """Return the current time value."""
        return parse_time_of_day(self.widget.values.get(self._value_key))

    async def async_set_value(self, value: time) -> None:
        """Send the new time to the PLC."""
        self._check_read_only()
        await self._send_optimistic(
            {f"{self.widget.path}.{self._value_key}": _time_to_iso(value)},
        )
