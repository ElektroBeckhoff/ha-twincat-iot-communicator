"""Fan platform for TwinCAT IoT Communicator (Ventilation widgets)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    DOMAIN,
    META_VENTILATION_MODE_CHANGEABLE,
    META_VENTILATION_MODE_VISIBLE,
    META_VENTILATION_ON_SWITCH_VISIBLE,
    META_VENTILATION_SLIDER_VISIBLE,
    VAL_MODE,
    VAL_MODES,
    VAL_VENTILATION_ON,
    VAL_VENTILATION_VALUE,
    VAL_VENTILATION_VALUE_REQUEST,
    WIDGET_TYPE_VENTILATION,
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
    """Set up TcIoT fan entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TcIotFan] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            if widget.metadata.widget_type == WIDGET_TYPE_VENTILATION:
                entities.append(TcIotFan(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new = [
            TcIotFan(coordinator, device_name, widget)
            for widget in widgets
            if widget.metadata.widget_type == WIDGET_TYPE_VENTILATION
        ]
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.FAN, _on_new_widgets)


class TcIotFan(TcIotEntity, FanEntity):
    """A TcIoT Ventilation widget exposed as HA fan entity."""

    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a discovered ventilation widget."""
        super().__init__(coordinator, device_name, widget)
        self._supports_on_off: bool = False
        self._supports_speed: bool = False
        self._mode_changeable: bool = False
        self._speed_min: float = 0
        self._speed_max: float = 100
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-read all metadata-dependent attributes from the live widget."""
        raw = self.widget.metadata.raw
        features = FanEntityFeature(0)

        self._supports_on_off = (
            raw.get(META_VENTILATION_ON_SWITCH_VISIBLE, "false").lower()
            == "true"
        )
        if self._supports_on_off:
            features |= FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

        self._supports_speed = (
            raw.get(META_VENTILATION_SLIDER_VISIBLE, "false").lower() == "true"
        )
        if self._supports_speed:
            features |= FanEntityFeature.SET_SPEED

        supports_mode = (
            raw.get(META_VENTILATION_MODE_VISIBLE, "false").lower() == "true"
        )
        can_change_mode = (
            raw.get(META_VENTILATION_MODE_CHANGEABLE, "false").lower()
            == "true"
        )
        self._mode_changeable = supports_mode and can_change_mode
        plc_modes = [m for m in self.widget.values.get(VAL_MODES, []) if m]
        if supports_mode and plc_modes:
            self._attr_preset_modes = plc_modes
            if can_change_mode:
                features |= FanEntityFeature.PRESET_MODE
        elif supports_mode:
            current_mode = self.widget.values.get(VAL_MODE, "")
            if current_mode:
                self._attr_preset_modes = [current_mode]
                if can_change_mode:
                    features |= FanEntityFeature.PRESET_MODE
            else:
                self._attr_preset_modes = []
        else:
            self._attr_preset_modes = []

        self._speed_min = self.widget.field_min(VAL_VENTILATION_VALUE, 0)
        self._speed_max = self.widget.field_max(VAL_VENTILATION_VALUE, 100)

        self._attr_supported_features = features

    # ── Scaling helpers ──────────────────────────────────────────────

    @staticmethod
    def _speed_plc_to_ha(
        plc_value: float, speed_min: float, speed_max: float,
    ) -> int:
        """Scale PLC speed value → HA percentage (0–100)."""
        speed_range = speed_max - speed_min
        if speed_range <= 0:
            return 0
        return min(
            100,
            max(0, round((plc_value - speed_min) / speed_range * 100)),
        )

    @staticmethod
    def _speed_ha_to_plc(
        percentage: int, speed_min: float, speed_max: float,
    ) -> int:
        """Scale HA percentage (0–100) → PLC speed value."""
        speed_range = speed_max - speed_min
        return round(speed_min + (percentage / 100) * speed_range)

    # ── State properties ─────────────────────────────────────────────

    @property
    def is_on(self) -> bool | None:
        """Return whether the fan is on."""
        if not self._supports_on_off:
            return None
        value = self.widget.values.get(VAL_VENTILATION_ON)
        if value is None:
            return None
        return bool(value)

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage (0–100)."""
        if not self._supports_speed:
            return None
        value = self.widget.values.get(VAL_VENTILATION_VALUE_REQUEST)
        if value is None:
            return None
        return self._speed_plc_to_ha(
            float(value), self._speed_min, self._speed_max,
        )

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self.widget.values.get(VAL_MODE) or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose current PLC speed value, unit, and mode changeable flag."""
        attrs = super().extra_state_attributes
        attrs["mode_changeable"] = self._mode_changeable
        value = self.widget.values.get(VAL_VENTILATION_VALUE)
        if value is not None:
            attrs["current_value"] = value
            unit = self.widget.field_unit(VAL_VENTILATION_VALUE)
            if unit:
                attrs["current_value_unit"] = unit
        return attrs

    # ── Commands ─────────────────────────────────────────────────────

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan, optionally setting speed and/or preset."""
        self._check_read_only()
        commands: dict[str, Any] = {}
        if self._supports_on_off:
            commands[f"{self.widget.path}.{VAL_VENTILATION_ON}"] = True
        if percentage is not None and self._supports_speed:
            plc_speed = self._speed_ha_to_plc(
                percentage, self._speed_min, self._speed_max,
            )
            commands[f"{self.widget.path}.{VAL_VENTILATION_VALUE_REQUEST}"] = (
                plc_speed
            )
        if preset_mode is not None and self._mode_changeable:
            if self._attr_preset_modes and preset_mode not in self._attr_preset_modes:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_preset_mode",
                    translation_placeholders={
                        "name": self.widget.effective_display_name(),
                        "mode": preset_mode,
                        "allowed": ", ".join(self._attr_preset_modes),
                    },
                )
            commands[f"{self.widget.path}.{VAL_MODE}"] = preset_mode
        if commands:
            await self._send_optimistic(commands)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        self._check_read_only()
        if not self._supports_on_off:
            return
        await self._send_optimistic(
            {f"{self.widget.path}.{VAL_VENTILATION_ON}": False},
        )

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed as a percentage."""
        self._check_read_only()
        if not self._supports_speed:
            return
        plc_speed = self._speed_ha_to_plc(
            percentage, self._speed_min, self._speed_max,
        )
        await self._send_optimistic(
            {f"{self.widget.path}.{VAL_VENTILATION_VALUE_REQUEST}": plc_speed},
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        self._check_read_only()
        if not self._mode_changeable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_changeable_command",
                translation_placeholders={
                    "name": self.widget.effective_display_name(),
                },
            )
        await self._send_optimistic(
            {f"{self.widget.path}.{VAL_MODE}": preset_mode},
        )
