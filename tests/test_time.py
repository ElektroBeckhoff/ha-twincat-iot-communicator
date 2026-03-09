"""Tests for TwinCAT IoT Communicator time platform."""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    VAL_TIMESWITCH_END_TIME,
    VAL_TIMESWITCH_START_TIME,
)
from homeassistant.components.twincat_iot_communicator.time import (
    TcIotTimeSwitchTime,
    _create_time_entities,
    _ms_to_time,
    _time_to_iso,
    _time_to_ms,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry

DEVICE_NAME = "TestDevice"


def _make_time_entities(
    hass, entry: MockConfigEntry,
) -> tuple[list[TcIotTimeSwitchTime], MagicMock]:
    """Create time entities from the TimeSwitch fixture."""
    dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entities = _create_time_entities(coordinator, DEVICE_NAME, widget)
    return entities, coordinator


class TestTimeConversions:
    """Tests for ms <-> time conversion helpers."""

    def test_ms_to_time_midnight(self) -> None:
        """Test converting 0 ms to midnight."""
        assert _ms_to_time(0) == time(0, 0, 0)

    def test_ms_to_time_noon(self) -> None:
        """Test converting 12h ms to noon."""
        assert _ms_to_time(12 * 3_600_000) == time(12, 0, 0)

    def test_ms_to_time_with_minutes_seconds(self) -> None:
        """Test converting ms including minutes and seconds."""
        ms = 8 * 3_600_000 + 30 * 60_000 + 15 * 1000
        assert _ms_to_time(ms) == time(8, 30, 15)

    def test_time_to_ms_midnight(self) -> None:
        """Test converting midnight to 0 ms."""
        assert _time_to_ms(time(0, 0, 0)) == 0

    def test_time_to_ms_roundtrip(self) -> None:
        """Test roundtrip conversion."""
        t = time(14, 45, 30)
        assert _ms_to_time(_time_to_ms(t)) == t

    def test_time_to_iso(self) -> None:
        """Test ISO format for PLC Rx channel."""
        assert _time_to_iso(time(17, 45, 0)) == "1970-01-01T17:45:00Z"

    def test_time_to_iso_midnight(self) -> None:
        """Test ISO format for midnight."""
        assert _time_to_iso(time(0, 0, 0)) == "1970-01-01T00:00:00Z"


class TestTimeSwitchTime:
    """Tests for TimeSwitch time entities."""

    def test_creates_two_time_entities(self, hass, mock_config_entry) -> None:
        """Test factory creates start and end time entities."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        assert len(entities) == 2

    def test_start_time_name(self, hass, mock_config_entry) -> None:
        """Test start time entity has correct name."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        start = next(e for e in entities if "start" in e.unique_id)
        assert start.translation_key == "start_time"

    def test_end_time_name(self, hass, mock_config_entry) -> None:
        """Test end time entity has correct name."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        end = next(e for e in entities if "end" in e.unique_id)
        assert end.translation_key == "end_time"

    def test_native_value_zero(self, hass, mock_config_entry) -> None:
        """Test native_value returns midnight for 0."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        start = entities[0]
        assert start.native_value == time(0, 0, 0)

    def test_native_value_none(self, hass, mock_config_entry) -> None:
        """Test native_value returns None when value missing."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        start = entities[0]
        del start.widget.values[VAL_TIMESWITCH_START_TIME]
        assert start.native_value is None

    def test_set_value_sends_command(self, hass, mock_config_entry) -> None:
        """Test async_set_value sends ISO string to PLC."""
        entities, coord = _make_time_entities(hass, mock_config_entry)
        start = entities[0]
        t = time(17, 45, 0)
        hass.loop.run_until_complete(start.async_set_value(t))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{start.widget.path}.{VAL_TIMESWITCH_START_TIME}"] == "1970-01-01T17:45:00Z"

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test async_set_value raises for read-only widget."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        start = entities[0]
        start.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(start.async_set_value(time(12, 0, 0)))

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test start and end time have distinct unique IDs."""
        entities, _ = _make_time_entities(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 2

    def test_visibility_hidden(self, hass, mock_config_entry) -> None:
        """Test no entities created when visibility is false."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchStartTimeVisible"] = "false"
        widget.metadata.raw["iot.TimeSwitchEndTimeVisible"] = "false"
        entities = _create_time_entities(coordinator, DEVICE_NAME, widget)
        assert len(entities) == 0
