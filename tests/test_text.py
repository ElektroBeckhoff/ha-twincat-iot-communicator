"""Tests for TwinCAT IoT Communicator text platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    DATATYPE_STRING,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.components.twincat_iot_communicator.text import (
    TcIotDatatypeArrayText,
    TcIotDatatypeText,
    _create_array_texts,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator, MOCK_DEVICE_NAME

from tests.common import MockConfigEntry


def _make_text(
    hass, entry: MockConfigEntry
) -> tuple[TcIotDatatypeText, MagicMock]:
    """Create a TcIotDatatypeText for testing."""
    meta = WidgetMetaData(display_name="Test Text", widget_type=DATATYPE_STRING)
    widget = WidgetData(
        widget_id="stScenes.sSTRING",
        path="stScenes.sSTRING",
        metadata=meta,
        values={"value": "Hello"},
        friendly_path="Test Text",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets["stScenes.sSTRING"] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotDatatypeText(coordinator, MOCK_DEVICE_NAME, widget)
    return entity, coordinator


class TestTextEntity:
    """Tests for the text entity."""

    def test_native_value(self, hass, mock_config_entry) -> None:
        """Test native value reads from widget values."""
        entity, _ = _make_text(hass, mock_config_entry)
        assert entity.native_value == "Hello"

    def test_set_value(self, hass, mock_config_entry) -> None:
        """Test set_value sends correct command."""
        entity, coord = _make_text(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_set_value("World"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[entity.widget.path] == "World"

    def test_set_value_truncated(self, hass, mock_config_entry) -> None:
        """Test value longer than 255 chars is truncated."""
        entity, coord = _make_text(hass, mock_config_entry)
        long_value = "A" * 300
        hass.loop.run_until_complete(entity.async_set_value(long_value))
        cmd = coord.async_send_command.call_args[0][1]
        assert len(cmd[entity.widget.path]) == 255

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test set_value raises for read-only widget."""
        entity, _ = _make_text(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_set_value("test"))

    def test_read_only_disabled_by_default(self, hass, mock_config_entry) -> None:
        """Test read-only STRING text is disabled in entity registry by default."""
        entity, _ = _make_text(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        ro = TcIotDatatypeText(entity.coordinator, MOCK_DEVICE_NAME, entity.widget)
        assert ro.entity_registry_enabled_default is False

    def test_writable_enabled_by_default(self, hass, mock_config_entry) -> None:
        """Test writable STRING text is enabled by default."""
        entity, _ = _make_text(hass, mock_config_entry)
        assert entity.entity_registry_enabled_default is True


# ── Array text tests ──────────────────────────────────────────────


def _make_array_texts(
    hass,
    entry: MockConfigEntry,
    *,
    values: list[str] | None = None,
) -> tuple[list[TcIotDatatypeArrayText], MagicMock]:
    """Create array text entities from the array_string fixture."""
    dev = build_device_with_widgets(
        MOCK_DEVICE_NAME, ["datatypes/array_string.json"]
    )
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    if values is not None:
        widget.values["value"] = values
    entities = _create_array_texts(coordinator, MOCK_DEVICE_NAME, widget)
    return entities, coordinator


class TestDatatypeArrayText:
    """Tests for PLC STRING array text entities."""

    def test_creates_correct_count(self, hass, mock_config_entry) -> None:
        """Test one entity per array element."""
        entities, _ = _make_array_texts(hass, mock_config_entry)
        assert len(entities) == 3

    def test_naming(self, hass, mock_config_entry) -> None:
        """Test entity names are bracket-indexed."""
        entities, _ = _make_array_texts(hass, mock_config_entry)
        assert [e.name for e in entities] == ["[0]", "[1]", "[2]"]

    def test_native_value(self, hass, mock_config_entry) -> None:
        """Test native values are correct."""
        entities, _ = _make_array_texts(hass, mock_config_entry)
        assert entities[0].native_value == "Hello"
        assert entities[1].native_value == "World"

    def test_bounds_check(self, hass, mock_config_entry) -> None:
        """Test out-of-bounds index returns None."""
        entities, _ = _make_array_texts(hass, mock_config_entry, values=["A"])
        entity = entities[0]
        entity.widget.values["value"] = []
        assert entity.native_value is None

    def test_unique_ids_differ(self, hass, mock_config_entry) -> None:
        """Test all unique IDs are distinct."""
        entities, _ = _make_array_texts(hass, mock_config_entry)
        ids = {e.unique_id for e in entities}
        assert len(ids) == 3

    def test_none_element_returns_none(self, hass, mock_config_entry) -> None:
        """Test that a None element in the array returns None."""
        entities, _ = _make_array_texts(
            hass, mock_config_entry, values=["Hello", None, "World"]
        )
        assert entities[0].native_value == "Hello"
        assert entities[1].native_value is None
        assert entities[2].native_value == "World"

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test writes are always blocked."""
        entities, _ = _make_array_texts(hass, mock_config_entry)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entities[0].async_set_value("new"))
