"""Tests for TwinCAT IoT Communicator cover platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_BLINDS_ACTIVE,
    VAL_BLINDS_ANGLE_DOWN,
    VAL_BLINDS_ANGLE_REQUEST,
    VAL_BLINDS_ANGLE_UP,
    VAL_BLINDS_POSITION_DOWN,
    VAL_BLINDS_POSITION_REQUEST,
    VAL_BLINDS_POSITION_UP,
    VAL_BLINDS_POSITION_VALUE,
)
from homeassistant.components.twincat_iot_communicator.cover import TcIotCover
from homeassistant.exceptions import ServiceValidationError

from .conftest import MOCK_DEVICE_NAME, build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


def _make_cover(
    hass, entry: MockConfigEntry, fixture: str
) -> tuple[TcIotCover, MagicMock]:
    """Create a TcIotCover from a fixture."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotCover(coordinator, MOCK_DEVICE_NAME, widget)
    return entity, coordinator


class TestBlindsSetup:
    """Tests for full Blinds widget features."""

    def test_blinds_features(self, hass, mock_config_entry) -> None:
        """Test Blinds widget has full feature set."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        feat = entity.supported_features
        assert feat & CoverEntityFeature.OPEN
        assert feat & CoverEntityFeature.CLOSE
        assert feat & CoverEntityFeature.STOP
        assert feat & CoverEntityFeature.SET_POSITION
        assert feat & CoverEntityFeature.OPEN_TILT
        assert feat & CoverEntityFeature.CLOSE_TILT
        assert feat & CoverEntityFeature.SET_TILT_POSITION

    def test_simple_blinds_features(self, hass, mock_config_entry) -> None:
        """Test SimpleBlinds widget has only open/close."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-simple-blinds.json")
        feat = entity.supported_features
        assert feat & CoverEntityFeature.OPEN
        assert feat & CoverEntityFeature.CLOSE
        assert not (feat & CoverEntityFeature.STOP)
        assert not (feat & CoverEntityFeature.SET_POSITION)
        assert not (feat & CoverEntityFeature.SET_TILT_POSITION)


class TestCoverCommands:
    """Tests for cover commands."""

    def test_open(self, hass, mock_config_entry) -> None:
        """Test open sends bPositionUp."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_open_cover())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_POSITION_UP}"] is True

    def test_close(self, hass, mock_config_entry) -> None:
        """Test close sends bPositionDown."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_close_cover())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_POSITION_DOWN}"] is True

    def test_stop(self, hass, mock_config_entry) -> None:
        """Test stop sends bActive."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_stop_cover())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ACTIVE}"] is True


class TestCoverPosition:
    """Tests for position and tilt."""

    def test_position_inversion(self, hass, mock_config_entry) -> None:
        """Test PLC position 0 maps to HA 100 (fully open)."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.widget.values[VAL_BLINDS_POSITION_VALUE] = 0
        assert entity.current_cover_position == 100

        entity.widget.values[VAL_BLINDS_POSITION_VALUE] = 100
        assert entity.current_cover_position == 0
        assert entity.is_closed is True

    def test_set_position(self, hass, mock_config_entry) -> None:
        """Test set_position inverts correctly."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(
            entity.async_set_cover_position(position=75)
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_POSITION_REQUEST}"] == 25

    def test_tilt_position(self, hass, mock_config_entry) -> None:
        """Test tilt position scales from angle range to 0-100."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        # fixture: min=-75, max=75, current=75
        entity.widget.values["nAngleValue"] = 75
        assert entity.current_cover_tilt_position == 100

        entity.widget.values["nAngleValue"] = -75
        assert entity.current_cover_tilt_position == 0

        entity.widget.values["nAngleValue"] = 0
        assert entity.current_cover_tilt_position == 50

    def test_set_tilt(self, hass, mock_config_entry) -> None:
        """Test set_cover_tilt_position maps HA 0-100 to angle range."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(
            entity.async_set_cover_tilt_position(tilt_position=50)
        )
        cmd = coord.async_send_command.call_args[0][1]
        # 50% of (-75..75) = 0
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ANGLE_REQUEST}"] == 0

    def test_open_tilt(self, hass, mock_config_entry) -> None:
        """Test open_tilt sends bAngleDown (swapped)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_open_cover_tilt())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ANGLE_DOWN}"] is True

    def test_close_tilt(self, hass, mock_config_entry) -> None:
        """Test close_tilt sends bAngleUp (swapped)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_close_cover_tilt())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ANGLE_UP}"] is True


class TestCoverPositionClamping:
    """Tests for position input clamping."""

    def test_set_position_clamped_above_100(self, hass, mock_config_entry) -> None:
        """Position > 100 is clamped to 100 (=PLC 0)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_set_cover_position(position=150))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_POSITION_REQUEST}"] == 0

    def test_set_position_clamped_below_0(self, hass, mock_config_entry) -> None:
        """Position < 0 is clamped to 0 (=PLC 100)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_set_cover_position(position=-10))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_POSITION_REQUEST}"] == 100

    def test_set_tilt_clamped_above_100(self, hass, mock_config_entry) -> None:
        """Tilt > 100 is clamped to 100 (=max angle)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_set_cover_tilt_position(tilt_position=200))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ANGLE_REQUEST}"] == 75

    def test_set_tilt_clamped_below_0(self, hass, mock_config_entry) -> None:
        """Tilt < 0 is clamped to 0 (=min angle)."""
        entity, coord = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        hass.loop.run_until_complete(entity.async_set_cover_tilt_position(tilt_position=-10))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_BLINDS_ANGLE_REQUEST}"] == -75


class TestCoverMovementDetection:
    """Tests for velocity-based movement detection."""

    @staticmethod
    def _update(entity: TcIotCover, position: int | None) -> None:
        """Simulate a widget update with the given position."""
        widget = entity.widget
        if position is not None:
            widget.values[VAL_BLINDS_POSITION_VALUE] = position
        else:
            widget.values.pop(VAL_BLINDS_POSITION_VALUE, None)
        with patch.object(entity, "async_write_ha_state"), \
             patch.object(entity, "_reschedule_stop_timer"):
            entity._on_widget_update(widget)

    def test_opening_detected(self, hass, mock_config_entry) -> None:
        """Test that a decreasing PLC position is detected as opening."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, 80)
        assert entity.is_opening is False

        self._update(entity, 60)
        assert entity.is_opening is True
        assert entity.is_closing is False

    def test_closing_detected(self, hass, mock_config_entry) -> None:
        """Test that an increasing PLC position is detected as closing."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, 20)

        self._update(entity, 50)
        assert entity.is_closing is True
        assert entity.is_opening is False

    def test_same_position_no_change(self, hass, mock_config_entry) -> None:
        """Test that an unchanged position does not alter movement direction."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, 50)
        self._update(entity, 30)
        assert entity.is_opening is True

        self._update(entity, 30)
        assert entity.is_opening is True

    def test_direction_reversal(self, hass, mock_config_entry) -> None:
        """Test that direction reverses when movement flips."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, 50)
        self._update(entity, 30)
        assert entity.is_opening is True

        self._update(entity, 60)
        assert entity.is_closing is True
        assert entity.is_opening is False

    def test_movement_timeout_stops(self, hass, mock_config_entry) -> None:
        """Test that the movement timeout callback marks cover as stopped."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, 50)
        self._update(entity, 30)
        assert entity.is_opening is True

        with patch.object(entity, "async_write_ha_state"):
            entity._on_movement_timeout()
        assert entity.is_opening is False
        assert entity.is_closing is False

    def test_no_position_no_movement(self, hass, mock_config_entry) -> None:
        """Test that None position does not crash or set movement."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.hass = hass
        self._update(entity, None)
        assert entity.is_opening is False
        assert entity.is_closing is False


class TestCoverReadOnly:
    """Test read-only guard for covers."""

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only cover."""
        entity, _ = _make_cover(hass, mock_config_entry, "widgets/base/widget-blinds.json")
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_open_cover())
