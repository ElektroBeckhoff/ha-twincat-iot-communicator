"""Tests for the TwinCAT IoT Communicator config flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt
import pytest

from homeassistant import config_entries
from homeassistant.components.twincat_iot_communicator.const import (
    AUTH_MODE_CREDENTIALS,
    AUTH_MODE_ONLINE,
    CONF_AUTH_MODE,
    CONF_AUTH_URL,
    CONF_JWT_TOKEN,
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    CONF_USE_TLS,
    DEFAULT_MAIN_TOPIC,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MOCK_ENTRY_DATA, MOCK_HOST, MOCK_MAIN_TOPIC, MOCK_PORT

from tests.common import MockConfigEntry


BROKER_INPUT = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_USE_TLS: False,
}

CREDENTIALS_INPUT = {
    CONF_USERNAME: "testuser",
    CONF_PASSWORD: "testpass",
}

TOPIC_INPUT = {
    CONF_MAIN_TOPIC: MOCK_MAIN_TOPIC,
}


async def test_full_flow_no_auth(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test full flow: broker -> no_auth -> topic -> select_devices -> create."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "auth_method"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "no_auth"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "topic"

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECTED_DEVICES: ["Usermode"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == MOCK_HOST
    assert result["data"][CONF_SELECTED_DEVICES] == ["Usermode"]
    assert result["data"][CONF_AUTH_MODE] == AUTH_MODE_CREDENTIALS
    assert result["data"][CONF_USERNAME] == ""


async def test_full_flow_with_credentials(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test flow: broker -> credentials -> topic -> select_devices -> create."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "topic"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["step_id"] == "select_devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECTED_DEVICES: ["Usermode"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "testuser"
    assert result["data"][CONF_PASSWORD] == "testpass"


async def test_broker_cannot_connect(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test broker connection failure with OSError."""
    mock_aiomqtt.return_value.__aenter__.side_effect = OSError("Connection refused")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_broker_invalid_auth(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test broker returns rc=5 (not authorized)."""
    mock_aiomqtt.return_value.__aenter__.side_effect = aiomqtt.MqttCodeError(
        rc=5,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_broker_timeout(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test broker connection timeout."""
    mock_aiomqtt.return_value.__aenter__.side_effect = asyncio.TimeoutError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "credentials"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "connection_timeout"}


async def test_no_devices_found(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test topic scan finds no devices."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "no_auth"}
    )

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(MOCK_MAIN_TOPIC, [])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "topic"
    assert result["errors"] == {"base": "no_devices_found"}


async def test_no_devices_selected(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test user selects no devices."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "no_auth"}
    )

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["step_id"] == "select_devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECTED_DEVICES: []}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices_selected"}


async def test_all_devices_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test abort when all discovered devices are already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "no_auth"}
    )

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "all_devices_configured"


async def test_duplicate_entry(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test abort for duplicate unique_id."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "no_auth"}
    )

    mock_instance = mock_aiomqtt.return_value
    mock_instance.messages = _make_device_messages(
        MOCK_MAIN_TOPIC, ["Usermode", "OtherDevice"]
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], TOPIC_INPUT
    )
    assert result["step_id"] == "select_devices"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECTED_DEVICES: ["OtherDevice"]}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _setup_oauth_flow(
    hass: HomeAssistant, mock_aiomqtt: MagicMock
) -> dict:
    """Set up OAuth flow up to the obtain_token external step.

    Returns the flow result at the EXTERNAL_STEP stage.
    """
    hass.http = MagicMock()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BROKER_INPUT
    )

    with (
        patch(
            "homeassistant.components.twincat_iot_communicator.config_flow.http.current_request"
        ) as mock_req_ctx,
        patch(
            "homeassistant.components.twincat_iot_communicator.config_flow.TcIotCommunicatorConfigFlow._discover_oidc",
            return_value=False,
        ),
    ):
        mock_request = MagicMock()
        mock_request.headers = {"HA-Frontend-Base": "http://localhost:8123"}
        mock_req_ctx.get.return_value = mock_request

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "auth_url"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_AUTH_URL: "https://auth.example.com"},
        )
        assert result["type"] is FlowResultType.EXTERNAL_STEP

    return result


async def test_oauth_token_timeout(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test OAuth aborts when no token is received."""
    result = await _setup_oauth_flow(hass, mock_aiomqtt)

    # Simulate the external step completing (callback would call this)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=None
    )
    # external_step_done transitions automatically to token_timeout → abort
    if result["type"] is FlowResultType.EXTERNAL_STEP_DONE:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "token_request_timeout"


async def test_oauth_token_invalid(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test OAuth aborts when JWT has no username."""
    import base64
    import json as json_mod

    payload = base64.urlsafe_b64encode(
        json_mod.dumps({"aud": "no_user", "exp": 9999999999}).encode()
    ).rstrip(b"=").decode()
    bad_token = f"eyJhbGciOiJSUzI1NiJ9.{payload}.fake"

    result = await _setup_oauth_flow(hass, mock_aiomqtt)

    from homeassistant.components.twincat_iot_communicator.config_flow import DATA_JWT_TOKENS

    hass.data.setdefault(DATA_JWT_TOKENS, {})[result["flow_id"]] = bad_token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=None
    )
    if result["type"] is FlowResultType.EXTERNAL_STEP_DONE:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_token"


async def test_oauth_token_expired(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
) -> None:
    """Test OAuth aborts when JWT is already expired."""
    import base64
    import json as json_mod

    payload = base64.urlsafe_b64encode(
        json_mod.dumps({"sub": "user", "exp": 1000000000}).encode()
    ).rstrip(b"=").decode()
    expired_token = f"eyJhbGciOiJSUzI1NiJ9.{payload}.fake"

    result = await _setup_oauth_flow(hass, mock_aiomqtt)

    from homeassistant.components.twincat_iot_communicator.config_flow import DATA_JWT_TOKENS

    hass.data.setdefault(DATA_JWT_TOKENS, {})[result["flow_id"]] = expired_token
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=None
    )
    if result["type"] is FlowResultType.EXTERNAL_STEP_DONE:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "token_expired"


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_aiomqtt: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test re-authentication flow for credentials."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"


# ── Helpers ──────────────────────────────────────────────────────────


class _MockMessageStream:
    """Mock async iterator for MQTT messages used in device scan."""

    def __init__(self, main_topic: str, device_names: list[str]) -> None:
        self._messages: list[MagicMock] = []
        for name in device_names:
            msg = MagicMock()
            msg.topic = f"{main_topic}/{name}/TcIotCommunicator/Desc"
            self._messages.append(msg)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index < len(self._messages):
            msg = self._messages[self._index]
            self._index += 1
            return msg
        raise StopAsyncIteration


def _make_device_messages(
    main_topic: str, device_names: list[str]
) -> _MockMessageStream:
    """Create a mock async iterator that yields MQTT messages for device discovery."""
    return _MockMessageStream(main_topic, device_names)


# ── Reconfigure flow tests ────────────────────────────────────────────


async def test_reconfigure_shows_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiomqtt: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure step shows currently selected and scanned devices."""
    mock_config_entry.add_to_hass(hass)

    mock_client = mock_aiomqtt.return_value
    mock_client.messages = _make_device_messages(
        MOCK_MAIN_TOPIC, ["Usermode", "NewDevice"]
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_updates_selected_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiomqtt: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure updates the selected devices list."""
    mock_config_entry.add_to_hass(hass)

    mock_client = mock_aiomqtt.return_value
    mock_client.messages = _make_device_messages(
        MOCK_MAIN_TOPIC, ["Usermode", "NewDevice"]
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    mock_client.messages = _make_device_messages(
        MOCK_MAIN_TOPIC, ["Usermode", "NewDevice"]
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_SELECTED_DEVICES: ["Usermode", "NewDevice"]},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_SELECTED_DEVICES] == [
        "Usermode",
        "NewDevice",
    ]


async def test_reconfigure_no_devices_selected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiomqtt: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure shows error when no devices are selected."""
    mock_config_entry.add_to_hass(hass)

    mock_client = mock_aiomqtt.return_value
    mock_client.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_client.messages = _make_device_messages(MOCK_MAIN_TOPIC, ["Usermode"])

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_SELECTED_DEVICES: []},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "no_devices_selected"


async def test_reconfigure_scan_failure_shows_current(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_aiomqtt: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure still shows current devices when broker scan fails."""
    mock_config_entry.add_to_hass(hass)

    mock_aiomqtt.side_effect = aiomqtt.MqttError("Connection refused")

    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
