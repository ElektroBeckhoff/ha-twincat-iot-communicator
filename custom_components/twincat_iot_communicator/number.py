"""Number platform for TwinCAT IoT Communicator.

Provides:
- PLC numeric datatype numbers (INT/REAL variants)
- General widget numbers (nValue2 / nValue3)
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DATATYPE_ARRAY_NUMBER,
    DATATYPE_NUMBER,
    META_DECIMAL_PRECISION,
    META_GENERAL_VALUE2_SLIDER_VISIBLE,
    META_GENERAL_VALUE3_SLIDER_VISIBLE,
    META_MAX_VALUE,
    META_MIN_VALUE,
    META_MOTION_BRIGHTNESS_VISIBLE,
    META_MOTION_HOLD_TIME_VISIBLE,
    META_MOTION_RANGE_VISIBLE,
    META_MOTION_SENSITIVITY_VISIBLE,
    META_UNIT,
    VAL_DATATYPE_VALUE,
    VAL_GENERAL_VALUE2,
    VAL_GENERAL_VALUE2_REQUEST,
    VAL_GENERAL_VALUE3,
    VAL_GENERAL_VALUE3_REQUEST,
    VAL_MOTION_BRIGHTNESS,
    VAL_MOTION_HOLD_TIME,
    VAL_MOTION_RANGE,
    VAL_MOTION_SENSITIVITY,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_MOTION,
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
    """Set up TcIoT number entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[NumberEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_numbers(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[NumberEntity] = []
        for widget in widgets:
            new.extend(_create_numbers(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.NUMBER, _on_new_widgets)


def _create_numbers(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[NumberEntity]:
    """Create number entities for a widget based on its type."""
    wt = widget.metadata.widget_type
    if wt == DATATYPE_NUMBER:
        return [TcIotDatatypeNumber(coordinator, device_name, widget)]
    if wt == DATATYPE_ARRAY_NUMBER:
        return _create_array_numbers(coordinator, device_name, widget)
    if wt == WIDGET_TYPE_GENERAL:
        return _create_general_numbers(coordinator, device_name, widget)
    if wt == WIDGET_TYPE_MOTION:
        return _create_motion_numbers(coordinator, device_name, widget)
    return []


def _create_general_numbers(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[NumberEntity]:
    """Create number entities for visible General widget value slots."""
    raw = widget.metadata.raw
    entities: list[NumberEntity] = []
    if raw.get(META_GENERAL_VALUE2_SLIDER_VISIBLE, "").lower() == "true":
        entities.append(TcIotGeneralNumber(
            coordinator, device_name, widget,
            value_key=VAL_GENERAL_VALUE2,
            request_key=VAL_GENERAL_VALUE2_REQUEST,
            suffix="_value2",
            translation_key="value_2",
        ))
    if raw.get(META_GENERAL_VALUE3_SLIDER_VISIBLE, "").lower() == "true":
        entities.append(TcIotGeneralNumber(
            coordinator, device_name, widget,
            value_key=VAL_GENERAL_VALUE3,
            request_key=VAL_GENERAL_VALUE3_REQUEST,
            suffix="_value3",
            translation_key="value_3",
        ))
    return entities


class TcIotDatatypeNumber(TcIotEntity, NumberEntity):
    """Number entity for a PLC numeric datatype (INT/REAL variants).

    Intentionally not a Sensor: the PLC's ReadOnly flag can change at
    runtime via metadata updates, so the entity type must always be the
    controllable variant.  Commands are blocked dynamically by
    _check_read_only().
    """

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a numeric datatype widget."""
        super().__init__(coordinator, device_name, widget)
        if widget.metadata.read_only:
            self._attr_entity_registry_enabled_default = False
        precision_str = widget.metadata.raw.get(META_DECIMAL_PRECISION, "")
        has_precision = False
        if precision_str:
            try:
                has_precision = int(precision_str) > 0
            except (ValueError, TypeError):
                pass
        self._is_float: bool = has_precision or isinstance(
            widget.values.get(VAL_DATATYPE_VALUE), float
        )
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read min/max/unit/step from live widget metadata."""
        meta = self.widget.metadata
        if meta.min_value is not None:
            self._attr_native_min_value = meta.min_value
        if meta.max_value is not None:
            self._attr_native_max_value = meta.max_value

        unit = meta.unit
        self._attr_native_unit_of_measurement = unit if unit else None

        precision_str = meta.raw.get(META_DECIMAL_PRECISION, "")
        if precision_str:
            try:
                precision = int(precision_str)
                self._attr_native_step = 10 ** -precision
                self._attr_suggested_display_precision = precision
                return
            except (ValueError, TypeError):
                pass

        if self._is_float:
            self._attr_native_step = 0.01
            self._attr_suggested_display_precision = 2
        else:
            self._attr_native_step = 1.0
            self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> float | int | None:
        """Return the current numeric value from the PLC."""
        value = self.widget.values.get(VAL_DATATYPE_VALUE)
        if value is None:
            return None
        if self._is_float:
            return float(value)
        return int(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value to the PLC."""
        self._check_read_only()
        if self._attr_native_min_value is not None:
            value = max(self._attr_native_min_value, value)
        if self._attr_native_max_value is not None:
            value = min(self._attr_native_max_value, value)
        plc_value: int | float = value if self._is_float else int(value)
        await self._send_optimistic({self.widget.path: plc_value})


class TcIotGeneralNumber(TcIotEntity, NumberEntity):
    """A General widget nValue2/nValue3 exposed as number entity."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        value_key: str,
        request_key: str,
        suffix: str,
        translation_key: str,
    ) -> None:
        """Initialize from a General widget value slot."""
        super().__init__(coordinator, device_name, widget)
        self._value_key = value_key
        self._request_key = request_key

        self._attr_unique_id = f"{self._attr_unique_id}{suffix}"
        self._attr_translation_key = translation_key
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read min/max/unit/precision from live widget field_metadata."""
        fm = self.widget.field_metadata.get(self._value_key, {})
        try:
            self._attr_native_min_value = float(fm[META_MIN_VALUE])
        except (KeyError, ValueError, TypeError):
            pass
        try:
            self._attr_native_max_value = float(fm[META_MAX_VALUE])
        except (KeyError, ValueError, TypeError):
            pass
        unit = fm.get(META_UNIT)
        self._attr_native_unit_of_measurement = unit if unit else None

        precision_str = fm.get(META_DECIMAL_PRECISION, "")
        if precision_str:
            try:
                precision = int(precision_str)
                self._attr_native_step = 10 ** -precision
                self._attr_suggested_display_precision = precision
                return
            except (ValueError, TypeError):
                pass
        self._attr_native_step = 1.0
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> float | int | None:
        """Return the current value."""
        value = self.widget.values.get(self._value_key)
        if value is None:
            return None
        if self._attr_native_step >= 1:
            return int(value)
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value to the PLC via the request key."""
        self._check_read_only()
        if self._attr_native_min_value is not None:
            value = max(self._attr_native_min_value, value)
        if self._attr_native_max_value is not None:
            value = min(self._attr_native_max_value, value)
        plc_value: int | float = value if self._attr_native_step < 1 else int(value)
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{self._request_key}": plc_value},
        )


# ── Motion widget numbers ────────────────────────────────────────

_MOTION_PCT_RANGE: tuple[int, int, str] = (0, 100, "%")

_MOTION_NUMBER_SLOTS: tuple[
    tuple[str, str, str, str, tuple[int, int, str] | None], ...
] = (
    (META_MOTION_HOLD_TIME_VISIBLE, VAL_MOTION_HOLD_TIME,
     "_hold_time", "motion_hold_time", None),
    (META_MOTION_BRIGHTNESS_VISIBLE, VAL_MOTION_BRIGHTNESS,
     "_brightness", "motion_brightness", _MOTION_PCT_RANGE),
    (META_MOTION_RANGE_VISIBLE, VAL_MOTION_RANGE,
     "_range", "motion_range", _MOTION_PCT_RANGE),
    (META_MOTION_SENSITIVITY_VISIBLE, VAL_MOTION_SENSITIVITY,
     "_sensitivity", "motion_sensitivity", _MOTION_PCT_RANGE),
)


def _create_motion_numbers(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[NumberEntity]:
    """Create number entities for visible Motion widget value fields."""
    raw = widget.metadata.raw
    entities: list[NumberEntity] = []
    for vis_key, val_key, suffix, tkey, fixed in _MOTION_NUMBER_SLOTS:
        if raw.get(vis_key, "").lower() != "true":
            continue
        entity = TcIotGeneralNumber(
            coordinator, device_name, widget,
            value_key=val_key,
            request_key=val_key,
            suffix=suffix,
            translation_key=tkey,
        )
        entity._attr_native_step = 1
        entity._attr_suggested_display_precision = 0
        if fixed is not None:
            entity._attr_native_min_value = fixed[0]
            entity._attr_native_max_value = fixed[1]
            entity._attr_native_unit_of_measurement = fixed[2]
        entities.append(entity)
    return entities


# ── PLC Array of numeric values ──────────────────────────────────


def _create_array_numbers(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[NumberEntity]:
    """Create one number entity per element in a PLC numeric array."""
    arr = widget.values.get("value", [])
    if not isinstance(arr, list):
        return []
    return [
        TcIotDatatypeArrayNumber(coordinator, device_name, widget, index=i)
        for i in range(len(arr))
    ]


class TcIotDatatypeArrayNumber(TcIotEntity, NumberEntity):
    """A single element of a PLC numeric array.

    Arrays are always read-only; write commands are blocked.
    """

    _attr_mode = NumberMode.BOX

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
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read min/max/unit/precision from live widget metadata."""
        meta = self.widget.metadata
        if meta.min_value is not None:
            self._attr_native_min_value = meta.min_value
        if meta.max_value is not None:
            self._attr_native_max_value = meta.max_value
        unit = meta.unit
        self._attr_native_unit_of_measurement = unit if unit else None

        precision_str = meta.raw.get(META_DECIMAL_PRECISION, "")
        if precision_str:
            try:
                precision = int(precision_str)
                self._attr_native_step = 10 ** -precision
                self._attr_suggested_display_precision = precision
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float | int | None:
        """Return the value of this array element."""
        arr = self.widget.values.get("value")
        if not isinstance(arr, list) or self._index >= len(arr):
            return None
        val = arr[self._index]
        if val is None:
            return None
        return float(val) if isinstance(val, float) else int(val)

    async def async_set_native_value(self, value: float) -> None:
        """Block writes — PLC arrays are read-only."""
        self._check_read_only()
