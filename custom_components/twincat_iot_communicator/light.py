"""Light platform for TwinCAT IoT Communicator.

Supports three widget types:
- Lighting: on/off, brightness, effects/modes.
- RGBW: on/off, brightness, HS or RGBW color, color temperature, effects.
- RGBWEL2564: on/off, 4-channel RGBW for Beckhoff EL2564 LED terminals.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import color_hs_to_RGB, color_RGB_to_hs

from . import TcIotConfigEntry
from .const import (
    DOMAIN,
    META_GENERAL_MODE1_CHANGEABLE,
    META_GENERAL_MODE1_VISIBLE,
    META_GENERAL_VALUE1_SWITCH_VISIBLE,
    META_LED_MODE_CHANGEABLE,
    META_LED_MODE_VISIBLE,
    META_LIGHT_COLOR_PALETTE_MODE,
    META_LIGHT_COLOR_PALETTE_VISIBLE,
    META_LIGHT_COLOR_TEMP_SLIDER_VISIBLE,
    META_LIGHT_MODE_CHANGEABLE,
    META_LIGHT_MODE_VISIBLE,
    META_LIGHT_SLIDER_VISIBLE,
    META_LIGHT_WHITE_SLIDER_VISIBLE,
    PLC_CM_COLOR_TEMP,
    PLC_CM_HS,
    PLC_CM_RGB,
    VAL_GENERAL_MODE1,
    VAL_GENERAL_MODES1,
    VAL_GENERAL_VALUE1,
    VAL_LED_BLUE,
    VAL_LED_GREEN,
    VAL_LED_ON,
    VAL_LED_RED,
    VAL_LED_WHITE,
    VAL_LIGHT_BLUE,
    VAL_LIGHT_COLOR_MODE,
    VAL_LIGHT_COLOR_TEMP,
    VAL_LIGHT_GREEN,
    VAL_LIGHT_HUE,
    VAL_LIGHT_LEVEL,
    VAL_LIGHT_ON,
    VAL_LIGHT_RED,
    VAL_LIGHT_SATURATION,
    VAL_LIGHT_WHITE,
    VAL_MODE,
    VAL_MODES,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_LIGHTING,
    WIDGET_TYPE_RGBW,
    WIDGET_TYPE_RGBW_EL2564,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import WidgetData

_LOGGER = logging.getLogger(__name__)

LIGHT_WIDGET_TYPES = frozenset(
    {WIDGET_TYPE_LIGHTING, WIDGET_TYPE_RGBW, WIDGET_TYPE_RGBW_EL2564}
)

EL2564_PLC_MAX = 32767

PARALLEL_UPDATES = 0

_COLOR_ATTRS = frozenset(
    {ATTR_HS_COLOR, ATTR_RGBW_COLOR, ATTR_COLOR_TEMP_KELVIN, ATTR_EFFECT}
)
_VALUE_ATTRS = _COLOR_ATTRS | {ATTR_BRIGHTNESS}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT light entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[LightEntity] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            entities.extend(_create_lights(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new: list[LightEntity] = []
        for widget in widgets:
            new.extend(_create_lights(coordinator, device_name, widget))
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.LIGHT, _on_new_widgets)


def _create_lights(
    coordinator: TcIotCoordinator,
    device_name: str,
    widget: WidgetData,
) -> list[LightEntity]:
    """Create light entities for a widget based on its type."""
    wt = widget.metadata.widget_type
    if wt in LIGHT_WIDGET_TYPES:
        return [TcIotLight(coordinator, device_name, widget)]
    if wt == WIDGET_TYPE_GENERAL:
        raw = widget.metadata.raw
        if raw.get(META_GENERAL_VALUE1_SWITCH_VISIBLE, "").lower() == "true":
            return [TcIotGeneralLight(coordinator, device_name, widget)]
    return []


class TcIotLight(TcIotEntity, LightEntity):
    """A TcIoT light entity (Lighting / RGBW / RGBWEL2564)."""

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a discovered widget."""
        super().__init__(coordinator, device_name, widget)

        self._is_el2564: bool = (
            widget.metadata.widget_type == WIDGET_TYPE_RGBW_EL2564
        )

        # nColorMode: PLC-reported bitmask of the active color channel.
        self._plc_reports_color_mode: bool = (
            VAL_LIGHT_COLOR_MODE in widget.values
        )

        # Legacy fallback: client-side color mode tracking for widgets
        # without nColorMode.
        self._active_color_mode: ColorMode | None = None

        self._native_rgb: bool = False
        self._mode_changeable: bool = False
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read all metadata-dependent attributes from the live widget."""
        raw = self.widget.metadata.raw

        palette = raw.get(META_LIGHT_COLOR_PALETTE_MODE, "").upper()
        self._native_rgb = palette == "RGB"

        if self._is_el2564:
            self._attr_supported_color_modes = {ColorMode.RGBW}
            mode_vis_key = META_LED_MODE_VISIBLE
            mode_chg_key = META_LED_MODE_CHANGEABLE
        else:
            self._sync_standard_color_modes(raw)
            mode_vis_key = META_LIGHT_MODE_VISIBLE
            mode_chg_key = META_LIGHT_MODE_CHANGEABLE

        mode_visible = raw.get(mode_vis_key, "").lower() == "true"
        self._mode_changeable = mode_visible and (
            raw.get(mode_chg_key, "").lower() == "true"
        )
        effect_list = self.widget.values.get(VAL_MODES, [])
        if effect_list and mode_visible:
            self._attr_effect_list = [e for e in effect_list if e]
            self._attr_supported_features = (
                LightEntityFeature.EFFECT
                if self._mode_changeable
                else LightEntityFeature(0)
            )
        elif mode_visible:
            current_effect = self.widget.values.get(VAL_MODE, "")
            if current_effect:
                self._attr_effect_list = [current_effect]
                self._attr_supported_features = (
                    LightEntityFeature.EFFECT
                    if self._mode_changeable
                    else LightEntityFeature(0)
                )
            else:
                self._attr_supported_features = LightEntityFeature(0)
                self._attr_effect_list = []
        else:
            self._attr_supported_features = LightEntityFeature(0)
            self._attr_effect_list = []

    def _sync_standard_color_modes(self, raw: dict[str, str]) -> None:
        """Derive supported color modes from widget metadata (non-EL2564)."""
        supports_brightness = (
            raw.get(META_LIGHT_SLIDER_VISIBLE, "true").lower() != "false"
        )
        supports_color = (
            raw.get(META_LIGHT_COLOR_PALETTE_VISIBLE, "false").lower() == "true"
        )
        supports_color_temp = (
            raw.get(META_LIGHT_COLOR_TEMP_SLIDER_VISIBLE, "false").lower()
            == "true"
        )
        supports_white = (
            raw.get(META_LIGHT_WHITE_SLIDER_VISIBLE, "false").lower() == "true"
        )

        modes: set[ColorMode] = set()
        if supports_color and supports_white:
            modes.add(ColorMode.RGBW)
        elif supports_color:
            modes.add(ColorMode.HS)
        if supports_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if supports_brightness and not modes:
            modes.add(ColorMode.BRIGHTNESS)
        if not modes:
            modes.add(ColorMode.ONOFF)

        self._attr_supported_color_modes = modes

        if supports_color_temp:
            self._attr_min_color_temp_kelvin = int(
                self.widget.field_min(VAL_LIGHT_COLOR_TEMP, 2000)
            )
            self._attr_max_color_temp_kelvin = int(
                self.widget.field_max(VAL_LIGHT_COLOR_TEMP, 6500)
            )

    # ── Scaling helpers ──────────────────────────────────────────────

    @staticmethod
    def _el2564_to_ha(val: int | float) -> int:
        """Scale EL2564 channel (0–32767) → HA (0–255)."""
        return min(255, max(0, round(float(val) / EL2564_PLC_MAX * 255)))

    @staticmethod
    def _ha_to_el2564(val: int | float) -> int:
        """Scale HA (0–255) → EL2564 channel (0–32767)."""
        return min(
            EL2564_PLC_MAX,
            max(0, round(float(val) / 255 * EL2564_PLC_MAX)),
        )

    @staticmethod
    def _white_plc_to_ha(plc_pct: int | float) -> int:
        """Scale PLC white percentage (0–100) → HA (0–255)."""
        return min(255, max(0, round(float(plc_pct) / 100 * 255)))

    @staticmethod
    def _white_ha_to_plc(ha_val: int | float) -> int:
        """Scale HA white (0–255) → PLC percentage (0–100)."""
        return round(int(ha_val) / 255 * 100)

    # ── State properties ─────────────────────────────────────────────

    @property
    def is_on(self) -> bool | None:
        """Return whether the light is on."""
        key = VAL_LED_ON if self._is_el2564 else VAL_LIGHT_ON
        val = self.widget.values.get(key)
        if val is None:
            return None
        return bool(val)

    @property
    def brightness(self) -> int | None:
        """Return brightness (nLight) scaled to 0–255.

        EL2564 does not have a separate brightness channel.
        """
        if self._is_el2564:
            return None
        val = self.widget.values.get(VAL_LIGHT_LEVEL)
        if val is None:
            return None
        brightness_min = self.widget.field_min(VAL_LIGHT_LEVEL, 0)
        brightness_max = self.widget.field_max(VAL_LIGHT_LEVEL, 100)
        brightness_range = brightness_max - brightness_min
        if brightness_range <= 0:
            return 0
        return min(
            255,
            max(0, round((val - brightness_min) / brightness_range * 255)),
        )

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode.

        Resolution order:
        1. EL2564 → always RGBW.
        2. Single supported mode → return it.
        3. PLC nColorMode bitmask (if available).
        4. Client-side _active_color_mode (legacy fallback).
        5. Static default priority: RGBW > HS > COLOR_TEMP > BRIGHTNESS > ONOFF.
        """
        if self._is_el2564:
            return ColorMode.RGBW

        modes = self._attr_supported_color_modes
        if len(modes) == 1:
            return next(iter(modes))

        resolved = self._resolve_plc_color_mode(modes)
        if resolved is not None:
            return resolved

        if self._active_color_mode and self._active_color_mode in modes:
            return self._active_color_mode

        for fallback in (
            ColorMode.RGBW,
            ColorMode.HS,
            ColorMode.COLOR_TEMP,
            ColorMode.BRIGHTNESS,
        ):
            if fallback in modes:
                return fallback
        return ColorMode.ONOFF

    def _resolve_plc_color_mode(
        self, modes: set[ColorMode],
    ) -> ColorMode | None:
        """Map PLC nColorMode bitmask to a HA ColorMode, or None."""
        if not self._plc_reports_color_mode:
            return None
        plc_color_mode = self.widget.values.get(VAL_LIGHT_COLOR_MODE)
        if plc_color_mode is None:
            return None

        bitmask = int(plc_color_mode)
        if bitmask & PLC_CM_RGB and ColorMode.RGBW in modes:
            return ColorMode.RGBW
        if bitmask & PLC_CM_HS:
            if ColorMode.RGBW in modes:
                return ColorMode.RGBW
            if ColorMode.HS in modes:
                return ColorMode.HS
        if bitmask & PLC_CM_COLOR_TEMP and ColorMode.COLOR_TEMP in modes:
            return ColorMode.COLOR_TEMP
        return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue/saturation tuple.

        The PLC always reports both HS and RGB — we read HS directly.
        """
        if self._is_el2564 or self.color_mode != ColorMode.HS:
            return None
        hue = self.widget.values.get(VAL_LIGHT_HUE)
        sat = self.widget.values.get(VAL_LIGHT_SATURATION)
        if hue is None or sat is None:
            return None
        return (float(hue), float(sat))

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the RGBW color tuple (0–255 each)."""
        if self.color_mode != ColorMode.RGBW:
            return None

        if self._is_el2564:
            return self._read_el2564_rgbw()
        return self._read_standard_rgbw()

    def _read_el2564_rgbw(self) -> tuple[int, int, int, int] | None:
        """Read RGBW from EL2564 hardware channels (0–32767 → 0–255)."""
        r = self.widget.values.get(VAL_LED_RED)
        g = self.widget.values.get(VAL_LED_GREEN)
        b = self.widget.values.get(VAL_LED_BLUE)
        w = self.widget.values.get(VAL_LED_WHITE)
        if r is None or g is None or b is None or w is None:
            return None
        return (
            self._el2564_to_ha(r),
            self._el2564_to_ha(g),
            self._el2564_to_ha(b),
            self._el2564_to_ha(w),
        )

    def _read_standard_rgbw(self) -> tuple[int, int, int, int] | None:
        """Read RGBW from standard widget values.

        With native RGB: reads nRed/nGreen/nBlue directly.
        Legacy (HS only): reconstructs RGB from nHueValue/nSaturation.
        White is always read from nWhite (PLC 0–100 → HA 0–255).
        """
        white_pct = self.widget.values.get(VAL_LIGHT_WHITE)
        if white_pct is None:
            return None
        white_ha = self._white_plc_to_ha(white_pct)

        if self._native_rgb:
            r = self.widget.values.get(VAL_LIGHT_RED)
            g = self.widget.values.get(VAL_LIGHT_GREEN)
            b = self.widget.values.get(VAL_LIGHT_BLUE)
            if r is None or g is None or b is None:
                return None
            return (int(r), int(g), int(b), white_ha)

        hue = self.widget.values.get(VAL_LIGHT_HUE)
        sat = self.widget.values.get(VAL_LIGHT_SATURATION)
        if hue is None or sat is None:
            return None
        r, g, b = color_hs_to_RGB(float(hue), float(sat))
        return (r, g, b, white_ha)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        if self.color_mode != ColorMode.COLOR_TEMP:
            return None
        val = self.widget.values.get(VAL_LIGHT_COLOR_TEMP)
        if val is None:
            return None
        return int(val)

    @property
    def effect(self) -> str | None:
        """Return the current effect (PLC mode string)."""
        return self.widget.values.get(VAL_MODE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose read_only, mode_changeable and PLC color palette mode."""
        attrs = super().extra_state_attributes
        attrs["mode_changeable"] = self._mode_changeable
        attrs["color_palette_mode"] = (
            self.widget.metadata.raw.get(META_LIGHT_COLOR_PALETTE_MODE) or "HS"
        )
        return attrs

    # ── Commands ─────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light and/or apply color/brightness attributes."""
        self._check_read_only()
        path = self.widget.path
        commands: dict[str, Any] = {}
        previous_mode = self._active_color_mode

        if self._is_el2564:
            self._build_el2564_commands(path, kwargs, commands)
        else:
            self._build_standard_commands(path, kwargs, commands)

        self._build_effect_command(path, kwargs, commands)

        await self.coordinator.async_send_command(self.device_name, commands)

        if (
            not self._plc_reports_color_mode
            and self._active_color_mode != previous_mode
            and self.hass is not None
        ):
            self.async_write_ha_state()

    def _build_el2564_commands(
        self,
        path: str,
        kwargs: dict[str, Any],
        commands: dict[str, Any],
    ) -> None:
        """Build commands for EL2564 4-channel LED hardware."""
        has_values = bool(kwargs.keys() & _VALUE_ATTRS)
        if not has_values:
            commands[f"{path}.{VAL_LED_ON}"] = True

        if ATTR_RGBW_COLOR in kwargs:
            r, g, b, w = kwargs[ATTR_RGBW_COLOR]
            commands[f"{path}.{VAL_LED_RED}"] = self._ha_to_el2564(r)
            commands[f"{path}.{VAL_LED_GREEN}"] = self._ha_to_el2564(g)
            commands[f"{path}.{VAL_LED_BLUE}"] = self._ha_to_el2564(b)
            commands[f"{path}.{VAL_LED_WHITE}"] = self._ha_to_el2564(w)

    def _build_standard_commands(
        self,
        path: str,
        kwargs: dict[str, Any],
        commands: dict[str, Any],
    ) -> None:
        """Build commands for standard Lighting/RGBW widgets."""
        has_values = bool(kwargs.keys() & _VALUE_ATTRS)
        has_color = bool(kwargs.keys() & _COLOR_ATTRS)
        effect_only = ATTR_EFFECT in kwargs and not bool(
            kwargs.keys()
            & {ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_RGBW_COLOR, ATTR_COLOR_TEMP_KELVIN}
        )

        if not self.is_on and not effect_only and (not has_values or has_color):
            commands[f"{path}.{VAL_LIGHT_ON}"] = True

        if ATTR_BRIGHTNESS in kwargs:
            self._add_brightness_command(path, kwargs[ATTR_BRIGHTNESS], commands)

        if ATTR_RGBW_COLOR in kwargs:
            self._add_rgbw_command(path, kwargs[ATTR_RGBW_COLOR], commands)

        if ATTR_HS_COLOR in kwargs:
            self._add_hs_command(path, kwargs[ATTR_HS_COLOR], commands)

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            commands[f"{path}.{VAL_LIGHT_COLOR_TEMP}"] = (
                kwargs[ATTR_COLOR_TEMP_KELVIN]
            )
            if not self._plc_reports_color_mode:
                self._active_color_mode = ColorMode.COLOR_TEMP

    def _add_brightness_command(
        self,
        path: str,
        ha_brightness: int,
        commands: dict[str, Any],
    ) -> None:
        """Map HA brightness (0–255) to PLC nLight range."""
        brightness_min = self.widget.field_min(VAL_LIGHT_LEVEL, 0)
        brightness_max = self.widget.field_max(VAL_LIGHT_LEVEL, 100)
        plc_brightness = round(
            brightness_min
            + (ha_brightness / 255) * (brightness_max - brightness_min)
        )
        commands[f"{path}.{VAL_LIGHT_LEVEL}"] = int(plc_brightness)

    def _add_rgbw_command(
        self,
        path: str,
        rgbw: tuple[int, int, int, int],
        commands: dict[str, Any],
    ) -> None:
        """Handle ATTR_RGBW_COLOR: send color + white to PLC."""
        r, g, b, w = rgbw

        # RGB=(0,0,0) means the "Farbhelligkeit" slider is at minimum.
        # Skip color update to avoid resetting the PLC's current color.
        if r == 0 and g == 0 and b == 0:
            _LOGGER.debug("RGBW color=(0,0,0) — skipping color fields")
        elif self._native_rgb:
            commands[f"{path}.{VAL_LIGHT_RED}"] = r
            commands[f"{path}.{VAL_LIGHT_GREEN}"] = g
            commands[f"{path}.{VAL_LIGHT_BLUE}"] = b
        else:
            hue, sat = color_RGB_to_hs(r, g, b)
            commands[f"{path}.{VAL_LIGHT_HUE}"] = round(hue)
            commands[f"{path}.{VAL_LIGHT_SATURATION}"] = round(sat)

        target_white = self._white_ha_to_plc(w)
        current_white = self.widget.values.get(VAL_LIGHT_WHITE)
        if current_white is None or int(current_white) != target_white:
            commands[f"{path}.{VAL_LIGHT_WHITE}"] = target_white

        if not self._plc_reports_color_mode:
            self._active_color_mode = ColorMode.RGBW

    def _add_hs_command(
        self,
        path: str,
        hs: tuple[float, float],
        commands: dict[str, Any],
    ) -> None:
        """Handle ATTR_HS_COLOR: send as RGB or HS depending on palette mode."""
        hue, sat = hs
        if self._native_rgb:
            r, g, b = color_hs_to_RGB(hue, sat)
            commands[f"{path}.{VAL_LIGHT_RED}"] = r
            commands[f"{path}.{VAL_LIGHT_GREEN}"] = g
            commands[f"{path}.{VAL_LIGHT_BLUE}"] = b
        else:
            commands[f"{path}.{VAL_LIGHT_HUE}"] = round(hue)
            commands[f"{path}.{VAL_LIGHT_SATURATION}"] = round(sat)

        if not self._plc_reports_color_mode:
            self._active_color_mode = ColorMode.HS

    def _build_effect_command(
        self,
        path: str,
        kwargs: dict[str, Any],
        commands: dict[str, Any],
    ) -> None:
        """Validate and add effect/mode command."""
        if ATTR_EFFECT not in kwargs:
            return
        if not self._mode_changeable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )
        effect = kwargs[ATTR_EFFECT]
        if self._attr_effect_list and effect not in self._attr_effect_list:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_effect",
                translation_placeholders={
                    "effect": effect,
                    "name": self.widget.effective_display_name(),
                    "allowed": ", ".join(self._attr_effect_list),
                },
            )
        commands[f"{path}.{VAL_MODE}"] = effect

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self._check_read_only()
        key = VAL_LED_ON if self._is_el2564 else VAL_LIGHT_ON
        await self.coordinator.async_send_command(
            self.device_name, {f"{self.widget.path}.{key}": False},
        )


class TcIotGeneralLight(TcIotEntity, LightEntity):
    """A General widget bValue1 exposed as light with modes as effects.

    This gives the HA voice assistant access to General widget modes via
    the standard light effect interface.
    """

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a General widget."""
        super().__init__(coordinator, device_name, widget)
        self._attr_unique_id = f"{self._attr_unique_id}_light"
        self._attr_translation_key = "light"
        self._attr_color_mode = ColorMode.ONOFF
        self._attr_supported_color_modes = {ColorMode.ONOFF}

        self._mode_changeable: bool = False
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read mode visibility/changeable from live widget metadata."""
        raw = self.widget.metadata.raw
        mode_visible = raw.get(META_GENERAL_MODE1_VISIBLE, "").lower() == "true"
        self._mode_changeable = mode_visible and (
            raw.get(META_GENERAL_MODE1_CHANGEABLE, "").lower() == "true"
        )
        modes = self.widget.values.get(VAL_GENERAL_MODES1, [])
        effects = [m for m in modes if m] if isinstance(modes, list) else []
        if effects and mode_visible:
            self._attr_effect_list = effects
            self._attr_supported_features = (
                LightEntityFeature.EFFECT
                if self._mode_changeable
                else LightEntityFeature(0)
            )
        elif mode_visible:
            current_effect = self.widget.values.get(VAL_GENERAL_MODE1, "")
            if current_effect:
                self._attr_effect_list = [current_effect]
                self._attr_supported_features = (
                    LightEntityFeature.EFFECT
                    if self._mode_changeable
                    else LightEntityFeature(0)
                )
            else:
                self._attr_supported_features = LightEntityFeature(0)
                self._attr_effect_list = []
        else:
            self._attr_supported_features = LightEntityFeature(0)
            self._attr_effect_list = []

    @property
    def is_on(self) -> bool | None:
        """Return whether bValue1 is True."""
        value = self.widget.values.get(VAL_GENERAL_VALUE1)
        if value is None:
            return None
        return bool(value)

    @property
    def effect(self) -> str | None:
        """Return the current mode as effect."""
        return self.widget.values.get(VAL_GENERAL_MODE1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose read_only and mode_changeable."""
        attrs = super().extra_state_attributes
        attrs["mode_changeable"] = self._mode_changeable
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on bValue1 and optionally set mode."""
        self._check_read_only()
        path = self.widget.path
        commands: dict[str, Any] = {}
        if ATTR_EFFECT not in kwargs:
            commands[f"{path}.{VAL_GENERAL_VALUE1}"] = True
        if ATTR_EFFECT in kwargs:
            if not self._mode_changeable:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_changeable_command",
                    translation_placeholders={
                        "name": self.widget.effective_display_name(),
                    },
                )
            effect = kwargs[ATTR_EFFECT]
            if self._attr_effect_list and effect not in self._attr_effect_list:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_effect",
                    translation_placeholders={
                        "effect": effect,
                        "name": self.widget.effective_display_name(),
                        "allowed": ", ".join(self._attr_effect_list),
                    },
                )
            commands[f"{path}.{VAL_GENERAL_MODE1}"] = effect
        await self.coordinator.async_send_command(self.device_name, commands)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off bValue1."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_GENERAL_VALUE1}": False},
        )
