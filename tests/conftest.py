"""Fixtures for TwinCAT IoT Communicator tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.twincat_iot_communicator.const import (
    AUTH_MODE_CREDENTIALS,
    AUTH_MODE_ONLINE,
    CONF_ASSIGN_DEVICES_TO_AREAS,
    CONF_AUTH_MODE,
    CONF_AUTH_URL,
    CONF_CREATE_AREAS,
    CONF_JWT_TOKEN,
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    CONF_USE_TLS,
    DATATYPE_ARRAY_BOOL,
    DATATYPE_ARRAY_NUMBER,
    DATATYPE_ARRAY_STRING,
    DATATYPE_BOOL,
    DATATYPE_NUMBER,
    DATATYPE_STRING,
    DOMAIN,
)
from homeassistant.components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
    parse_metadata,
)
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from tests.common import MockConfigEntry


def attach_entity_to_hass(hass: HomeAssistant, entity: Entity, domain: str) -> None:
    """Bind a standalone test entity so async_write_ha_state() can run.

    Unit tests construct entities without going through EntityPlatform; HA Core
    requires both hass and entity_id before writing state.
    """
    uid = str(getattr(entity, "unique_id", "test"))
    safe = "t_" + "".join(
        c if c.isalnum() or c in "_-" else "_" for c in uid
    )[:115]
    entity.hass = hass
    entity.entity_id = f"{domain}.{safe.lower()}"
    # Avoid name resolution via translation_key when platform_data is unset (HA 2025+).
    if getattr(entity, "_attr_name", None) is None:
        entity._attr_name = "Test"

FIXTURES_DIR = Path(__file__).parent / "fixtures"

MOCK_HOST = "192.168.1.100"
MOCK_PORT = 1883
MOCK_MAIN_TOPIC = "IotApp.Sample"
MOCK_DEVICE_NAME = "Usermode"

MOCK_ENTRY_DATA = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_USE_TLS: False,
    CONF_AUTH_MODE: AUTH_MODE_CREDENTIALS,
    CONF_USERNAME: "testuser",
    CONF_PASSWORD: "testpass",
    CONF_MAIN_TOPIC: MOCK_MAIN_TOPIC,
    CONF_SELECTED_DEVICES: [MOCK_DEVICE_NAME],
    CONF_CREATE_AREAS: True,
    CONF_ASSIGN_DEVICES_TO_AREAS: True,
}

MOCK_ENTRY_DATA_OAUTH = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_USE_TLS: False,
    CONF_AUTH_MODE: AUTH_MODE_ONLINE,
    CONF_USERNAME: "oauth_user",
    CONF_PASSWORD: "",
    CONF_MAIN_TOPIC: MOCK_MAIN_TOPIC,
    CONF_SELECTED_DEVICES: [MOCK_DEVICE_NAME],
    CONF_CREATE_AREAS: True,
    CONF_ASSIGN_DEVICES_TO_AREAS: True,
    CONF_JWT_TOKEN: "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvYXV0aF91c2VyIiwiZXhwIjo5OTk5OTk5OTk5fQ.fake",
    CONF_CLIENT_ID: "tc-iot-client-id-secret",
    CONF_AUTH_URL: "https://auth.internal.example.com/realms/plc",
}


def load_fixture_json(name: str) -> dict[str, Any]:
    """Load a JSON fixture file by name."""
    return json.loads((FIXTURES_DIR / name).read_text())


def _build_widget_from_fixture(fixture_name: str) -> tuple[str, WidgetData]:
    """Build a WidgetData from a JSON fixture file.

    Returns (widget_id, widget_data).
    """
    data = load_fixture_json(fixture_name)
    values_root = data["Values"]
    metadata_root = data["MetaData"]

    widget_id = next(iter(values_root))
    raw_values = values_root[widget_id]
    raw_meta = metadata_root.get(widget_id, {})

    meta = parse_metadata(raw_meta)

    field_metadata: dict[str, dict[str, str]] = {}
    for key in metadata_root:
        if key.startswith(f"{widget_id}."):
            field_name = key[len(widget_id) + 1 :]
            field_metadata[field_name] = metadata_root[key]

    is_scalar = not isinstance(raw_values, dict)
    if is_scalar:
        wid = widget_id
        values = {"value": raw_values}
    else:
        wid = widget_id
        values = {k: v for k, v in raw_values.items() if k != "sDisplayName"}

    widget = WidgetData(
        widget_id=wid,
        path=wid,
        metadata=meta,
        values=values,
        friendly_path=meta.display_name,
        field_metadata=field_metadata,
    )

    if not meta.widget_type and is_scalar:
        val = values.get("value")
        if isinstance(val, list):
            if val and isinstance(val[0], bool):
                widget.metadata.widget_type = DATATYPE_ARRAY_BOOL
            elif val and isinstance(val[0], (int, float)):
                widget.metadata.widget_type = DATATYPE_ARRAY_NUMBER
            elif val and isinstance(val[0], str):
                widget.metadata.widget_type = DATATYPE_ARRAY_STRING
            widget.metadata.read_only = True
        elif isinstance(val, bool):
            widget.metadata.widget_type = DATATYPE_BOOL
        elif isinstance(val, (int, float)):
            widget.metadata.widget_type = DATATYPE_NUMBER
        elif isinstance(val, str):
            widget.metadata.widget_type = DATATYPE_STRING

    return wid, widget


def build_device_with_widgets(
    device_name: str, fixture_names: list[str]
) -> DeviceContext:
    """Build a DeviceContext loaded with widgets from fixture files."""
    dev = DeviceContext(device_name=device_name)
    dev.online = True
    dev.registered = True
    dev.awaiting_full_snapshot = False
    for fname in fixture_names:
        wid, widget = _build_widget_from_fixture(fname)
        dev.widgets[wid] = widget
        dev.known_widget_paths.add(wid)
    return dev


def build_device_from_multi_widget_fixture(
    device_name: str, fixture_name: str
) -> DeviceContext:
    """Build a DeviceContext from a fixture containing multiple widgets.

    Parses all widget entries in Values/MetaData (both dict and scalar).
    """
    data = load_fixture_json(fixture_name)
    values_root = data["Values"]
    metadata_root = data.get("MetaData", {})

    dev = DeviceContext(device_name=device_name)
    dev.online = True
    dev.registered = True
    dev.awaiting_full_snapshot = False

    for wid, raw_values in values_root.items():
        raw_meta = metadata_root.get(wid, {})
        meta = parse_metadata(raw_meta)

        field_metadata: dict[str, dict[str, str]] = {}
        for key in metadata_root:
            if key.startswith(f"{wid}."):
                field_name = key[len(wid) + 1 :]
                field_metadata[field_name] = metadata_root[key]

        is_scalar = not isinstance(raw_values, dict)
        if is_scalar:
            values = {"value": raw_values}
        else:
            values = {k: v for k, v in raw_values.items() if k != "sDisplayName"}

        widget = WidgetData(
            widget_id=wid,
            path=wid,
            metadata=meta,
            values=values,
            friendly_path=meta.display_name,
            field_metadata=field_metadata,
        )

        if not meta.widget_type and is_scalar:
            val = values.get("value")
            if isinstance(val, list):
                if val and isinstance(val[0], bool):
                    widget.metadata.widget_type = DATATYPE_ARRAY_BOOL
                elif val and isinstance(val[0], (int, float)):
                    widget.metadata.widget_type = DATATYPE_ARRAY_NUMBER
                elif val and isinstance(val[0], str):
                    widget.metadata.widget_type = DATATYPE_ARRAY_STRING
                widget.metadata.read_only = True
            elif isinstance(val, bool):
                widget.metadata.widget_type = DATATYPE_BOOL
            elif isinstance(val, (int, float)):
                widget.metadata.widget_type = DATATYPE_NUMBER
            elif isinstance(val, str):
                widget.metadata.widget_type = DATATYPE_STRING

        dev.widgets[wid] = widget
        dev.known_widget_paths.add(wid)

    return dev


def create_mock_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    devices: dict[str, DeviceContext] | None = None,
) -> MagicMock:
    """Create a mock TcIotCoordinator."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.entry = entry
    coordinator.hostname = entry.data[CONF_HOST]
    coordinator.main_topic = entry.data[CONF_MAIN_TOPIC]
    coordinator.connected = True
    coordinator.devices = devices or {}
    coordinator._listeners = {}
    coordinator.async_start = AsyncMock()
    coordinator.async_stop = AsyncMock()
    coordinator.async_send_command = AsyncMock()
    coordinator.async_acknowledge_message = AsyncMock()
    coordinator.async_delete_message = AsyncMock()
    coordinator.async_request_full_update = AsyncMock()
    coordinator.register_listener = MagicMock(return_value=MagicMock())
    coordinator.register_new_widget_callback = MagicMock()
    coordinator.register_new_device_callback = MagicMock()
    coordinator.register_hub_status_callback = MagicMock(return_value=MagicMock())
    coordinator.register_message_callback = MagicMock(return_value=MagicMock())
    coordinator.get_device = MagicMock(
        side_effect=lambda name: (devices or {}).get(name)
    )
    coordinator.get_area_for_widget = MagicMock(return_value=None)
    coordinator.on_areas_ready = MagicMock(return_value=MagicMock())
    coordinator.listener_count = 0
    return coordinator


def make_widget_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    fixture: str,
    entity_cls: type,
    domain: str,
    device_name: str = MOCK_DEVICE_NAME,
) -> tuple:
    """Generic helper: build a device from *fixture*, instantiate *entity_cls*, and bind to hass.

    Returns (entity, coordinator).
    """
    dev = build_device_with_widgets(device_name, [fixture])
    coordinator = create_mock_coordinator(hass, entry, {device_name: dev})
    widget = next(iter(dev.widgets.values()))
    entity = entity_cls(coordinator, device_name, widget)
    attach_entity_to_hass(hass, entity, domain)
    return entity, coordinator


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock config entry for credentials auth."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA,
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}_{MOCK_MAIN_TOPIC}",
        title=f"TcIoT {MOCK_MAIN_TOPIC} ({MOCK_HOST})",
        version=2,
        minor_version=4,
    )


@pytest.fixture
def mock_config_entry_oauth() -> MockConfigEntry:
    """Create a mock config entry for OAuth auth."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA_OAUTH,
        unique_id=f"{MOCK_HOST}:{MOCK_PORT}_{MOCK_MAIN_TOPIC}",
        title=f"TcIoT {MOCK_MAIN_TOPIC} ({MOCK_HOST})",
        version=2,
        minor_version=4,
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Patch async_setup_entry for config flow tests."""
    with patch(
        "homeassistant.components.twincat_iot_communicator.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def mock_aiomqtt() -> Generator[MagicMock]:
    """Patch aiomqtt.Client for config flow broker tests."""
    with patch(
        "homeassistant.components.twincat_iot_communicator.config_flow.aiomqtt.Client"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.subscribe = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client_cls.return_value = mock_client
        yield mock_client_cls
