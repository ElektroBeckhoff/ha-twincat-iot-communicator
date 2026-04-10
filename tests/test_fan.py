"""Tests for TwinCAT IoT Communicator fan platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.fan import FanEntityFeature
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_MODE,
    VAL_VENTILATION_ON,
    VAL_VENTILATION_VALUE_REQUEST,
)
from homeassistant.components.twincat_iot_communicator.fan import TcIotFan
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


def _make_fan(
    hass, entry: MockConfigEntry, fixture: str = "widgets/ventilation.json",
) -> tuple[TcIotFan, MagicMock]:
    """Create a TcIotFan from the given fixture."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotFan(coordinator, MOCK_DEVICE_NAME, widget)
    return entity, coordinator


class TestFanSetup:
    """Tests for fan entity initialization."""

    def test_features(self, hass, mock_config_entry) -> None:
        """Test fan supports on/off, speed, and presets from fixture."""
        entity, _ = _make_fan(hass, mock_config_entry)
        feat = entity.supported_features
        assert feat & FanEntityFeature.TURN_ON
        assert feat & FanEntityFeature.TURN_OFF
        assert feat & FanEntityFeature.SET_SPEED
        assert feat & FanEntityFeature.PRESET_MODE

    def test_is_on(self, hass, mock_config_entry) -> None:
        """Test is_on reads bOn value from fixture."""
        entity, _ = _make_fan(hass, mock_config_entry)
        assert entity.is_on is True

    def test_percentage(self, hass, mock_config_entry) -> None:
        """Test percentage scales from PLC min/max range."""
        entity, _ = _make_fan(hass, mock_config_entry)
        # fixture: nValueRequest=650, nValue min=400 (from stVentilation.nValue metadata)
        # But field_min/max are on nValue, percentage reads from nValueRequest
        # The fan uses _plc_min/_plc_max from VAL_VENTILATION_VALUE
        # fixture min=400, max=1400 => (650-400)/(1400-400)*100 = 25%
        pct = entity.percentage
        assert pct == 25

    def test_preset_mode(self, hass, mock_config_entry) -> None:
        """Test preset mode reads sMode."""
        entity, _ = _make_fan(hass, mock_config_entry)
        assert entity.preset_mode == "Automatic"
        assert entity.preset_modes == ["Automatic", "Manual"]


class TestFanCommands:
    """Tests for fan commands."""

    def test_turn_on(self, hass, mock_config_entry) -> None:
        """Test turn_on sends bOn=True."""
        entity, coord = _make_fan(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_VENTILATION_ON}"] is True

    def test_turn_off(self, hass, mock_config_entry) -> None:
        """Test turn_off sends bOn=False."""
        entity, coord = _make_fan(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_VENTILATION_ON}"] is False

    def test_set_percentage(self, hass, mock_config_entry) -> None:
        """Test set_percentage scales HA 0-100 to PLC range."""
        entity, coord = _make_fan(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_percentage(50))
        cmd = coord.async_send_command.call_args[0][1]
        # 50% of (400..1400) = 400 + 500 = 900
        assert cmd[f"{entity.widget.path}.{VAL_VENTILATION_VALUE_REQUEST}"] == 900

    def test_set_preset_mode(self, hass, mock_config_entry) -> None:
        """Test set_preset_mode sends sMode."""
        entity, coord = _make_fan(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_preset_mode("Manual"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE}"] == "Manual"

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only fan."""
        entity, _ = _make_fan(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_turn_on())


class TestFanPresetValidation:
    """Tests for preset mode input validation."""

    def test_invalid_preset_raises(self, hass, mock_config_entry) -> None:
        """Test turn_on with invalid preset_mode raises ServiceValidationError."""
        entity, _ = _make_fan(hass, mock_config_entry)
        assert entity.preset_modes == ["Automatic", "Manual"]
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_turn_on(preset_mode="NonExistent"),
            )

    def test_valid_preset_accepted(self, hass, mock_config_entry) -> None:
        """Test turn_on with valid preset_mode succeeds."""
        entity, coord = _make_fan(hass, mock_config_entry)
        hass.loop.run_until_complete(
            entity.async_turn_on(preset_mode="Manual"),
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE}"] == "Manual"


class TestFanModeHidden:
    """Tests for fan with VentilationModeVisible=false."""

    def test_preset_modes_empty(self, hass, mock_config_entry) -> None:
        """No preset modes when mode is hidden."""
        entity, _ = _make_fan(
            hass, mock_config_entry, "widgets/ventilation_mode_hidden.json",
        )
        assert entity.preset_modes == []

    def test_mode_not_changeable(self, hass, mock_config_entry) -> None:
        """mode_changeable gated by visibility."""
        entity, _ = _make_fan(
            hass, mock_config_entry, "widgets/ventilation_mode_hidden.json",
        )
        assert entity._mode_changeable is False

    def test_no_preset_mode_feature(self, hass, mock_config_entry) -> None:
        """PRESET_MODE feature must not be set when mode hidden."""
        entity, _ = _make_fan(
            hass, mock_config_entry, "widgets/ventilation_mode_hidden.json",
        )
        assert not (entity.supported_features & FanEntityFeature.PRESET_MODE)

    def test_on_off_still_works(self, hass, mock_config_entry) -> None:
        """On/off features are independent of mode visibility."""
        entity, _ = _make_fan(
            hass, mock_config_entry, "widgets/ventilation_mode_hidden.json",
        )
        feat = entity.supported_features
        assert feat & FanEntityFeature.TURN_ON
        assert feat & FanEntityFeature.TURN_OFF

    def test_set_preset_mode_raises(self, hass, mock_config_entry) -> None:
        """Setting preset mode raises when mode is hidden."""
        entity, _ = _make_fan(
            hass, mock_config_entry, "widgets/ventilation_mode_hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_set_preset_mode("Manual"),
            )
