"""Tests for TwinCAT IoT Communicator select platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    META_GENERAL_MODE1_CHANGEABLE,
    META_GENERAL_MODE1_VISIBLE,
    META_LOCK_MODE_CHANGEABLE,
    META_LOCK_MODE_VISIBLE,
    META_MOTION_MODE_CHANGEABLE,
    META_MOTION_MODE_VISIBLE,
    META_TIMESWITCH_MODE_CHANGEABLE,
    META_TIMESWITCH_MODE_VISIBLE,
    VAL_GENERAL_MODE1,
    VAL_GENERAL_MODES1,
    VAL_MODE,
    VAL_MODES,
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_TIME_SWITCH,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)
from homeassistant.components.twincat_iot_communicator.select import (
    TcIotGeneralSelect,
    _create_lock_selects,
    _create_motion_selects,
    _create_selects,
    _create_timeswitch_selects,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import (
    attach_entity_to_hass,
    build_device_with_widgets,
    create_mock_coordinator,
    MOCK_DEVICE_NAME,
)

from tests.common import MockConfigEntry


def _make_select(
    hass,
    entry: MockConfigEntry,
    *,
    options: list[str] | None = None,
    current: str = "Schalten",
    changeable: bool = True,
    read_only: bool = False,
) -> tuple[TcIotGeneralSelect, MagicMock]:
    """Create a TcIotGeneralSelect with configurable parameters."""
    options = options or ["Schalten", "Speichern"]
    raw = {
        META_GENERAL_MODE1_VISIBLE: "true",
        META_GENERAL_MODE1_CHANGEABLE: "true" if changeable else "false",
    }
    meta = WidgetMetaData(
        display_name="Szene 1",
        widget_type=WIDGET_TYPE_GENERAL,
        read_only=read_only,
        raw=raw,
    )
    widget = WidgetData(
        widget_id="stGeneral",
        path="stGeneral",
        metadata=meta,
        values={
            VAL_GENERAL_MODE1: current,
            VAL_GENERAL_MODES1: options,
        },
        friendly_path="Szene 1",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets["stGeneral"] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    entity = TcIotGeneralSelect(
        coordinator,
        MOCK_DEVICE_NAME,
        widget,
        value_key=VAL_GENERAL_MODE1,
        options_key=VAL_GENERAL_MODES1,
        chg_key=META_GENERAL_MODE1_CHANGEABLE,
        suffix="_mode1",
        translation_key="mode_1",
    )
    attach_entity_to_hass(hass, entity, "select")
    return entity, coordinator


class TestSelectSetup:
    """Tests for select entity initialization."""

    def test_options_from_values(self, hass, mock_config_entry) -> None:
        """Test options are derived from aModes1."""
        entity, _ = _make_select(hass, mock_config_entry)
        assert entity.options == ["Schalten", "Speichern"]

    def test_current_option(self, hass, mock_config_entry) -> None:
        """Test current_option returns sMode1 value."""
        entity, _ = _make_select(hass, mock_config_entry, current="Speichern")
        assert entity.current_option == "Speichern"

    def test_changeable_attribute(self, hass, mock_config_entry) -> None:
        """Test changeable is exposed in extra_state_attributes."""
        entity, _ = _make_select(hass, mock_config_entry, changeable=True)
        assert entity.extra_state_attributes.get("changeable") is True

    def test_not_changeable_attribute(self, hass, mock_config_entry) -> None:
        """Test changeable=false is exposed."""
        entity, _ = _make_select(hass, mock_config_entry, changeable=False)
        assert entity.extra_state_attributes.get("changeable") is False

    def test_read_only_attribute(self, hass, mock_config_entry) -> None:
        """Test read_only is exposed via base extra_state_attributes."""
        entity, _ = _make_select(hass, mock_config_entry, read_only=True)
        assert entity.extra_state_attributes.get("read_only") is True


class TestSelectCommands:
    """Tests for select commands."""

    def test_select_option_sends_command(self, hass, mock_config_entry) -> None:
        """Test async_select_option sends correct command."""
        entity, coord = _make_select(hass, mock_config_entry, changeable=True)
        hass.loop.run_until_complete(entity.async_select_option("Speichern"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_GENERAL_MODE1}"] == "Speichern"

    def test_select_option_not_changeable_raises(
        self, hass, mock_config_entry
    ) -> None:
        """Test async_select_option raises when not changeable."""
        entity, _ = _make_select(hass, mock_config_entry, changeable=False)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_select_option("Speichern"))

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test async_select_option raises for read-only widget."""
        entity, _ = _make_select(hass, mock_config_entry, read_only=True)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_select_option("Speichern"))

    def test_invalid_option_raises(self, hass, mock_config_entry) -> None:
        """Test async_select_option raises for option not in allowed list."""
        entity, _ = _make_select(
            hass, mock_config_entry, options=["Schalten", "Speichern"], changeable=True,
        )
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_select_option("Ungueltig"))

    def test_valid_option_accepted(self, hass, mock_config_entry) -> None:
        """Test async_select_option passes for option in allowed list."""
        entity, coord = _make_select(
            hass, mock_config_entry, options=["Schalten", "Speichern"], changeable=True,
        )
        hass.loop.run_until_complete(entity.async_select_option("Schalten"))
        coord.async_send_command.assert_called_once()


class TestSelectSyncMetadata:
    """Tests for dynamic metadata updates."""

    def test_sync_metadata_updates_options(self, hass, mock_config_entry) -> None:
        """Test _sync_metadata updates options when values change."""
        entity, _ = _make_select(hass, mock_config_entry)
        assert entity.options == ["Schalten", "Speichern"]
        entity.widget.values[VAL_GENERAL_MODES1] = ["A", "B", "C"]
        entity._sync_metadata()
        assert entity.options == ["A", "B", "C"]

    def test_sync_metadata_updates_changeable(self, hass, mock_config_entry) -> None:
        """Test _sync_metadata updates changeable flag from metadata."""
        entity, _ = _make_select(hass, mock_config_entry, changeable=True)
        assert entity.extra_state_attributes.get("changeable") is True
        entity.widget.metadata.raw[META_GENERAL_MODE1_CHANGEABLE] = "false"
        entity._sync_metadata()
        assert entity.extra_state_attributes.get("changeable") is False


class TestSelectFromFixture:
    """Tests using General widget fixtures."""

    def test_create_selects_fully_featured(self, hass, mock_config_entry) -> None:
        """Test _create_selects creates 3 selects from fully featured General fixture."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-general.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        entities = _create_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 3
        for sel in entities:
            assert isinstance(sel, TcIotGeneralSelect)

    def test_create_selects_minimal(self, hass, mock_config_entry) -> None:
        """Test _create_selects creates 1 select from minimal General fixture."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/variants/widget-general-minimal.json"])
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        widget = next(iter(dev.widgets.values()))
        entities = _create_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1
        sel = entities[0]
        assert isinstance(sel, TcIotGeneralSelect)
        assert sel.options == ["Schalten", "Speichern"]
        assert sel.current_option == "Schalten"


class TestTimeSwitchSelect:
    """Tests for TimeSwitch mode select entity."""

    def _make_ts_select(
        self, hass, entry: MockConfigEntry, *, changeable: bool = True,
    ) -> tuple[TcIotGeneralSelect, MagicMock]:
        raw = {
            META_TIMESWITCH_MODE_VISIBLE: "true",
            META_TIMESWITCH_MODE_CHANGEABLE: "true" if changeable else "false",
        }
        meta = WidgetMetaData(
            display_name="Timer 1",
            widget_type=WIDGET_TYPE_TIME_SWITCH,
            raw=raw,
        )
        widget = WidgetData(
            widget_id="stTimeSwitch",
            path="stTimeSwitch",
            metadata=meta,
            values={
                VAL_MODE: "Automatisch",
                VAL_MODES: ["Automatisch", "Manuell", "Aus"],
            },
            friendly_path="Timer 1",
        )
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        dev.widgets["stTimeSwitch"] = widget
        coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
        entities = _create_timeswitch_selects(coordinator, MOCK_DEVICE_NAME, widget)
        attach_entity_to_hass(hass, entities[0], "select")
        return entities[0], coordinator

    def test_options(self, hass, mock_config_entry) -> None:
        """Test options from aModes."""
        entity, _ = self._make_ts_select(hass, mock_config_entry)
        assert entity.options == ["Automatisch", "Manuell", "Aus"]

    def test_current_option(self, hass, mock_config_entry) -> None:
        """Test current_option returns sMode."""
        entity, _ = self._make_ts_select(hass, mock_config_entry)
        assert entity.current_option == "Automatisch"

    def test_select_sends_command(self, hass, mock_config_entry) -> None:
        """Test selecting an option sends correct command."""
        entity, coord = self._make_ts_select(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_select_option("Manuell"))
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_MODE}"] == "Manuell"

    def test_not_changeable_raises(self, hass, mock_config_entry) -> None:
        """Test selecting raises when mode is not changeable."""
        entity, _ = self._make_ts_select(hass, mock_config_entry, changeable=False)
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_select_option("Manuell"))

    def test_create_selects_routes_timeswitch(self, hass, mock_config_entry) -> None:
        """Test _create_selects dispatches TimeSwitch correctly."""
        raw = {
            META_TIMESWITCH_MODE_VISIBLE: "true",
            META_TIMESWITCH_MODE_CHANGEABLE: "true",
        }
        meta = WidgetMetaData(
            display_name="Timer",
            widget_type=WIDGET_TYPE_TIME_SWITCH,
            raw=raw,
        )
        widget = WidgetData(
            widget_id="stTS",
            path="stTS",
            metadata=meta,
            values={VAL_MODE: "Aus", VAL_MODES: ["Aus", "An"]},
            friendly_path="Timer",
        )
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.online = True
        dev.widgets["stTS"] = widget
        coordinator = create_mock_coordinator(hass, mock_config_entry, {MOCK_DEVICE_NAME: dev})
        entities = _create_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1
        assert entities[0].current_option == "Aus"


# ── Lock select tests ───────────────────────────────────────────────


class TestLockSelect:
    """Tests for Lock widget mode select."""

    def test_creates_select_from_fixture(self, hass, mock_config_entry) -> None:
        """Test _create_lock_selects creates mode select from Lock fixture."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_lock_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1
        sel = entities[0]
        assert isinstance(sel, TcIotGeneralSelect)
        assert sel.options == ["Auto", "Manuell", "Nacht"]
        assert sel.current_option == "Auto"

    def test_create_selects_routes_lock(self, hass, mock_config_entry) -> None:
        """Test _create_selects dispatches Lock correctly."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1


# ── Motion select tests ─────────────────────────────────────────────


class TestMotionSelect:
    """Tests for Motion widget mode select."""

    def test_creates_select_from_fixture(self, hass, mock_config_entry) -> None:
        """Test _create_motion_selects creates mode select from Motion fixture."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_motion_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1
        sel = entities[0]
        assert sel.options == ["Auto", "Manuell", "Test", "Aus"]
        assert sel.current_option == "Auto"

    def test_create_selects_routes_motion(self, hass, mock_config_entry) -> None:
        """Test _create_selects dispatches Motion correctly."""
        dev = build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-motion.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        entities = _create_selects(coordinator, MOCK_DEVICE_NAME, widget)
        assert len(entities) == 1


# ── Hidden-mode parametrized tests ──────────────────────────────────


@pytest.mark.parametrize(
    ("fixture", "factory", "hide_key"),
    [
        ("widgets/base/widget-time-switch.json", _create_timeswitch_selects, META_TIMESWITCH_MODE_VISIBLE),
        ("widgets/base/widget-lock.json", _create_lock_selects, META_LOCK_MODE_VISIBLE),
        ("widgets/base/widget-motion.json", _create_motion_selects, META_MOTION_MODE_VISIBLE),
    ],
)
def test_hidden_mode_no_entities(
    hass, mock_config_entry, fixture, factory, hide_key,
) -> None:
    """Test no select is created when mode visibility is false."""
    dev = build_device_with_widgets(MOCK_DEVICE_NAME, [fixture])
    coordinator = create_mock_coordinator(
        hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
    )
    widget = next(iter(dev.widgets.values()))
    widget.metadata.raw[hide_key] = "false"
    entities = factory(coordinator, MOCK_DEVICE_NAME, widget)
    assert len(entities) == 0
