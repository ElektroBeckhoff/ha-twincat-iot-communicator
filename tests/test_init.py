"""Tests for TwinCAT IoT Communicator setup and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from homeassistant.components.twincat_iot_communicator import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ACKNOWLEDGEMENT,
    ATTR_DEVICE_NAME,
    ATTR_MESSAGE_ID,
    ATTR_MESSAGE_TEXT,
    ATTR_MESSAGE_TYPE,
    SERVICE_ACKNOWLEDGE_MESSAGE,
    SERVICE_DELETE_MESSAGE,
    SERVICE_REMOVE_STALE_WIDGETS,
    SERVICE_REQUEST_SNAPSHOT,
    SERVICE_SEND_MESSAGE,
    _find_coordinator,
)
from homeassistant.components.twincat_iot_communicator.const import (
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    DOMAIN,
)
from homeassistant.components.twincat_iot_communicator.models import TcIotMessage
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .conftest import MOCK_DEVICE_NAME, build_device_with_widgets, create_mock_coordinator

from tests.common import MockConfigEntry


async def _setup_entry_with_mock_coordinator(
    hass: HomeAssistant, entry: MockConfigEntry
) -> AsyncMock:
    """Set up a config entry with a mocked coordinator."""
    coordinator = create_mock_coordinator(
        hass,
        entry,
        {MOCK_DEVICE_NAME: build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/base/widget-lighting.json"])},
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.twincat_iot_communicator.TcIotCoordinator",
        return_value=coordinator,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return coordinator


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful setup of a config entry."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator.async_start.assert_awaited_once()


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test unloading a config entry stops the coordinator."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    coordinator.async_stop.assert_awaited_once()


async def test_services_registered(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that all services are registered during setup."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    assert hass.services.has_service(DOMAIN, SERVICE_ACKNOWLEDGE_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_DELETE_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_REQUEST_SNAPSHOT)
    assert hass.services.has_service(DOMAIN, SERVICE_REMOVE_STALE_WIDGETS)


async def test_find_coordinator_requires_entry_id_for_duplicate_device_names(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Duplicate PLC device names across entries must not route arbitrarily."""
    coord1 = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        data={
            **mock_config_entry.data,
            CONF_MAIN_TOPIC: "Other.Sample",
        },
        unique_id="test-duplicate-device",
        title="Test Duplicate",
        version=2,
        minor_version=4,
    )
    coord2 = await _setup_entry_with_mock_coordinator(hass, entry2)

    with pytest.raises(ServiceValidationError):
        _find_coordinator(hass, MOCK_DEVICE_NAME)

    assert _find_coordinator(
        hass, MOCK_DEVICE_NAME, mock_config_entry.entry_id,
    ) is coord1
    assert _find_coordinator(hass, MOCK_DEVICE_NAME, entry2.entry_id) is coord2


async def test_service_accepts_config_entry_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Services can select the intended duplicate device by config_entry_id."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REQUEST_SNAPSHOT,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_CONFIG_ENTRY_ID: mock_config_entry.entry_id,
        },
        blocking=True,
    )

    coordinator.async_request_full_update.assert_awaited_once_with(MOCK_DEVICE_NAME)


async def test_unload_platforms_before_coordinator_stop(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that platforms are unloaded before the coordinator is stopped."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    call_order: list[str] = []
    original_unload = hass.config_entries.async_unload_platforms

    async def track_unload(*args, **kwargs):
        call_order.append("unload_platforms")
        return await original_unload(*args, **kwargs)

    async def track_stop(*args, **kwargs):
        call_order.append("async_stop")

    coordinator.async_stop = AsyncMock(side_effect=track_stop)

    with patch.object(
        hass.config_entries, "async_unload_platforms", side_effect=track_unload
    ):
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert call_order == ["unload_platforms", "async_stop"]


async def test_services_persist_after_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that services persist after config entry unload (registered in async_setup)."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    assert hass.services.has_service(DOMAIN, SERVICE_ACKNOWLEDGE_MESSAGE)

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_ACKNOWLEDGE_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_DELETE_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE)
    assert hass.services.has_service(DOMAIN, SERVICE_REQUEST_SNAPSHOT)
    assert hass.services.has_service(DOMAIN, SERVICE_REMOVE_STALE_WIDGETS)


async def test_migrate_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that async_migrate_entry returns True."""
    from homeassistant.components.twincat_iot_communicator import async_migrate_entry

    mock_config_entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, mock_config_entry) is True


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test removing a device updates config entry and calls coordinator."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.async_remove_device = AsyncMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is True
    coordinator.async_remove_device.assert_awaited_once_with(MOCK_DEVICE_NAME)
    assert MOCK_DEVICE_NAME not in (
        mock_config_entry.data.get(CONF_SELECTED_DEVICES) or []
    )


async def test_remove_config_entry_device_unknown_identifier(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test removing a device with non-matching identifier returns False."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.async_remove_device = AsyncMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("other_domain", "other_id")},
        name="Other",
    )

    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is False
    coordinator.async_remove_device.assert_not_awaited()


async def test_service_acknowledge_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test acknowledge_message service calls coordinator."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_MESSAGE_ID: "42",
            ATTR_ACKNOWLEDGEMENT: "OK",
        },
        blocking=True,
    )

    coordinator.async_acknowledge_message.assert_awaited_once_with(
        MOCK_DEVICE_NAME, "42", "OK",
    )


async def test_service_acknowledge_default_text(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test acknowledge_message uses default acknowledgement text."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_MESSAGE_ID: "1",
        },
        blocking=True,
    )

    coordinator.async_acknowledge_message.assert_awaited_once_with(
        MOCK_DEVICE_NAME, "1", "Acknowledged",
    )


async def test_service_delete_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test delete_message service calls coordinator."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_DELETE_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_MESSAGE_ID: "7",
        },
        blocking=True,
    )

    coordinator.async_delete_message.assert_awaited_once_with(
        MOCK_DEVICE_NAME, "7",
    )


@pytest.mark.parametrize(
    ("service", "extra"),
    [
        (SERVICE_ACKNOWLEDGE_MESSAGE, {ATTR_ACKNOWLEDGEMENT: "OK"}),
        (SERVICE_DELETE_MESSAGE, {}),
    ],
)
async def test_service_device_not_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    service: str,
    extra: dict,
) -> None:
    """Test service raises when device is unknown."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            service,
            {ATTR_DEVICE_NAME: "NonExistent", ATTR_MESSAGE_ID: "1", **extra},
            blocking=True,
        )


async def test_service_acknowledge_all_messages(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test acknowledge without message_id processes all messages."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    dev = coordinator.get_device(MOCK_DEVICE_NAME)
    dev.messages["1"] = TcIotMessage(
        message_id="1", timestamp="2026-01-01T00:00:00", text="msg1",
    )
    dev.messages["2"] = TcIotMessage(
        message_id="2", timestamp="2026-01-01T00:01:00", text="msg2",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_ACKNOWLEDGEMENT: "ACK",
        },
        blocking=True,
    )

    assert coordinator.async_acknowledge_message.await_count == 2
    coordinator.async_acknowledge_message.assert_has_awaits(
        [call(MOCK_DEVICE_NAME, "1", "ACK"), call(MOCK_DEVICE_NAME, "2", "ACK")],
        any_order=True,
    )


async def test_service_delete_all_messages(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test delete without message_id processes all messages."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    dev = coordinator.get_device(MOCK_DEVICE_NAME)
    dev.messages["3"] = TcIotMessage(
        message_id="3", timestamp="2026-01-01T00:00:00", text="msg3",
    )
    dev.messages["4"] = TcIotMessage(
        message_id="4", timestamp="2026-01-01T00:01:00", text="msg4",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_DELETE_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
        },
        blocking=True,
    )

    assert coordinator.async_delete_message.await_count == 2
    coordinator.async_delete_message.assert_has_awaits(
        [call(MOCK_DEVICE_NAME, "3"), call(MOCK_DEVICE_NAME, "4")],
        any_order=True,
    )


@pytest.mark.parametrize(
    ("service", "coordinator_method"),
    [
        (SERVICE_ACKNOWLEDGE_MESSAGE, "async_acknowledge_message"),
        (SERVICE_DELETE_MESSAGE, "async_delete_message"),
    ],
)
async def test_service_all_no_messages(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    service: str,
    coordinator_method: str,
) -> None:
    """Test service without message_id on empty device is a no-op."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        service,
        {ATTR_DEVICE_NAME: MOCK_DEVICE_NAME},
        blocking=True,
    )

    getattr(coordinator, coordinator_method).assert_not_awaited()


# ── Hub Device removal guard ─────────────────────────────────────────


async def test_remove_hub_device_blocked_when_online(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that an online Hub Device cannot be deleted."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.is_device_removable = MagicMock(return_value=False)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is False
    coordinator.async_remove_device.assert_not_awaited()


async def test_remove_hub_device_allowed_when_offline(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that an offline Hub Device can be deleted."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.is_device_removable = MagicMock(return_value=True)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is True
    coordinator.async_remove_device.assert_awaited_once_with(MOCK_DEVICE_NAME)
    coordinator.reconcile_stale_device_repair.assert_called_once()


async def test_remove_hub_device_allowed_when_not_in_coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that a Hub Device unknown to the coordinator can be deleted."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.devices = {}
    coordinator.is_device_removable = MagicMock(return_value=True)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is True
    coordinator.async_remove_device.assert_awaited_once_with(MOCK_DEVICE_NAME)
    coordinator.reconcile_stale_device_repair.assert_called_once()


# ── Widget Sub-Device removal guard ──────────────────────────────────


async def test_remove_widget_device_allowed_when_stale(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that a stale Widget Sub-Device can be deleted."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.is_widget_removable = MagicMock(return_value=True)

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    widget = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stLighting")},
        name="Strahler Couch",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, widget,
    )

    assert result is True
    coordinator.is_widget_removable.assert_called_once_with(MOCK_DEVICE_NAME, "stLighting")
    coordinator.async_remove_widget.assert_awaited_once_with(MOCK_DEVICE_NAME, "stLighting")
    coordinator.reconcile_stale_device_repair.assert_called_once()


async def test_remove_widget_device_blocked_when_active(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that an active Widget Sub-Device cannot be deleted."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.is_widget_removable = MagicMock(return_value=False)

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    widget = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stLighting")},
        name="Strahler Couch",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, widget,
    )

    assert result is False
    coordinator.async_remove_widget.assert_not_awaited()


async def test_remove_widget_device_allowed_when_hub_offline(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that a Widget Sub-Device can be deleted when its Hub is offline."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.is_widget_removable = MagicMock(return_value=True)

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    widget = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stBlinds")},
        name="Raffstore Süd",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, widget,
    )

    assert result is True
    coordinator.is_widget_removable.assert_called_once_with(MOCK_DEVICE_NAME, "stBlinds")
    coordinator.async_remove_widget.assert_awaited_once_with(MOCK_DEVICE_NAME, "stBlinds")


async def test_remove_device_coordinator_none(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that device removal returns False when runtime_data is not set."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = None

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device,
    )

    assert result is False


async def test_remove_widget_parent_not_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that widget removal returns False when parent hub device is gone."""
    from homeassistant.components.twincat_iot_communicator import (
        async_remove_config_entry_device,
    )

    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    fake_widget = MagicMock(spec=dr.DeviceEntry)
    fake_widget.identifiers = {
        (DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stPlug")
    }
    fake_widget.via_device_id = "nonexistent_device_id"

    result = await async_remove_config_entry_device(
        hass, mock_config_entry, fake_widget,
    )

    assert result is False
    coordinator.async_remove_widget.assert_not_awaited()


# ── send_message service ─────────────────────────────────────────────


async def test_service_send_message_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test send_message service calls coordinator."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_MESSAGE_TEXT: "Hello PLC",
            ATTR_MESSAGE_TYPE: "Info",
        },
        blocking=True,
    )

    coordinator.async_send_message.assert_awaited_once_with(
        MOCK_DEVICE_NAME, "Hello PLC", "Info",
    )


async def test_service_send_message_default_type(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test send_message uses default type 'Default' when not specified."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        {
            ATTR_DEVICE_NAME: MOCK_DEVICE_NAME,
            ATTR_MESSAGE_TEXT: "Test message",
        },
        blocking=True,
    )

    coordinator.async_send_message.assert_awaited_once_with(
        MOCK_DEVICE_NAME, "Test message", "Default",
    )


async def test_service_send_message_device_not_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test send_message raises when device is unknown."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            {
                ATTR_DEVICE_NAME: "NonExistent",
                ATTR_MESSAGE_TEXT: "Hello",
            },
            blocking=True,
        )


# ── request_snapshot service ─────────────────────────────────────────


async def test_service_request_snapshot_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test request_snapshot service calls coordinator."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REQUEST_SNAPSHOT,
        {ATTR_DEVICE_NAME: MOCK_DEVICE_NAME},
        blocking=True,
    )

    coordinator.async_request_full_update.assert_awaited_once_with(MOCK_DEVICE_NAME)


async def test_service_request_snapshot_device_not_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test request_snapshot raises when device is unknown."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REQUEST_SNAPSHOT,
            {ATTR_DEVICE_NAME: "NonExistent"},
            blocking=True,
        )


# ── remove_stale_widgets service ─────────────────────────────────────


async def test_service_remove_stale_widgets_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test remove_stale_widgets service removes stale widgets."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.get_stale_widget_info.return_value = [
        (MOCK_DEVICE_NAME, "stPlug"),
    ]

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}")},
        name=MOCK_DEVICE_NAME,
    )
    dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}_stPlug")},
        name="Steckdose",
        via_device=(DOMAIN, f"{mock_config_entry.entry_id}_{MOCK_DEVICE_NAME}"),
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_REMOVE_STALE_WIDGETS,
        {ATTR_DEVICE_NAME: MOCK_DEVICE_NAME},
        blocking=True,
    )

    coordinator.async_remove_widget.assert_awaited_once_with(MOCK_DEVICE_NAME, "stPlug")
    coordinator.reconcile_stale_device_repair.assert_called()


async def test_service_remove_stale_widgets_no_stale(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test remove_stale_widgets raises when no stale widgets exist."""
    coordinator = await _setup_entry_with_mock_coordinator(hass, mock_config_entry)
    coordinator.get_stale_widget_info.return_value = []

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REMOVE_STALE_WIDGETS,
            {ATTR_DEVICE_NAME: MOCK_DEVICE_NAME},
            blocking=True,
        )


async def test_service_remove_stale_widgets_device_not_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test remove_stale_widgets raises when device is unknown."""
    await _setup_entry_with_mock_coordinator(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REMOVE_STALE_WIDGETS,
            {ATTR_DEVICE_NAME: "NonExistent"},
            blocking=True,
        )
