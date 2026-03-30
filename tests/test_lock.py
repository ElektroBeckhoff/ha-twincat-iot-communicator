"""Tests for TwinCAT IoT Communicator lock platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.lock import LockEntityFeature
from homeassistant.components.twincat_iot_communicator.const import (
    VAL_LOCK_JAMMED,
    VAL_LOCK_LOCK,
    VAL_LOCK_LOCKED,
    VAL_LOCK_OPEN,
    VAL_LOCK_OPENED,
    VAL_LOCK_STATE,
    VAL_LOCK_UNLOCK,
)
from homeassistant.components.twincat_iot_communicator.lock import (
    TcIotLock,
    _create_locks,
)
from homeassistant.exceptions import ServiceValidationError

from .conftest import build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


DEVICE_NAME = "TestDevice"


def _make_lock(
    hass, entry: MockConfigEntry,
) -> tuple[TcIotLock, MagicMock]:
    """Create a TcIotLock from the Lock fixture."""
    dev = build_device_with_widgets(DEVICE_NAME, ["widgets/lock.json"])
    coordinator = create_mock_coordinator(hass, entry, {DEVICE_NAME: dev})
    widget = next(iter(dev.widgets.values()))
    entity = TcIotLock(coordinator, DEVICE_NAME, widget)
    return entity, coordinator


class TestLockEntity:
    """Tests for the Lock widget entity."""

    def test_setup(self, hass, mock_config_entry) -> None:
        """Test Lock entity has correct initial state."""
        entity, _ = _make_lock(hass, mock_config_entry)
        assert entity.is_locked is True
        assert entity.is_jammed is False
        assert entity.is_open is False

    def test_open_feature_flag(self, hass, mock_config_entry) -> None:
        """Test OPEN feature is set when LockOpenVisible is true."""
        entity, _ = _make_lock(hass, mock_config_entry)
        assert entity.supported_features & LockEntityFeature.OPEN

    def test_open_feature_hidden(self, hass, mock_config_entry) -> None:
        """Test OPEN feature is not set when LockOpenVisible is false."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.LockOpenVisible"] = "false"
        entity = TcIotLock(coordinator, DEVICE_NAME, widget)
        assert not (entity.supported_features & LockEntityFeature.OPEN)
        assert entity.is_open is None

    def test_is_jammed_hidden(self, hass, mock_config_entry) -> None:
        """Test is_jammed returns False when JammedVisible is false."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/lock.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw["iot.LockJammedVisible"] = "false"
        widget.values[VAL_LOCK_JAMMED] = True
        entity = TcIotLock(coordinator, DEVICE_NAME, widget)
        assert entity.is_jammed is False

    def test_is_jammed_true(self, hass, mock_config_entry) -> None:
        """Test is_jammed returns True when jammed and visible."""
        entity, _ = _make_lock(hass, mock_config_entry)
        entity.widget.values[VAL_LOCK_JAMMED] = True
        assert entity.is_jammed is True

    def test_unlocked_state(self, hass, mock_config_entry) -> None:
        """Test is_locked reflects bLocked value."""
        entity, _ = _make_lock(hass, mock_config_entry)
        entity.widget.values[VAL_LOCK_LOCKED] = False
        assert entity.is_locked is False

    def test_door_opened(self, hass, mock_config_entry) -> None:
        """Test is_open reflects bOpened value."""
        entity, _ = _make_lock(hass, mock_config_entry)
        entity.widget.values[VAL_LOCK_OPENED] = True
        assert entity.is_open is True

    def test_extra_state_attributes(self, hass, mock_config_entry) -> None:
        """Test extra_state_attributes includes lock_state."""
        entity, _ = _make_lock(hass, mock_config_entry)
        attrs = entity.extra_state_attributes
        assert attrs["lock_state"] == "Locked"
        assert "read_only" in attrs

    def test_async_lock(self, hass, mock_config_entry) -> None:
        """Test async_lock sends bLock=True."""
        entity, coord = _make_lock(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_lock())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LOCK_LOCK}"] is True

    def test_async_unlock(self, hass, mock_config_entry) -> None:
        """Test async_unlock sends bUnlock=True."""
        entity, coord = _make_lock(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_unlock())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LOCK_UNLOCK}"] is True

    def test_async_open(self, hass, mock_config_entry) -> None:
        """Test async_open sends bOpen=True."""
        entity, coord = _make_lock(hass, mock_config_entry)
        hass.loop.run_until_complete(entity.async_open())
        cmd = coord.async_send_command.call_args[0][1]
        assert cmd[f"{entity.widget.path}.{VAL_LOCK_OPEN}"] is True

    def test_read_only_raises(self, hass, mock_config_entry) -> None:
        """Test commands raise for read-only lock."""
        entity, _ = _make_lock(hass, mock_config_entry)
        entity.widget.metadata.read_only = True
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_lock())
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_unlock())
        with pytest.raises(ServiceValidationError):
            hass.loop.run_until_complete(entity.async_open())

    def test_create_locks_wrong_type(self, hass, mock_config_entry) -> None:
        """Test _create_locks returns empty for non-Lock widgets."""
        dev = build_device_with_widgets(DEVICE_NAME, ["widgets/plug.json"])
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        assert _create_locks(coordinator, DEVICE_NAME, widget) == []

    def test_unique_id(self, hass, mock_config_entry) -> None:
        """Test unique_id is set correctly."""
        entity, _ = _make_lock(hass, mock_config_entry)
        assert entity.unique_id is not None
        assert "stLock" in entity.unique_id
