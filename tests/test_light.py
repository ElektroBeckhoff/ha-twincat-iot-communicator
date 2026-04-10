"""Tests for TwinCAT IoT Communicator light platform."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.components.twincat_iot_communicator.const import (
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
    WIDGET_TYPE_LIGHTING,
    WIDGET_TYPE_RGBW,
    WIDGET_TYPE_RGBW_EL2564,
)
from homeassistant.components.twincat_iot_communicator.light import (
    EL2564_PLC_MAX,
    TcIotLight,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


DEVICE_NAME = "TestDevice"


def _make_light(
    hass, entry: MockConfigEntry, fixture: str
) -> tuple[TcIotLight, MagicMock]:
    """Create a TcIotLight from a fixture and return (entity, coordinator)."""
    dev = build_device_with_widgets(DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotLight(coordinator, DEVICE_NAME, widget)
    return entity, coordinator


class TestLightingWidget:
    """Tests for the standard Lighting widget."""

    def test_setup(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        assert entity.is_on is False
        assert entity.brightness == 0
        assert ColorMode.BRIGHTNESS in entity.supported_color_modes

    def test_turn_on(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        hass.loop.run_until_complete(entity.async_turn_on())
        coord.async_send_command.assert_awaited_once()
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_ON}"] is True

    def test_turn_on_brightness(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        entity.widget.values[VAL_LIGHT_ON] = True
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert f"{entity.widget.path}.{VAL_LIGHT_LEVEL}" in cmd
        plc_val = cmd[f"{entity.widget.path}.{VAL_LIGHT_LEVEL}"]
        assert 45 <= plc_val <= 55

    def test_turn_off(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        hass.loop.run_until_complete(entity.async_turn_off())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_ON}"] is False

    def test_effects(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        assert entity.effect_list is not None
        assert len(entity.effect_list) > 0
        assert "Raumszenen" in entity.effect_list

    def test_set_effect(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        entity.widget.values[VAL_LIGHT_ON] = True
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_EFFECT: "Szene 1"})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE}"] == "Szene 1"


class TestRGBWWidget:
    """Tests for the RGBW widget with HS color support (no white slider)."""

    def test_color_modes_hs_only(self, hass, mock_config_entry) -> None:
        """Fixture has LightWhiteSliderVisible=false -> HS only, no WHITE."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        assert ColorMode.HS in entity.supported_color_modes
        assert ColorMode.WHITE not in entity.supported_color_modes
        assert ColorMode.RGBW not in entity.supported_color_modes

    def test_hs_color(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        entity.widget.values[VAL_LIGHT_HUE] = 180
        entity.widget.values[VAL_LIGHT_SATURATION] = 75
        assert entity.hs_color == (180.0, 75.0)

    def test_turn_on_hs(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        entity.widget.values[VAL_LIGHT_ON] = True
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_HS_COLOR: (240.0, 80.0)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_HUE}"] == 240
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_SATURATION}"] == 80

    def test_no_rgbw_color(self, hass, mock_config_entry) -> None:
        """Non-EL2564 should never expose rgbw_color."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        assert entity.rgbw_color is None

    def test_color_turns_on_when_off(self, hass, mock_config_entry) -> None:
        """Color command on an off light should also send bLight=true."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        assert entity.is_on is False
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_HS_COLOR: (120.0, 50.0)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_ON}"] is True

    def test_color_no_bon_when_already_on(self, hass, mock_config_entry) -> None:
        """Color command on an already-on light should NOT resend bLight."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        entity.widget.values[VAL_LIGHT_ON] = True
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_HS_COLOR: (120.0, 50.0)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert f"{entity.widget.path}.{VAL_LIGHT_ON}" not in cmd


class TestRGBWWithWhite:
    """Tests for RGBW widget with white slider — uses ColorMode.RGBW."""

    def test_color_modes_rgbw(self, hass, mock_config_entry) -> None:
        """Widget with HS + white -> RGBW mode (not HS)."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        assert ColorMode.RGBW in entity.supported_color_modes
        assert ColorMode.COLOR_TEMP in entity.supported_color_modes
        assert ColorMode.HS not in entity.supported_color_modes

    def test_default_color_mode_is_rgbw(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        assert entity.color_mode == ColorMode.RGBW

    def test_rgbw_color_reads_hs_and_white(self, hass, mock_config_entry) -> None:
        """rgbw_color reconstructs from PLC HS + nWhite."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        entity.widget.values[VAL_LIGHT_HUE] = 0
        entity.widget.values[VAL_LIGHT_SATURATION] = 100
        entity.widget.values[VAL_LIGHT_WHITE] = 50
        color = entity.rgbw_color
        assert color is not None
        assert color[0] == 255  # red
        assert color[1] == 0    # green
        assert color[2] == 0    # blue
        assert color[3] == 128  # white 50% -> ~128

    def test_turn_on_rgbw(self, hass, mock_config_entry) -> None:
        """ATTR_RGBW_COLOR converts RGB->HS and scales W."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_RGBW_COLOR: (255, 0, 0, 128)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        path = entity.widget.path
        assert cmd[f"{path}.{VAL_LIGHT_HUE}"] == 0
        assert cmd[f"{path}.{VAL_LIGHT_SATURATION}"] == 100
        assert cmd[f"{path}.{VAL_LIGHT_WHITE}"] == 50  # 128/255*100 ≈ 50
        assert entity.color_mode == ColorMode.RGBW

    def test_turn_on_color_temp(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_COLOR_TEMP_KELVIN: 4000})
        )
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LIGHT_COLOR_TEMP}"] == 4000
        assert entity.color_mode == ColorMode.COLOR_TEMP

    def test_brightness_always_sends_nlight(self, hass, mock_config_entry) -> None:
        """ATTR_BRIGHTNESS always controls nLight."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        for mode in (ColorMode.RGBW, ColorMode.COLOR_TEMP):
            entity._active_color_mode = mode
            coord.async_send_command.reset_mock()
            hass.loop.run_until_complete(
                entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
            )
            cmd = coord.async_send_command.call_args[0][1]
            assert f"{entity.widget.path}.{VAL_LIGHT_LEVEL}" in cmd

    def test_brightness_reads_nlight(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        entity.widget.values[VAL_LIGHT_LEVEL] = 50
        assert 125 <= entity.brightness <= 130

    def test_mode_switches_rgbw_to_ct(self, hass, mock_config_entry) -> None:
        """Test sequential mode switching RGBW -> CT -> RGBW."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        assert entity.color_mode == ColorMode.RGBW

        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_COLOR_TEMP_KELVIN: 3000})
        )
        assert entity.color_mode == ColorMode.COLOR_TEMP

        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_RGBW_COLOR: (0, 255, 0, 0)})
        )
        assert entity.color_mode == ColorMode.RGBW

    def test_state_write_only_on_mode_change(self, hass, mock_config_entry) -> None:
        """async_write_ha_state only fires when color_mode actually changes."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_white.json")
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        entity._active_color_mode = ColorMode.RGBW
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_BRIGHTNESS: 128})
        )
        entity.async_write_ha_state.assert_not_called()

        entity.async_write_ha_state.reset_mock()
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_COLOR_TEMP_KELVIN: 4000})
        )
        entity.async_write_ha_state.assert_called_once()


class TestRGBWEL2564Widget:
    """Tests for the RGBWEL2564 widget (unchanged — real RGBW hardware)."""

    def test_color_mode_rgbw(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_el2564.json")
        assert entity.supported_color_modes == {ColorMode.RGBW}
        assert entity.color_mode == ColorMode.RGBW

    def test_rgbw_color_scaling(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_el2564.json")
        color = entity.rgbw_color
        assert color is not None
        assert color[2] == 255  # blue = max
        assert color[0] == 0   # red = 0

    def test_turn_on_rgbw(self, hass, mock_config_entry) -> None:
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_el2564.json")
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_RGBW_COLOR: (255, 0, 128, 64)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        path = entity.widget.path
        assert cmd[f"{path}.{VAL_LED_RED}"] == EL2564_PLC_MAX
        assert cmd[f"{path}.{VAL_LED_GREEN}"] == 0
        assert 16000 <= cmd[f"{path}.{VAL_LED_BLUE}"] <= 17000
        assert 8000 <= cmd[f"{path}.{VAL_LED_WHITE}"] <= 8500

    def test_is_on(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_el2564.json")
        assert entity.is_on is True


class TestRGBWFuture:
    """Tests for future RGBW widget with native RGB fields + nColorMode."""

    def test_color_mode_hs(self, hass, mock_config_entry) -> None:
        """Future fixture has palette=RGB but no white -> HS mode."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        assert ColorMode.HS in entity.supported_color_modes
        assert entity._native_rgb is True
        assert entity._plc_reports_color_mode is True

    def test_turn_on_no_color_mode_written(self, hass, mock_config_entry) -> None:
        """nColorMode is read-only — PLC sets it based on written fields."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        path = entity.widget.path
        assert cmd[f"{path}.{VAL_LIGHT_ON}"] is True
        assert f"{path}.{VAL_LIGHT_COLOR_MODE}" not in cmd

    def test_hs_sends_rgb_fields(self, hass, mock_config_entry) -> None:
        """palette_mode=RGB → HS color is converted and sent as nRed/nGreen/nBlue."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_HS_COLOR: (0.0, 100.0)})  # pure red
        )
        cmd = coord.async_send_command.call_args[0][1]
        path = entity.widget.path
        assert cmd[f"{path}.{VAL_LIGHT_RED}"] == 255
        assert cmd[f"{path}.{VAL_LIGHT_GREEN}"] == 0
        assert cmd[f"{path}.{VAL_LIGHT_BLUE}"] == 0
        assert f"{path}.{VAL_LIGHT_HUE}" not in cmd
        assert f"{path}.{VAL_LIGHT_SATURATION}" not in cmd

    def test_hs_color_reads_hs_directly(self, hass, mock_config_entry) -> None:
        """PLC always sends both HS and RGB — hs_color reads nHueValue/nSaturation."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        entity.widget.values[VAL_LIGHT_HUE] = 120
        entity.widget.values[VAL_LIGHT_SATURATION] = 100
        hs = entity.hs_color
        assert hs is not None
        assert hs == (120.0, 100.0)

    def test_rgbw_native_sends_rgb_fields(self, hass, mock_config_entry) -> None:
        """When native RGB + white available, RGBW sends nRed/nGreen/nBlue directly."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        entity.widget.metadata.raw["iot.LightWhiteSliderVisible"] = "true"
        entity._sync_metadata()
        hass.loop.run_until_complete(
            entity.async_turn_on(**{ATTR_RGBW_COLOR: (200, 100, 50, 128)})
        )
        cmd = coord.async_send_command.call_args[0][1]
        path = entity.widget.path
        assert cmd[f"{path}.{VAL_LIGHT_RED}"] == 200
        assert cmd[f"{path}.{VAL_LIGHT_GREEN}"] == 100
        assert cmd[f"{path}.{VAL_LIGHT_BLUE}"] == 50
        assert cmd[f"{path}.{VAL_LIGHT_WHITE}"] == 50  # 128/255*100 ≈ 50

    def test_rgbw_native_reads_rgb_fields(self, hass, mock_config_entry) -> None:
        """rgbw_color reads nRed/nGreen/nBlue directly when native RGB."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        entity.widget.metadata.raw["iot.LightWhiteSliderVisible"] = "true"
        entity._sync_metadata()
        entity._active_color_mode = ColorMode.RGBW
        entity.widget.values[VAL_LIGHT_RED] = 200
        entity.widget.values[VAL_LIGHT_GREEN] = 100
        entity.widget.values[VAL_LIGHT_BLUE] = 50
        entity.widget.values[VAL_LIGHT_WHITE] = 50
        color = entity.rgbw_color
        assert color == (200, 100, 50, 128)  # white 50% -> ~128

    def test_legacy_widget_no_color_mode_field(self, hass, mock_config_entry) -> None:
        """Legacy widget (no nColorMode) should NOT send nColorMode."""
        entity, coord = _make_light(hass, mock_config_entry, "widgets/rgbw.json")
        assert entity._plc_reports_color_mode is False
        hass.loop.run_until_complete(entity.async_turn_on())
        cmd = coord.async_send_command.call_args[0][1]
        assert VAL_LIGHT_COLOR_MODE not in str(cmd)

    def test_non_numeric_color_mode_returns_none(self, hass, mock_config_entry) -> None:
        """Non-numeric nColorMode from PLC should not crash, returns None."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        entity.widget.values[VAL_LIGHT_COLOR_MODE] = "invalid"
        assert entity.color_mode is not None  # falls back to default, not crash

    def test_empty_string_color_mode_no_crash(self, hass, mock_config_entry) -> None:
        """Empty string nColorMode from PLC should not crash."""
        entity, _ = _make_light(hass, mock_config_entry, "widgets/rgbw_future.json")
        entity.widget.values[VAL_LIGHT_COLOR_MODE] = ""
        assert entity.color_mode is not None


class TestEffectValidation:
    """Tests for effect input validation."""

    def test_invalid_effect_raises(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        entity.widget.values[VAL_LIGHT_ON] = True
        assert entity.effect_list is not None
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_turn_on(**{ATTR_EFFECT: "NonExistentMode"})
            )


class TestReadOnlyLight:
    """Test read-only guard."""

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        entity, _ = _make_light(hass, mock_config_entry, "widgets/lighting.json")
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_turn_on())


class TestLightModeHidden:
    """Tests for Lighting widget with LightModeVisible=false."""

    def test_effect_list_empty(self, hass, mock_config_entry) -> None:
        """No effects when mode is hidden."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        assert entity.effect_list == []

    def test_mode_not_changeable(self, hass, mock_config_entry) -> None:
        """mode_changeable gated by visibility."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        assert entity._mode_changeable is False

    def test_no_effect_feature(self, hass, mock_config_entry) -> None:
        """EFFECT feature must not be set when mode hidden."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        assert not (entity.supported_features & LightEntityFeature.EFFECT)

    def test_brightness_still_works(self, hass, mock_config_entry) -> None:
        """Brightness/color modes are independent of mode visibility."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        assert ColorMode.BRIGHTNESS in entity.supported_color_modes

    def test_effect_via_turn_on_raises(self, hass, mock_config_entry) -> None:
        """Setting effect via turn_on raises when mode is hidden."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(
                entity.async_turn_on(**{ATTR_EFFECT: "Szene 1"}),
            )

    def test_effect_still_reads_current(self, hass, mock_config_entry) -> None:
        """effect property still returns current PLC value for state display."""
        entity, _ = _make_light(
            hass, mock_config_entry, "widgets/lighting_mode_hidden.json",
        )
        assert entity.effect == "Raumszenen"
