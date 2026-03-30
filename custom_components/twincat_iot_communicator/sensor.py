"""Sensor platform for TwinCAT IoT Communicator.

Provides:
- Device-level diagnostic sensors (Desc timestamp, message count, etc.)
- Widget-based sensors for EnergyMonitoring / ChargingStation / Lock / Motion
- Read-only companion sensors for scalar PLC datatype widgets (BOOL, NUMBER, STRING)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DATATYPE_NUMBER,
    DATATYPE_STRING,
    META_CHARGING_STATION_PHASE2_VISIBLE,
    META_CHARGING_STATION_PHASE3_VISIBLE,
    META_ENERGY_MONITORING_PHASE2_VISIBLE,
    META_ENERGY_MONITORING_PHASE3_VISIBLE,
    META_GENERAL_VALUE2_VISIBLE,
    META_GENERAL_VALUE3_VISIBLE,
    META_DECIMAL_PRECISION,
    META_ICON,
    META_LOCK_STATE_VISIBLE,
    META_MOTION_BATTERY_VISIBLE,
    META_UNIT,
    VAL_AC_MODE,
    VAL_CHARGING_BATTERY_LEVEL,
    VAL_CHARGING_CURRENT_POWER,
    VAL_CHARGING_ENERGY,
    VAL_CHARGING_STATUS,
    VAL_CHARGING_THREE_PHASE_AMPERAGE,
    VAL_CHARGING_THREE_PHASE_CURRENT_POWER,
    VAL_CHARGING_THREE_PHASE_MAX_POWER,
    VAL_CHARGING_THREE_PHASE_VOLTAGE,
    VAL_CHARGING_TIME,
    VAL_DATATYPE_VALUE,
    VAL_ENERGY_CURRENT_POWER,
    VAL_ENERGY_POWER_QUALITY_FACTOR,
    VAL_ENERGY_POWER_UNIT,
    VAL_ENERGY_STATUS,
    VAL_ENERGY_THREE_PHASE_AMPERAGE,
    VAL_ENERGY_THREE_PHASE_AMPERAGE_UNITS,
    VAL_ENERGY_THREE_PHASE_CURRENT_POWER,
    VAL_ENERGY_THREE_PHASE_POWER_UNITS,
    VAL_ENERGY_THREE_PHASE_VOLTAGE,
    VAL_ENERGY_THREE_PHASE_VOLTAGE_UNITS,
    VAL_ENERGY_UNIT,
    VAL_ENERGY_VALUE,
    VAL_GENERAL_VALUE2,
    VAL_GENERAL_VALUE3,
    VAL_LOCK_STATE,
    VAL_MOTION_BATTERY,
    WIDGET_TYPE_AIRCON,
    WIDGET_TYPE_CHARGING_STATION,
    WIDGET_TYPE_ENERGY_MONITORING,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_LOCK,
    WIDGET_TYPE_MOTION,
)
from . import TcIotConfigEntry
from .coordinator import TcIotCoordinator
from .entity import TcIotDeviceEntity, TcIotEntity
from .models import DeviceContext, TcIotMessage, WidgetData

PARALLEL_UPDATES = 0

UNIT_DEVICE_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "°C": SensorDeviceClass.TEMPERATURE,
    "°F": SensorDeviceClass.TEMPERATURE,
    "K": SensorDeviceClass.TEMPERATURE,
    "%": SensorDeviceClass.HUMIDITY,
    "W": SensorDeviceClass.POWER,
    "kW": SensorDeviceClass.POWER,
    "mW": SensorDeviceClass.POWER,
    "V": SensorDeviceClass.VOLTAGE,
    "A": SensorDeviceClass.CURRENT,
    "mA": SensorDeviceClass.CURRENT,
    "kWh": SensorDeviceClass.ENERGY,
    "Wh": SensorDeviceClass.ENERGY,
    "hPa": SensorDeviceClass.PRESSURE,
    "Pa": SensorDeviceClass.PRESSURE,
    "bar": SensorDeviceClass.PRESSURE,
    "lx": SensorDeviceClass.ILLUMINANCE,
    "Hz": SensorDeviceClass.FREQUENCY,
    "ppm": SensorDeviceClass.CO2,
}

ICON_SENSOR_CLASS_MAP: dict[str, SensorDeviceClass] = {
    "Temperature": SensorDeviceClass.TEMPERATURE,
    "Droplet": SensorDeviceClass.HUMIDITY,
    "Co2": SensorDeviceClass.CO2,
    "Co2_Filled": SensorDeviceClass.CO2,
    "Snowflake": SensorDeviceClass.TEMPERATURE,
    "Snowflake_Blue": SensorDeviceClass.TEMPERATURE,
}

AC_MODE_MAP: dict[int, str] = {
    0: "none",
    1: "cooling",
    2: "ventilation",
    3: "heating",
    4: "cooling_off",
    5: "ventilation_off",
    6: "heating_off",
}

AC_MODE_OPTIONS: list[str] = list(AC_MODE_MAP.values())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT sensors (diagnostic + EnergyMonitoring)."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []

    for device in coordinator.devices.values():
        entities.append(TcIotDescTimestamp(coordinator, device))
        entities.append(TcIotHeartbeatInterval(coordinator, device))
        entities.append(TcIotMessageCount(coordinator, device))
        entities.append(TcIotLastMessage(coordinator, device))
        entities.append(TcIotLastMessageType(coordinator, device))

    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(
                _create_widget_sensors(coordinator, device_name, widget)
            )

    if entities:
        async_add_entities(entities)

    def _on_new_device(device: DeviceContext) -> None:
        async_add_entities([
            TcIotDescTimestamp(coordinator, device),
            TcIotHeartbeatInterval(coordinator, device),
            TcIotMessageCount(coordinator, device),
            TcIotLastMessage(coordinator, device),
            TcIotLastMessageType(coordinator, device),
        ])

    coordinator.register_new_device_callback(_on_new_device)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[SensorEntity] = []
        for widget in widgets:
            new.extend(
                _create_widget_sensors(coordinator, device_name, widget)
            )
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.SENSOR, _on_new_widgets)


def _create_widget_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create sensor entities for a single widget based on its type."""
    match widget.metadata.widget_type:
        case t if t == WIDGET_TYPE_AIRCON:
            return _create_ac_sensors(coordinator, device_name, widget)
        case t if t == WIDGET_TYPE_GENERAL:
            return _create_general_sensors(coordinator, device_name, widget)
        case t if t == WIDGET_TYPE_ENERGY_MONITORING:
            return _create_energy_monitoring_sensors(
                coordinator, device_name, widget,
            )
        case t if t == WIDGET_TYPE_CHARGING_STATION:
            return _create_charging_station_sensors(
                coordinator, device_name, widget,
            )
        case t if t == WIDGET_TYPE_LOCK:
            return _create_lock_sensors(coordinator, device_name, widget)
        case t if t == WIDGET_TYPE_MOTION:
            return _create_motion_sensors(coordinator, device_name, widget)
        case t if t in {DATATYPE_NUMBER, DATATYPE_STRING}:
            return [TcIotDatatypeSensor(coordinator, device_name, widget)]
    return []


# ── AC mode sensor ────────────────────────────────────────────────────


def _create_ac_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create sensor entities for an AC widget."""
    return [TcIotAcModeSensor(coordinator, device_name, widget)]


class TcIotAcModeSensor(TcIotEntity, SensorEntity):
    """Sensor exposing the E_IoT_AcMode enum as an HA enum sensor."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AC_MODE_OPTIONS

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the AC mode sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_{VAL_AC_MODE}"
        self._attr_translation_key = "ac_mode"

    @property
    def native_value(self) -> str | None:
        """Return the AC mode as a mapped string."""
        raw = self.widget.values.get(VAL_AC_MODE)
        if raw is None:
            return None
        try:
            return AC_MODE_MAP.get(int(raw), AC_MODE_MAP[0])
        except (TypeError, ValueError):
            return None


# ── General widget value sensors ─────────────────────────────────────


_GENERAL_VALUE_SLOTS: tuple[tuple[str, str, str], ...] = (
    (META_GENERAL_VALUE2_VISIBLE, VAL_GENERAL_VALUE2, "general_value_2"),
    (META_GENERAL_VALUE3_VISIBLE, VAL_GENERAL_VALUE3, "general_value_3"),
)


def _create_general_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create read-only sensor entities for visible General widget value slots."""
    raw = widget.metadata.raw
    entities: list[SensorEntity] = []
    for vis_key, val_key, tkey in _GENERAL_VALUE_SLOTS:
        if raw.get(vis_key, "").lower() != "true":
            continue
        fm = widget.field_metadata.get(val_key, {})
        unit = fm.get(META_UNIT)
        precision: int = 0
        precision_str = fm.get(META_DECIMAL_PRECISION, "")
        if precision_str:
            try:
                precision = int(precision_str)
            except (ValueError, TypeError):
                pass
        entities.append(TcIotEnergyFieldSensor(
            coordinator, device_name, widget,
            field_key=val_key,
            translation_key=tkey,
            device_class=None,
            fallback_unit=unit,
            state_class=None,
            suggested_display_precision=precision,
        ))
    return entities


def _create_energy_monitoring_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create multiple sensor entities for an EnergyMonitoring widget."""
    raw = widget.metadata.raw
    has_phase2 = (
        raw.get(META_ENERGY_MONITORING_PHASE2_VISIBLE, "false").lower()
        == "true"
    )
    has_phase3 = (
        raw.get(META_ENERGY_MONITORING_PHASE3_VISIBLE, "false").lower()
        == "true"
    )
    num_phases = 1 + (1 if has_phase2 else 0) + (1 if has_phase3 else 0)

    entities: list[SensorEntity] = []

    _PHASE_KEYS = ["l1", "l2", "l3"]

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_ENERGY_STATUS, translation_key="status",
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_ENERGY_CURRENT_POWER, translation_key="power",
        device_class=SensorDeviceClass.POWER,
        unit_field=VAL_ENERGY_POWER_UNIT, fallback_unit="kW",
        state_class=SensorStateClass.MEASUREMENT,
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_ENERGY_VALUE, translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        unit_field=VAL_ENERGY_UNIT, fallback_unit="kWh",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_ENERGY_POWER_QUALITY_FACTOR, translation_key="power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ))

    for phase_index in range(num_phases):
        pk = _PHASE_KEYS[phase_index]

        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_ENERGY_THREE_PHASE_CURRENT_POWER,
            unit_array_key=VAL_ENERGY_THREE_PHASE_POWER_UNITS,
            phase_index=phase_index, translation_key=f"{pk}_power",
            device_class=SensorDeviceClass.POWER,
            fallback_unit="W",
        ))
        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_ENERGY_THREE_PHASE_VOLTAGE,
            unit_array_key=VAL_ENERGY_THREE_PHASE_VOLTAGE_UNITS,
            phase_index=phase_index, translation_key=f"{pk}_voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            fallback_unit="V",
        ))
        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_ENERGY_THREE_PHASE_AMPERAGE,
            unit_array_key=VAL_ENERGY_THREE_PHASE_AMPERAGE_UNITS,
            phase_index=phase_index, translation_key=f"{pk}_current",
            device_class=SensorDeviceClass.CURRENT,
            fallback_unit="A",
        ))

    return entities


def _create_charging_station_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create multiple sensor entities for a ChargingStation widget."""
    raw = widget.metadata.raw
    has_phase2 = (
        raw.get(META_CHARGING_STATION_PHASE2_VISIBLE, "false").lower()
        == "true"
    )
    has_phase3 = (
        raw.get(META_CHARGING_STATION_PHASE3_VISIBLE, "false").lower()
        == "true"
    )
    num_phases = 1 + (1 if has_phase2 else 0) + (1 if has_phase3 else 0)

    entities: list[SensorEntity] = []

    _PHASE_KEYS = ["l1", "l2", "l3"]

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_CHARGING_STATUS, translation_key="status",
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_CHARGING_BATTERY_LEVEL, translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        fallback_unit="%",
        state_class=SensorStateClass.MEASUREMENT,
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_CHARGING_CURRENT_POWER, translation_key="power",
        device_class=SensorDeviceClass.POWER,
        fallback_unit="kW",
        state_class=SensorStateClass.MEASUREMENT,
    ))

    entities.append(TcIotEnergyFieldSensor(
        coordinator, device_name, widget,
        field_key=VAL_CHARGING_ENERGY, translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        fallback_unit="kWh",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ))

    entities.append(TcIotChargingTimeSensor(
        coordinator, device_name, widget,
    ))

    for phase_index in range(num_phases):
        pk = _PHASE_KEYS[phase_index]

        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_CHARGING_THREE_PHASE_CURRENT_POWER,
            unit_array_key=None,
            phase_index=phase_index, translation_key=f"{pk}_power",
            device_class=SensorDeviceClass.POWER,
            fallback_unit="kW",
        ))
        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_CHARGING_THREE_PHASE_MAX_POWER,
            unit_array_key=None,
            phase_index=phase_index, translation_key=f"{pk}_max_power",
            device_class=SensorDeviceClass.POWER,
            fallback_unit="kW",
        ))
        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_CHARGING_THREE_PHASE_VOLTAGE,
            unit_array_key=None,
            phase_index=phase_index, translation_key=f"{pk}_voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            fallback_unit="V",
        ))
        entities.append(TcIotEnergyPhaseSensor(
            coordinator, device_name, widget,
            array_key=VAL_CHARGING_THREE_PHASE_AMPERAGE,
            unit_array_key=None,
            phase_index=phase_index, translation_key=f"{pk}_current",
            device_class=SensorDeviceClass.CURRENT,
            fallback_unit="A",
        ))

    return entities


# ── Lock sensors ─────────────────────────────────────────────────────


def _create_lock_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create sensor entities for a Lock widget."""
    raw = widget.metadata.raw
    if raw.get(META_LOCK_STATE_VISIBLE, "false").lower() != "true":
        return []
    return [
        TcIotEnergyFieldSensor(
            coordinator, device_name, widget,
            field_key=VAL_LOCK_STATE,
            translation_key="lock_state",
        ),
    ]


# ── Motion sensors ───────────────────────────────────────────────────


def _create_motion_sensors(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[SensorEntity]:
    """Create sensor entities for a Motion widget."""
    raw = widget.metadata.raw
    if raw.get(META_MOTION_BATTERY_VISIBLE, "false").lower() != "true":
        return []
    return [
        TcIotEnergyFieldSensor(
            coordinator, device_name, widget,
            field_key=VAL_MOTION_BATTERY,
            translation_key="motion_battery",
            device_class=SensorDeviceClass.BATTERY,
            fallback_unit="%",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ]


# ── Scalar datatype companion sensor ─────────────────────────────────


class TcIotDatatypeSensor(TcIotEntity, SensorEntity):
    """Read-only sensor companion for PLC datatype widgets (BOOL, NUMBER, STRING)."""

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the datatype companion sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_sensor"
        self._attr_translation_key = "dt_sensor"
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        raw = self.widget.metadata.raw
        icon_name = raw.get(META_ICON, "")

        device_class = ICON_SENSOR_CLASS_MAP.get(icon_name)

        unit = self.widget.metadata.unit
        if not device_class and unit:
            device_class = UNIT_DEVICE_CLASS_MAP.get(unit)

        self._attr_device_class = device_class
        self._attr_state_class = (
            SensorStateClass.MEASUREMENT if device_class else None
        )
        self._attr_native_unit_of_measurement = unit if unit else None

        precision_str = raw.get(META_DECIMAL_PRECISION, "")
        if precision_str:
            try:
                self._attr_suggested_display_precision = int(precision_str)
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> Any:
        """Return the current PLC value."""
        return self.widget.values.get(VAL_DATATYPE_VALUE)


# ── Charging station time sensor ─────────────────────────────────────


class TcIotChargingTimeSensor(TcIotEntity, SensorEntity):
    """Sensor for the charging duration in seconds."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize the charging time sensor."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_{VAL_CHARGING_TIME}"
        self._attr_translation_key = "charging_time"

    @property
    def native_value(self) -> float | None:
        """Return the charging time in seconds."""
        val = self.widget.values.get(VAL_CHARGING_TIME)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None


# ── Energy monitoring sensors ────────────────────────────────────────


class TcIotEnergyFieldSensor(TcIotEntity, SensorEntity):
    """Sensor for a single scalar field of an EnergyMonitoring widget."""

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        field_key: str,
        translation_key: str,
        device_class: SensorDeviceClass | None = None,
        unit_field: str | None = None,
        fallback_unit: str | None = None,
        state_class: SensorStateClass | None = None,
        suggested_display_precision: int | None = None,
    ) -> None:
        """Initialize from a widget and field key."""
        super().__init__(coordinator, device_name, widget)
        self._field_key = field_key
        self._unit_field = unit_field
        self._fallback_unit = fallback_unit

        self._attr_unique_id = f"{self._attr_unique_id}_{field_key}"
        self._attr_translation_key = translation_key
        if device_class:
            self._attr_device_class = device_class
        if state_class:
            self._attr_state_class = state_class
        if suggested_display_precision is not None:
            self._attr_suggested_display_precision = suggested_display_precision
        if not unit_field:
            self._attr_native_unit_of_measurement = fallback_unit

    @property
    def native_value(self) -> Any:
        """Return the current field value."""
        return self.widget.values.get(self._field_key)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the dynamic unit from PLC, falling back to the default."""
        if self._unit_field:
            unit = self.widget.values.get(self._unit_field)
            if unit:
                return str(unit)
            return self._fallback_unit
        return self._attr_native_unit_of_measurement


class TcIotEnergyPhaseSensor(TcIotEntity, SensorEntity):
    """Sensor for a single phase element of an EnergyMonitoring array field."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
        *,
        array_key: str,
        unit_array_key: str | None,
        phase_index: int,
        translation_key: str,
        device_class: SensorDeviceClass | None = None,
        fallback_unit: str = "",
    ) -> None:
        """Initialize from a widget, array key, and phase index."""
        super().__init__(coordinator, device_name, widget)
        self._array_key = array_key
        self._unit_array_key = unit_array_key
        self._phase_index = phase_index
        self._fallback_unit = fallback_unit

        self._attr_unique_id = (
            f"{self._attr_unique_id}_{array_key}_{phase_index}"
        )
        self._attr_translation_key = translation_key
        if device_class:
            self._attr_device_class = device_class

    @property
    def native_value(self) -> float | None:
        """Return the phase value from the PLC array."""
        phases = self.widget.values.get(self._array_key)
        if isinstance(phases, list) and self._phase_index < len(phases):
            try:
                return float(phases[self._phase_index])
            except (TypeError, ValueError):
                return None
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the phase unit from the PLC array, falling back to default."""
        if self._unit_array_key:
            units = self.widget.values.get(self._unit_array_key)
            if isinstance(units, list) and self._phase_index < len(units):
                return str(units[self._phase_index])
        return self._fallback_unit


# ── Device-level diagnostic sensors ──────────────────────────────────


class TcIotDescTimestamp(TcIotDeviceEntity, SensorEntity):
    """Diagnostic sensor showing the last Desc timestamp from the PLC."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the Desc timestamp diagnostic sensor."""
        super().__init__(coordinator, device, "desc_timestamp")
        self._unsub_hub: Callable[[], None] | None = None
        self._attr_translation_key = "desc_timestamp"

    @property
    def native_value(self) -> datetime | None:
        """Return the last Desc timestamp as a datetime."""
        timestamp = self._dev.desc_timestamp
        if not timestamp:
            return None
        try:
            datetime_val = datetime.fromisoformat(timestamp)
            if datetime_val.tzinfo is None:
                datetime_val = datetime_val.replace(
                    tzinfo=dt_util.get_default_time_zone()
                )
            return datetime_val
        except (ValueError, TypeError):
            return None

    async def async_added_to_hass(self) -> None:
        """Register the hub status callback when the entity is added."""
        self._unsub_hub = self.coordinator.register_hub_status_callback(
            self._dev.device_name, self._on_update,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the hub status callback when the entity is removed."""
        if self._unsub_hub:
            self._unsub_hub()
            self._unsub_hub = None

    @callback
    def _on_update(self) -> None:
        """Handle a hub status update from the coordinator."""
        self.async_write_ha_state()


class TcIotHeartbeatInterval(TcIotDeviceEntity, SensorEntity):
    """Diagnostic sensor showing the measured Desc heartbeat interval."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the heartbeat interval diagnostic sensor."""
        super().__init__(coordinator, device, "heartbeat_interval")
        self._unsub_hub: Callable[[], None] | None = None
        self._attr_translation_key = "heartbeat_interval"

    @property
    def native_value(self) -> float | None:
        """Return the measured Desc interval in seconds."""
        return self._dev.desc_interval

    async def async_added_to_hass(self) -> None:
        """Register the hub status callback when the entity is added."""
        self._unsub_hub = self.coordinator.register_hub_status_callback(
            self._dev.device_name, self._on_update,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the hub status callback when the entity is removed."""
        if self._unsub_hub:
            self._unsub_hub()
            self._unsub_hub = None

    @callback
    def _on_update(self) -> None:
        """Handle a hub status update from the coordinator."""
        self.async_write_ha_state()


class TcIotMessageCount(TcIotDeviceEntity, SensorEntity):
    """Diagnostic sensor showing the number of unacknowledged PLC messages."""

    _attr_icon = "mdi:message-badge"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "messages"

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the message count sensor."""
        super().__init__(coordinator, device, "message_count")
        self._unsub: Callable[[], None] | None = None
        self._attr_translation_key = "message_count"

    @property
    def native_value(self) -> int:
        """Return the number of unacknowledged messages."""
        return sum(
            1 for message in self._dev.messages.values()
            if not message.acknowledged
        )

    async def async_added_to_hass(self) -> None:
        """Register the message callback when the entity is added."""
        self._unsub = self.coordinator.register_message_callback(
            self._dev.device_name, self._on_message,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the message callback when the entity is removed."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_message(self, event_type: str, message: TcIotMessage | None) -> None:
        """Handle any message change and update the count."""
        self.async_write_ha_state()


class TcIotLastMessage(TcIotDeviceEntity, SensorEntity):
    """Sensor showing the last PLC message text."""

    _attr_icon = "mdi:message-text-outline"

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the last message sensor."""
        super().__init__(coordinator, device, "last_message")
        self._unsub: Callable[[], None] | None = None
        self._last_message: TcIotMessage | None = None
        self._attr_translation_key = "last_message"

    @property
    def native_value(self) -> str | None:
        """Return the text of the most recent message."""
        return self._last_message.text if self._last_message else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return message details as attributes."""
        if not self._last_message:
            return {}
        return {
            "message_id": self._last_message.message_id,
            "type": self._last_message.message_type,
            "timestamp": self._last_message.timestamp,
            "acknowledged": self._last_message.acknowledged,
        }

    async def async_added_to_hass(self) -> None:
        """Register the message callback when the entity is added."""
        self._unsub = self.coordinator.register_message_callback(
            self._dev.device_name, self._on_message,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the message callback when the entity is removed."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_message(self, event_type: str, message: TcIotMessage | None) -> None:
        """Update the last message on new message received."""
        if event_type == "received" and message:
            self._last_message = message
            self.async_write_ha_state()


class TcIotLastMessageType(TcIotDeviceEntity, SensorEntity):
    """Sensor showing the type/severity of the last PLC message."""

    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self, coordinator: TcIotCoordinator, device: DeviceContext,
    ) -> None:
        """Initialize the last message type sensor."""
        super().__init__(coordinator, device, "last_message_type")
        self._unsub: Callable[[], None] | None = None
        self._last_message: TcIotMessage | None = None
        self._attr_translation_key = "last_message_type"

    @property
    def native_value(self) -> str | None:
        """Return the type of the most recent message."""
        return self._last_message.message_type if self._last_message else None

    async def async_added_to_hass(self) -> None:
        """Register the message callback when the entity is added."""
        self._unsub = self.coordinator.register_message_callback(
            self._dev.device_name, self._on_message,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the message callback when the entity is removed."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_message(self, event_type: str, message: TcIotMessage | None) -> None:
        """Update the last message type on new message received."""
        if event_type == "received" and message:
            self._last_message = message
            self.async_write_ha_state()
