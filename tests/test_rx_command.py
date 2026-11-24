"""Tests for the Rx/Data command payload (header and number types)."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.twincat_iot_communicator.coordinator import TcIotCoordinator
from custom_components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)

from .conftest import MOCK_DEVICE_NAME, MOCK_ENTRY_DATA, MOCK_MAIN_TOPIC

DOMAIN = "twincat_iot_communicator"
RX_TOPIC = f"{MOCK_MAIN_TOPIC}/{MOCK_DEVICE_NAME}/TcIotCommunicator/Json/Rx/Data"


def _coordinator(hass: HomeAssistant, data: dict[str, Any] | None = None) -> TcIotCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data or MOCK_ENTRY_DATA,
        unique_id="test",
        title="Test",
        version=2,
        minor_version=2,
    )
    coord = TcIotCoordinator(hass, entry)
    coord._client = AsyncMock()
    return coord


def _widget(path: str, widget_type: str, values: dict[str, Any]) -> WidgetData:
    return WidgetData(
        widget_id=path.rsplit(".", 1)[-1],
        path=path,
        metadata=WidgetMetaData(widget_type=widget_type),
        values=values,
    )


def _device(*widgets: WidgetData) -> DeviceContext:
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    for widget in widgets:
        dev.widgets[widget.path] = widget
    return dev


def _sent(coord: TcIotCoordinator) -> list[tuple[str, str]]:
    """Return (topic, raw payload) of every publish."""
    return [
        (call.args[0], call.kwargs["payload"])
        for call in coord._client.publish.call_args_list
    ]


class TestRxHeader:
    """Commands carry Timestamp, User and ClientId like the official app."""

    @pytest.mark.asyncio
    async def test_header_and_key_order(self, hass: HomeAssistant) -> None:
        coord = _coordinator(hass)
        await coord.async_send_command(MOCK_DEVICE_NAME, {"stPlug.bOn": True})

        [(topic, raw)] = _sent(coord)
        assert topic == RX_TOPIC
        payload = json.loads(raw)
        assert list(payload) == ["Timestamp", "User", "ClientId", "Values"]
        assert payload["User"] == "testuser"
        assert payload["ClientId"] == coord._client_id
        assert payload["Values"] == {"stPlug.bOn": True}

    @pytest.mark.asyncio
    async def test_timestamp_is_utc_iso_with_milliseconds(self, hass: HomeAssistant) -> None:
        coord = _coordinator(hass)
        await coord.async_send_command(MOCK_DEVICE_NAME, {"stPlug.bOn": False})

        stamp = json.loads(_sent(coord)[0][1])["Timestamp"]
        assert stamp.endswith("Z")
        # YYYY-MM-DDThh:mm:ss.fffZ
        assert len(stamp) == 24
        assert stamp[19] == "."
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert parsed.utcoffset().total_seconds() == 0

    @pytest.mark.asyncio
    async def test_user_left_out_without_mqtt_user(self, hass: HomeAssistant) -> None:
        coord = _coordinator(hass)
        coord._username = None
        await coord.async_send_command(MOCK_DEVICE_NAME, {"stPlug.bOn": True})

        payload = json.loads(_sent(coord)[0][1])
        assert list(payload) == ["Timestamp", "ClientId", "Values"]

    @pytest.mark.asyncio
    async def test_one_message_per_key(self, hass: HomeAssistant) -> None:
        coord = _coordinator(hass)
        await coord.async_send_command(
            MOCK_DEVICE_NAME, {"stLight.bLight": True, "stLight.nLight": 40},
        )

        values = [json.loads(raw)["Values"] for _, raw in _sent(coord)]
        assert values == [{"stLight.bLight": True}, {"stLight.nLight": 40}]

    @pytest.mark.asyncio
    async def test_nan_is_rejected(self, hass: HomeAssistant) -> None:
        coord = _coordinator(hass)
        with pytest.raises(HomeAssistantError):
            await coord.async_send_command(MOCK_DEVICE_NAME, {"fValue": float("nan")})
        coord._client.publish.assert_not_called()


class TestRxNumberTypes:
    """Whole numbers keep a fraction when the PLC reports the field as float."""

    async def _send(
        self, hass: HomeAssistant, dev: DeviceContext | None, key: str, value: Any,
    ) -> str:
        coord = _coordinator(hass)
        if dev is not None:
            coord.devices[MOCK_DEVICE_NAME] = dev
        await coord.async_send_command(MOCK_DEVICE_NAME, {key: value})
        raw = _sent(coord)[0][1]
        # Return the raw JSON text of the value: 58 and 58.0 compare equal.
        return raw[raw.index('"Values"'):]

    @pytest.mark.asyncio
    async def test_float_field_gets_fraction(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("stAC", "AC", {"nTemperatureRequest": 21.5}))
        raw = await self._send(hass, dev, "stAC.nTemperatureRequest", 22)
        assert raw == '"Values": {"stAC.nTemperatureRequest": 22.0}}'

    @pytest.mark.asyncio
    async def test_integer_field_stays_integer(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("stLight", "Lighting", {"nLight": 30}))
        raw = await self._send(hass, dev, "stLight.nLight", 58)
        assert raw == '"Values": {"stLight.nLight": 58}}'

    @pytest.mark.asyncio
    async def test_request_field_uses_reported_value(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("stGen", "General", {"nValue2": 12.25}))
        raw = await self._send(hass, dev, "stGen.nValue2Request", 15)
        assert raw == '"Values": {"stGen.nValue2Request": 15.0}}'

    @pytest.mark.asyncio
    async def test_datatype_widget_value(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("fSetpoint", "_dt_number", {"value": 20.0}))
        raw = await self._send(hass, dev, "fSetpoint", 21)
        assert raw == '"Values": {"fSetpoint": 21.0}}'

    @pytest.mark.asyncio
    async def test_bool_is_never_converted(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("stPlug", "Plug", {"bOn": 1.0}))
        raw = await self._send(hass, dev, "stPlug.bOn", True)
        assert raw == '"Values": {"stPlug.bOn": true}}'

    @pytest.mark.asyncio
    async def test_float_command_unchanged(self, hass: HomeAssistant) -> None:
        dev = _device(_widget("stLight", "Lighting", {"nLight": 30}))
        raw = await self._send(hass, dev, "stLight.nLight", 12.5)
        assert raw == '"Values": {"stLight.nLight": 12.5}}'

    @pytest.mark.asyncio
    async def test_unknown_device_or_field_unchanged(self, hass: HomeAssistant) -> None:
        raw = await self._send(hass, None, "stX.nValue", 7)
        assert raw == '"Values": {"stX.nValue": 7}}'
        dev = _device(_widget("stLight", "Lighting", {"nLight": 30.0}))
        raw = await self._send(hass, dev, "stLight.nOther", 7)
        assert raw == '"Values": {"stLight.nOther": 7}}'
