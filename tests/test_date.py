"""Tests for TwinCAT IoT Communicator date platform."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    VAL_TIMESWITCH_START_DATE,
)
from homeassistant.components.twincat_iot_communicator.date import (
    TcIotTimeSwitchDate,
    _create_date_entities,
    _date_to_epoch_seconds,
    _date_to_iso,
    _epoch_seconds_to_date,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry

DEVICE_NAME = "TestDevice"


def _make_date_entities(
    hass, entry: MockConfigEntry,
) -> tuple[list[TcIotTimeSwitchDate], MagicMock]:
    """Create date entities from the TimeSwitch fixture."""
    dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entities = _create_date_entities(coordinator, DEVICE_NAME, widget)
    return entities, coordinator


class TestDateConversions:
    """Tests for epoch-seconds <-> date conversion helpers."""

    def test_epoch_to_date_zero(self) -> None:
        """Test epoch 0 converts to 1970-01-01."""
        assert _epoch_seconds_to_date(0) == datetime.date(1970, 1, 1)

    def test_epoch_to_date_known(self) -> None:
        """Test a known date converts correctly."""
        assert _epoch_seconds_to_date(1_704_067_200) == datetime.date(2024, 1, 1)

    def test_date_to_epoch_zero(self) -> None:
        """Test 1970-01-01 converts to 0."""
        assert _date_to_epoch_seconds(datetime.date(1970, 1, 1)) == 0

    def test_roundtrip(self) -> None:
        """Test roundtrip conversion."""
        d = datetime.date(2026, 3, 7)
        assert _epoch_seconds_to_date(_date_to_epoch_seconds(d)) == d

    def test_date_to_iso(self) -> None:
        """Test ISO format for PLC Rx channel."""
        assert _date_to_iso(datetime.date(2027, 3, 1)) == "2027-03-01T00:00:00"

    def test_date_to_iso_epoch(self) -> None:
        """Test ISO format for epoch date."""
        assert _date_to_iso(datetime.date(1970, 1, 1)) == "1970-01-01T00:00:00"


class TestTimeSwitchDate:
    """Tests for TimeSwitch date entities."""

    def test_creates_two_date_entities(self, hass, mock_config_entry) -> None:
        """Test factory creates start and end date entities."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        assert len(entities) == 2

    def test_start_date_name(self, hass, mock_config_entry) -> None:
        """Test start date entity has correct name."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        start = next(e for e in entities if "start" in e.unique_id)
        assert start.name == "Start date"

    def test_end_date_name(self, hass, mock_config_entry) -> None:
        """Test end date entity has correct name."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        end = next(e for e in entities if "end" in e.unique_id)
        assert end.name == "End date"

    def test_native_value_zero(self, hass, mock_config_entry) -> None:
        """Test native_value returns 1970-01-01 for 0."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        start = entities[0]
        assert start.native_value == datetime.date(1970, 1, 1)

    def test_native_value_none(self, hass, mock_config_entry) -> None:
        """Test native_value returns None when value missing."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        start = entities[0]
        del start.widget.values[VAL_TIMESWITCH_START_DATE]
        assert start.native_value is None

    def test_set_value_sends_command(self, hass, mock_config_entry) -> None:
        """Test async_set_value sends ISO string to PLC."""
        entities, coord = _make_date_entities(hass, mock_config_entry)
        start = entities[0]
        d = datetime.date(2027, 3, 1)
        hass.loop.run_until_complete(start.async_set_value(d))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{start.widget.path}.{VAL_TIMESWITCH_START_DATE}"] == "2027-03-01T00:00:00"

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test async_set_value raises for read-only widget."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        start = entities[0]
        start.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(start.async_set_value(datetime.date(2026, 1, 1)))

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test start and end date have distinct unique IDs."""
        entities, _ = _make_date_entities(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 2

    def test_visibility_hidden(self, hass, mock_config_entry) -> None:
        """Test no entities created when visibility is false."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/timeswitch.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.TimeSwitchStartDateVisible"] = "false"
        widget.metadata.raw["iot.TimeSwitchEndDateVisible"] = "false"
        entities = _create_date_entities(coordinator, DEVICE_NAME, widget)
        assert len(entities) == 0
