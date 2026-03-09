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

# All keys must be lowercase — lookup is always done via .lower()
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
    "heizen+kühlen": HVACMode.HEAT_COOL,
    "heizen+kuehlen": HVACMode.HEAT_COOL,
    "fan_only": HVACMode.FAN_ONLY,
    "lüften": HVACMode.FAN_ONLY,
    "lueften": HVACMode.FAN_ONLY,
    "ventilating": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "trocknen": HVACMode.DRY,
    "drying": HVACMode.DRY,
}

# Strength/fan-mode mapping (DE + EN → normalized HA fan-mode string).
# HA fan_mode is a free string — we normalize to lowercase English.
STRENGTH_MODE_MAP: dict[str, str] = {
    "aus": "off",
    "off": "off",
    "niedrig": "low",
    "low": "low",
    "gering": "low",
    "mittel": "medium",
    "medium": "medium",
    "hoch": "high",
    "high": "high",
    "stark": "high",
    "auto": "auto",
    "automatisch": "auto",
    "automatic": "auto",
    "heizen": "heat",
    "heat": "heat",
    "heating": "heat",
    "kühlen": "cool",
    "kuehlen": "cool",
    "cool": "cool",
    "cooling": "cool",
}

# Lamella/swing-mode mapping (DE + EN → normalized HA swing-mode string).
LAMELLA_MODE_MAP: dict[str, str] = {
    "aus": "off",
    "off": "off",
    "auto": "auto",
    "automatisch": "auto",
    "automatic": "auto",
    "horizontal": "horizontal",
    "vertikal": "vertical",
    "vertical": "vertical",
    "links": "left",
    "left": "left",
    "rechts": "right",
    "right": "right",
    "mitte": "center",
    "center": "center",
    "oben": "top",
    "top": "top",
    "unten": "bottom",
    "bottom": "bottom",
    "schaukel": "swing",
    "swing": "swing",
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
        # lowercase plc string → HVACMode
        self._hvac_map: dict[str, HVACMode] = {}
        self._preset_modes: list[str] = []
        # lowercase plc string → original plc string (for preset lookup)
        self._preset_lower_map: dict[str, str] = {}
        # HVACMode → original plc string (for writing back to PLC)
        self._reverse_hvac: dict[HVACMode, str] = {}
        # lowercase plc string → normalized HA fan-mode string
        self._fan_mode_map: dict[str, str] = {}
        # normalized HA fan-mode string → original plc string
        self._reverse_fan_mode: dict[str, str] = {}
        # lowercase plc string → normalized HA swing-mode string
        self._swing_mode_map: dict[str, str] = {}
        # normalized HA swing-mode string → original plc string
        self._reverse_swing_mode: dict[str, str] = {}
        # changeable flags from PLC metadata (runtime-updated via _sync_modes)
        self._mode_changeable: bool = False
        self._strength_changeable: bool = False
        self._lamella_changeable: bool = False
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

        # ── Mode 1: HVAC (sMode / aModes) ────────────────────────────
        plc_modes = self.widget.values.get(VAL_MODES, [])
        self._plc_modes = [m for m in plc_modes if m]
        # lowercase plc string → HVACMode (case-insensitive lookup)
        self._hvac_map = {}
        # HVACMode → first matching original plc string (for write-back)
        self._reverse_hvac = {}
        self._preset_modes = []
        self._preset_lower_map = {}

        for plc_str in self._plc_modes:
            ha_mode = HVAC_MODE_MAP.get(plc_str.lower())
            if ha_mode:
                self._hvac_map[plc_str.lower()] = ha_mode
                if ha_mode not in self._reverse_hvac:
                    self._reverse_hvac[ha_mode] = plc_str
            else:
                self._preset_modes.append(plc_str)
                self._preset_lower_map[plc_str.lower()] = plc_str

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
        self._mode_changeable = can_change_mode
        if supports_mode and can_change_mode:
            features |= (
                ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
            )

        # ── Mode 2: Strength / fan mode (sMode_Strength / aModes_Strength) ──
        supports_strength = (
            raw.get(META_AC_MODE_STRENGTH_VISIBLE, "false").lower() == "true"
        )
        can_change_strength = (
            raw.get(META_AC_MODE_STRENGTH_CHANGEABLE, "false").lower()
            == "true"
        )
        self._strength_changeable = can_change_strength
        raw_strength = [
            m for m in self.widget.values.get(VAL_MODES_STRENGTH, []) if m
        ]
        self._fan_mode_map = {}
        self._reverse_fan_mode = {}
        if supports_strength and raw_strength:
            ha_fan_modes: list[str] = []
            for plc_str in raw_strength:
                ha_str = STRENGTH_MODE_MAP.get(plc_str.lower(), plc_str)
                self._fan_mode_map[plc_str.lower()] = ha_str
                if ha_str not in self._reverse_fan_mode:
                    self._reverse_fan_mode[ha_str] = plc_str
                if ha_str not in ha_fan_modes:
                    ha_fan_modes.append(ha_str)
            self._attr_fan_modes = ha_fan_modes
            if can_change_strength:
                features |= ClimateEntityFeature.FAN_MODE
        else:
            self._attr_fan_modes = []

        # ── Mode 3: Lamella / swing mode (sMode_Lamella / aModes_Lamella) ──
        supports_lamella = (
            raw.get(META_AC_MODE_LAMELLA_VISIBLE, "false").lower() == "true"
        )
        can_change_lamella = (
            raw.get(META_AC_MODE_LAMELLA_CHANGEABLE, "false").lower() == "true"
        )
        self._lamella_changeable = can_change_lamella
        raw_lamella = [
            m for m in self.widget.values.get(VAL_MODES_LAMELLA, []) if m
        ]
        self._swing_mode_map = {}
        self._reverse_swing_mode = {}
        if supports_lamella and raw_lamella:
            ha_swing_modes: list[str] = []
            for plc_str in raw_lamella:
                ha_str = LAMELLA_MODE_MAP.get(plc_str.lower(), plc_str)
                self._swing_mode_map[plc_str.lower()] = ha_str
                if ha_str not in self._reverse_swing_mode:
                    self._reverse_swing_mode[ha_str] = plc_str
                if ha_str not in ha_swing_modes:
                    ha_swing_modes.append(ha_str)
            self._attr_swing_modes = ha_swing_modes
            if can_change_lamella:
                features |= ClimateEntityFeature.SWING_MODE
        else:
            self._attr_swing_modes = []

        self._attr_supported_features = features

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
        """Return the current HVAC mode mapped from the PLC sMode string."""
        current = self.widget.values.get(VAL_MODE, "")
        # Case-insensitive lookup via lowercase key
        return self._hvac_map.get(current.lower(), HVACMode.OFF)

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset, or None if the current mode is an HVAC mode."""
        if not self._preset_modes:
            return None
        current = self.widget.values.get(VAL_MODE, "")
        return self._preset_lower_map.get(current.lower())

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the list of available preset modes."""
        return self._preset_modes if self._preset_modes else None

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan speed mapped from sMode_Strength."""
        current = self.widget.values.get(VAL_MODE_STRENGTH, "")
        if not current:
            return None
        return self._fan_mode_map.get(current.lower(), current)

    @property
    def swing_mode(self) -> str | None:
        """Return the current swing mode mapped from sMode_Lamella."""
        current = self.widget.values.get(VAL_MODE_LAMELLA, "")
        if not current:
            return None
        return self._swing_mode_map.get(current.lower(), current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose read_only and per-mode changeable flags."""
        attrs = super().extra_state_attributes
        attrs["mode_changeable"] = self._mode_changeable
        attrs["strength_changeable"] = self._strength_changeable
        attrs["lamella_changeable"] = self._lamella_changeable
        ac_mode = self.widget.values.get(VAL_AC_MODE)
        if ac_mode is not None:
            attrs["ac_mode_icon"] = int(ac_mode)
        return attrs

    # ── Guards ───────────────────────────────────────────────────────

    def _check_mode_changeable(self) -> None:
        """Raise if the PLC has marked the main mode as not changeable."""
        if not self._mode_changeable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )

    def _check_strength_changeable(self) -> None:
        """Raise if the PLC has marked the strength mode as not changeable."""
        if not self._strength_changeable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )

    def _check_lamella_changeable(self) -> None:
        """Raise if the PLC has marked the lamella mode as not changeable."""
        if not self._lamella_changeable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )

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
        """Set the HVAC mode by mapping back to the original PLC sMode string."""
        self._check_read_only()
        self._check_mode_changeable()
        plc_mode_string = self._reverse_hvac.get(hvac_mode)
        if plc_mode_string is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_preset_mode",
                translation_placeholders={
                    "mode": str(hvac_mode),
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(
                        str(m) for m in self._reverse_hvac
                    ),
                },
            )
        # Only write sMode — nAcMode is a read-only display icon (0–6)
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE}": plc_mode_string},
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a preset mode (non-HVAC PLC mode string)."""
        self._check_read_only()
        self._check_mode_changeable()
        if preset_mode not in self._preset_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_preset_mode",
                translation_placeholders={
                    "mode": preset_mode,
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(self._preset_modes),
                },
            )
        # Only write sMode — nAcMode is a read-only display icon (0–6)
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE}": preset_mode},
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed mode, translating back to the original PLC string."""
        self._check_read_only()
        self._check_strength_changeable()
        if self._attr_fan_modes and fan_mode not in self._attr_fan_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_fan_mode",
                translation_placeholders={
                    "mode": fan_mode,
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(self._attr_fan_modes),
                },
            )
        plc_str = self._reverse_fan_mode.get(fan_mode, fan_mode)
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE_STRENGTH}": plc_str},
        )

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the lamella/swing mode, translating back to the original PLC string."""
        self._check_read_only()
        self._check_lamella_changeable()
        if self._attr_swing_modes and swing_mode not in self._attr_swing_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_swing_mode",
                translation_placeholders={
                    "mode": swing_mode,
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(self._attr_swing_modes),
                },
            )
        plc_str = self._reverse_swing_mode.get(swing_mode, swing_mode)
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_MODE_LAMELLA}": plc_str},
        )

    async def async_turn_on(self) -> None:
        """Turn on by setting the first non-OFF HVAC mode."""
        self._check_read_only()
        self._check_mode_changeable()
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
        self._check_read_only()
        self._check_mode_changeable()
        await self.async_set_hvac_mode(HVACMode.OFF)
