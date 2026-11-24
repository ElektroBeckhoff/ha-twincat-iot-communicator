"""Optimistic values stay in the entity and never reach the coordinator state.

The coordinator holds what the PLC reported on ``Json/Tx/Data``. A command
sent from Home Assistant is only shown optimistically by the sending entity
until the hold time has passed; afterwards the entity shows the PLC value
again, whether the PLC accepted the command or not.
"""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.twincat_iot_communicator.const import (
    WIDGET_TYPE_GENERAL,
    WIDGET_TYPE_LIGHTING,
)
from custom_components.twincat_iot_communicator.coordinator import TcIotCoordinator
from custom_components.twincat_iot_communicator.entity import (
    _OPTIMISTIC_HOLD,
    TcIotEntity,
)
from custom_components.twincat_iot_communicator.fan import TcIotFan
from custom_components.twincat_iot_communicator.models import (
    DeviceContext,
    WidgetData,
    WidgetMetaData,
)

from .conftest import (
    MOCK_DEVICE_NAME,
    MOCK_ENTRY_DATA,
    attach_entity_to_hass,
    build_device_with_widgets,
)

DOMAIN = "twincat_iot_communicator"
PATH = "stLighting"


def _setup(
    hass: HomeAssistant,
    values: dict[str, Any],
    widget_type: str = WIDGET_TYPE_LIGHTING,
) -> tuple[TcIotEntity, TcIotCoordinator, DeviceContext]:
    """Return an entity on a real coordinator with a mocked MQTT client."""
    coord = _coordinator(hass)
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.awaiting_full_snapshot = False
    widget = WidgetData(
        widget_id=PATH,
        path=PATH,
        metadata=WidgetMetaData(display_name="Light", widget_type=widget_type),
        values=values,
        friendly_path="Light",
    )
    dev.widgets[PATH] = widget
    dev.known_widget_paths.add(PATH)
    coord.devices[MOCK_DEVICE_NAME] = dev
    entity = TcIotEntity(coord, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "light")
    # The coordinator notifies the entity like it does after async_added_to_hass.
    coord.register_listener(MOCK_DEVICE_NAME, PATH, entity._on_widget_update)
    return entity, coord, dev


def _coordinator(hass: HomeAssistant) -> TcIotCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_ENTRY_DATA,
        unique_id="test",
        title="Test",
        version=2,
        minor_version=2,
    )
    coord = TcIotCoordinator(hass, entry)
    coord._client = AsyncMock()
    coord._connected = True
    return coord


def _plc_reports(coord: TcIotCoordinator, dev: DeviceContext, values: dict[str, Any]) -> None:
    """Merge a Tx/Data ``Values`` block like the message handler does."""
    coord._update_widgets(dev, {PATH: values})


async def _hold_elapsed(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=_OPTIMISTIC_HOLD + 1),
    )
    await hass.async_block_till_done()


class TestCoordinatorStateStaysPlcState:
    """The optimistic value is an overlay of the entity only."""

    async def test_command_does_not_change_coordinator_values(
        self, hass: HomeAssistant,
    ) -> None:
        entity, _coord, dev = _setup(hass, {"bLight": True, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})

        # The entity shows the requested value right away ...
        assert entity.widget.values["nLight"] == 80
        # ... the coordinator still holds what the PLC reported.
        assert dev.widgets[PATH].values["nLight"] == 10

    async def test_extra_fields_do_not_change_coordinator_values(
        self, hass: HomeAssistant,
    ) -> None:
        entity, _coord, dev = _setup(hass, {"bLight": False, "nHueValue": 0})

        await entity._send_optimistic(
            {f"{PATH}.bLight": True}, optimistic_extra={"nHueValue": 180},
        )

        assert entity.widget.values["nHueValue"] == 180
        assert dev.widgets[PATH].values == {"bLight": False, "nHueValue": 0}

    async def test_plc_update_during_hold_keeps_coordinator_values(
        self, hass: HomeAssistant,
    ) -> None:
        """A PLC update inside the hold time must not be overwritten in the coordinator."""
        entity, coord, dev = _setup(hass, {"bLight": True, "nLight": 10, "sMode": "A"})

        await entity._send_optimistic({f"{PATH}.nLight": 80})
        # The PLC does not take the value over and reports another field.
        _plc_reports(coord, dev, {"nLight": 10, "sMode": "B"})

        assert dev.widgets[PATH].values["nLight"] == 10
        # Inside the hold time the entity still shows the requested value,
        # together with the fresh PLC value of the other field.
        assert entity.widget.values["nLight"] == 80
        assert entity.widget.values["sMode"] == "B"


class TestHoldExpiry:
    """After the hold time the entity shows the PLC value again."""

    async def test_rejected_command_falls_back_without_further_plc_message(
        self, hass: HomeAssistant,
    ) -> None:
        """The PLC ignores the command and sends nothing more (pure OnChange)."""
        entity, coord, dev = _setup(hass, {"bLight": True, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})
        _plc_reports(coord, dev, {"nLight": 10})
        assert entity.widget.values["nLight"] == 80

        with patch.object(entity, "async_write_ha_state") as write_state:
            await _hold_elapsed(hass)

        assert entity.widget.values["nLight"] == 10
        assert entity._optimistic_values == {}
        write_state.assert_called()

    async def test_accepted_command_shows_plc_value_after_hold(
        self, hass: HomeAssistant,
    ) -> None:
        entity, coord, dev = _setup(hass, {"bLight": True, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})
        _plc_reports(coord, dev, {"nLight": 80})
        await _hold_elapsed(hass)

        assert entity.widget.values["nLight"] == 80
        assert dev.widgets[PATH].values["nLight"] == 80

    async def test_second_command_restarts_hold(self, hass: HomeAssistant) -> None:
        """A command inside the hold time keeps the earlier value and restarts the timer."""
        entity, _coord, dev = _setup(hass, {"bLight": False, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})
        first_timer = MagicMock(wraps=entity._cancel_optimistic_timer)
        entity._cancel_optimistic_timer = first_timer
        await entity._send_optimistic({f"{PATH}.bLight": True})

        first_timer.assert_called_once()
        assert entity._cancel_optimistic_timer is not first_timer
        assert entity.widget.values == {"bLight": True, "nLight": 80}
        assert dev.widgets[PATH].values == {"bLight": False, "nLight": 10}

        await _hold_elapsed(hass)
        assert entity.widget.values == {"bLight": False, "nLight": 10}

    async def test_removed_entity_cancels_timer(self, hass: HomeAssistant) -> None:
        entity, _coord, _dev = _setup(hass, {"bLight": True, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})
        await entity.async_will_remove_from_hass()

        with patch.object(entity, "async_write_ha_state") as write_state:
            await _hold_elapsed(hass)
        write_state.assert_not_called()


class TestSendFailure:
    """A failed publish shows the PLC value again."""

    async def test_failure_restores_plc_values(self, hass: HomeAssistant) -> None:
        entity, coord, dev = _setup(hass, {"bLight": True, "nLight": 10})
        coord._client = None  # not connected

        with pytest.raises(HomeAssistantError):
            await entity._send_optimistic({f"{PATH}.nLight": 80})

        assert entity.widget.values["nLight"] == 10
        assert dev.widgets[PATH].values["nLight"] == 10
        assert entity._optimistic_values == {}


class TestFloatFieldCommand:
    """Whole numbers for a field the PLC reports as float keep their fraction.

    The number type is taken from the value the PLC reported last, so the
    optimistic value must not replace it before the command is encoded.
    """

    async def test_integer_command_for_float_field_is_sent_as_float(
        self, hass: HomeAssistant,
    ) -> None:
        entity, coord, _dev = _setup(
            hass, {"nValue2": 22.0, "nValue2Request": 22.0}, WIDGET_TYPE_GENERAL,
        )

        await entity._send_optimistic({f"{PATH}.nValue2Request": 24})

        raw = coord._client.publish.call_args.kwargs["payload"]
        assert f'"{PATH}.nValue2Request": 24.0' in raw
        assert json.loads(raw)["Values"] == {f"{PATH}.nValue2Request": 24.0}

    async def test_second_integer_command_is_still_sent_as_float(
        self, hass: HomeAssistant,
    ) -> None:
        """The reported float type survives commands, also when the PLC confirms."""
        entity, coord, dev = _setup(
            hass, {"nValue2": 22.0, "nValue2Request": 22.0}, WIDGET_TYPE_GENERAL,
        )

        await entity._send_optimistic({f"{PATH}.nValue2Request": 24})
        _plc_reports(coord, dev, {"nValue2Request": 24.0})
        await entity._send_optimistic({f"{PATH}.nValue2Request": 25})

        raw = coord._client.publish.call_args.kwargs["payload"]
        assert f'"{PATH}.nValue2Request": 25.0' in raw

    async def test_integer_field_is_sent_as_integer(self, hass: HomeAssistant) -> None:
        entity, coord, _dev = _setup(hass, {"bLight": True, "nLight": 10})

        await entity._send_optimistic({f"{PATH}.nLight": 80})

        raw = coord._client.publish.call_args.kwargs["payload"]
        assert f'"{PATH}.nLight": 80}}' in raw


class TestVentilationSpeedReportedAsFloat:
    """Fan speed of a Ventilation widget whose PLC field is a REAL."""

    def _fan(self, hass: HomeAssistant, speed: float | int) -> tuple[TcIotFan, TcIotCoordinator]:
        coord = _coordinator(hass)
        dev = build_device_with_widgets(
            MOCK_DEVICE_NAME, ["widgets/domain/widget-ventilation.json"],
        )
        widget = dev.widgets["stVentilation"]
        widget.values["nValue"] = speed
        widget.values["nValueRequest"] = speed
        coord.devices[MOCK_DEVICE_NAME] = dev
        fan = TcIotFan(coord, MOCK_DEVICE_NAME, widget)
        attach_entity_to_hass(hass, fan, "fan")
        return fan, coord

    async def test_speed_is_sent_with_fraction(self, hass: HomeAssistant) -> None:
        fan, coord = self._fan(hass, 650.0)

        await fan.async_set_percentage(50)

        raw = coord._client.publish.call_args.kwargs["payload"]
        value = json.loads(raw)["Values"]["stVentilation.nValueRequest"]
        assert isinstance(value, float)
        assert f'"stVentilation.nValueRequest": {value!r}' in raw

    async def test_integer_speed_stays_integer(self, hass: HomeAssistant) -> None:
        fan, coord = self._fan(hass, 650)

        await fan.async_set_percentage(50)

        raw = coord._client.publish.call_args.kwargs["payload"]
        value = json.loads(raw)["Values"]["stVentilation.nValueRequest"]
        assert isinstance(value, int)
