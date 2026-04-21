"""TwinCAT IoT Communicator integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_ASSIGN_DEVICES_TO_AREAS,
    CONF_CREATE_AREAS,
    CONF_SELECTED_DEVICES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TcIotCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

type TcIotConfigEntry = ConfigEntry[TcIotCoordinator]

SERVICE_ACKNOWLEDGE_MESSAGE = "acknowledge_message"
SERVICE_DELETE_MESSAGE = "delete_message"
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_REQUEST_SNAPSHOT = "request_snapshot"
SERVICE_REMOVE_STALE_WIDGETS = "remove_stale_widgets"
ATTR_DEVICE_NAME = "device_name"
ATTR_MESSAGE_ID = "message_id"
ATTR_MESSAGE_TEXT = "message"
ATTR_MESSAGE_TYPE = "type"
ATTR_ACKNOWLEDGEMENT = "acknowledgement"

VALID_MESSAGE_TYPES = ("Default", "Info", "Warning", "Error", "Critical")

SERVICE_ACKNOWLEDGE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
    vol.Optional(ATTR_MESSAGE_ID): cv.string,
    vol.Optional(ATTR_ACKNOWLEDGEMENT, default="Acknowledged"): cv.string,
})

SERVICE_DELETE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
    vol.Optional(ATTR_MESSAGE_ID): cv.string,
})

SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
    vol.Required(ATTR_MESSAGE_TEXT): cv.string,
    vol.Optional(ATTR_MESSAGE_TYPE, default="Default"): vol.In(VALID_MESSAGE_TYPES),
})

SERVICE_DEVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
})


def _find_coordinator(hass: HomeAssistant, device_name: str) -> TcIotCoordinator | None:
    """Find the coordinator that owns the given device_name."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator: TcIotCoordinator = entry.runtime_data
        if coordinator.get_device(device_name):
            return coordinator
    return None


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up TwinCAT IoT Communicator services."""

    async def handle_acknowledge(call: ServiceCall) -> None:
        """Handle acknowledge_message service call."""
        device_name = call.data[ATTR_DEVICE_NAME]
        coord = _find_coordinator(hass, device_name)
        if coord is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": device_name},
            )
        message_id = call.data.get(ATTR_MESSAGE_ID)
        ack_text = call.data[ATTR_ACKNOWLEDGEMENT]
        if message_id:
            await coord.async_acknowledge_message(
                device_name, message_id, ack_text,
            )
        else:
            dev = coord.get_device(device_name)
            if dev:
                for mid in list(dev.messages):
                    await coord.async_acknowledge_message(
                        device_name, mid, ack_text,
                    )

    async def handle_delete(call: ServiceCall) -> None:
        """Handle delete_message service call."""
        device_name = call.data[ATTR_DEVICE_NAME]
        coord = _find_coordinator(hass, device_name)
        if coord is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": device_name},
            )
        message_id = call.data.get(ATTR_MESSAGE_ID)
        if message_id:
            await coord.async_delete_message(device_name, message_id)
        else:
            dev = coord.get_device(device_name)
            if dev:
                for mid in list(dev.messages):
                    await coord.async_delete_message(device_name, mid)

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle send_message service call."""
        device_name = call.data[ATTR_DEVICE_NAME]
        coord = _find_coordinator(hass, device_name)
        if coord is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": device_name},
            )
        await coord.async_send_message(
            device_name,
            call.data[ATTR_MESSAGE_TEXT],
            call.data[ATTR_MESSAGE_TYPE],
        )

    async def handle_request_snapshot(call: ServiceCall) -> None:
        """Handle request_snapshot service call."""
        device_name = call.data[ATTR_DEVICE_NAME]
        coord = _find_coordinator(hass, device_name)
        if coord is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": device_name},
            )
        await coord.async_request_full_update(device_name)

    async def handle_remove_stale_widgets(call: ServiceCall) -> None:
        """Handle remove_stale_widgets service call."""
        device_name = call.data[ATTR_DEVICE_NAME]
        coord = _find_coordinator(hass, device_name)
        if coord is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device": device_name},
            )
        stale = [
            (dn, wp) for dn, wp in coord.get_stale_widget_info()
            if dn == device_name
        ]
        if not stale:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_stale_widgets",
                translation_placeholders={"device": device_name},
            )
        entry = coord.entry
        dev_reg = dr.async_get(hass)
        for dn, widget_path in stale:
            await coord.async_remove_widget(dn, widget_path)
            widget_ident = (DOMAIN, f"{entry.entry_id}_{dn}_{widget_path}")
            widget_dev = dev_reg.async_get_device(identifiers={widget_ident})
            if widget_dev is not None:
                dev_reg.async_remove_device(widget_dev.id)
        coord.reconcile_stale_device_repair()

    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE_MESSAGE,
        handle_acknowledge, schema=SERVICE_ACKNOWLEDGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_MESSAGE,
        handle_delete, schema=SERVICE_DELETE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE,
        handle_send_message, schema=SERVICE_SEND_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REQUEST_SNAPSHOT,
        handle_request_snapshot, schema=SERVICE_DEVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_STALE_WIDGETS,
        handle_remove_stale_widgets, schema=SERVICE_DEVICE_SCHEMA,
    )

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: TcIotConfigEntry) -> bool:
    """Migrate config entries to the current version."""
    _LOGGER.debug(
        "Migrating config entry from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    if entry.version == 2 and entry.minor_version < 3:
        new_data = {**entry.data}
        new_data.setdefault(CONF_CREATE_AREAS, True)
        hass.config_entries.async_update_entry(
            entry, data=new_data, minor_version=3
        )
        _LOGGER.debug("Migrated config entry to version 2.3")

    if entry.version == 2 and entry.minor_version < 4:
        new_data = {**entry.data}
        new_data.setdefault(CONF_ASSIGN_DEVICES_TO_AREAS, True)
        hass.config_entries.async_update_entry(
            entry, data=new_data, minor_version=4
        )
        _LOGGER.debug("Migrated config entry to version 2.4")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: TcIotConfigEntry) -> bool:
    """Set up TwinCAT IoT Communicator from a config entry."""
    coordinator = TcIotCoordinator(hass, entry)
    await coordinator.async_start()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "TcIoT Communicator ready: %s on %s:%s",
        coordinator.main_topic,
        entry.data.get(CONF_HOST),
        entry.data.get(CONF_PORT),
    )
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Remove a TcIoT Hub Device or Widget Sub-Device from the config entry.

    Hub Devices (no via_device) are removable when offline or absent.
    Widget Sub-Devices are removable when their widget path is stale
    (absent from the last full snapshot) or their Hub Device is gone.
    Active, online devices are protected from deletion.
    """
    coordinator: TcIotCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return False

    prefix = f"{entry.entry_id}_"
    ident_value: str | None = None
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            ident_value = identifier.removeprefix(prefix)
            break

    if ident_value is None:
        return False

    if device_entry.via_device_id is None:
        # ── Hub Device ──
        device_name = ident_value
        if not coordinator.is_device_removable(device_name):
            return False

        await coordinator.async_remove_device(device_name)

        dev_reg = dr.async_get(hass)
        sub_prefix = f"{entry.entry_id}_{device_name}_"
        for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if dev.via_device_id is None:
                continue
            for d, i in dev.identifiers:
                if d == DOMAIN and i.startswith(sub_prefix):
                    dev_reg.async_remove_device(dev.id)
                    break

        selected: list[str] = list(entry.data.get(CONF_SELECTED_DEVICES) or [])
        if device_name in selected:
            selected.remove(device_name)
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_SELECTED_DEVICES: selected},
            )
    else:
        # ── Widget Sub-Device ──
        dev_reg = dr.async_get(hass)
        parent = dev_reg.async_get(device_entry.via_device_id)
        if parent is None:
            return False

        parent_name: str | None = None
        for d, i in parent.identifiers:
            if d == DOMAIN and i.startswith(prefix):
                parent_name = i.removeprefix(prefix)
                break
        if parent_name is None:
            return False

        widget_path = ident_value.removeprefix(f"{parent_name}_")
        if not coordinator.is_widget_removable(parent_name, widget_path):
            return False

        await coordinator.async_remove_widget(parent_name, widget_path)

    coordinator.reconcile_stale_device_repair()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TcIotConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: TcIotCoordinator = entry.runtime_data
    await coordinator.async_stop()

    _LOGGER.info("TcIoT Communicator unloaded: %s", coordinator.main_topic)
    return unload_ok
