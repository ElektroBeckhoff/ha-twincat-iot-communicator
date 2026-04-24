"""Cover platform for TwinCAT IoT Communicator (Blind / SimpleBlind widgets)."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TcIotConfigEntry
from .const import (
    META_BLINDS_ANGLE_SLIDER_VISIBLE,
    VAL_BLINDS_ACTIVE,
    VAL_BLINDS_ANGLE_DOWN,
    VAL_BLINDS_ANGLE_REQUEST,
    VAL_BLINDS_ANGLE_UP,
    VAL_BLINDS_ANGLE_VALUE,
    VAL_BLINDS_POSITION_DOWN,
    VAL_BLINDS_POSITION_REQUEST,
    VAL_BLINDS_POSITION_UP,
    VAL_BLINDS_POSITION_VALUE,
    VAL_MODE,
    WIDGET_TYPE_BLINDS,
    WIDGET_TYPE_SIMPLE_BLINDS,
)
from .coordinator import TcIotCoordinator
from .entity import TcIotEntity
from .models import metadata_unless_false, WidgetData

PARALLEL_UPDATES = 0

BLIND_WIDGET_TYPES = frozenset({WIDGET_TYPE_BLINDS, WIDGET_TYPE_SIMPLE_BLINDS})

# After this many seconds without a position change the cover is considered stopped.
_MOVEMENT_TIMEOUT: Final = 5.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TcIoT cover entities from all discovered devices."""
    coordinator: TcIotCoordinator = entry.runtime_data

    entities: list[TcIotCover] = []
    for device_name, device in coordinator.devices.items():
        for widget in device.widgets.values():
            if widget.metadata.widget_type in BLIND_WIDGET_TYPES:
                entities.append(TcIotCover(coordinator, device_name, widget))
    if entities:
        async_add_entities(entities)

    def _on_new_widgets(device_name: str, widgets: list[WidgetData]) -> None:
        new = [
            TcIotCover(coordinator, device_name, widget)
            for widget in widgets
            if widget.metadata.widget_type in BLIND_WIDGET_TYPES
        ]
        if new:
            async_add_entities(new)

    coordinator.register_new_widget_callback(Platform.COVER, _on_new_widgets)


class TcIotCover(TcIotEntity, CoverEntity):
    """A TcIoT Blind widget exposed as HA cover entity."""

    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(
        self,
        coordinator: TcIotCoordinator,
        device_name: str,
        widget: WidgetData,
    ) -> None:
        """Initialize from a discovered blind widget."""
        super().__init__(coordinator, device_name, widget)
        self._last_position: int | None = None
        self._moving_dir: int = 0  # -1=closing, 0=stopped, 1=opening
        self._stop_call: CALLBACK_TYPE | None = None
        self._sync_metadata()

    def _sync_metadata(self) -> None:
        """Re-build supported features from live widget metadata."""
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

        if self.widget.metadata.widget_type == WIDGET_TYPE_BLINDS:
            features |= (
                CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
            )

        if self._supports_tilt():
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )

        self._attr_supported_features = features

    def _supports_tilt(self) -> bool:
        """Return True if the blind supports tilt angle control."""
        if self.widget.metadata.widget_type == WIDGET_TYPE_SIMPLE_BLINDS:
            return False
        return metadata_unless_false(
            self.widget.metadata.raw.get(
                META_BLINDS_ANGLE_SLIDER_VISIBLE, "true",
            ),
        )

    # ── Tilt scaling helpers ─────────────────────────────────────────

    @staticmethod
    def _angle_to_ha_tilt(
        angle: float, angle_min: float, angle_max: float,
    ) -> int:
        """Scale PLC angle → HA tilt percentage (0–100)."""
        angle_range = angle_max - angle_min
        if angle_range == 0:
            return 0
        return max(
            0, min(100, round((angle - angle_min) / angle_range * 100))
        )

    @staticmethod
    def _ha_tilt_to_angle(
        tilt: int, angle_min: float, angle_max: float,
    ) -> int:
        """Scale HA tilt percentage (0–100) → PLC angle."""
        return round(angle_min + (tilt / 100) * (angle_max - angle_min))

    # ── State properties ─────────────────────────────────────────────

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is fully closed."""
        position = self.widget.values.get(VAL_BLINDS_POSITION_VALUE)
        if position is None:
            return None
        return int(position) >= 100

    @property
    def current_cover_position(self) -> int | None:
        """Return the current cover position (0=closed, 100=open)."""
        position = self.widget.values.get(VAL_BLINDS_POSITION_VALUE)
        if position is None:
            return None
        return 100 - int(position)

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position scaled to 0–100."""
        angle = self.widget.values.get(VAL_BLINDS_ANGLE_VALUE)
        if angle is None:
            return None
        return self._angle_to_ha_tilt(
            float(angle),
            self.widget.field_min(VAL_BLINDS_ANGLE_VALUE, -90),
            self.widget.field_max(VAL_BLINDS_ANGLE_VALUE, 90),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose widget metadata as state attributes."""
        attrs: dict[str, Any] = {"read_only": self.widget.metadata.read_only}
        mode = self.widget.values.get(VAL_MODE)
        if mode is not None:
            attrs["mode"] = mode
        return attrs

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the movement timeout when the entity is removed."""
        self._cancel_stop_timer()
        await super().async_will_remove_from_hass()

    def _cancel_stop_timer(self) -> None:
        """Cancel any pending movement-stop timer."""
        if self._stop_call is not None:
            self._stop_call()
            self._stop_call = None

    def _reschedule_stop_timer(self) -> None:
        """(Re-)start the timer that marks the cover as stopped."""
        self._cancel_stop_timer()
        self._stop_call = async_call_later(
            self.hass, _MOVEMENT_TIMEOUT, self._on_movement_timeout
        )

    @callback
    def _on_movement_timeout(self, *_: Any) -> None:
        """Mark cover as stopped after no position change for _MOVEMENT_TIMEOUT s."""
        self._stop_call = None
        self._moving_dir = 0
        self.async_write_ha_state()

    @callback
    def _on_widget_update(self, widget: WidgetData) -> None:
        """Detect movement direction from position delta with velocity timeout.

        Direction is set whenever the position changes and held until either a
        new delta reverses it or no position update arrives within
        _MOVEMENT_TIMEOUT seconds (at which point the cover is considered
        stopped). This works for all widget types regardless of whether the PLC
        exposes an explicit movement status field.
        """
        new_position = widget.values.get(VAL_BLINDS_POSITION_VALUE)

        if new_position is not None:
            pos = int(new_position)
            if self._last_position is not None:
                delta = pos - self._last_position
                if delta > 0:
                    self._moving_dir = -1  # PLC pos increasing = closing
                    self._reschedule_stop_timer()
                elif delta < 0:
                    self._moving_dir = 1   # PLC pos decreasing = opening
                    self._reschedule_stop_timer()
                # delta == 0: position unchanged, timer keeps running
            self._last_position = pos

        super()._on_widget_update(widget)

    @property
    def is_opening(self) -> bool | None:
        """Return True while the cover is actively opening."""
        return self._moving_dir == 1

    @property
    def is_closing(self) -> bool | None:
        """Return True while the cover is actively closing."""
        return self._moving_dir == -1

    # ── Commands ─────────────────────────────────────────────────────

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_POSITION_UP}": True},
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_POSITION_DOWN}": True},
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover movement by toggling bActive."""
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_ACTIVE}": True},
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover to a specific position."""
        self._check_read_only()
        ha_position = max(0, min(100, int(kwargs[ATTR_POSITION])))
        plc_position = 100 - ha_position
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_POSITION_REQUEST}": plc_position},
        )

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the cover tilt.

        Intentionally swapped: PLC bAngleDown physically opens the lamellae
        (angle increases towards max), while bAngleUp closes them.
        """
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_ANGLE_DOWN}": True},
        )

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the cover tilt.

        Intentionally swapped: PLC bAngleUp physically closes the lamellae
        (angle decreases towards min), while bAngleDown opens them.
        """
        self._check_read_only()
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_ANGLE_UP}": True},
        )

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set the cover tilt to a specific position."""
        self._check_read_only()
        ha_tilt = max(0, min(100, int(kwargs[ATTR_TILT_POSITION])))
        plc_angle = self._ha_tilt_to_angle(
            ha_tilt,
            self.widget.field_min(VAL_BLINDS_ANGLE_VALUE, -90),
            self.widget.field_max(VAL_BLINDS_ANGLE_VALUE, 90),
        )
        await self.coordinator.async_send_command(
            self.device_name,
            {f"{self.widget.path}.{VAL_BLINDS_ANGLE_REQUEST}": plc_angle},
        )
