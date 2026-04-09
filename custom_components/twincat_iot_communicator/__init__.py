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
ATTR_DEVICE_NAME = "device_name"
ATTR_MESSAGE_ID = "message_id"
ATTR_ACKNOWLEDGEMENT = "acknowledgement"

SERVICE_ACKNOWLEDGE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
    vol.Optional(ATTR_MESSAGE_ID): cv.string,
    vol.Optional(ATTR_ACKNOWLEDGEMENT, default="Acknowledged"): cv.string,
})

SERVICE_DELETE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_NAME): cv.string,
    vol.Optional(ATTR_MESSAGE_ID): cv.string,
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

    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE_MESSAGE,
        handle_acknowledge, schema=SERVICE_ACKNOWLEDGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_MESSAGE,
        handle_delete, schema=SERVICE_DELETE_SCHEMA,
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
    """Remove a TcIoT device from the config entry.

    Only hub devices (no via_device) can be removed. Widget sub-devices
    are cleaned up automatically when their parent hub device is removed.
    """
    if device_entry.via_device_id is not None:
        return False

    coordinator: TcIotCoordinator | None = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return False

    device_name: str | None = None
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN:
            prefix = f"{entry.entry_id}_"
            if identifier.startswith(prefix):
                device_name = identifier.removeprefix(prefix)
                break

    if device_name is None:
        return False

    await coordinator.async_remove_device(device_name)

    dev_reg = dr.async_get(hass)
    sub_prefix = f"{entry.entry_id}_{device_name}_"
    for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for domain, ident in dev.identifiers:
            if domain == DOMAIN and ident.startswith(sub_prefix):
                dev_reg.async_remove_device(dev.id)
                break

    selected: list[str] = list(entry.data.get(CONF_SELECTED_DEVICES) or [])
    if device_name in selected:
        selected.remove(device_name)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_SELECTED_DEVICES: selected},
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TcIotConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: TcIotCoordinator = entry.runtime_data
    await coordinator.async_stop()

    _LOGGER.info("TcIoT Communicator unloaded: %s", coordinator.main_topic)
    return unload_ok
