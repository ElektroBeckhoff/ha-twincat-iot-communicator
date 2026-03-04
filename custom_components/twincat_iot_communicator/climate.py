"""Climate platform for TwinCAT IoT Communicator (AC widgets)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DOMAIN,
    META_AC_MODE_CHANGEABLE,
    META_AC_MODE_LAMELLA_CHANGEABLE,
    META_AC_MODE_LAMELLA_VISIBLE,
    META_AC_MODE_STRENGTH_CHANGEABLE,
    META_AC_MODE_STRENGTH_VISIBLE,
    META_AC_MODE_VISIBLE,
    META_AC_VALUE_REQUEST_VISIBLE,
    META_DECIMAL_PRECISION,
    META_UNIT,
    VAL_AC_MODE,
    VAL_AC_TEMPERATURE,
    VAL_AC_TEMPERATURE_REQUEST,
    VAL_MODE,
    VAL_MODES,
    VAL_MODE_LAMELLA,
    VAL_MODE_STRENGTH,
    VAL_MODES_LAMELLA,
    VAL_MODES_STRENGTH,
    WIDGET_TYPE_AIRCON,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

HVAC_MODE_MAP: dict[str, HVACMode] = {
    "auto": HVACMode.AUTO,
    "automatisch": HVACMode.AUTO,
    "automatic": HVACMode.AUTO,
    "heizen": HVACMode.HEAT,
    "heat": HVACMode.HEAT,
    "heating": HVACMode.HEAT,
    "kühlen": HVACMode.COOL,
    "kuehlen": HVACMode.COOL,
    "cool": HVACMode.COOL,
    "cooling": HVACMode.COOL,
    "aus": HVACMode.OFF,
    "off": HVACMode.OFF,
    "heat_cool": HVACMode.HEAT_COOL,
    "fan_only": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT climate entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TcIotClimate] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            if widget.metadata.widget_type == WIDGET_TYPE_AIRCON:
                entities.append(TcIotClimate(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new = [
            TcIotClimate(coordinator, device_name, widget)
            for widget in widgets
            if widget.metadata.widget_type == WIDGET_TYPE_AIRCON
        ]
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.CLIMATE, _on_new_widgets)


class TcIotClimate(TcIotEntity, ClimateEntity):
    """A TcIoT AC widget exposed as HA climate entity."""

    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a discovered AC widget."""
        super().__init__(coordinator, device_name, widget)
        self._plc_modes: list[str] = []
        self._hvac_map: dict[str, HVACMode] = {}
        self._preset_modes: list[str] = []
        self._reverse_hvac: dict[HVACMode, str] = {}
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read all metadata-dependent attributes from the live widget."""
        self._sync_temperature()
        self._sync_modes()

    def _sync_temperature(self) -> None:
        """Configure temperature unit, range, and step from widget metadata."""
        temp_unit = self.widget.field_metadata.get(
            VAL_AC_TEMPERATURE, {},
        ).get(META_UNIT, "°C")
        if "F" in temp_unit:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
        else:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS

        self._attr_min_temp = self.widget.field_min(VAL_AC_TEMPERATURE, 16)
        self._attr_max_temp = self.widget.field_max(VAL_AC_TEMPERATURE, 30)

        precision = self.widget.field_metadata.get(
            VAL_AC_TEMPERATURE, {},
        ).get(META_DECIMAL_PRECISION, "1")
        try:
            self._attr_target_temperature_step = 10 ** -int(precision)
        except (ValueError, TypeError):
            self._attr_target_temperature_step = 0.5

    def _sync_modes(self) -> None:
        """Configure HVAC modes, presets, fan, swing, and features."""
        raw = self.widget.metadata.raw
        features = ClimateEntityFeature(0)

        can_set_temp = (
            raw.get(META_AC_VALUE_REQUEST_VISIBLE, "false").lower() == "true"
        )
        if can_set_temp:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        plc_modes = self.widget.values.get(VAL_MODES, [])
        self._plc_modes = [m for m in plc_modes if m]
        self._hvac_map = {}
        self._preset_modes = []

        for mode_string in self._plc_modes:
            ha_mode = HVAC_MODE_MAP.get(mode_string.lower())
            if ha_mode:
                self._hvac_map[mode_string] = ha_mode
            else:
                self._preset_modes.append(mode_string)

        mapped_hvac = set(self._hvac_map.values())
        if HVACMode.OFF not in mapped_hvac:
            mapped_hvac.add(HVACMode.OFF)
        self._attr_hvac_modes = sorted(mapped_hvac, key=lambda m: m.value)

        if self._preset_modes:
            features |= ClimateEntityFeature.PRESET_MODE

        supports_mode = (
            raw.get(META_AC_MODE_VISIBLE, "false").lower() == "true"
        )
        can_change_mode = (
            raw.get(META_AC_MODE_CHANGEABLE, "false").lower() == "true"
        )
        if supports_mode and can_change_mode:
            features |= (
                ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
            )

        supports_strength = (
            raw.get(META_AC_MODE_STRENGTH_VISIBLE, "false").lower() == "true"
        )
        can_change_strength = (
            raw.get(META_AC_MODE_STRENGTH_CHANGEABLE, "false").lower()
            == "true"
        )
        strength_modes = [
            m for m in self.widget.values.get(VAL_MODES_STRENGTH, []) if m
        ]
        if supports_strength and strength_modes:
            self._attr_fan_modes = strength_modes
            if can_change_strength:
                features |= ClimateEntityFeature.FAN_MODE
        else:
            self._attr_fan_modes = []

        supports_lamella = (
            raw.get(META_AC_MODE_LAMELLA_VISIBLE, "false").lower() == "true"
        )
        can_change_lamella = (
            raw.get(META_AC_MODE_LAMELLA_CHANGEABLE, "false").lower() == "true"
        )
        lamella_modes = [
            m for m in self.widget.values.get(VAL_MODES_LAMELLA, []) if m
        ]
        if supports_lamella and lamella_modes:
            self._attr_swing_modes = lamella_modes
            if can_change_lamella:
                features |= ClimateEntityFeature.SWING_MODE
        else:
            self._attr_swing_modes = []

        self._attr_supported_features = features

        self._reverse_hvac = {}
        for plc_mode_string, ha_mode in self._hvac_map.items():
            if ha_mode not in self._reverse_hvac:
                self._reverse_hvac[ha_mode] = plc_mode_string

    # ── State properties ─────────────────────────────────────────────

    @property
    def current_temperature(self) -> float | None:
        """Return the current measured temperature."""
        value = self.widget.values.get(VAL_AC_TEMPERATURE)
        if value is None:
            return None
        return float(value)

    @property
    def target_temperature(self) -> float | None:
        """Return the target (requested) temperature."""
        value = self.widget.values.get(VAL_AC_TEMPERATURE_REQUEST)
        if value is None:
            return None
        return float(value)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode mapped from the PLC mode string."""
        current = self.widget.values.get(VAL_MODE, "")
        mapped = self._hvac_map.get(current)
        if mapped:
            return mapped
        return HVACMode.OFF

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset, or None if the current mode is an HVAC mode."""
        if not self._preset_modes:
            return None
        current = self.widget.values.get(VAL_MODE, "")
        if current in self._preset_modes:
            return current
        return None

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the list of available preset modes."""
        return self._preset_modes if self._preset_modes else None

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan speed mode."""
        return self.widget.values.get(VAL_MODE_STRENGTH)

    @property
    def swing_mode(self) -> str | None:
        """Return the current lamella/swing mode."""
        return self.widget.values.get(VAL_MODE_LAMELLA)

    # ── Commands ─────────────────────────────────────────────────────

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        self._check_read_only()
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = max(
            self._attr_min_temp,
            min(self._attr_max_temp, float(temperature)),
        )
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_AC_TEMPERATURE_REQUEST}": temperature},
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode by mapping back to the PLC mode string."""
        self._check_read_only()
        plc_mode_string = self._reverse_hvac.get(hvac_mode)
        if plc_mode_string is None:
            _LOGGER.warning("No PLC mode mapping for %s", hvac_mode)
            return
        commands: dict[str, Any] = {
            f"{self.widget.path}.{VAL_MODE}": plc_mode_string,
        }
        if plc_mode_string in self._plc_modes:
            commands[f"{self.widget.path}.{VAL_AC_MODE}"] = (
                self._plc_modes.index(plc_mode_string)
            )
        await self.coordinator.async_send_command(self.device_name, commands)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a preset mode (non-HVAC PLC mode)."""
        self._check_read_only()
        if preset_mode not in self._preset_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_preset_mode",
                translation_placeholders={
                    "mode": preset_mode,
                    "name": self.name or "",
                    "allowed": ", ".join(self._preset_modes),
                },
            )
        commands: dict[str, Any] = {
            f"{self.widget.path}.{VAL_MODE}": preset_mode,
        }
        if preset_mode in self._plc_modes:
            commands[f"{self.widget.path}.{VAL_AC_MODE}"] = (
                self._plc_modes.index(preset_mode)
            )
        await self.coordinator.async_send_command(self.device_name, commands)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed mode."""
        self._check_read_only()
        if self._attr_fan_modes and fan_mode not in self._attr_fan_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_fan_mode",
                translation_placeholders={
                    "mode": fan_mode,
                    "name": self.name or "",
                    "allowed": ", ".join(self._attr_fan_modes),
                },
            )
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE_STRENGTH}": fan_mode},
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the lamella/swing mode."""
        self._check_read_only()
        if self._attr_swing_modes and swing_mode not in self._attr_swing_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_swing_mode",
                translation_placeholders={
                    "mode": swing_mode,
                    "name": self.name or "",
                    "allowed": ", ".join(self._attr_swing_modes),
                },
            )
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE_LAMELLA}": swing_mode},
        )

    async def async_turn_on(self) -> None:
        """Turn on by setting the first non-OFF HVAC mode."""
        self._check_read_only()
        for mode in (
            HVACMode.AUTO,
            HVACMode.HEAT_COOL,
            HVACMode.HEAT,
            HVACMode.COOL,
        ):
            if mode in self._reverse_hvac:
                await self.async_set_hvac_mode(mode)
                return
        if self._plc_modes:
            await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        """Turn off by setting HVAC mode to OFF."""
        await self.async_set_hvac_mode(HVACMode.OFF)
