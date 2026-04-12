"""Tests for TwinCAT IoT Communicator base entity (TcIotEntity)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    META_VALUE_TEXT_COLOR,
    META_VALUE_TEXT_COLOR_DARK,
    WIDGET_TYPE_PLUG,
)
from homeassistant.components.twincat_iot_communicator.entity import TcIotEntity
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import (
    MOCK_DEVICE_NAME,
    attach_entity_to_hass,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry


def _make_entity(
    hass,
    entry: MockConfigEntry,
    *,
    values: dict | None = None,
    raw_meta: dict | None = None,
    read_only: bool = False,
    widget_type: str = WIDGET_TYPE_PLUG,
) -> tuple[TcIotEntity, MagicMock, DeviceContext]:
    """Create a bare TcIotEntity with configurable widget data."""
    meta = WidgetMetaData(
        display_name="Test Widget",
        widget_type=widget_type,
        read_only=read_only,
        raw=raw_meta or {},
    )
    widget = WidgetData(
        widget_id="stTest.widget",
        path="stTest.widget",
        metadata=meta,
        values=values if values is not None else {"bOn": True},
        friendly_path="Test Widget",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets["stTest.widget"] = widget
    dev.known_widget_paths.add("stTest.widget")
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotEntity(coordinator, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "switch")
    return entity, coordinator, dev


class TestSendOptimisticRollback:
    """Tests for _send_optimistic rollback on HomeAssistantError."""

    async def test_rollback_on_send_failure(self, hass, mock_config_entry) -> None:
        """Widget values must be restored when async_send_command raises."""
        entity, coord, _ = _make_entity(
            hass, mock_config_entry, values={"bOn": False},
        )
        coord.async_send_command = AsyncMock(
            side_effect=HomeAssistantError("MQTT fail"),
        )

        with pytest.raises(HomeAssistantError):
            await entity._send_optimistic({"stTest.widget.bOn": True})

        assert entity.widget.values["bOn"] is False
        assert entity._optimistic_values == {}
        assert entity._optimistic_until == 0.0

    async def test_rollback_removes_previously_absent_key(self, hass, mock_config_entry) -> None:
        """Keys that were None before the command must be removed on rollback."""
        entity, coord, _ = _make_entity(
            hass, mock_config_entry, values={"placeholder": True},
        )
        coord.async_send_command = AsyncMock(
            side_effect=HomeAssistantError("fail"),
        )

        with pytest.raises(HomeAssistantError):
            await entity._send_optimistic({"stTest.widget.bOn": True})

        assert "bOn" not in entity.widget.values

    def test_success_preserves_optimistic_values(self, hass, mock_config_entry) -> None:
        """On success, optimistic values remain applied with a cooldown."""
        entity, coord, _ = _make_entity(
            hass, mock_config_entry, values={"bOn": False},
        )

        hass.loop.run_until_complete(
            entity._send_optimistic({"stTest.widget.bOn": True})
        )

        assert entity.widget.values["bOn"] is True
        assert entity._optimistic_values == {"bOn": True}
        assert entity._optimistic_until > time.monotonic()


class TestOnWidgetUpdateOptimistic:
    """Tests for _on_widget_update with optimistic overlay."""

    def test_overlay_during_cooldown(self, hass, mock_config_entry) -> None:
        """Optimistic values overwrite incoming widget data during cooldown."""
        entity, _, _ = _make_entity(
            hass, mock_config_entry, values={"bOn": True},
        )
        entity._optimistic_values = {"bOn": True}
        entity._optimistic_until = time.monotonic() + 10.0

        incoming = WidgetData(
            widget_id="stTest.widget",
            path="stTest.widget",
            metadata=entity.widget.metadata,
            values={"bOn": False},
            friendly_path="Test Widget",
        )
        entity._on_widget_update(incoming)

        assert entity.widget.values["bOn"] is True

    def test_overlay_cleared_after_cooldown(self, hass, mock_config_entry) -> None:
        """After cooldown, incoming values are used as-is."""
        entity, _, _ = _make_entity(
            hass, mock_config_entry, values={"bOn": True},
        )
        entity._optimistic_values = {"bOn": True}
        entity._optimistic_until = time.monotonic() - 1.0

        incoming = WidgetData(
            widget_id="stTest.widget",
            path="stTest.widget",
            metadata=entity.widget.metadata,
            values={"bOn": False},
            friendly_path="Test Widget",
        )
        entity._on_widget_update(incoming)

        assert entity.widget.values["bOn"] is False
        assert entity._optimistic_values == {}


class TestSendOptimisticExtra:
    """Tests for the optimistic_extra parameter."""

    def test_extras_applied_but_not_sent(self, hass, mock_config_entry) -> None:
        """Extra fields appear in widget.values but not in the send command."""
        entity, coord, _ = _make_entity(
            hass, mock_config_entry, values={"bOn": False, "nHue": 0},
        )

        hass.loop.run_until_complete(
            entity._send_optimistic(
                {"stTest.widget.bOn": True},
                optimistic_extra={"nHue": 180},
            )
        )

        assert entity.widget.values["nHue"] == 180
        cmd = coord.async_send_command.call_args[0][1]
        assert "stTest.widget.nHue" not in cmd
        assert "stTest.widget.bOn" in cmd


class TestAvailableProperty:
    """Tests for TcIotEntity.available with all branches."""

    def test_available_normal(self, hass, mock_config_entry) -> None:
        """Entity is available when device is online and values are present."""
        entity, _, _ = _make_entity(hass, mock_config_entry)
        assert entity.available is True

    def test_unavailable_device_none(self, hass, mock_config_entry) -> None:
        """Entity is unavailable when get_device returns None."""
        entity, coord, _ = _make_entity(hass, mock_config_entry)
        coord.get_device = MagicMock(return_value=None)
        assert entity.available is False

    def test_unavailable_not_connected(self, hass, mock_config_entry) -> None:
        """Entity is unavailable when MQTT is disconnected."""
        entity, coord, _ = _make_entity(hass, mock_config_entry)
        coord.connected = False
        assert entity.available is False

    def test_unavailable_device_offline(self, hass, mock_config_entry) -> None:
        """Entity is unavailable when device is offline."""
        entity, _, dev = _make_entity(hass, mock_config_entry)
        dev.online = False
        assert entity.available is False

    def test_unavailable_stale_widget(self, hass, mock_config_entry) -> None:
        """Entity is unavailable when widget path is in stale set."""
        entity, _, dev = _make_entity(hass, mock_config_entry)
        dev.stale_widget_paths.add("stTest.widget")
        assert entity.available is False

    def test_unavailable_empty_values(self, hass, mock_config_entry) -> None:
        """Entity is unavailable when widget has no values."""
        entity, _, _ = _make_entity(hass, mock_config_entry, values={})
        # Widget with empty dict → bool({}) is False
        assert entity.available is False


class TestExtraStateAttributes:
    """Tests for extra_state_attributes including text color metadata."""

    def test_read_only_always_present(self, hass, mock_config_entry) -> None:
        """read_only key is always in extra_state_attributes."""
        entity, _, _ = _make_entity(hass, mock_config_entry)
        attrs = entity.extra_state_attributes
        assert "read_only" in attrs
        assert attrs["read_only"] is False

    def test_read_only_true(self, hass, mock_config_entry) -> None:
        """read_only reflects widget metadata."""
        entity, _, _ = _make_entity(hass, mock_config_entry, read_only=True)
        assert entity.extra_state_attributes["read_only"] is True

    def test_value_text_color(self, hass, mock_config_entry) -> None:
        """value_text_color is exposed when metadata contains it."""
        entity, _, _ = _make_entity(
            hass, mock_config_entry,
            raw_meta={META_VALUE_TEXT_COLOR: "#FF0000"},
        )
        attrs = entity.extra_state_attributes
        assert attrs["value_text_color"] == "#FF0000"
        assert "value_text_color_dark" not in attrs

    def test_value_text_color_dark(self, hass, mock_config_entry) -> None:
        """value_text_color_dark is exposed when metadata contains it."""
        entity, _, _ = _make_entity(
            hass, mock_config_entry,
            raw_meta={META_VALUE_TEXT_COLOR_DARK: "#00FF00"},
        )
        attrs = entity.extra_state_attributes
        assert attrs["value_text_color_dark"] == "#00FF00"
        assert "value_text_color" not in attrs

    def test_both_colors(self, hass, mock_config_entry) -> None:
        """Both text color attributes are exposed when both exist."""
        entity, _, _ = _make_entity(
            hass, mock_config_entry,
            raw_meta={
                META_VALUE_TEXT_COLOR: "#FF0000",
                META_VALUE_TEXT_COLOR_DARK: "#00FF00",
            },
        )
        attrs = entity.extra_state_attributes
        assert attrs["value_text_color"] == "#FF0000"
        assert attrs["value_text_color_dark"] == "#00FF00"

    def test_no_colors_when_absent(self, hass, mock_config_entry) -> None:
        """No color attributes when metadata has none."""
        entity, _, _ = _make_entity(hass, mock_config_entry)
        attrs = entity.extra_state_attributes
        assert "value_text_color" not in attrs
        assert "value_text_color_dark" not in attrs


class TestCheckReadOnly:
    """Tests for the _check_read_only guard."""

    def test_raises_when_read_only(self, hass, mock_config_entry) -> None:
        """_check_read_only raises ServiceValidationError."""
        entity, _, _ = _make_entity(hass, mock_config_entry, read_only=True)
        with pytest.raises(ServiceValidationError):
            entity._check_read_only()

    def test_passes_when_writable(self, hass, mock_config_entry) -> None:
        """_check_read_only does not raise for writable widgets."""
        entity, _, _ = _make_entity(hass, mock_config_entry, read_only=False)
        entity._check_read_only()


class TestSendOptimisticScalarPath:
    """Tests for _send_optimistic with scalar path (key == widget.path)."""

    def test_scalar_path_sets_value_key(self, hass, mock_config_entry) -> None:
        """When command key equals widget.path, it sets values['value']."""
        entity, coord, _ = _make_entity(
            hass, mock_config_entry, values={"value": 42},
        )

        hass.loop.run_until_complete(
            entity._send_optimistic({"stTest.widget": 99})
        )

        assert entity.widget.values["value"] == 99
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd["stTest.widget"] == 99
