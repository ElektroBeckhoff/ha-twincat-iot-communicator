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

from .conftest import (
    MOCK_DEVICE_NAME,
    attach_entity_to_hass,
    build_device_from_multi_widget_fixture,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry


def _make_climate(
    hass, entry: MockConfigEntry, fixture: str = "widgets/base/widget-ac.json",
) -> tuple[TcIotClimate, MagicMock]:
    """Create a TcIotClimate from the given fixture (default: AC)."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotClimate(coordinator, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "climate")
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

    def test_visible_flags_fully_featured(self, hass, mock_config_entry) -> None:
        """Visible flags match fully featured AC widget."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity._mode_visible is True
        assert entity._strength_visible is True
        assert entity._lamella_visible is True

    def test_visible_flags_lamella_hidden(self, hass, mock_config_entry) -> None:
        """Visible flags for AC variant with lamella hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry,
            "widgets/variants/widget-ac-lamella-hidden.json",
        )
        assert entity._mode_visible is True
        assert entity._strength_visible is True
        assert entity._lamella_visible is False

    def test_extra_state_attributes_fully_featured(self, hass, mock_config_entry) -> None:
        """extra_state_attributes for fully featured AC widget."""
        entity, _ = _make_climate(hass, mock_config_entry)
        attrs = entity.extra_state_attributes
        assert attrs["mode_visible"] is True
        assert attrs["mode_changeable"] is True
        assert attrs["strength_visible"] is True
        assert attrs["strength_changeable"] is True
        assert attrs["lamella_visible"] is True
        assert attrs["lamella_changeable"] is True
        assert "ac_mode_icon" in attrs

    def test_extra_state_attributes_lamella_hidden(self, hass, mock_config_entry) -> None:
        """extra_state_attributes for AC variant with lamella hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry,
            "widgets/variants/widget-ac-lamella-hidden.json",
        )
        attrs = entity.extra_state_attributes
        assert attrs["mode_visible"] is True
        assert attrs["mode_changeable"] is True
        assert attrs["strength_visible"] is True
        assert attrs["strength_changeable"] is False
        assert attrs["lamella_visible"] is False
        assert attrs["lamella_changeable"] is False
        assert "ac_mode_icon" in attrs


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

    def test_hvac_mode_none_when_preset_active(self, hass, mock_config_entry) -> None:
        """hvac_mode must return None (not OFF) when the active mode is a preset."""
        entity, _ = _make_climate(hass, mock_config_entry)
        entity._preset_modes = ["Turbo"]
        entity._preset_lower_map = {"turbo": "Turbo"}
        entity.widget.values["sMode"] = "Turbo"
        assert entity.hvac_mode is None
        assert entity.preset_mode == "Turbo"

    def test_hvac_mode_off_for_empty_mode(self, hass, mock_config_entry) -> None:
        """hvac_mode falls back to OFF when sMode is empty."""
        entity, _ = _make_climate(hass, mock_config_entry)
        entity.widget.values["sMode"] = ""
        assert entity.hvac_mode == HVACMode.OFF

    def test_fan_mode_fully_featured(self, hass, mock_config_entry) -> None:
        """Test fan mode reads from sMode_Strength (fully featured: Hoch -> high)."""
        entity, _ = _make_climate(hass, mock_config_entry)
        assert entity.fan_mode == "high"

    def test_fan_mode_lamella_hidden(self, hass, mock_config_entry) -> None:
        """Test fan mode reads 'off' from lamella-hidden variant."""
        entity, _ = _make_climate(
            hass, mock_config_entry,
            "widgets/variants/widget-ac-lamella-hidden.json",
        )
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
        hass.loop.run_until_complete(entity.async_set_fan_mode("low"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE_STRENGTH}"] == "Niedrig"

    def test_set_fan_mode_not_changeable_raises(self, hass, mock_config_entry) -> None:
        """Test set_fan_mode raises when strength is not changeable."""
        entity, _ = _make_climate(
            hass, mock_config_entry,
            "widgets/variants/widget-ac-lamella-hidden.json",
        )
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

    def test_hvac_modes_single_derived_when_hidden(self, hass, mock_config_entry) -> None:
        """When ModeVisible is false, hvac_modes lists only the derived nAcMode state."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        # Hidden UI: single chip from nAcMode (fixture nAcMode=0 → OFF), not sMode.
        assert entity.hvac_modes == [HVACMode.OFF]

    def test_hvac_mode_still_reflects_plc_state(self, hass, mock_config_entry) -> None:
        """State still shows the actual PLC mode even when hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        # Derived from nAcMode when ACModeVisible is false (not from sMode "Auto").
        assert entity.hvac_mode == HVACMode.OFF

    def test_no_turn_on_off_features(self, hass, mock_config_entry) -> None:
        """TURN_ON / TURN_OFF features must not be set."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        feat = entity.supported_features
        assert not (feat & ClimateEntityFeature.TURN_ON)
        assert not (feat & ClimateEntityFeature.TURN_OFF)

    def test_visible_flags_all_false(self, hass, mock_config_entry) -> None:
        """All visible flags must be False when modes are hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity._mode_visible is False
        assert entity._strength_visible is False
        assert entity._lamella_visible is False

    def test_extra_state_attributes_hidden(self, hass, mock_config_entry) -> None:
        """extra_state_attributes reflects hidden state."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        attrs = entity.extra_state_attributes
        assert attrs["mode_visible"] is False
        assert attrs["mode_changeable"] is False
        assert attrs["strength_visible"] is False
        assert attrs["strength_changeable"] is False
        assert attrs["lamella_visible"] is False
        assert attrs["lamella_changeable"] is False

    def test_mode_not_changeable(self, hass, mock_config_entry) -> None:
        """mode_changeable must be False when mode is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity._mode_changeable is False

    def test_no_preset_modes(self, hass, mock_config_entry) -> None:
        """No preset modes when mode is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity.preset_modes is None

    def test_no_fan_selector(self, hass, mock_config_entry) -> None:
        """No fan mode selector when strength is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity._attr_fan_modes == []

    def test_fan_mode_still_mapped(self, hass, mock_config_entry) -> None:
        """Fan state still maps PLC strings even when hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        # Strength UI hidden: fan_mode_map is not built; value passes through.
        assert entity.fan_mode == "Aus"

    def test_strength_not_changeable(self, hass, mock_config_entry) -> None:
        """strength_changeable gated by visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity._strength_changeable is False

    def test_lamella_not_changeable(self, hass, mock_config_entry) -> None:
        """lamella_changeable gated by visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        assert entity._lamella_changeable is False

    def test_target_temp_still_works(self, hass, mock_config_entry) -> None:
        """Target temperature feature is independent of mode visibility."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        feat = entity.supported_features
        assert feat & ClimateEntityFeature.TARGET_TEMPERATURE

    def test_set_hvac_mode_raises(self, hass, mock_config_entry) -> None:
        """Setting HVAC mode raises when mode is hidden (not changeable)."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_set_hvac_mode(HVACMode.HEAT),
            )

    def test_set_fan_mode_raises_when_hidden(self, hass, mock_config_entry) -> None:
        """Setting fan mode raises when strength is hidden."""
        entity, _ = _make_climate(
            hass, mock_config_entry, "widgets/variants/widget-ac-mode-hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_fan_mode("heat"))


def _make_extended_entities(
    hass, entry: MockConfigEntry,
) -> dict[str, TcIotClimate]:
    """Create TcIotClimate entities from ac_extended.json (3 widgets)."""
    dev = build_device_from_multi_widget_fixture(
        MOCK_DEVICE_NAME, "widgets/variants/widget-ac-extended.json",
    )
    coord = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    return {
        wid: TcIotClimate(coord, MOCK_DEVICE_NAME, w)
        for wid, w in dev.widgets.items()
    }


class TestClimateExtendedVisibility:
    """Tests for mixed visible/changeable combos (ac_extended.json)."""

    def test_heizung_all_visible_changeable(self, hass, mock_config_entry) -> None:
        """stAC_Heizung: all three modes visible + changeable."""
        entities = _make_extended_entities(hass, mock_config_entry)
        e = entities["stAC_Heizung"]
        assert e._mode_visible is True
        assert e._mode_changeable is True
        assert e._strength_visible is True
        assert e._strength_changeable is True
        assert e._lamella_visible is True
        assert e._lamella_changeable is True
        feat = e.supported_features
        assert feat & ClimateEntityFeature.FAN_MODE
        assert feat & ClimateEntityFeature.SWING_MODE

    def test_klimaanlage_lamella_visible_not_changeable(
        self, hass, mock_config_entry,
    ) -> None:
        """stAC_Klimaanlage: lamella visible but not changeable → no SWING feature."""
        entities = _make_extended_entities(hass, mock_config_entry)
        e = entities["stAC_Klimaanlage"]
        assert e._lamella_visible is True
        assert e._lamella_changeable is False
        assert not (e.supported_features & ClimateEntityFeature.SWING_MODE)
        assert e.swing_mode == "auto"

    def test_sensor_only_mode_visible_not_changeable(
        self, hass, mock_config_entry,
    ) -> None:
        """stAC_Sensor_only: mode visible but not changeable → no TURN_ON/OFF."""
        entities = _make_extended_entities(hass, mock_config_entry)
        e = entities["stAC_Sensor_only"]
        assert e._mode_visible is True
        assert e._mode_changeable is False
        assert e._lamella_visible is False
        feat = e.supported_features
        assert not (feat & ClimateEntityFeature.TURN_ON)
        assert not (feat & ClimateEntityFeature.TURN_OFF)

    def test_sensor_only_extra_attrs(self, hass, mock_config_entry) -> None:
        """stAC_Sensor_only: extra_state_attributes reflect mixed state."""
        entities = _make_extended_entities(hass, mock_config_entry)
        attrs = entities["stAC_Sensor_only"].extra_state_attributes
        assert attrs["mode_visible"] is True
        assert attrs["mode_changeable"] is False
        assert attrs["strength_visible"] is True
        assert attrs["strength_changeable"] is False
        assert attrs["lamella_visible"] is False
        assert attrs["lamella_changeable"] is False
