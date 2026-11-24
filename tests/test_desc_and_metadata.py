"""Tests for the Desc topic, device permission and MetaData robustness."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.twincat_iot_communicator.const import (
    DESC_ONLINE,
    DESC_PERMITTED_USERS,
)
from custom_components.twincat_iot_communicator.coordinator import TcIotCoordinator
from custom_components.twincat_iot_communicator.models import DeviceContext, parse_metadata

from .conftest import MOCK_DEVICE_NAME, MOCK_ENTRY_DATA, load_fixture_json

DOMAIN = "twincat_iot_communicator"
_CALL_LATER = "custom_components.twincat_iot_communicator.coordinator.async_call_later"

# Values a JSON document can carry where the PLC sends a string.
NON_STRING_VALUES = [5, 1.5, True, None, ["x"], {"a": 1}]


def _make_coordinator(hass: HomeAssistant) -> TcIotCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA,
        unique_id="test",
        title="Test",
        version=2,
        minor_version=2,
    )
    coord = TcIotCoordinator(hass, entry)
    coord._username = "testuser"
    return coord


def _new_device() -> DeviceContext:
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    return dev


def _tx_msg(payload: dict[str, Any]) -> MagicMock:
    msg = MagicMock()
    msg.topic = f"IotApp.Sample/{MOCK_DEVICE_NAME}/TcIotCommunicator/Json/Tx/Data"
    msg.payload = json.dumps(payload).encode()
    return msg


# ── Desc topic ───────────────────────────────────────────────────────


class TestDescTopicBelongsToPlc:
    """The device status on ``.../TcIotCommunicator/Desc`` is published by the PLC only."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.coord = _make_coordinator(hass)
        self.coord._client = AsyncMock()
        self.dev = _new_device()
        self.dev.icon_name = "Lock"
        self.dev.permitted_users = "*"
        self.dev.desc_timestamp = "2026-03-01T10:00:00"
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev

    async def test_watchdog_expiry_marks_offline_locally_only(self) -> None:
        """A missed heartbeat is a local observation, not a new device status."""
        self.dev.desc_interval = 60.0
        self.dev.desc_count = 5

        self.coord._desc_watchdog_expired(self.dev)
        await self.hass.async_block_till_done()

        assert self.dev.online is False
        self.coord._client.publish.assert_not_called()

    async def test_next_desc_brings_device_back_online(self) -> None:
        self.dev.desc_interval = 60.0
        self.coord._desc_watchdog_expired(self.dev)
        await self.hass.async_block_till_done()

        self.coord._handle_desc(self.dev, {DESC_ONLINE: True})

        assert self.dev.online is True
        self.coord._client.publish.assert_not_called()


class TestWatchdogFollowsHeartbeatInterval:
    """``tHeartbeatInterval`` of the PLC is free; the timeout must exceed it."""

    @pytest.mark.parametrize("interval", [5.0, 60.0, 300.0, 600.0, 900.0, 3600.0])
    def test_timeout_is_longer_than_measured_interval(self, interval: float) -> None:
        dev = _new_device()
        dev.desc_interval = interval

        timeout = TcIotCoordinator._calc_desc_watchdog_timeout(dev)

        assert timeout > interval

    def test_slow_heartbeat_starts_watchdog_beyond_next_desc(
        self, hass: HomeAssistant,
    ) -> None:
        """A PLC with a 15 minute heartbeat is not marked offline between two Desc."""
        coord = _make_coordinator(hass)
        dev = _new_device()
        coord.devices[MOCK_DEVICE_NAME] = dev
        dev.desc_count = 2
        dev.last_desc_received = hass.loop.time() - 900.0

        with patch(_CALL_LATER) as call_later:
            coord._handle_desc(dev, {DESC_ONLINE: True})

        assert dev.desc_interval == pytest.approx(900.0, abs=1.0)
        delay = call_later.call_args.args[1]
        assert delay > 900.0


# ── device permission ────────────────────────────────────────────────


class TestDevicePermissionRestore:
    """Restored device permission recovers only what the denial made stale."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        self.coord = _make_coordinator(hass)
        self.data = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev
        self.coord._discover_widgets(
            self.dev, self.data["Values"], self.data["MetaData"],
        )

    def _deny(self) -> None:
        self.coord._handle_desc(
            self.dev, {DESC_ONLINE: True, DESC_PERMITTED_USERS: "admin_only"},
        )

    def _permit(self) -> None:
        self.coord._handle_desc(
            self.dev, {DESC_ONLINE: True, DESC_PERMITTED_USERS: "admin_only,testuser"},
        )

    def test_widget_missing_from_snapshot_stays_stale(self) -> None:
        """A widget the PLC no longer sends is not revived by the device permission."""
        self.dev.awaiting_full_snapshot = True
        self.dev.snapshot_accumulated_paths = self.dev.known_widget_paths - {"stPlug"}
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert self.dev.stale_widget_paths == {"stPlug"}

        self._deny()
        assert self.dev.stale_widget_paths == self.dev.known_widget_paths
        self._permit()

        assert self.dev.stale_widget_paths == {"stPlug"}

    def test_widget_denied_by_own_permitted_users_stays_stale(self) -> None:
        meta = dict(self.data["MetaData"])
        meta["stLighting"] = {**meta["stLighting"], "iot.PermittedUsers": "admin_only"}
        self.coord._discover_widgets(self.dev, self.data["Values"], meta)
        assert self.dev.stale_widget_paths == {"stLighting"}

        self._deny()
        self._permit()

        assert self.dev.stale_widget_paths == {"stLighting"}

    def test_widgets_denied_by_device_are_recovered(self) -> None:
        self._deny()
        assert self.dev.stale_widget_paths == self.dev.known_widget_paths
        self._permit()
        assert self.dev.stale_widget_paths == set()

    def test_repeated_denied_desc_then_restore(self) -> None:
        """The heartbeat repeats the denying Desc; the restore still recovers all."""
        self._deny()
        self._deny()
        self._permit()
        assert self.dev.stale_widget_paths == set()

    def test_listeners_notified_for_recovered_widgets_only(self) -> None:
        self.dev.stale_widget_paths.add("stPlug")
        self._deny()
        plug = MagicMock()
        light = MagicMock()
        self.coord._listeners[f"{MOCK_DEVICE_NAME}/stPlug"] = [plug]
        self.coord._listeners[f"{MOCK_DEVICE_NAME}/stLighting"] = [light]

        self._permit()

        plug.assert_not_called()
        light.assert_called_once()


# ── non-string MetaData values ───────────────────────────────────────


def _views_payload(room_meta: dict[str, Any], plug_meta: dict[str, Any]) -> dict[str, Any]:
    """A view with one widget next to a second, well-formed widget."""
    return {
        "Values": {
            "stRoom": {"stPlug": {"sDisplayName": "", "bOn": True}},
            "stOther": {"sDisplayName": "", "bOn": False},
            "fTemp": 21.5,
            "aTemps": [1.0, 2.0],
        },
        "MetaData": {
            "stRoom": room_meta,
            "stRoom.stPlug": {"iot.WidgetType": "Plug", **plug_meta},
            "stOther": {"iot.DisplayName": "Other", "iot.WidgetType": "Plug"},
            "fTemp": {"iot.DisplayName": "Temp", "iot.Unit": "°C"},
            "aTemps": {"iot.DisplayName": "Temps"},
        },
    }


class TestNonStringMetadata:
    """One malformed MetaData value must not discard the whole message."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        self.coord = _make_coordinator(hass)
        self.dev = _new_device()
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev

    def _discover(self, payload: dict[str, Any]) -> None:
        self.coord._discover_widgets(self.dev, payload["Values"], payload["MetaData"])

    def _assert_all_discovered(self) -> None:
        assert set(self.dev.widgets) == {"stRoom.stPlug", "stOther", "fTemp", "aTemps"}
        for widget in self.dev.widgets.values():
            assert isinstance(widget.metadata.display_name, str)
            assert isinstance(widget.metadata.unit, str)
            assert isinstance(widget.metadata.widget_type, str)
            assert isinstance(widget.friendly_path, str)
        for view in self.dev.views.values():
            assert isinstance(view.display_name, str)
            assert isinstance(view.icon, str)

    @pytest.mark.parametrize("bad", NON_STRING_VALUES)
    def test_widget_display_name(self, bad: Any) -> None:
        self._discover(_views_payload({"iot.DisplayName": "Room"}, {"iot.DisplayName": bad}))
        self._assert_all_discovered()

    @pytest.mark.parametrize("bad", NON_STRING_VALUES)
    def test_view_display_name(self, bad: Any) -> None:
        self._discover(_views_payload({"iot.DisplayName": bad}, {"iot.DisplayName": "Plug"}))
        self._assert_all_discovered()

    @pytest.mark.parametrize("bad", NON_STRING_VALUES)
    def test_view_icon(self, bad: Any) -> None:
        self._discover(
            _views_payload(
                {"iot.DisplayName": "Room", "iot.NestedStructIcon": bad},
                {"iot.DisplayName": "Plug"},
            )
        )
        self._assert_all_discovered()

    @pytest.mark.parametrize("bad", NON_STRING_VALUES)
    def test_datatype_and_array_display_name_and_unit(self, bad: Any) -> None:
        payload = _views_payload({"iot.DisplayName": "Room"}, {"iot.DisplayName": "Plug"})
        payload["MetaData"]["fTemp"] = {"iot.DisplayName": bad, "iot.Unit": bad}
        payload["MetaData"]["aTemps"] = {"iot.DisplayName": bad, "iot.Unit": bad}
        self._discover(payload)
        assert {"stRoom.stPlug", "stOther"} <= set(self.dev.widgets)
        for widget in self.dev.widgets.values():
            assert isinstance(widget.metadata.display_name, str)
            assert isinstance(widget.metadata.unit, str)
            assert isinstance(widget.friendly_path, str)

    @pytest.mark.parametrize("bad", NON_STRING_VALUES)
    def test_widget_type(self, bad: Any) -> None:
        """A widget with a malformed type is skipped, its neighbours are kept."""
        payload = _views_payload({"iot.DisplayName": "Room"}, {"iot.DisplayName": "Plug"})
        payload["MetaData"]["stRoom.stPlug"]["iot.WidgetType"] = bad
        self._discover(payload)
        assert {"stOther", "fTemp", "aTemps"} <= set(self.dev.widgets)

    async def test_message_with_malformed_entry_is_processed(self) -> None:
        payload = _views_payload({"iot.DisplayName": 5}, {"iot.DisplayName": 7})
        await self.coord._async_dispatch_message(_tx_msg(payload))
        self._assert_all_discovered()

    def test_string_values_are_unchanged(self) -> None:
        meta = parse_metadata(
            {"iot.DisplayName": "Küche", "iot.Unit": "°C", "iot.WidgetType": "Plug"}
        )
        assert (meta.display_name, meta.unit, meta.widget_type) == ("Küche", "°C", "Plug")

    def test_numbers_and_booleans_become_text(self) -> None:
        meta = parse_metadata({"iot.DisplayName": 5, "iot.Unit": True})
        assert (meta.display_name, meta.unit) == ("5", "true")


# ── MetaData change on datatype and array variables ──────────────────


class TestDatatypeMetadataChange:
    """Changed attributes of a plain variable reach the entity without a value change."""

    @pytest.fixture(autouse=True)
    async def setup(self, hass: HomeAssistant) -> None:
        self.coord = _make_coordinator(hass)
        self.payload = {
            "Values": {"fTemp": 21.5, "aTemps": [1.0, 2.0]},
            "MetaData": {
                "fTemp": {"iot.DisplayName": "Temp", "iot.Unit": "°C"},
                "aTemps": {"iot.DisplayName": "Temps", "iot.Unit": "°C"},
            },
        }
        await self.coord._async_dispatch_message(_tx_msg(self.payload))
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        self.dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.listeners = {}
        for path in ("fTemp", "aTemps"):
            self.listeners[path] = MagicMock()
            self.coord.register_listener(MOCK_DEVICE_NAME, path, self.listeners[path])

    def _changed(self, path: str, attr: str, value: str) -> dict[str, Any]:
        payload = json.loads(json.dumps(self.payload))
        payload["MetaData"][path][attr] = value
        return payload

    @pytest.mark.parametrize("path", ["fTemp", "aTemps"])
    @pytest.mark.parametrize(
        ("attr", "value"),
        [
            ("iot.Unit", "K"),
            ("iot.DisplayName", "Renamed"),
            ("iot.MaxValue", "50"),
            ("iot.DecimalPrecision", "1"),
        ],
    )
    async def test_metadata_change_notifies_once(
        self, path: str, attr: str, value: str,
    ) -> None:
        await self.coord._async_dispatch_message(_tx_msg(self._changed(path, attr, value)))

        self.listeners[path].assert_called_once()
        widget = self.listeners[path].call_args.args[0]
        assert widget.metadata.raw[attr] == value
        other = "aTemps" if path == "fTemp" else "fTemp"
        self.listeners[other].assert_not_called()

    async def test_metadata_and_value_change_notify_once(self) -> None:
        payload = self._changed("fTemp", "iot.Unit", "K")
        payload["Values"]["fTemp"] = 30.0
        await self.coord._async_dispatch_message(_tx_msg(payload))
        self.listeners["fTemp"].assert_called_once()

    async def test_unchanged_metadata_does_not_notify(self) -> None:
        # A different, well-formed block forces the walk without touching the variables.
        payload = json.loads(json.dumps(self.payload))
        payload["Values"]["stOther"] = {"bOn": True}
        payload["MetaData"]["stOther"] = {"iot.WidgetType": "Plug"}
        await self.coord._async_dispatch_message(_tx_msg(payload))
        self.listeners["fTemp"].assert_not_called()
        self.listeners["aTemps"].assert_not_called()
