"""Climate platform for TwinCAT IoT Communicator (AC widgets)."""

from __future__ import annotations

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
from .models import WidgetData, metadata_bool

PARALLEL_UPDATES = 0


def _as_float(value: Any) -> float | None:
    """Best-effort float conversion for PLC state values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str:
    """Return a safe text value for PLC mode fields."""
    return value if isinstance(value, str) else str(value or "")


def _as_text_list(value: Any) -> list[str]:
    """Normalize PLC mode arrays while tolerating scalar values."""
    if isinstance(value, list):
        return [_as_text(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


# All keys must be lowercase — lookup is always done via .lower()
HVAC_MODE_MAP: dict[str, HVACMode] = {
    "auto": HVACMode.AUTO,
    "automatisch": HVACMode.AUTO,
    "automatic": HVACMode.AUTO,
    "heizen": HVACMode.HEAT,
    "heizung": HVACMode.HEAT,
    "heat": HVACMode.HEAT,
    "heating": HVACMode.HEAT,
    "kühlen": HVACMode.COOL,
    "kuehlen": HVACMode.COOL,
    "kühlung": HVACMode.COOL,
    "kuehlung": HVACMode.COOL,
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
    "lüftung": HVACMode.FAN_ONLY,
    "lueftung": HVACMode.FAN_ONLY,
    "ventilation": HVACMode.FAN_ONLY,
    "ventilating": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "trocknen": HVACMode.DRY,
    "trocknung": HVACMode.DRY,
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

# nAcMode (0–6) → HVACMode fallback when META_AC_MODE_VISIBLE is false.
# Values 4–6 are "inactive" (valve closed) but still represent the operating mode.
AC_MODE_HVAC_MAP: dict[int, HVACMode] = {
    0: HVACMode.OFF,
    1: HVACMode.COOL,
    2: HVACMode.FAN_ONLY,
    3: HVACMode.HEAT,
    4: HVACMode.COOL,
    5: HVACMode.FAN_ONLY,
    6: HVACMode.HEAT,
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
        # visible + changeable flags from PLC metadata (runtime-updated)
        self._mode_visible: bool = False
        self._mode_changeable: bool = False
        self._strength_visible: bool = False
        self._strength_changeable: bool = False
        self._lamella_visible: bool = False
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

        can_set_temp = metadata_bool(raw.get(META_AC_VALUE_REQUEST_VISIBLE))
        if can_set_temp:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        # ── Mode 1: HVAC (sMode / aModes) ────────────────────────────
        supports_mode = metadata_bool(raw.get(META_AC_MODE_VISIBLE))
        can_change_mode = metadata_bool(raw.get(META_AC_MODE_CHANGEABLE))
        self._mode_visible = supports_mode
        self._mode_changeable = supports_mode and can_change_mode

        if supports_mode:
            self._plc_modes = _as_text_list(self.widget.values.get(VAL_MODES, []))
            self._hvac_map = {}
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

            # When aModes is empty but sMode has a value, include it
            current_smode = _as_text(self.widget.values.get(VAL_MODE, ""))
            if current_smode and current_smode.lower() not in self._hvac_map:
                ha_mode = HVAC_MODE_MAP.get(current_smode.lower())
                if ha_mode:
                    self._hvac_map[current_smode.lower()] = ha_mode
                    if ha_mode not in self._reverse_hvac:
                        self._reverse_hvac[ha_mode] = current_smode

            mapped_hvac = set(self._hvac_map.values())
            if HVACMode.OFF not in mapped_hvac:
                mapped_hvac.add(HVACMode.OFF)
            self._attr_hvac_modes = sorted(mapped_hvac, key=lambda m: m.value)

            if self._preset_modes:
                features |= ClimateEntityFeature.PRESET_MODE

            if can_change_mode:
                features |= (
                    ClimateEntityFeature.TURN_ON
                    | ClimateEntityFeature.TURN_OFF
                )
        else:
            self._plc_modes = []
            self._hvac_map = {}
            self._reverse_hvac = {}
            self._preset_modes = []
            self._preset_lower_map = {}
            self._attr_hvac_modes = []

        # ── Mode 2: Strength / fan mode (sMode_Strength / aModes_Strength) ──
        supports_strength = metadata_bool(raw.get(META_AC_MODE_STRENGTH_VISIBLE))
        can_change_strength = metadata_bool(
            raw.get(META_AC_MODE_STRENGTH_CHANGEABLE)
        )
        self._strength_visible = supports_strength
        self._strength_changeable = supports_strength and can_change_strength
        raw_strength = _as_text_list(self.widget.values.get(VAL_MODES_STRENGTH, []))
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
        elif supports_strength:
            current_strength = _as_text(self.widget.values.get(VAL_MODE_STRENGTH, ""))
            if current_strength:
                ha_str = STRENGTH_MODE_MAP.get(
                    current_strength.lower(), current_strength,
                )
                self._fan_mode_map[current_strength.lower()] = ha_str
                self._reverse_fan_mode[ha_str] = current_strength
                self._attr_fan_modes = [ha_str]
                if can_change_strength:
                    features |= ClimateEntityFeature.FAN_MODE
            else:
                self._attr_fan_modes = []
        else:
            self._attr_fan_modes = []

        # ── Mode 3: Lamella / swing mode (sMode_Lamella / aModes_Lamella) ──
        supports_lamella = metadata_bool(raw.get(META_AC_MODE_LAMELLA_VISIBLE))
        can_change_lamella = metadata_bool(raw.get(META_AC_MODE_LAMELLA_CHANGEABLE))
        self._lamella_visible = supports_lamella
        self._lamella_changeable = supports_lamella and can_change_lamella
        raw_lamella = _as_text_list(self.widget.values.get(VAL_MODES_LAMELLA, []))
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
        elif supports_lamella:
            current_lamella = _as_text(self.widget.values.get(VAL_MODE_LAMELLA, ""))
            if current_lamella:
                ha_str = LAMELLA_MODE_MAP.get(
                    current_lamella.lower(), current_lamella,
                )
                self._swing_mode_map[current_lamella.lower()] = ha_str
                self._reverse_swing_mode[ha_str] = current_lamella
                self._attr_swing_modes = [ha_str]
                if can_change_lamella:
                    features |= ClimateEntityFeature.SWING_MODE
            else:
                self._attr_swing_modes = []
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
        return _as_float(value)

    @property
    def target_temperature(self) -> float | None:
        """Return the target (requested) temperature."""
        value = self.widget.values.get(VAL_AC_TEMPERATURE_REQUEST)
        if value is None:
            return None
        return _as_float(value)

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode.

        When mode is visible, map from the PLC sMode string.
        When hidden, derive from nAcMode (physical valve state).
        """
        if not self._mode_visible:
            raw = self.widget.values.get(VAL_AC_MODE)
            if raw is None:
                return HVACMode.OFF
            try:
                return AC_MODE_HVAC_MAP.get(int(raw), HVACMode.OFF)
            except (TypeError, ValueError):
                return HVACMode.OFF
        current = _as_text(self.widget.values.get(VAL_MODE, ""))
        ha_mode = self._hvac_map.get(current.lower())
        if ha_mode is not None:
            return ha_mode
        if current and current.lower() in self._preset_lower_map:
            return None
        return HVACMode.OFF

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return available HVAC modes.

        When mode is hidden, expose only the current nAcMode-derived state
        so the frontend shows a single non-selectable mode chip.
        """
        if not self._mode_visible:
            return [self.hvac_mode or HVACMode.OFF]
        return self._attr_hvac_modes

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset, or None if the current mode is an HVAC mode."""
        if not self._preset_modes:
            return None
        current = _as_text(self.widget.values.get(VAL_MODE, ""))
        return self._preset_lower_map.get(current.lower())

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the list of available preset modes."""
        return self._preset_modes if self._preset_modes else None

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan speed mapped from sMode_Strength."""
        current = _as_text(self.widget.values.get(VAL_MODE_STRENGTH, ""))
        if not current:
            return None
        return self._fan_mode_map.get(current.lower(), current)

    @property
    def swing_mode(self) -> str | None:
        """Return the current swing mode mapped from sMode_Lamella."""
        current = _as_text(self.widget.values.get(VAL_MODE_LAMELLA, ""))
        if not current:
            return None
        return self._swing_mode_map.get(current.lower(), current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose read_only and per-mode changeable flags."""
        attrs = super().extra_state_attributes
        attrs["mode_visible"] = self._mode_visible
        attrs["mode_changeable"] = self._mode_changeable
        attrs["strength_visible"] = self._strength_visible
        attrs["strength_changeable"] = self._strength_changeable
        attrs["lamella_visible"] = self._lamella_visible
        attrs["lamella_changeable"] = self._lamella_changeable
        ac_mode = self.widget.values.get(VAL_AC_MODE)
        if ac_mode is not None:
            try:
                attrs["ac_mode_icon"] = int(ac_mode)
            except (TypeError, ValueError):
                pass
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
        await self._send_optimistic(
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
                translation_key="invalid_hvac_mode",
                translation_placeholders={
                    "mode": str(hvac_mode),
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(
                        str(m) for m in self._reverse_hvac
                    ),
                },
            )
        await self._send_optimistic(
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
        await self._send_optimistic(
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
        await self._send_optimistic(
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
        await self._send_optimistic(
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
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_available_hvac_mode",
            translation_placeholders={
                "name": self.widget.effective_display_name(),
            },
        )

    async def async_turn_off(self) -> None:
        """Turn off by setting HVAC mode to OFF."""
        self._check_read_only()
        self._check_mode_changeable()
        await self.async_set_hvac_mode(HVACMode.OFF)
