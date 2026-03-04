"""Tests for TwinCAT IoT Communicator diagnostics."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.twincat_iot_communicator.const import (
    CONF_AUTH_URL,
    CONF_JWT_TOKEN,
    DOMAIN,
)
from homeassistant.const import CONF_CLIENT_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .conftest import (
    MOCK_DEVICE_NAME,
    build_device_with_widgets,
    create_mock_coordinator,
)

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry


async def _setup_diagnostics(
    hass: HomeAssistant, hass_client, entry: MockConfigEntry
) -> dict:
    """Set up the integration and return diagnostics output."""
    coordinator = create_mock_coordinator(
        hass,
        entry,
        {MOCK_DEVICE_NAME: build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/lighting.json"])},
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.twincat_iot_communicator.TcIotCoordinator",
        return_value=coordinator,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return await get_diagnostics_for_config_entry(
        hass, hass_client, entry
    )


async def test_diagnostics_output(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client,
) -> None:
    """Test diagnostics returns expected structure."""
    diag = await _setup_diagnostics(hass, hass_client, mock_config_entry)

    assert "config_entry" in diag
    assert "coordinator" in diag
    assert "devices" in diag
    assert diag["coordinator"]["connected"] is True
    assert MOCK_DEVICE_NAME in diag["devices"]


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant,
    mock_config_entry_oauth: MockConfigEntry,
    hass_client,
) -> None:
    """Test diagnostics redacts all sensitive config and device fields."""
    coordinator = create_mock_coordinator(
        hass,
        mock_config_entry_oauth,
        {MOCK_DEVICE_NAME: build_device_with_widgets(MOCK_DEVICE_NAME, ["widgets/lighting.json"])},
    )
    coordinator.devices[MOCK_DEVICE_NAME].permitted_users = "admin,operator"
    mock_config_entry_oauth.add_to_hass(hass)

    with patch(
        "homeassistant.components.twincat_iot_communicator.TcIotCoordinator",
        return_value=coordinator,
    ):
        await hass.config_entries.async_setup(mock_config_entry_oauth.entry_id)
        await hass.async_block_till_done()

    diag = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry_oauth
    )

    config = diag["config_entry"]
    assert config[CONF_USERNAME] == "**REDACTED**"
    assert config[CONF_JWT_TOKEN] == "**REDACTED**"
    assert config[CONF_CLIENT_ID] == "**REDACTED**"
    assert config[CONF_AUTH_URL] == "**REDACTED**"
    assert CONF_PASSWORD in config

    device_diag = diag["devices"][MOCK_DEVICE_NAME]
    assert device_diag["permitted_users"] == "**REDACTED**"
