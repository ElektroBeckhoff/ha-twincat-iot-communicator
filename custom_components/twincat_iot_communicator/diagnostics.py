"""Diagnostics support for TwinCAT IoT Communicator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_CLIENT_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TcIotConfigEntry
from .const import AUTH_MODE_ONLINE, CONF_AUTH_MODE, CONF_AUTH_URL, CONF_JWT_TOKEN
from .jwt_helper import (
    decode_jwt_unverified,
    jwt_expiry_summary,
    jwt_is_expired,
    jwt_remaining_seconds,
)

TO_REDACT_CONFIG = frozenset(
    {CONF_PASSWORD, CONF_USERNAME, CONF_JWT_TOKEN, CONF_CLIENT_ID, CONF_AUTH_URL}
)
TO_REDACT_DEVICE = frozenset({"permitted_users"})


def _jwt_diagnostics(token: str) -> dict[str, Any]:
    """Extract non-sensitive JWT metadata for diagnostics."""
    try:
        claims = decode_jwt_unverified(token)
    except (ValueError, Exception):  # noqa: BLE001
        return {"error": "invalid_jwt_format"}

    exp = claims.get("exp")
    result: dict[str, Any] = {
        "expired": jwt_is_expired(token),
        "validity": jwt_expiry_summary(token),
    }
    remaining = jwt_remaining_seconds(token)
    if remaining is not None:
        result["remaining_seconds"] = round(remaining)
    if isinstance(exp, (int, float)):
        result["expires_at"] = datetime.fromtimestamp(exp, tz=UTC).isoformat()
    iss = claims.get("iss")
    if iss:
        result["issuer"] = iss
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: TcIotConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    if coordinator is None:
        return {
            "config_entry": async_redact_data(entry.data, TO_REDACT_CONFIG),
            "error": "integration not loaded",
        }

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
            "awaiting_full_snapshot": device.awaiting_full_snapshot,
        }

    coordinator_data: dict[str, Any] = {
        "connected": coordinator.connected,
        "hostname": coordinator.hostname,
        "main_topic": coordinator.main_topic,
        "device_count": len(coordinator.devices),
        "listener_count": coordinator.listener_count,
    }

    jwt_token = entry.data.get(CONF_JWT_TOKEN)
    if entry.data.get(CONF_AUTH_MODE) == AUTH_MODE_ONLINE and jwt_token:
        coordinator_data["jwt"] = _jwt_diagnostics(jwt_token)

    return {
        "config_entry": async_redact_data(entry.data, TO_REDACT_CONFIG),
        "coordinator": coordinator_data,
        "devices": {
            name: async_redact_data(info, TO_REDACT_DEVICE)
            for name, info in devices_data.items()
        },
    }
