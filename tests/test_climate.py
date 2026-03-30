"""Tests for TwinCAT IoT Communicator climate platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.twincat_iot_communicator.climate import TcIotClimate
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_AC_TEMPERATURE,
    VAL_AC_TEMPERATURE_REQUEST,
    VAL_MODE,
    VAL_MODE_LAMELLA,
    VAL_MODE_STRENGTH,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


DEVICE_NAME = "TestDevice"


def _make_climate(
    hass, entry: MockConfigEntry, fixture: str = "widgets/ac.json",
) -> tuple[TcIotClimate, MagicMock]:
    """Create a TcIotClimate from the given fixture (default: AC)."""
    dev = build_device_with_widgets(DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotClimate(coordinator, DEVICE_NAME, widget)
    return entity, coordinator


class TestClimateSetup:
    """Tests for climate entity initialization."""

    def test_hvac_modes(self, hass, mock_config_entry) -> None:
        """Test HVAC modes are mapped from PLC modes."""
        entity, _ = _make_climate(hass, mock_config_entry)
        modes = entity.hvac_modes
        assert HVACMode.AUTO in modes
        assert HVACMode.HEAT in modes
        assert HVACMode.COOL in modes
        assert HVACMode.OFF in modes

    def test_temperature_unit(self, hass, mock_config_entry) -> None:
        """Test temperature unit is Celsius from fixture metadata."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity.temperature_unit == UnitOfTemperature.CELSIUS

    def test_features(self, hass, mock_config_entry) -> None:
        """Test supported features include target temp and on/off."""
        entity, _ = _make_climate(hass, mock_config_entry)
        feat = entity.supported_features
        assert feat & ClimateEntityFeature.TARGET_TEMPERATURE
        assert feat & ClimateEntityFeature.TURN_ON
        assert feat & ClimateEntityFeature.TURN_OFF


class TestClimateState:
    """Tests for climate state reading."""

    def test_current_temperature(self, hass, mock_config_entry) -> None:
        """Test current temperature from PLC value."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity.current_temperature == 16.0

    def test_target_temperature(self, hass, mock_config_entry) -> None:
        """Test target temperature from PLC request value."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity.target_temperature == 16.0

    def test_hvac_mode_mapped(self, hass, mock_config_entry) -> None:
        """Test current HVAC mode is mapped from PLC mode string."""
        entity, _ = _make_climate(hass, mock_config_entry)
        # fixture: sMode = "Auto"
        assert entity.hvac_mode == HVACMode.AUTO

    def test_fan_mode(self, hass, mock_config_entry) -> None:
        """Test fan mode reads from sMode_Strength."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity.fan_mode == "off"


class TestClimateCommands:
    """Tests for climate commands."""

    def test_set_temperature(self, hass, mock_config_entry) -> None:
        """Test set_temperature sends nTemperatureRequest."""
        entity, coord = _make_climate(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_temperature(temperature=22.0))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_AC_TEMPERATURE_REQUEST}"] == 22.0

    def test_set_hvac_mode(self, hass, mock_config_entry) -> None:
        """Test set_hvac_mode sends PLC mode string."""
        entity, coord = _make_climate(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_hvac_mode(HVACMode.HEAT))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE}"] == "Heizen"

    def test_preset_modes(self, hass, mock_config_entry) -> None:
        """Test unmapped PLC modes become presets."""
        entity, _ = _make_climate(hass, mock_config_entry)
        # "Auto", "Heizen", "Kühlen", "Aus" are all mapped, no presets expected
        assert entity.preset_modes is None

    def test_set_fan_mode(self, hass, mock_config_entry) -> None:
        """Test set_fan_mode sends sMode_Strength with reverse-mapped PLC string."""
        entity, coord = _make_climate(hass, mock_config_entry)
        entity._strength_changeable = True
        hass.loop.run_until_complete(entity.async_set_fan_mode("heat"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE_STRENGTH}"] == "Heizen"

    def test_set_fan_mode_not_changeable_raises(self, hass, mock_config_entry) -> None:
        """Test set_fan_mode raises when strength is not changeable."""
        entity, _ = _make_climate(hass, mock_config_entry)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_fan_mode("heat"))

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test set_temperature raises for read-only widget."""
        entity, _ = _make_climate(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_temperature(temperature=22.0))


class TestClimateInputValidation:
    """Tests for input validation added in the security/best-practice review."""

    def test_set_temperature_clamped_high(self, hass, mock_config_entry) -> None:
        """Temperature above max_temp is clamped."""
        entity, coord = _make_climate(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_temperature(temperature=999.0))
        cmd = coord.async_send_command.call_args[0][1]
        sent_temp = cmd[f"{entity.widget.path}.{VAL_AC_TEMPERATURE_REQUEST}"]
        assert sent_temp == entity._attr_max_temp

    def test_set_temperature_clamped_low(self, hass, mock_config_entry) -> None:
        """Temperature below min_temp is clamped."""
        entity, coord = _make_climate(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_temperature(temperature=-50.0))
        cmd = coord.async_send_command.call_args[0][1]
        sent_temp = cmd[f"{entity.widget.path}.{VAL_AC_TEMPERATURE_REQUEST}"]
        assert sent_temp == entity._attr_min_temp

    def test_set_fan_mode_invalid_raises(self, hass, mock_config_entry) -> None:
        """Invalid fan mode raises ServiceValidationError."""
        entity, _ = _make_climate(hass, mock_config_entry)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_fan_mode("Turbo"))

    def test_set_swing_mode_invalid_raises(self, hass, mock_config_entry) -> None:
        """Invalid swing mode raises ServiceValidationError."""
        entity, _ = _make_climate(hass, mock_config_entry)
        entity._attr_swing_modes = ["horizontal", "vertical"]
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_swing_mode("diagonal"))

    def test_set_preset_mode_invalid_raises(self, hass, mock_config_entry) -> None:
        """Invalid preset mode raises ServiceValidationError."""
        entity, _ = _make_climate(hass, mock_config_entry)
        entity._preset_modes = ["Eco", "Comfort"]
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_preset_mode("Sport"))


class TestClimateModeHidden:
    """Tests for AC widget with ACModeVisible=false."""

    def test_hvac_modes_empty(self, hass, mock_config_entry) -> None:
        """When ModeVisible is false, hvac_modes must be empty (no selector)."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity.hvac_modes == []

    def test_hvac_mode_still_reflects_plc_state(self, hass, mock_config_entry) -> None:
        """State still shows the actual PLC mode even when hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        # fixture: sMode = "Auto" → map still populated for state reading
        assert entity.hvac_mode == HVACMode.AUTO

    def test_no_turn_on_off_features(self, hass, mock_config_entry) -> None:
        """TURN_ON / TURN_OFF features must not be set."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        feat = entity.supported_features
        assert not (feat & ClimateEntityFeature.TURN_ON)
        assert not (feat & ClimateEntityFeature.TURN_OFF)

    def test_mode_not_changeable(self, hass, mock_config_entry) -> None:
        """mode_changeable must be False when mode is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity._mode_changeable is False

    def test_no_preset_modes(self, hass, mock_config_entry) -> None:
        """No preset modes when mode is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity.preset_modes is None

    def test_no_fan_selector(self, hass, mock_config_entry) -> None:
        """No fan mode selector when strength is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity._attr_fan_modes == []

    def test_fan_mode_still_mapped(self, hass, mock_config_entry) -> None:
        """Fan state still maps PLC strings even when hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        # fixture: sMode_Strength = "Aus" → should map to "off", not raw "Aus"
        assert entity.fan_mode == "off"

    def test_strength_not_changeable(self, hass, mock_config_entry) -> None:
        """strength_changeable gated by visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity._strength_changeable is False

    def test_lamella_not_changeable(self, hass, mock_config_entry) -> None:
        """lamella_changeable gated by visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        assert entity._lamella_changeable is False

    def test_target_temp_still_works(self, hass, mock_config_entry) -> None:
        """Target temperature feature is independent of mode visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        feat = entity.supported_features
        assert feat & ClimateEntityFeature.TARGET_TEMPERATURE

    def test_set_hvac_mode_raises(self, hass, mock_config_entry) -> None:
        """Setting HVAC mode raises when mode is hidden (not changeable)."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_set_hvac_mode(HVACMode.HEAT),
            )

    def test_set_fan_mode_raises_when_hidden(self, hass, mock_config_entry) -> None:
        """Setting fan mode raises when strength is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/ac_mode_hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_fan_mode("heat"))
