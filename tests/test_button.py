"""Tests for TwinCAT IoT Communicator button platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.button import (
    TcIotChargingReserveButton,
    TcIotChargingStartButton,
    TcIotChargingStopButton,
    _create_buttons,
)
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_CHARGING_RESERVE,
    VAL_CHARGING_START,
    VAL_CHARGING_STOP,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import MOCK_DEVICE_NAME, build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


def _make_charging_buttons(
    hass, entry: MockConfigEntry,
) -> tuple[
    TcIotChargingStartButton,
    TcIotChargingStopButton,
    TcIotChargingReserveButton,
    MagicMock,
]:
    """Create start, stop, and reserve buttons from the ChargingStation fixture."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    buttons = _create_buttons(coordinator, MOCK_DEVICE_NAME, widget)
    start = next(b for b in buttons if isinstance(b, TcIotChargingStartButton))
    stop = next(b for b in buttons if isinstance(b, TcIotChargingStopButton))
    reserve = next(b for b in buttons if isinstance(b, TcIotChargingReserveButton))
    return start, stop, reserve, coordinator


class TestChargingButtons:
    """Tests for ChargingStation start/stop buttons."""

    def test_creates_three_buttons_with_reserve(self, hass, mock_config_entry) -> None:
        """Test factory creates three buttons when reserve is visible."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        buttons = _create_buttons(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(buttons) == 3

    def test_creates_two_buttons_without_reserve(self, hass, mock_config_entry) -> None:
        """Test factory creates two buttons when reserve is hidden."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-charging-station.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.ChargingStationReserveVisible"] = "false"
        buttons = _create_buttons(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(buttons) == 2

    def test_start_button_name(self, hass, mock_config_entry) -> None:
        """Test start button has correct translation key."""
        start, _, _, _ = _make_charging_buttons(hass, mock_config_entry)
        assert start.translation_key == "charging_start"

    def test_stop_button_name(self, hass, mock_config_entry) -> None:
        """Test stop button has correct translation key."""
        _, stop, _, _ = _make_charging_buttons(hass, mock_config_entry)
        assert stop.translation_key == "charging_stop"

    def test_reserve_button_name(self, hass, mock_config_entry) -> None:
        """Test reserve button has correct translation key."""
        _, _, reserve, _ = _make_charging_buttons(hass, mock_config_entry)
        assert reserve.translation_key == "charging_reserve"

    def test_start_sends_command(self, hass, mock_config_entry) -> None:
        """Test pressing start sends bStartCharging=true."""
        start, _, _, coord = _make_charging_buttons(hass, mock_config_entry)
        hass.loop.run_until_complete(start.async_press())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{start.widget.path}.{VAL_CHARGING_START}"] is True

    def test_stop_sends_command(self, hass, mock_config_entry) -> None:
        """Test pressing stop sends bStopCharging=true."""
        _, stop, _, coord = _make_charging_buttons(hass, mock_config_entry)
        hass.loop.run_until_complete(stop.async_press())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{stop.widget.path}.{VAL_CHARGING_STOP}"] is True

    def test_reserve_sends_command(self, hass, mock_config_entry) -> None:
        """Test pressing reserve sends bReserveCharging=true."""
        _, _, reserve, coord = _make_charging_buttons(hass, mock_config_entry)
        hass.loop.run_until_complete(reserve.async_press())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{reserve.widget.path}.{VAL_CHARGING_RESERVE}"] is True

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test pressing a read-only button raises an error."""
        start, _, _, _ = _make_charging_buttons(hass, mock_config_entry)
        start.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(start.async_press())

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all buttons have distinct unique IDs."""
        start, stop, reserve, _ = _make_charging_buttons(hass, mock_config_entry)
        ids = {start.unique_id, stop.unique_id, reserve.unique_id}
        assert len(ids) == 3
        assert start.unique_id.endswith("_start")
        assert stop.unique_id.endswith("_stop")
        assert reserve.unique_id.endswith("_reserve")
