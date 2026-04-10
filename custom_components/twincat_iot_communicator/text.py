"""Text platform for TwinCAT IoT Communicator (PLC STRING datatypes)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import DATATYPE_ARRAY_STRING, DATATYPE_STRING, VAL_DATATYPE_VALUE
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT text entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TextEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_texts(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[TextEntity] = []
        for widget in widgets:
            new.extend(_create_texts(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.TEXT, _on_new_widgets)


def _create_texts(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[TextEntity]:
    """Create text entities for a widget based on its type."""
    wt = widget.metadata.widget_type
    if wt == DATATYPE_STRING:
        return [TcIotDatatypeText(coordinator, device_name, widget)]
    if wt == DATATYPE_ARRAY_STRING:
        return _create_array_texts(coordinator, device_name, widget)
    return []


class TcIotDatatypeText(TcIotEntity, TextEntity):
    """A PLC STRING exposed as text entity.

    Intentionally not a Sensor: the PLC's ReadOnly flag can change at
    runtime via metadata updates, so the entity type must always be the
    controllable variant.  Commands are blocked dynamically by
    _check_read_only().
    """

    _attr_native_max = 255

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a STRING datatype widget."""
        super().__init__(coordinator, device_name, widget)
        if widget.metadata.read_only:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        """Return the current string value from the PLC."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        return str(value)

    async def async_set_value(self, value: str) -> None:
        """Write a new string value to the PLC."""
        self._check_read_only()
        value = value[: self._attr_native_max]
        await self._send_optimistic({self.widget.path: value})


# ── PLC Array of STRING values ───────────────────────────────────


def _create_array_texts(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[TextEntity]:
    """Create one text entity per element in a PLC STRING array."""
    arr = widget.values.get("value", [])
    if not isinstance(arr, list):
        return []
    return [
        TcIotDatatypeArrayText(coordinator, device_name, widget, index=i)
        for i in range(len(arr))
    ]


class TcIotDatatypeArrayText(TcIotEntity, TextEntity):
    """A single element of a PLC STRING array.

    Arrays are always read-only; write commands are blocked.
    """

    _attr_native_max = 255

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
    def native_value(self) -> str | None:
        """Return the string value of this array element."""
        arr = self.widget.values.get("value")
        if not isinstance(arr, list) or self._index >= len(arr):
            return None
        val = arr[self._index]
        if val is None:
            return None
        return str(val)

    async def async_set_value(self, value: str) -> None:
        """Block writes — PLC arrays are read-only."""
        self._check_read_only()
