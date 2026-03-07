"""Tests for TcIotCoordinator discovery, update, and reconciliation logic."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.components.twincat_iot_communicator.coordinator import TcIotCoordinator
from homeassistant.components.twincat_iot_communicator.models import DeviceContext, WidgetData

from .conftest import (
    MOCK_DEVICE_NAME,
    MOCK_ENTRY_DATA,
    build_device_from_multi_widget_fixture,
    load_fixture_json,
)

from tests.common import MockConfigEntry

DOMAIN = "twincat_iot_communicator"


def _make_coordinator(hass: HomeAssistant) -> TcIotCoordinator:
    """Create a coordinator with mocked hass and entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA,
        unique_id="test",
        title="Test",
        version=2,
        minor_version=2,
    )
    return TcIotCoordinator(hass, entry)


def _new_device(name: str = MOCK_DEVICE_NAME) -> DeviceContext:
    """Create a fresh DeviceContext."""
    dev = DeviceContext(device_name=name)
    dev.online = True
    return dev


# ── payloads/snapshot_full.json: initial discovery ─────────────────────────


class TestMultiWidgetDiscovery:
    """Tests for discovering multiple widgets from a single payload."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Load fixture and run initial discovery."""
        self.coord = _make_coordinator(hass)
        self.data = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()
        self.new_widgets: dict[Platform, list[WidgetData]] = {}

        self.coord._discover_widgets(
            self.dev,
            self.data["Values"],
            self.data["MetaData"],
        )

    def test_discovers_all_five_widgets(self) -> None:
        assert len(self.dev.widgets) == 5

    def test_known_widget_paths(self) -> None:
        expected = {"stLighting", "stBlinds", "stPlug", "stAC", "stSensor.fREAL"}
        assert self.dev.known_widget_paths == expected

    def test_lighting_widget_type(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.metadata.widget_type == "Lighting"

    def test_lighting_values(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.values["bLight"] is True
        assert w.values["nLight"] == 75
        assert w.values["sMode"] == "Szene 1"

    def test_blinds_widget_type(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.metadata.widget_type == "Blinds"

    def test_blinds_values(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.values["nPositionValue"] == 30
        assert w.values["nAngleValue"] == 0

    def test_plug_widget_type(self) -> None:
        w = self.dev.widgets["stPlug"]
        assert w.metadata.widget_type == "Plug"

    def test_plug_on(self) -> None:
        w = self.dev.widgets["stPlug"]
        assert w.values["bOn"] is True

    def test_ac_widget_type(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.metadata.widget_type == "AC"

    def test_ac_temperatures(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.values["nTemperature"] == 22.5
        assert w.values["nTemperatureRequest"] == 23.0

    def test_datatype_sensor_discovered(self) -> None:
        w = self.dev.widgets["stSensor.fREAL"]
        assert w.metadata.read_only is True
        assert w.values == {"value": 22.5}

    def test_datatype_sensor_type(self) -> None:
        w = self.dev.widgets["stSensor.fREAL"]
        assert w.metadata.widget_type == "_dt_number"

    def test_field_metadata_lighting(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.field_metadata["nLight"]["iot.Unit"] == "%"
        assert w.field_metadata["nLight"]["iot.MaxValue"] == "100"

    def test_field_metadata_blinds_angle(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.field_metadata["nAngleValue"]["iot.MinValue"] == "-75"
        assert w.field_metadata["nAngleValue"]["iot.MaxValue"] == "75"

    def test_display_names(self) -> None:
        assert self.dev.widgets["stLighting"].metadata.display_name == "Strahler Couch"
        assert self.dev.widgets["stBlinds"].metadata.display_name == "Raffstore Süd"
        assert self.dev.widgets["stPlug"].metadata.display_name == "Steckdose Fenster"
        assert self.dev.widgets["stAC"].metadata.display_name == "Fußbodenheizung"
        assert self.dev.widgets["stSensor.fREAL"].metadata.display_name == "Mittlere Temperatur"

    def test_widget_path_prefixes_for_datatype(self) -> None:
        assert "stSensor" in self.dev.widget_path_prefixes


# ── payloads/onchange_values_only.json: value-only update ──────────────────────


class TestOnChangeValuesOnly:
    """Tests for a value-only OnChange update (no MetaData)."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Set up initial state from multi_widget_room, then apply onchange."""
        self.coord = _make_coordinator(hass)
        self.initial = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()

        self.coord._discover_widgets(
            self.dev,
            self.initial["Values"],
            self.initial["MetaData"],
        )
        self.dev.awaiting_full_snapshot = False

        self.onchange = load_fixture_json("payloads/onchange_values_only.json")
        self.coord._update_widgets(self.dev, self.onchange["Values"])

    def test_widget_count_unchanged(self) -> None:
        """No new widgets should be added by a value-only update."""
        assert len(self.dev.widgets) == 5

    def test_known_paths_unchanged(self) -> None:
        expected = {"stLighting", "stBlinds", "stPlug", "stAC", "stSensor.fREAL"}
        assert self.dev.known_widget_paths == expected

    def test_lighting_brightness_updated(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.values["nLight"] == 85

    def test_lighting_light_state_unchanged(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.values["bLight"] is True

    def test_lighting_modes_preserved(self) -> None:
        """Keys not in the onchange payload should be preserved."""
        w = self.dev.widgets["stLighting"]
        assert w.values["sMode"] == "Szene 1"
        assert "aModes" in w.values

    def test_blinds_position_updated(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.values["nPositionValue"] == 60
        assert w.values["nAngleValue"] == -30

    def test_blinds_other_values_preserved(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.values["bActive"] is False
        assert w.values["sMode"] == "Manuell"

    def test_plug_turned_off(self) -> None:
        w = self.dev.widgets["stPlug"]
        assert w.values["bOn"] is False

    def test_ac_temperature_updated(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.values["nTemperature"] == 23.1

    def test_ac_mode_updated(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.values["sMode"] == "Kühlen"

    def test_ac_request_temp_preserved(self) -> None:
        """nTemperatureRequest was not in the onchange, must be preserved."""
        w = self.dev.widgets["stAC"]
        assert w.values["nTemperatureRequest"] == 23.0

    def test_scalar_datatype_updated(self) -> None:
        w = self.dev.widgets["stSensor.fREAL"]
        assert w.values["value"] == 23.1

    def test_no_stale_widgets(self) -> None:
        assert len(self.dev.stale_widget_paths) == 0

    def test_metadata_not_altered(self) -> None:
        """Metadata should remain from the initial discovery."""
        w = self.dev.widgets["stLighting"]
        assert w.metadata.widget_type == "Lighting"
        assert w.metadata.display_name == "Strahler Couch"


# ── snapshot reconciliation: stale marking on active=1 snapshot ─────────


class TestActiveSnapshotReconciliation:
    """Tests for snapshot reconciliation after active=1 (startup/15-min/reconnect).

    Simulates the scenario where a partial snapshot (2 of 5 widgets) arrives
    after publishing active=1. Uses _discover_widgets with path_accumulator
    and then _finalize_snapshot to trigger stale marking.
    """

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Set up all 5 widgets, then reconcile against a partial snapshot."""
        self.coord = _make_coordinator(hass)
        self.initial = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()

        self.coord._discover_widgets(
            self.dev,
            self.initial["Values"],
            self.initial["MetaData"],
        )
        self.dev.awaiting_full_snapshot = False

        self.force = load_fixture_json("payloads/onchange_force.json")

        self.dev.awaiting_full_snapshot = True
        self.dev.snapshot_accumulated_paths.clear()
        self.coord._discover_widgets(
            self.dev,
            self.force["Values"],
            self.force["MetaData"],
            path_accumulator=self.dev.snapshot_accumulated_paths,
        )
        self.coord._update_widgets(self.dev, self.force["Values"])
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

    def test_widget_count_unchanged(self) -> None:
        """All widgets stay in dev.widgets, stale ones are just marked."""
        assert len(self.dev.widgets) == 5

    def test_two_widgets_remain_active(self) -> None:
        active = self.dev.known_widget_paths - self.dev.stale_widget_paths
        assert active == {"stLighting", "stBlinds"}

    def test_three_widgets_marked_stale(self) -> None:
        assert self.dev.stale_widget_paths == {
            "stPlug", "stAC", "stSensor.fREAL"
        }

    def test_lighting_values_updated(self) -> None:
        w = self.dev.widgets["stLighting"]
        assert w.values["bLight"] is False
        assert w.values["nLight"] == 0

    def test_blinds_values_updated(self) -> None:
        w = self.dev.widgets["stBlinds"]
        assert w.values["nPositionValue"] == 0
        assert w.values["nAngleValue"] == 75
        assert w.values["sMode"] == "Inaktiv"

    def test_stale_widget_values_untouched(self) -> None:
        """Stale widgets keep their last known values."""
        w = self.dev.widgets["stPlug"]
        assert w.values["bOn"] is True

    def test_stale_ac_keeps_values(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.values["nTemperature"] == 22.5

    def test_stale_sensor_keeps_value(self) -> None:
        w = self.dev.widgets["stSensor.fREAL"]
        assert w.values["value"] == 22.5

    def test_awaiting_flag_cleared(self) -> None:
        """After finalization, awaiting_full_snapshot must be False."""
        assert self.dev.awaiting_full_snapshot is False


class TestActiveSnapshotRecovery:
    """Tests that stale widgets recover when they reappear in a subsequent active=1 snapshot."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Mark some widgets stale via partial snapshot, then recover via full snapshot."""
        self.coord = _make_coordinator(hass)
        self.initial = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()

        self.coord._discover_widgets(
            self.dev,
            self.initial["Values"],
            self.initial["MetaData"],
        )
        self.dev.awaiting_full_snapshot = False
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev

        force_partial = load_fixture_json("payloads/onchange_force.json")
        self.dev.awaiting_full_snapshot = True
        self.dev.snapshot_accumulated_paths.clear()
        self.coord._discover_widgets(
            self.dev,
            force_partial["Values"],
            force_partial["MetaData"],
            path_accumulator=self.dev.snapshot_accumulated_paths,
        )
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert self.dev.stale_widget_paths == {
            "stPlug", "stAC", "stSensor.fREAL"
        }

        self.dev.awaiting_full_snapshot = True
        self.dev.snapshot_accumulated_paths.clear()
        self.coord._discover_widgets(
            self.dev,
            self.initial["Values"],
            self.initial["MetaData"],
            path_accumulator=self.dev.snapshot_accumulated_paths,
        )
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

    def test_all_stale_recovered(self) -> None:
        assert len(self.dev.stale_widget_paths) == 0

    def test_all_widgets_still_known(self) -> None:
        assert len(self.dev.known_widget_paths) == 5

    def test_recovered_plug_value_updated(self) -> None:
        w = self.dev.widgets["stPlug"]
        assert w.values["bOn"] is True

    def test_recovered_ac_value_updated(self) -> None:
        w = self.dev.widgets["stAC"]
        assert w.values["nTemperature"] == 22.5
        assert w.values["nTemperatureRequest"] == 23.0

    def test_recovered_sensor_value_updated(self) -> None:
        w = self.dev.widgets["stSensor.fREAL"]
        assert w.values["value"] == 22.5

    def test_awaiting_flag_cleared(self) -> None:
        """After full recovery, awaiting_full_snapshot must be False."""
        assert self.dev.awaiting_full_snapshot is False


class TestDispatchMessageRouting:
    """Tests for _async_dispatch_message routing the right codepath."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        self.coord = _make_coordinator(hass)
        self.initial = load_fixture_json("payloads/snapshot_full.json")

    def _make_msg(self, topic: str, payload: dict) -> MagicMock:
        msg = MagicMock()
        msg.topic = topic
        msg.payload = json.dumps(payload).encode()
        return msg

    def _topic(self, suffix: str) -> str:
        return f"IotApp.Sample/{MOCK_DEVICE_NAME}/TcIotCommunicator/{suffix}"

    @pytest.mark.asyncio
    async def test_initial_snapshot_discovers_widgets_and_accumulates(self) -> None:
        """First Tx/Data message discovers widgets and starts snapshot accumulation."""
        msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(msg)

        dev = self.coord.devices[MOCK_DEVICE_NAME]
        assert len(dev.widgets) == 5
        assert dev.awaiting_full_snapshot is True
        assert len(dev.snapshot_accumulated_paths) == 5

        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.awaiting_full_snapshot is False

    @pytest.mark.asyncio
    async def test_subsequent_value_only_updates(self) -> None:
        """Value-only OnChange after discovery merges without new discovery."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

        onchange = load_fixture_json("payloads/onchange_values_only.json")
        onchange_msg = self._make_msg(self._topic("Tx/Data"), onchange)
        await self.coord._async_dispatch_message(onchange_msg)

        dev = self.coord.devices[MOCK_DEVICE_NAME]
        assert len(dev.widgets) == 5
        assert dev.widgets["stLighting"].values["nLight"] == 85
        assert dev.widgets["stPlug"].values["bOn"] is False

    @pytest.mark.asyncio
    async def test_force_update_never_marks_stale(self) -> None:
        """ForceUpdate=true always uses additive discovery; never marks stale."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

        force = load_fixture_json("payloads/onchange_force.json")
        force_msg = self._make_msg(self._topic("Tx/Data"), force)
        await self.coord._async_dispatch_message(force_msg)

        assert dev.stale_widget_paths == set()
        assert dev.awaiting_full_snapshot is False

    @pytest.mark.asyncio
    async def test_force_update_does_not_consume_awaiting_flag(self) -> None:
        """ForceUpdate does not consume awaiting_full_snapshot; next real snapshot does."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

        dev.awaiting_full_snapshot = True
        dev.snapshot_accumulated_paths.clear()

        force = load_fixture_json("payloads/onchange_force.json")
        await self.coord._async_dispatch_message(
            self._make_msg(self._topic("Tx/Data"), force)
        )
        assert dev.awaiting_full_snapshot is True

        await self.coord._async_dispatch_message(
            self._make_msg(self._topic("Tx/Data"), self.initial)
        )
        assert dev.awaiting_full_snapshot is True
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.awaiting_full_snapshot is False

    @pytest.mark.asyncio
    async def test_post_active_snapshot_marks_missing_stale(self) -> None:
        """Payload after active=1 (awaiting=True) marks missing widgets stale after finalization."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.stale_widget_paths == set()

        dev.awaiting_full_snapshot = True
        dev.snapshot_accumulated_paths.clear()

        partial = load_fixture_json("payloads/onchange_force.json")
        partial_no_fu = {k: v for k, v in partial.items() if k != "ForceUpdate"}
        await self.coord._async_dispatch_message(
            self._make_msg(self._topic("Tx/Data"), partial_no_fu)
        )
        assert dev.awaiting_full_snapshot is True

        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.awaiting_full_snapshot is False
        assert dev.stale_widget_paths == {"stPlug", "stAC", "stSensor.fREAL"}

    @pytest.mark.asyncio
    async def test_post_active_snapshot_recovers_stale(self) -> None:
        """Full snapshot after active=1 recovers previously stale widgets after finalization."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)

        dev.stale_widget_paths = {"stPlug", "stAC", "stSensor.fREAL"}
        dev.awaiting_full_snapshot = True
        dev.snapshot_accumulated_paths.clear()

        await self.coord._async_dispatch_message(
            self._make_msg(self._topic("Tx/Data"), self.initial)
        )
        assert dev.awaiting_full_snapshot is True

        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.stale_widget_paths == set()
        assert dev.awaiting_full_snapshot is False

    @pytest.mark.asyncio
    async def test_onchange_without_awaiting_never_marks_stale(self) -> None:
        """Normal payload without awaiting_full_snapshot=True never marks stale."""
        initial_msg = self._make_msg(self._topic("Tx/Data"), self.initial)
        await self.coord._async_dispatch_message(initial_msg)
        dev = self.coord.devices[MOCK_DEVICE_NAME]
        self.coord._finalize_snapshot(MOCK_DEVICE_NAME)
        assert dev.awaiting_full_snapshot is False

        partial = load_fixture_json("payloads/onchange_force.json")
        partial_no_fu = {k: v for k, v in partial.items() if k != "ForceUpdate"}
        await self.coord._async_dispatch_message(
            self._make_msg(self._topic("Tx/Data"), partial_no_fu)
        )
        assert dev.stale_widget_paths == set()

    @pytest.mark.asyncio
    async def test_unselected_device_ignored(self) -> None:
        """Messages from devices not in selected_devices are ignored."""
        topic = "IotApp.Sample/OtherDevice/TcIotCommunicator/Tx/Data"
        msg = self._make_msg(topic, self.initial)
        await self.coord._async_dispatch_message(msg)

        assert "OtherDevice" not in self.coord.devices


class TestTopicSegmentValidation:
    """Tests for _is_safe_topic_segment used in MQTT topic injection prevention."""

    def test_accepts_alphanumeric(self) -> None:
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            _is_safe_topic_segment,
        )
        assert _is_safe_topic_segment("Usermode") is True
        assert _is_safe_topic_segment("Device_01") is True
        assert _is_safe_topic_segment("stRooms.stLighting") is True

    def test_rejects_mqtt_wildcards(self) -> None:
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            _is_safe_topic_segment,
        )
        assert _is_safe_topic_segment("device+") is False
        assert _is_safe_topic_segment("device#") is False
        assert _is_safe_topic_segment("#") is False
        assert _is_safe_topic_segment("+") is False

    def test_rejects_path_separator(self) -> None:
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            _is_safe_topic_segment,
        )
        assert _is_safe_topic_segment("a/b") is False
        assert _is_safe_topic_segment("/") is False

    def test_rejects_empty(self) -> None:
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            _is_safe_topic_segment,
        )
        assert _is_safe_topic_segment("") is False

    def test_rejects_spaces(self) -> None:
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            _is_safe_topic_segment,
        )
        assert _is_safe_topic_segment("device name") is False


class TestMessageEviction:
    """Tests for bounded message storage in DeviceContext."""

    def test_oldest_message_evicted(self, hass: HomeAssistant) -> None:
        """Messages beyond MAX_MESSAGES_PER_DEVICE evict the oldest entry."""
        from homeassistant.components.twincat_iot_communicator.coordinator import (
            MAX_MESSAGES_PER_DEVICE,
        )

        coord = _make_coordinator(hass)
        dev = _new_device()
        coord.devices[MOCK_DEVICE_NAME] = dev

        for i in range(MAX_MESSAGES_PER_DEVICE + 5):
            msg_id = f"msg_{i:04d}"
            payload = json.dumps({
                "Timestamp": "2026-01-01T00:00:00",
                "Message": f"Message {i}",
                "Type": "Default",
            }).encode()
            coord._handle_plc_message(dev, msg_id, payload)

        assert len(dev.messages) == MAX_MESSAGES_PER_DEVICE
        assert "msg_0000" not in dev.messages
        assert "msg_0004" not in dev.messages
        assert f"msg_{MAX_MESSAGES_PER_DEVICE + 4:04d}" in dev.messages


class TestFieldMetaIndex:
    """Tests for _build_field_meta_index performance optimization."""

    def test_builds_correct_index(self) -> None:
        """Field metadata grouped by parent widget path."""
        metadata = {
            "stLighting": {"iot.WidgetType": "Lighting"},
            "stLighting.nLight": {"iot.Unit": "%", "iot.MaxValue": "100"},
            "stLighting.bLight": {"iot.ReadOnly": "false"},
            "stBlinds": {"iot.WidgetType": "Blinds"},
            "stBlinds.nAngleValue": {"iot.MinValue": "-75", "iot.MaxValue": "75"},
        }
        index = TcIotCoordinator._build_field_meta_index(metadata)

        assert "stLighting" in index
        assert "nLight" in index["stLighting"]
        assert index["stLighting"]["nLight"]["iot.Unit"] == "%"
        assert "bLight" in index["stLighting"]
        assert "stBlinds" in index
        assert "nAngleValue" in index["stBlinds"]

    def test_skips_non_dict_metadata(self) -> None:
        """Non-dict metadata entries are skipped."""
        metadata = {
            "stLighting": {"iot.WidgetType": "Lighting"},
            "stLighting.nLight": "not_a_dict",
        }
        index = TcIotCoordinator._build_field_meta_index(metadata)
        assert index.get("stLighting", {}).get("nLight") is None

    def test_empty_metadata(self) -> None:
        index = TcIotCoordinator._build_field_meta_index({})
        assert index == {}


class TestBuildDeviceFromMultiWidgetFixture:
    """Tests that the conftest helper correctly parses multi-widget fixtures."""

    def test_builds_all_widgets(self) -> None:
        dev = build_device_from_multi_widget_fixture(
            MOCK_DEVICE_NAME, "payloads/snapshot_full.json"
        )
        assert len(dev.widgets) == 5

    def test_widget_types(self) -> None:
        dev = build_device_from_multi_widget_fixture(
            MOCK_DEVICE_NAME, "payloads/snapshot_full.json"
        )
        assert dev.widgets["stLighting"].metadata.widget_type == "Lighting"
        assert dev.widgets["stBlinds"].metadata.widget_type == "Blinds"
        assert dev.widgets["stPlug"].metadata.widget_type == "Plug"
        assert dev.widgets["stAC"].metadata.widget_type == "AC"
        assert dev.widgets["stSensor.fREAL"].metadata.widget_type == "_dt_number"

    def test_device_flags(self) -> None:
        dev = build_device_from_multi_widget_fixture(
            MOCK_DEVICE_NAME, "payloads/snapshot_full.json"
        )
        assert dev.online is True
        assert dev.registered is True
        assert dev.awaiting_full_snapshot is False


# ── PermittedUsers runtime logic ─────────────────────────────────────


class TestPermittedUsersRuntime:
    """Tests for runtime PermittedUsers changes on device and widget level."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Load fixture and discover widgets."""
        self.coord = _make_coordinator(hass)
        self.coord._username = "testuser"
        self.data = load_fixture_json("payloads/snapshot_full.json")
        self.dev = _new_device()
        values = self.data["Values"]
        metadata = self.data["MetaData"]
        self.coord._discover_widgets(self.dev, values, metadata)

    def test_is_user_permitted_none(self) -> None:
        """Field absent (None) means permitted."""
        assert self.coord._is_user_permitted(None) is True

    def test_is_user_permitted_wildcard(self) -> None:
        """Wildcard means permitted."""
        assert self.coord._is_user_permitted("*") is True

    def test_is_user_permitted_listed(self) -> None:
        """User in comma list is permitted."""
        assert self.coord._is_user_permitted("admin, testuser") is True

    def test_is_user_permitted_not_listed(self) -> None:
        """User not in list is denied."""
        assert self.coord._is_user_permitted("admin,other") is False

    def test_is_user_permitted_empty_string(self) -> None:
        """Empty string means nobody is permitted."""
        assert self.coord._is_user_permitted("") is False

    def test_is_user_permitted_whitespace(self) -> None:
        """Whitespace-only means nobody is permitted."""
        assert self.coord._is_user_permitted("  ") is False

    def test_device_permission_revoked_marks_stale(self) -> None:
        """Revoking device permission marks all widgets stale."""
        assert len(self.dev.stale_widget_paths) == 0
        self.coord._handle_desc(self.dev, {
            "Online": True,
            "PermittedUsers": "admin_only",
        })
        assert self.dev.stale_widget_paths == self.dev.known_widget_paths

    def test_device_permission_restored_clears_stale(self) -> None:
        """Restoring device permission recovers stale widgets."""
        self.coord._handle_desc(self.dev, {
            "Online": True,
            "PermittedUsers": "admin_only",
        })
        assert len(self.dev.stale_widget_paths) > 0

        self.coord._handle_desc(self.dev, {
            "Online": True,
            "PermittedUsers": "testuser,admin_only",
        })
        assert len(self.dev.stale_widget_paths) == 0

    def test_widget_permission_revoked_marks_stale(self) -> None:
        """Revoking widget-level permission marks that widget stale."""
        path = "stLighting"
        assert path not in self.dev.stale_widget_paths

        meta = dict(self.data["MetaData"])
        meta[path] = {**meta[path], "iot.PermittedUsers": "admin_only"}
        self.coord._discover_widgets(self.dev, self.data["Values"], meta)

        assert path in self.dev.stale_widget_paths

    def test_widget_permission_restored_recovers(self) -> None:
        """Restoring widget-level permission recovers it."""
        path = "stLighting"
        meta = dict(self.data["MetaData"])
        meta[path] = {**meta[path], "iot.PermittedUsers": "admin_only"}
        self.coord._discover_widgets(self.dev, self.data["Values"], meta)
        assert path in self.dev.stale_widget_paths

        meta[path] = {**meta[path], "iot.PermittedUsers": "testuser"}
        self.coord._discover_widgets(self.dev, self.data["Values"], meta)
        assert path not in self.dev.stale_widget_paths


# ── async_remove_device ──────────────────────────────────────────────


class TestAsyncRemoveDevice:
    """Tests for coordinator.async_remove_device."""

    @pytest.fixture(autouse=True)
    def setup(self, hass: HomeAssistant) -> None:
        """Set up coordinator with a discovered device."""
        self.coord = _make_coordinator(hass)
        self.dev = _new_device()
        self.coord.devices[MOCK_DEVICE_NAME] = self.dev
        if self.coord._selected_devices is not None:
            self.coord._selected_devices.add(MOCK_DEVICE_NAME)

    @pytest.mark.asyncio
    async def test_removes_device_from_state(self, hass: HomeAssistant) -> None:
        """Test device is removed from coordinator state."""
        await self.coord.async_remove_device(MOCK_DEVICE_NAME)
        assert MOCK_DEVICE_NAME not in self.coord.devices
        assert MOCK_DEVICE_NAME in self.coord._ignored_devices

    @pytest.mark.asyncio
    async def test_removes_from_selected_devices(self, hass: HomeAssistant) -> None:
        """Test device is removed from selected filter."""
        await self.coord.async_remove_device(MOCK_DEVICE_NAME)
        if self.coord._selected_devices is not None:
            assert MOCK_DEVICE_NAME not in self.coord._selected_devices

    @pytest.mark.asyncio
    async def test_cleans_up_listeners(self, hass: HomeAssistant) -> None:
        """Test that listeners for the removed device are cleaned up."""
        self.coord._listeners[f"{MOCK_DEVICE_NAME}/widget1"] = [MagicMock()]
        self.coord._listeners["other_device/widget2"] = [MagicMock()]

        await self.coord.async_remove_device(MOCK_DEVICE_NAME)

        assert f"{MOCK_DEVICE_NAME}/widget1" not in self.coord._listeners
        assert "other_device/widget2" in self.coord._listeners
