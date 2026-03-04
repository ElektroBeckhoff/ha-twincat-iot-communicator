"""Diagnostics support for TwinCAT IoT Communicator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_CLIENT_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TcIotConfigEntry
from .const import CONF_AUTH_URL, CONF_JWT_TOKEN

TO_REDACT_CONFIG = frozenset(
    {CONF_PASSWORD, CONF_USERNAME, CONF_JWT_TOKEN, CONF_CLIENT_ID, CONF_AUTH_URL}
)
TO_REDACT_DEVICE = frozenset({"permitted_users"})


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    devices_data: dict[str, Any] = {}
    for name, device in coordinator.devices.items():
        devices_data[name] = {
            "online": device.online,
            "registered": device.registered,
            "icon": device.icon_name,
            "permitted_users": device.permitted_users,
            "widget_count": len(device.widgets),
            "known_widget_paths": len(device.known_widget_paths),
            "stale_widget_paths": sorted(device.stale_widget_paths),
            "message_count": len(device.messages),
            "initial_snapshot_received": device.initial_snapshot_received,
        }

    return {
        "config_entry": async_redact_data(entry.data, TO_REDACT_CONFIG),
        "coordinator": {
            "connected": coordinator.connected,
            "hostname": coordinator.hostname,
            "main_topic": coordinator.main_topic,
            "device_count": len(coordinator.devices),
            "listener_count": coordinator.listener_count,
        },
        "devices": {
            name: async_redact_data(info, TO_REDACT_DEVICE)
            for name, info in devices_data.items()
        },
    }
