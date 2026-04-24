"""Coordinator for TwinCAT IoT Communicator – manages its own MQTT connection.

Subscribes with wildcard topics to auto-discover multiple PLC devices
on the same broker/main_topic. Each device gets its own DeviceContext.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import ssl
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
import uuid

import aiomqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .const import (
    AUTH_MODE_CREDENTIALS,
    AUTH_MODE_ONLINE,
    CONF_ASSIGN_DEVICES_TO_AREAS,
    CONF_AUTH_MODE,
    CONF_CREATE_AREAS,
    CONF_JWT_TOKEN,
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    CONF_USE_TLS,
    DOMAIN,
    DESC_ICON,
    DESC_ONLINE,
    DESC_PERMITTED_USERS,
    DESC_TIMESTAMP,
    DESC_WATCHDOG_GRACE_FACTOR,
    DESC_WATCHDOG_MAX_TIMEOUT,
    DESC_WATCHDOG_MIN_TIMEOUT,
    FULL_SNAPSHOT_INTERVAL,
    HEARTBEAT_INTERVAL,
    SNAPSHOT_MAX_DURATION,
    SNAPSHOT_PROBE_TIMEOUT,
    SNAPSHOT_QUIET_PERIOD,
    SNAPSHOT_STABLE_MIN_COUNT,
    SNAPSHOT_STABLE_PERIOD,
    JSON_METADATA,
    JSON_VALUES,
    META_DISPLAY_NAME,
    META_NESTED_STRUCT_ICON,
    META_PERMITTED_USERS,
    META_READ_ONLY,
    META_WIDGET_TYPE,
    MSG_ACKNOWLEDGEMENT,
    MSG_MESSAGE,
    MSG_SENT,
    MSG_TIMESTAMP,
    MSG_TYPE,
    MSG_TYPE_DEFAULT,
    TCIOT_ICON_MAP,
    VAL_DISPLAY_NAME,
    TOPIC_COMM,
    TOPIC_COMM_ACTIVE,
    TOPIC_COMM_HEARTBEAT,
    TOPIC_DESC,
    TOPIC_MESSAGE,
    TOPIC_RX,
    TOPIC_SUB_DESC,
    TOPIC_SUB_MESSAGES,
    TOPIC_SUB_TX,
    WIDGET_MULTI_PLATFORM_MAP,
    WIDGET_PLATFORM_MAP,
    DATATYPE_BOOL,
    DATATYPE_NUMBER,
    DATATYPE_STRING,
    DATATYPE_ARRAY_BOOL,
    DATATYPE_ARRAY_NUMBER,
    DATATYPE_ARRAY_STRING,
)
from .jwt_helper import jwt_expiry_summary, jwt_is_expired
from .models import (
    DeviceContext,
    TcIotMessage,
    ViewData,
    WidgetData,
    metadata_bool,
    parse_metadata,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5
MAX_MESSAGES_PER_DEVICE = 200
MAX_IGNORED_DEVICES = 100
JSON_PARSE_EXECUTOR_THRESHOLD = 50_000  # bytes; large payloads are parsed off the event loop

type WidgetCallback = Callable[[WidgetData], None]
type NewWidgetCallback = Callable[[str, list[WidgetData]], None]
type NewDeviceCallback = Callable[[DeviceContext], None]
type MessageCallback = Callable[[str, TcIotMessage], None]


_SAFE_TOPIC_SEGMENT = re.compile(r"^[^\x00/#+]+$")


def _is_safe_topic_segment(segment: str) -> bool:
    """Validate that a string is safe for MQTT topic interpolation.

    Rejects segments containing MQTT wildcards (#, +), path separators (/),
    or null bytes.  Spaces and other printable characters are allowed.
    """
    return bool(segment) and _SAFE_TOPIC_SEGMENT.match(segment) is not None


def _extract_device_name(topic: str) -> str | None:
    """Extract the device_name segment from an incoming topic.

    Topic structure: {main_topic}/{device_name}/TcIotCommunicator/...
    We find 'TcIotCommunicator' and take the segment before it.
    """
    parts = topic.split("/")
    try:
        tc_idx = parts.index("TcIotCommunicator")
        if tc_idx >= 1:
            name = parts[tc_idx - 1]
            if _is_safe_topic_segment(name):
                return name
            _LOGGER.warning("Rejected unsafe device name in topic: %s", name)
    except ValueError:
        pass
    return None


class TcIotCoordinator:
    """Manage MQTT connection and multi-device state for TcIoT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        self.hass = hass
        self.entry = entry

        self._hostname: str = entry.data[CONF_HOST]
        self._port: int = entry.data[CONF_PORT]
        self._use_tls: bool = entry.data.get(CONF_USE_TLS, False)
        self._main_topic: str = entry.data[CONF_MAIN_TOPIC]
        self._auth_mode: str = entry.data.get(CONF_AUTH_MODE, AUTH_MODE_CREDENTIALS)
        self._jwt_token: str | None = entry.data.get(CONF_JWT_TOKEN)
        self._create_areas: bool = entry.data.get(CONF_CREATE_AREAS, True)
        self._assign_devices_to_areas: bool = entry.data.get(
            CONF_ASSIGN_DEVICES_TO_AREAS, True,
        )

        if self._auth_mode == AUTH_MODE_ONLINE and self._jwt_token:
            self._username: str | None = entry.data.get(CONF_USERNAME) or None
            self._password: str | None = self._jwt_token
        else:
            self._username = entry.data.get(CONF_USERNAME) or None
            self._password = entry.data.get(CONF_PASSWORD) or None
        raw_selected = entry.data.get(CONF_SELECTED_DEVICES)
        self._selected_devices: set[str] | None = (
            set(raw_selected) if raw_selected is not None else None
        )
        self._ignored_devices: set[str] = set()

        self.devices: dict[str, DeviceContext] = {}
        self._listeners: dict[str, list[WidgetCallback]] = {}
        self._new_widget_callbacks: dict[Platform, NewWidgetCallback] = {}
        self._new_device_callbacks: list[NewDeviceCallback] = []
        self._hub_status_callbacks: dict[str, list[Callable[[], None]]] = {}
        self._message_callbacks: dict[str, list[MessageCallback]] = {}

        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._full_snapshot_task: asyncio.Task[None] | None = None
        self._probe_tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event: asyncio.Event = asyncio.Event()
        self._connected: bool = False

        self._client_id: str = str(uuid.uuid5(uuid.NAMESPACE_URL, entry.entry_id))

        self._snapshot_timers: dict[str, CALLBACK_TYPE] = {}
        # Per-device events signalled when the PLC responds to active=1 with metadata
        self._snapshot_probe_events: dict[str, asyncio.Event] = {}
        self._snapshot_probe_start: dict[str, float] = {}
        self._desc_watchdog_timers: dict[str, CALLBACK_TYPE] = {}

        self._view_area_map: dict[str, str] = {}
        self._areas_ready_callbacks: list[Callable[[], bool]] = []

    # ── properties ──────────────────────────────────────────────────

    @property
    def hostname(self) -> str:
        """Return the MQTT broker hostname."""
        return self._hostname

    @property
    def main_topic(self) -> str:
        """Return the configured MQTT main topic."""
        return self._main_topic

    @property
    def connected(self) -> bool:
        """Return True if the MQTT client is connected."""
        return self._connected

    @property
    def listener_count(self) -> int:
        """Return the total number of registered widget listeners."""
        return sum(len(cbs) for cbs in self._listeners.values())

    @property
    def _areas_created(self) -> bool:
        """True when at least one device has finished area creation."""
        return any(d.areas_from_views_done for d in self.devices.values())

    # ── per-device topic helpers ────────────────────────────────────

    def _rx_topic(self, device_name: str) -> str:
        """Return the Rx/Data command topic for a device."""
        return TOPIC_RX.format(main_topic=self._main_topic, device_name=device_name)

    def _comm_topic(self, device_name: str) -> str:
        """Return the communicator registration topic for a device."""
        return TOPIC_COMM.format(
            main_topic=self._main_topic, device_name=device_name, client_id=self._client_id,
        )

    def _comm_active_topic(self, device_name: str) -> str:
        """Return the communicator active flag topic for a device."""
        return TOPIC_COMM_ACTIVE.format(
            main_topic=self._main_topic, device_name=device_name, client_id=self._client_id,
        )

    def _comm_heartbeat_topic(self, device_name: str) -> str:
        """Return the communicator heartbeat topic for a device."""
        return TOPIC_COMM_HEARTBEAT.format(
            main_topic=self._main_topic, device_name=device_name, client_id=self._client_id,
        )

    def _desc_topic(self, device_name: str) -> str:
        """Return the Desc topic for a device."""
        return TOPIC_DESC.format(main_topic=self._main_topic, device_name=device_name)

    def _message_topic(self, device_name: str, message_id: str) -> str:
        """Return the Messages topic for a specific message on a device."""
        return TOPIC_MESSAGE.format(
            main_topic=self._main_topic, device_name=device_name, message_id=message_id,
        )

    # ── helpers ─────────────────────────────────────────────────────

    def _safe_invoke(self, fn: Callable, *args: Any) -> None:
        """Invoke a callback, catching and logging any exceptions."""
        try:
            fn(*args)
        except Exception:
            _LOGGER.exception("Callback %s raised an exception", fn)

    @staticmethod
    def _sanitize_payload(payload: bytes | bytearray | str) -> str:
        """Decode payload to str and strip null bytes.

        TwinCAT IoT Communicator payloads are null-padded to a fixed buffer
        size.  The PLC may encode special characters (e.g. '°') as Latin-1
        instead of UTF-8, so we fall back to latin-1 when UTF-8 decoding fails.
        """
        if isinstance(payload, (bytes, bytearray)):
            stripped = payload.replace(b"\x00", b"")
            try:
                return stripped.decode("utf-8-sig")
            except UnicodeDecodeError:
                return stripped.decode("latin-1")
        return payload.replace("\x00", "")

    async def _async_parse_json_payload(
        self, payload: bytes | bytearray | str, topic: str,
    ) -> dict[str, Any] | None:
        """Strip null bytes, parse JSON, and return dict or None on failure.

        Offloads to the executor for payloads exceeding the threshold to
        avoid blocking the event loop with large PLC snapshots (~230 KB).
        """
        try:
            raw = self._sanitize_payload(payload)
            if len(raw) > JSON_PARSE_EXECUTOR_THRESHOLD:
                return await self.hass.async_add_executor_job(json.loads, raw)
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            _LOGGER.debug("Discarding non-JSON payload on %s", topic)
            return None

    def _parse_json_payload_sync(
        self, payload: bytes | bytearray | str, topic: str,
    ) -> dict[str, Any] | None:
        """Sync JSON parse for small payloads (messages, desc)."""
        try:
            raw = self._sanitize_payload(payload)
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            _LOGGER.debug("Discarding non-JSON payload on %s", topic)
            return None

    def _notify_widget_listeners(self, dev: DeviceContext, paths: set[str]) -> None:
        """Invoke all widget listeners for the given paths."""
        for path in paths:
            widget = dev.widgets.get(path)
            if widget:
                key = f"{dev.device_name}/{path}"
                for fn in self._listeners.get(key, []):
                    self._safe_invoke(fn, widget)

    # ── PermittedUsers check ────────────────────────────────────────

    def _is_user_permitted(self, permitted_users: str | None) -> bool:
        """Check whether the current MQTT user is in a PermittedUsers value.

        Returns True (= access granted) when:
        - permitted_users is None (field absent in JSON = no restriction)
        - permitted_users is "*" (wildcard = no restriction)
        - No MQTT username is configured (anonymous = full access)
        - The username appears in the comma-separated list

        Empty or whitespace-only strings mean nobody is permitted.
        """
        if permitted_users is None or permitted_users.strip() == "*":
            return True
        if not self._username:
            return True
        return any(u.strip() == self._username for u in permitted_users.split(",") if u.strip())

    # ── TLS ──────────────────────────────────────────────────────────

    async def _build_tls_context(self) -> ssl.SSLContext | None:
        """Create a default TLS context in an executor to avoid blocking."""
        if not self._use_tls:
            return None
        return await self.hass.async_add_executor_job(ssl.create_default_context)

    def _reset_connection_state(self) -> None:
        """Clear client reference and mark all devices as needing a fresh snapshot."""
        self._client = None
        self._connected = False
        self._cancel_all_desc_watchdogs()
        for dev in self.devices.values():
            self._reset_desc_measurement(dev)
            self._begin_snapshot_window(dev)

    # ── lifecycle ───────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Connect to broker and start the message loop.

        Raises ConfigEntryNotReady when the initial connection attempt fails.
        """
        if self._auth_mode == AUTH_MODE_ONLINE and self._jwt_token:
            validity = jwt_expiry_summary(self._jwt_token)
            if jwt_is_expired(self._jwt_token):
                _LOGGER.warning("JWT %s: requesting re-authentication", validity)
                self.entry.async_start_reauth(self.hass)
                raise ConfigEntryNotReady("JWT token has expired")
            _LOGGER.info("JWT token %s", validity)

        self._stop_event.clear()
        self._task = self.hass.async_create_background_task(
            self._mqtt_loop(), f"twincat_iot_mqtt_{self._main_topic}"
        )
        _LOGGER.info(
            "TcIoT MQTT started for %s@%s:%s",
            self._main_topic, self._hostname, self._port,
        )

    async def async_stop(self) -> None:
        """Disconnect and stop the message loop."""
        await self._stop_heartbeat()
        await self._deregister_all()
        self._cancel_all_desc_watchdogs()
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._client = None
        self._connected = False

        self._listeners.clear()
        self._new_widget_callbacks.clear()
        self._new_device_callbacks.clear()
        self._hub_status_callbacks.clear()
        self._message_callbacks.clear()
        self._areas_ready_callbacks.clear()

        _LOGGER.info("TcIoT MQTT stopped for %s", self._main_topic)

    # ── MQTT loop ───────────────────────────────────────────────────

    async def _mqtt_loop(self) -> None:
        """Persistent MQTT loop with automatic reconnection."""
        tls_ctx = await self._build_tls_context()

        while not self._stop_event.is_set():
            if self._auth_mode == AUTH_MODE_ONLINE and self._jwt_token:
                validity = jwt_expiry_summary(self._jwt_token)
                if jwt_is_expired(self._jwt_token):
                    _LOGGER.warning(
                        "JWT %s: requesting re-authentication, "
                        "stopping reconnect loop", validity,
                    )
                    self.entry.async_start_reauth(self.hass)
                    return
                _LOGGER.debug("Reconnect loop: JWT %s", validity)

            try:
                async with aiomqtt.Client(
                    hostname=self._hostname,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    identifier=self._client_id,
                    tls_context=tls_ctx,
                ) as client:
                    self._client = client
                    self._connected = True
                    _LOGGER.info("Connected to MQTT broker %s:%s", self._hostname, self._port)

                    sub_tx = TOPIC_SUB_TX.format(main_topic=self._main_topic)
                    sub_desc = TOPIC_SUB_DESC.format(main_topic=self._main_topic)
                    sub_msg = TOPIC_SUB_MESSAGES.format(main_topic=self._main_topic)

                    await client.subscribe(sub_tx, qos=1)
                    await client.subscribe(sub_desc, qos=1)
                    await client.subscribe(sub_msg, qos=1)
                    _LOGGER.debug(
                        "Subscribed to topics (3):\n  %s\n  %s\n  %s",
                        sub_tx, sub_desc, sub_msg,
                    )

                    await asyncio.gather(*(
                        self._register_communicator(dev.device_name)
                        for dev in self.devices.values()
                    ))

                    # Re-probe devices whose snapshot capability is still unknown
                    # (e.g. connection dropped during the initial probe).
                    for dev in self.devices.values():
                        if (
                            dev.supports_active_snapshot is None
                            and dev.device_name not in self._probe_tasks
                        ):
                            self._snapshot_probe_events[dev.device_name] = asyncio.Event()
                            self._snapshot_probe_start[dev.device_name] = self.hass.loop.time()
                            self._probe_tasks[dev.device_name] = (
                                self.hass.async_create_background_task(
                                    self._probe_device_snapshot(dev.device_name),
                                    f"twincat_iot_probe_{dev.device_name}",
                                )
                            )

                    self._heartbeat_task = self.hass.async_create_background_task(
                        self._heartbeat_loop(),
                        f"twincat_iot_heartbeat_{self._main_topic}",
                    )
                    # On reconnect, start loop directly for devices whose
                    # capability was already confirmed in a prior session.
                    if any(
                        d.supports_active_snapshot is True
                        for d in self.devices.values()
                    ):
                        self._full_snapshot_task = self.hass.async_create_background_task(
                            self._full_snapshot_loop(),
                            f"twincat_iot_full_snapshot_{self._main_topic}",
                        )

                    try:
                        async for message in client.messages:
                            if self._stop_event.is_set():
                                return
                            await self._async_dispatch_message(message)
                    finally:
                        await self._stop_heartbeat()
                        await self._deregister_all()

            except aiomqtt.MqttCodeError as err:
                self._reset_connection_state()
                if err.rc == 5 and self._auth_mode == AUTH_MODE_ONLINE:
                    _LOGGER.warning(
                        "MQTT auth rejected (rc=5) with JWT: requesting re-authentication"
                    )
                    self.entry.async_start_reauth(self.hass)
                    return
                _LOGGER.warning(
                    "MQTT connection lost (%s): all entities unavailable, "
                    "reconnecting in %ss",
                    err, RECONNECT_INTERVAL,
                )
            except aiomqtt.MqttError as err:
                self._reset_connection_state()
                _LOGGER.warning(
                    "MQTT connection lost (%s): all entities unavailable, "
                    "reconnecting in %ss",
                    err, RECONNECT_INTERVAL,
                )
            except asyncio.CancelledError:
                return
            except Exception:
                self._reset_connection_state()
                _LOGGER.exception(
                    "Unexpected MQTT error: all entities unavailable, "
                    "reconnecting in %ss",
                    RECONNECT_INTERVAL,
                )

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=RECONNECT_INTERVAL)
                return
            except asyncio.TimeoutError:
                pass

    # ── communicator registration (per device) ──────────────────────

    async def _register_communicator(self, device_name: str) -> None:
        """Publish communicator registration + active=1 for a device.

        Setting active=1 triggers the PLC to send the complete Tx/Data JSON.
        Sets awaiting_full_snapshot=True so the response triggers reconciliation.
        """
        if self._client is None:
            return

        registration = json.dumps({"apns": "0", "fcm": "0", "ba": "0"})
        await self._client.publish(self._comm_topic(device_name), payload=registration, qos=1, retain=True)
        await self._client.publish(self._comm_active_topic(device_name), payload="1", qos=1, retain=True)
        await self._client.publish(self._comm_heartbeat_topic(device_name), payload="1", qos=1, retain=True)

        dev = self.devices.get(device_name)
        if dev:
            dev.registered = True
            self._begin_snapshot_window(dev)
            self._snapshot_probe_start[device_name] = self.hass.loop.time()
        _LOGGER.info("Registered communicator for device %s", device_name)

    async def _deregister_all(self) -> None:
        """Set active=0 for all known devices on clean disconnect."""
        if self._client is None:
            return

        async def _deregister_one(dev: DeviceContext) -> None:
            if dev.registered:
                with contextlib.suppress(aiomqtt.MqttError):
                    await self._client.publish(
                        self._comm_active_topic(dev.device_name), payload="0", qos=1, retain=True,
                    )
                dev.registered = False

        await asyncio.gather(*(
            _deregister_one(dev) for dev in self.devices.values()
        ))
        _LOGGER.debug("Deregistered all device communicators")

    async def async_remove_device(self, device_name: str) -> None:
        """Deregister a single device and remove it from the coordinator.

        Publishes active=0 to tell the PLC this client is no longer listening,
        removes the device from the internal state, and updates the
        selected_devices filter so future MQTT messages are ignored.
        """
        dev = self.devices.get(device_name)
        if dev is not None and dev.registered and self._client is not None:
            with contextlib.suppress(aiomqtt.MqttError):
                await self._client.publish(
                    self._comm_active_topic(device_name),
                    payload="0", qos=1, retain=True,
                )

        self.devices.pop(device_name, None)
        if self._selected_devices is not None:
            self._selected_devices.discard(device_name)
        if len(self._ignored_devices) < MAX_IGNORED_DEVICES:
            self._ignored_devices.add(device_name)

        cancel_wd = self._desc_watchdog_timers.pop(device_name, None)
        if cancel_wd is not None:
            cancel_wd()
        cancel_snap = self._snapshot_timers.pop(device_name, None)
        if cancel_snap is not None:
            cancel_snap()
        probe = self._probe_tasks.pop(device_name, None)
        if probe is not None and not probe.done():
            probe.cancel()

        for key in list(self._listeners):
            if key.startswith(f"{device_name}/") or key == device_name:
                del self._listeners[key]
        self._hub_status_callbacks.pop(device_name, None)
        self._message_callbacks.pop(device_name, None)

        _LOGGER.info("Removed device %s from coordinator", device_name)

    async def _heartbeat_loop(self) -> None:
        """Periodically publish heartbeat for all known devices."""
        try:
            while not self._stop_event.is_set() and self._client is not None:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                client = self._client
                if client is None:
                    return

                async def _hb_one(
                    dev: DeviceContext, cli: aiomqtt.Client,
                ) -> None:
                    try:
                        await cli.publish(
                            self._comm_heartbeat_topic(dev.device_name),
                            payload="1", qos=1, retain=False,
                        )
                    except aiomqtt.MqttError:
                        _LOGGER.debug(
                            "Heartbeat publish failed for %s, will retry",
                            dev.device_name,
                        )

                await asyncio.gather(*(
                    _hb_one(d, client) for d in self.devices.values()
                    if d.registered
                ))
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Heartbeat loop terminated unexpectedly", exc_info=True)

    async def _probe_device_snapshot(self, device_name: str) -> None:
        """Probe a single device for active=1 snapshot support.

        Started per device on discovery. Waits up to SNAPSHOT_PROBE_TIMEOUT
        seconds for the PLC to respond with a metadata snapshot. On success
        starts the global periodic _full_snapshot_loop if not already running.
        """
        try:
            event = self._snapshot_probe_events.get(device_name)
            if event is None:
                return
            task = asyncio.current_task()
            try:
                await asyncio.wait_for(event.wait(), timeout=SNAPSHOT_PROBE_TIMEOUT)
                t0 = self._snapshot_probe_start.get(device_name)
                elapsed_ms = (self.hass.loop.time() - t0) * 1000 if t0 is not None else 0.0
                dev = self.devices.get(device_name)
                if dev:
                    dev.supports_active_snapshot = True
                _LOGGER.info(
                    "Device %s responded to active probe in %.0fms — "
                    "periodic snapshot refresh enabled",
                    device_name, elapsed_ms,
                )
                if not self._full_snapshot_task or self._full_snapshot_task.done():
                    self._full_snapshot_task = self.hass.async_create_background_task(
                        self._full_snapshot_loop(),
                        f"twincat_iot_full_snapshot_{self._main_topic}",
                    )
            except asyncio.TimeoutError:
                dev = self.devices.get(device_name)
                if dev and dev.online:
                    dev.supports_active_snapshot = False
                    _LOGGER.info(
                        "Device %s did not respond to active probe within %ss "
                        "— periodic snapshot refresh disabled",
                        device_name,
                        SNAPSHOT_PROBE_TIMEOUT,
                    )
                elif dev:
                    _LOGGER.info(
                        "Device %s is offline — active probe deferred until "
                        "device comes back online",
                        device_name,
                    )
            finally:
                if self._snapshot_probe_events.get(device_name) is event:
                    self._snapshot_probe_events.pop(device_name, None)
                    self._snapshot_probe_start.pop(device_name, None)
                if self._probe_tasks.get(device_name) is task:
                    self._probe_tasks.pop(device_name, None)
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug(
                "Probe task for %s terminated unexpectedly",
                device_name, exc_info=True,
            )

    async def _full_snapshot_loop(self) -> None:
        """Periodically request a full snapshot by publishing active=1.

        Runs every FULL_SNAPSHOT_INTERVAL seconds (15 minutes). Only runs for
        devices that confirmed active=1 support during the startup probe.
        Published without retain so the PLC receives a fresh message every time.
        """
        try:
            while not self._stop_event.is_set() and self._client is not None:
                await asyncio.sleep(FULL_SNAPSHOT_INTERVAL)
                client = self._client
                if client is None:
                    return

                async def _snap_one(
                    dev: DeviceContext, cli: aiomqtt.Client,
                ) -> None:
                    try:
                        await cli.publish(
                            self._comm_active_topic(dev.device_name),
                            payload="1", qos=1, retain=False,
                        )
                        self._begin_snapshot_window(dev)
                        _LOGGER.debug(
                            "Full snapshot requested for %s (15-min interval)",
                            dev.device_name,
                        )
                    except aiomqtt.MqttError:
                        _LOGGER.debug(
                            "Full snapshot request failed for %s, will retry",
                            dev.device_name,
                        )

                await asyncio.gather(*(
                    _snap_one(d, client) for d in self.devices.values()
                    if d.registered and d.supports_active_snapshot
                ))
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Full snapshot loop terminated unexpectedly", exc_info=True)

    async def _stop_heartbeat(self) -> None:
        """Cancel the heartbeat, full-snapshot, probe, and snapshot timer tasks."""
        for task in (self._heartbeat_task, self._full_snapshot_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._heartbeat_task = None
        self._full_snapshot_task = None
        for task in list(self._probe_tasks.values()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._probe_tasks.clear()
        for cancel in self._snapshot_timers.values():
            cancel()
        self._snapshot_timers.clear()

    # ── snapshot window management ──────────────────────────────────

    def _begin_snapshot_window(self, dev: DeviceContext) -> None:
        """Open a new accumulation window for the device's full snapshot.

        Cancels any in-progress window, clears accumulated paths, and sets the
        awaiting flag so the next batch of metadata messages is collected before
        reconciliation runs via _finalize_snapshot.
        """
        dev.awaiting_full_snapshot = True
        dev.snapshot_accumulated_paths.clear()
        dev.snapshot_started_at = None
        dev.snapshot_stable_count = 0
        cancel = self._snapshot_timers.pop(dev.device_name, None)
        if cancel:
            cancel()

    def _reschedule_snapshot_timer(
        self, dev: DeviceContext, *, grew: bool = True,
    ) -> None:
        """Reset the quiet-period timer for a device's snapshot window.

        Tracks how many consecutive messages arrived without new widget
        paths (``snapshot_stable_count``).  Once that counter reaches
        SNAPSHOT_STABLE_MIN_COUNT, a one-shot SNAPSHOT_STABLE_PERIOD timer
        is started and NOT reset by further messages.  This allows the
        timer to actually fire even when the PLC sends faster than the
        stable period (e.g. every 500ms).

        Any message with new paths resets the counter so PLCs that send
        different groups at varying cadences are handled correctly.

        The remaining SNAPSHOT_MAX_DURATION is always honored as an upper
        bound to prevent infinite accumulation.
        """
        now = self.hass.loop.time()
        if dev.snapshot_started_at is None:
            dev.snapshot_started_at = now

        if grew:
            dev.snapshot_stable_count = 0
        else:
            dev.snapshot_stable_count += 1

        # Once stable, let the running timer fire without resetting it.
        if (
            not grew
            and dev.snapshot_stable_count > SNAPSHOT_STABLE_MIN_COUNT
            and dev.device_name in self._snapshot_timers
        ):
            return

        cancel = self._snapshot_timers.pop(dev.device_name, None)
        if cancel:
            cancel()
        device_name = dev.device_name

        remaining = SNAPSHOT_MAX_DURATION - (now - dev.snapshot_started_at)
        stable = dev.snapshot_stable_count >= SNAPSHOT_STABLE_MIN_COUNT
        quiet = SNAPSHOT_STABLE_PERIOD if stable else SNAPSHOT_QUIET_PERIOD
        delay = min(quiet, max(remaining, 0.1))

        @callback
        def _on_timer(_now: Any) -> None:
            self._finalize_snapshot(device_name)

        self._snapshot_timers[device_name] = async_call_later(
            self.hass,
            delay,
            _on_timer,
        )

    @callback
    def _finalize_snapshot(self, device_name: str) -> None:
        """Run stale/recovery reconciliation after the snapshot window closes.

        Fires either after SNAPSHOT_QUIET_PERIOD of silence or when
        SNAPSHOT_MAX_DURATION is reached (whichever comes first).
        """
        self._snapshot_timers.pop(device_name, None)
        dev = self.devices.get(device_name)
        if dev is None or not dev.awaiting_full_snapshot:
            return
        dev.snapshot_started_at = None

        accumulated = dev.snapshot_accumulated_paths
        if not accumulated:
            _LOGGER.warning(
                "Tx/Data/JsonFull window closed for %s with no widgets — skipping stale marking",
                device_name,
            )
            dev.awaiting_full_snapshot = False
            return

        # --- stale: known but absent from snapshot ---
        newly_stale = dev.known_widget_paths - accumulated - dev.stale_widget_paths
        if newly_stale:
            dev.stale_widget_paths |= newly_stale
            _LOGGER.info(
                "Marking %d widget(s) stale on %s (snapshot: %d seen)",
                len(newly_stale), device_name, len(accumulated),
            )
            self._notify_widget_listeners(dev, newly_stale)

        # --- recovered: was stale but reappeared ---
        recovered = dev.stale_widget_paths & accumulated
        if recovered:
            dev.stale_widget_paths -= recovered
            _LOGGER.info(
                "Recovered %d previously stale widget(s) on %s", len(recovered), device_name,
            )
            self._notify_widget_listeners(dev, recovered)

        _LOGGER.debug(
                "Tx/Data/JsonFull reconciled on %s: %d seen, %d known, %d stale",
            device_name, len(accumulated), len(dev.known_widget_paths), len(dev.stale_widget_paths),
        )
        dev.snapshot_accumulated_paths = set()
        dev.awaiting_full_snapshot = False
        self._create_areas_from_views(dev)
        self.reconcile_stale_device_repair()

    # ── device auto-discovery ───────────────────────────────────────

    def _get_or_create_device(self, device_name: str) -> tuple[DeviceContext, bool]:
        """Return existing DeviceContext or create a new one. Returns (ctx, is_new)."""
        if device_name in self.devices:
            return self.devices[device_name], False

        dev = DeviceContext(device_name=device_name)
        self.devices[device_name] = dev
        _LOGGER.info("Discovered new device: %s", device_name)
        return dev, True

    def _seed_known_widget_paths(self, dev: DeviceContext) -> None:
        """Pre-populate known_widget_paths from the HA device registry.

        On a fresh start the coordinator has no memory of previous widgets.
        Reading the registry ensures _finalize_snapshot can detect widgets
        that existed before the restart but are no longer in the PLC payload.
        """
        dev_reg = dr.async_get(self.hass)
        hub_prefix = f"{self.entry.entry_id}_{dev.device_name}_"
        for device in dr.async_entries_for_config_entry(dev_reg, self.entry.entry_id):
            if device.via_device_id is None:
                continue
            for domain, ident in device.identifiers:
                if domain == DOMAIN and ident.startswith(hub_prefix):
                    widget_path = ident.removeprefix(hub_prefix)
                    dev.known_widget_paths.add(widget_path)
        if dev.known_widget_paths:
            _LOGGER.debug(
                "Seeded %d known widget path(s) for %s from device registry",
                len(dev.known_widget_paths), dev.device_name,
            )

    def _on_new_device(self, dev: DeviceContext) -> None:
        """Notify callbacks about a newly discovered device."""
        self._seed_known_widget_paths(dev)
        for cb in self._new_device_callbacks:
            self._safe_invoke(cb, dev)
        # Create probe event and per-device probe task immediately on discovery
        # so the probe task exists before _register_communicator sends active=1.
        if dev.supports_active_snapshot is None:
            self._snapshot_probe_events[dev.device_name] = asyncio.Event()
            probe_task = self.hass.async_create_background_task(
                self._probe_device_snapshot(dev.device_name),
                f"twincat_iot_probe_{dev.device_name}",
            )
            self._probe_tasks[dev.device_name] = probe_task
        self.hass.async_create_background_task(
            self._register_communicator(dev.device_name),
            f"twincat_iot_register_{dev.device_name}",
        )

    def _start_reprobe(self, dev: DeviceContext) -> None:
        """Re-probe a device for active=1 snapshot support.

        Called when a device transitions from offline to online and has not
        yet confirmed snapshot support.  Cancels any stale probe, sends a
        fresh active=1 and starts a new probe task.
        """
        name = dev.device_name
        old_task = self._probe_tasks.pop(name, None)
        if old_task and not old_task.done():
            old_task.cancel()
        self._snapshot_probe_events.pop(name, None)

        dev.supports_active_snapshot = None
        self._snapshot_probe_events[name] = asyncio.Event()
        probe_task = self.hass.async_create_background_task(
            self._probe_device_snapshot(name),
            f"twincat_iot_probe_{name}",
        )
        self._probe_tasks[name] = probe_task

        async def _send_active() -> None:
            client = self._client
            if client is None:
                return
            try:
                await client.publish(
                    self._comm_active_topic(name),
                    payload="1", qos=1, retain=False,
                )
                self._begin_snapshot_window(dev)
                self._snapshot_probe_start[name] = self.hass.loop.time()
                _LOGGER.info(
                    "Device %s back online — sent active probe", name,
                )
            except aiomqtt.MqttError:
                _LOGGER.debug("Active probe publish failed for %s", name)

        self.hass.async_create_background_task(
            _send_active(),
            f"twincat_iot_reprobe_{name}",
        )

    # ── message dispatch ────────────────────────────────────────────

    async def _async_dispatch_message(self, msg: aiomqtt.Message) -> None:
        """Route an incoming MQTT message to the right per-device handler.

        Metadata routing:
        - awaiting_full_snapshot=True + MetaData → snapshot accumulation
          (_discover_widgets with path_accumulator). After
          SNAPSHOT_QUIET_PERIOD of silence, _finalize_snapshot runs stale
          marking / recovery.
        - Otherwise with MetaData → additive discovery (_discover_widgets).
        - No MetaData → value update only via _update_widgets.

        awaiting_full_snapshot is set by _register_communicator (active=1 publish),
        _full_snapshot_loop (every 15 min), and _reset_connection_state (reconnect).
        New devices start with awaiting_full_snapshot=True so the first retained
        message triggers reconciliation to establish the initial widget set.
        """
        topic = str(msg.topic)

        device_name = _extract_device_name(topic)
        if device_name is None:
            _LOGGER.debug("Ignoring message: unable to extract device name from topic %s", topic)
            return

        if device_name in self._ignored_devices:
            return
        if self._selected_devices is not None and device_name not in self._selected_devices:
            return

        dev, is_new = self._get_or_create_device(device_name)
        if is_new:
            self._on_new_device(dev)

        if "/TcIotCommunicator/Messages/" in topic:
            msg_id = topic.rsplit("/", 1)[-1]
            if not _is_safe_topic_segment(msg_id):
                _LOGGER.warning("Rejected unsafe message_id: %s", msg_id)
                return
            self._handle_plc_message(dev, msg_id, msg.payload)
            return

        if topic.endswith("/TcIotCommunicator/Desc"):
            data = self._parse_json_payload_sync(msg.payload, topic)
            if data is None:
                return
            self._handle_desc(dev, data)
            return

        data = await self._async_parse_json_payload(msg.payload, topic)
        if data is None:
            return
        if not isinstance(data, dict):
            _LOGGER.warning(
                "Ignoring Tx/Data payload on %s: top-level JSON must be an object",
                topic,
            )
            return

        if not self._is_user_permitted(dev.permitted_users):
            return

        raw_values = data.get(JSON_VALUES)
        raw_metadata = data.get(JSON_METADATA)
        if raw_values is None:
            values: dict[str, Any] = {}
        elif isinstance(raw_values, dict):
            values = raw_values
        else:
            _LOGGER.warning(
                "Ignoring Tx/Data Values on %s: expected object, got %s",
                topic, type(raw_values).__name__,
            )
            values = {}
        if raw_metadata is None:
            metadata: dict[str, Any] = {}
        elif isinstance(raw_metadata, dict):
            metadata = raw_metadata
        else:
            _LOGGER.warning(
                "Ignoring Tx/Data MetaData on %s: expected object, got %s",
                topic, type(raw_metadata).__name__,
            )
            metadata = {}
        # Note: the PLC payload may contain ForceUpdate=true which signals
        # the TwinCAT IoT Communicator app to refresh its cached UI.
        # This integration does not need it — every incoming MQTT message
        # is fully processed (metadata via _discover_widgets, values via
        # _update_widgets) regardless of the flag.

        meta_changed = 0
        meta_changed_paths: set[str] = set()
        is_snapshot = dev.awaiting_full_snapshot
        if metadata:
            if dev.awaiting_full_snapshot:
                # Accumulate widget paths across all snapshot messages.
                # The PLC sends one MQTT message per group in response to
                # bActive=1, so a single message is never the full picture.
                # _finalize_snapshot runs after SNAPSHOT_QUIET_PERIOD seconds
                # of silence and does the actual stale/recovery marking.
                count_before = len(dev.snapshot_accumulated_paths)
                meta_changed = self._discover_widgets(
                    dev, values, metadata,
                    path_accumulator=dev.snapshot_accumulated_paths,
                    meta_changed_paths=meta_changed_paths,
                )
                grew = len(dev.snapshot_accumulated_paths) > count_before
                _LOGGER.debug(
                    "Tx/Data/JsonFull %s: accumulating %d widgets so far",
                    dev.device_name, len(dev.snapshot_accumulated_paths),
                )
                self._reschedule_snapshot_timer(dev, grew=grew)
                # Signal probe only after active=1 was actually sent
                # (dev.registered). Retained messages arriving before
                # registration must not trigger the probe.
                probe_event = self._snapshot_probe_events.get(dev.device_name)
                if probe_event and not probe_event.is_set() and dev.registered:
                    probe_event.set()
                # Late-response recovery: probe timed out but PLC responded
                # eventually. Re-enable the periodic loop for this device.
                elif dev.supports_active_snapshot is False:
                    _LOGGER.info(
                        "Device %s responded late — re-enabling periodic "
                        "snapshot refresh",
                        dev.device_name,
                    )
                    dev.supports_active_snapshot = True
                    if not self._full_snapshot_task or self._full_snapshot_task.done():
                        self._full_snapshot_task = self.hass.async_create_background_task(
                            self._full_snapshot_loop(),
                            f"twincat_iot_full_snapshot_{self._main_topic}",
                        )
            else:
                # Additive discovery: new widgets are registered, existing
                # ones updated in place.
                meta_changed = self._discover_widgets(
                    dev, values, metadata,
                    meta_changed_paths=meta_changed_paths,
                )
        elif dev.awaiting_full_snapshot and values:
            _LOGGER.debug(
                "Tx/Data/JsonFull %s: value-only payload during snapshot window",
                dev.device_name,
            )
            self._reschedule_snapshot_timer(dev, grew=False)

        n_known = len(dev.known_widget_paths)
        log_budget: list[int] = [self._UPDATE_LOG_CAP]
        change_lines: list[str] = []
        hit_count, changed_count = self._update_widgets(
            dev, values, _log_budget=log_budget, _change_lines=change_lines,
            also_notify=meta_changed_paths,
        )
        # Notify listeners for widgets whose metadata changed but whose
        # values were not present in this payload (so _update_widgets never
        # visited them).  The set is consumed by _update_widgets for paths
        # it did process, so only unvisited paths remain here.
        for path in meta_changed_paths:
            widget = dev.widgets.get(path)
            if widget is not None:
                listener_key = f"{dev.device_name}/{path}"
                for fn in self._listeners.get(listener_key, []):
                    self._safe_invoke(fn, widget)

        if changed_count > 0 or meta_changed > 0:
            msg_type = "Tx/Data/JsonFull" if is_snapshot else "Tx/Data/JsonOnChange"
            _LOGGER.debug(
                "%s %s: %d/%d w — %d changed, %d meta",
                msg_type, dev.device_name,
                hit_count, n_known, changed_count, meta_changed,
            )

    # ── Desc handlers ──────────────────────────────────────────────

    def _handle_desc(self, dev: DeviceContext, data: dict[str, Any]) -> None:
        """Process a Desc message and update the device context."""
        was_online = dev.online
        online = data.get(DESC_ONLINE, True)
        if not online and self._connected:
            _LOGGER.warning("Device %s reported offline", dev.device_name)
        new_online = bool(online)
        new_icon = data.get(DESC_ICON)
        new_permitted = data.get(DESC_PERMITTED_USERS)
        new_timestamp = data.get(DESC_TIMESTAMP)
        old_permitted = dev.permitted_users
        changed = (
            new_online != dev.online
            or new_icon != dev.icon_name
            or new_permitted != dev.permitted_users
            or new_timestamp != dev.desc_timestamp
        )
        dev.online = new_online
        dev.icon_name = new_icon
        dev.permitted_users = new_permitted
        dev.desc_timestamp = new_timestamp

        if dev.online:
            self._update_desc_watchdog(dev)
        else:
            self._cancel_desc_watchdog(dev)
        if changed:
            _LOGGER.debug(
                "Device descriptor updated for %s: online=%s, icon=%s",
                dev.device_name, dev.online, dev.icon_name,
            )

        was_permitted = self._is_user_permitted(old_permitted)
        permitted = self._is_user_permitted(new_permitted)

        stale_before = len(dev.stale_widget_paths)
        if not permitted and dev.known_widget_paths:
            newly_stale = dev.known_widget_paths - dev.stale_widget_paths
            if newly_stale:
                dev.stale_widget_paths |= newly_stale
                _LOGGER.info(
                    "Device %s not permitted for user %s – marking %d widget(s) stale",
                    dev.device_name, self._username, len(newly_stale),
                )
                self._notify_widget_listeners(dev, newly_stale)
        elif permitted and not was_permitted and dev.stale_widget_paths:
            recovered = set(dev.stale_widget_paths)
            dev.stale_widget_paths.clear()
            _LOGGER.info(
                "Device %s permission restored for user %s – recovering %d widget(s)",
                dev.device_name, self._username, len(recovered),
            )
            self._notify_widget_listeners(dev, recovered)

        if len(dev.stale_widget_paths) != stale_before:
            self.reconcile_stale_device_repair()

        if was_online != dev.online:
            if dev.online:
                _LOGGER.debug("Device %s back online", dev.device_name)
                if dev.supports_active_snapshot is not True and dev.registered:
                    self._start_reprobe(dev)
            self._notify_widget_listeners(dev, set(dev.widgets.keys()))
            self.reconcile_stale_device_repair()

        self._notify_hub_status(dev.device_name)

    # ── Desc watchdog ────────────────────────────────────────────────

    def _update_desc_watchdog(self, dev: DeviceContext) -> None:
        """Measure Desc interval and (re)start the watchdog timer.

        Desc #1 is the online event (not timer-based) — skip measurement.
        Desc #2 is the first timer tick — record timestamp only.
        Desc #3+ measures the real PLC-configured interval between #2 and #3.
        The watchdog is only activated once a valid interval is known.
        """
        now = self.hass.loop.time()
        dev.desc_count += 1

        if dev.desc_count == 1:
            return
        if dev.desc_count == 2:
            dev.last_desc_received = now
            return

        dev.desc_interval = now - dev.last_desc_received
        dev.last_desc_received = now

        cancel = self._desc_watchdog_timers.pop(dev.device_name, None)
        if cancel is not None:
            cancel()

        timeout = self._calc_desc_watchdog_timeout(dev)
        device_name = dev.device_name

        @callback
        def _on_watchdog(_now: Any) -> None:
            self._desc_watchdog_expired(dev)

        self._desc_watchdog_timers[device_name] = async_call_later(
            self.hass, timeout, _on_watchdog,
        )

    @staticmethod
    def _calc_desc_watchdog_timeout(dev: DeviceContext) -> float:
        """Return the watchdog timeout based on the measured Desc interval."""
        if dev.desc_interval is not None and dev.desc_interval > 0:
            timeout = dev.desc_interval * DESC_WATCHDOG_GRACE_FACTOR
            return max(DESC_WATCHDOG_MIN_TIMEOUT, min(timeout, DESC_WATCHDOG_MAX_TIMEOUT))
        return float(DESC_WATCHDOG_MIN_TIMEOUT)

    def _desc_watchdog_expired(self, dev: DeviceContext) -> None:
        """Called when no Desc message arrived within the expected interval."""
        self._desc_watchdog_timers.pop(dev.device_name, None)
        if not dev.online:
            return
        _LOGGER.warning(
            "Device %s: no Desc received for %.0fs (expected every %.0fs) "
            "— marking offline",
            dev.device_name,
            self._calc_desc_watchdog_timeout(dev),
            dev.desc_interval or 0,
        )
        dev.online = False
        self._reset_desc_measurement(dev)
        self._notify_widget_listeners(dev, set(dev.widgets.keys()))
        self._notify_hub_status(dev.device_name)
        self.reconcile_stale_device_repair()
        self.hass.async_create_task(self._publish_desc_offline(dev))

    async def _publish_desc_offline(self, dev: DeviceContext) -> None:
        """Publish a retained Desc payload with Online=false to the broker."""
        client = self._client
        if client is None:
            return
        payload: dict[str, Any] = {DESC_ONLINE: False}
        if dev.desc_timestamp:
            payload[DESC_TIMESTAMP] = dev.desc_timestamp
        if dev.icon_name:
            payload[DESC_ICON] = dev.icon_name
        if dev.permitted_users:
            payload[DESC_PERMITTED_USERS] = dev.permitted_users
        try:
            await client.publish(
                self._desc_topic(dev.device_name),
                payload=json.dumps(payload),
                qos=1,
                retain=True,
            )
            _LOGGER.info(
                "Published offline Desc for %s to broker (retained)",
                dev.device_name,
            )
        except aiomqtt.MqttError:
            _LOGGER.debug(
                "Failed to publish offline Desc for %s", dev.device_name,
            )

    @staticmethod
    def _reset_desc_measurement(dev: DeviceContext) -> None:
        """Reset Desc interval measurement so re-calibration starts fresh."""
        dev.desc_count = 0
        dev.desc_interval = None
        dev.last_desc_received = None

    def _cancel_desc_watchdog(self, dev: DeviceContext) -> None:
        """Cancel the Desc watchdog timer and reset measurement for a device."""
        cancel = self._desc_watchdog_timers.pop(dev.device_name, None)
        if cancel is not None:
            cancel()
        self._reset_desc_measurement(dev)

    def _cancel_all_desc_watchdogs(self) -> None:
        """Cancel all pending Desc watchdog timers."""
        for cancel in self._desc_watchdog_timers.values():
            cancel()
        self._desc_watchdog_timers.clear()

    # ── PLC Messages ─────────────────────────────────────────────────

    def _handle_plc_message(
        self, dev: DeviceContext, msg_id: str, payload: bytes | bytearray | str,
    ) -> None:
        """Process a message from the PLC Messages topic.

        Empty payload means the retained message was deleted on the broker.
        A payload with an Acknowledgement key means the message was acknowledged.
        """
        if not payload:
            old = dev.messages.pop(msg_id, None)
            if old:
                _LOGGER.debug("PLC message %s removed on %s", msg_id, dev.device_name)
                self._notify_message_callbacks(dev.device_name, "deleted", old)
            return

        data = self._parse_json_payload_sync(payload, f"Messages/{msg_id}")
        if data is None:
            return

        text = data.get(MSG_MESSAGE, "")
        timestamp = data.get(MSG_TIMESTAMP, "")
        msg_type = data.get(MSG_TYPE, MSG_TYPE_DEFAULT)
        ack_text = data.get(MSG_ACKNOWLEDGEMENT)

        existing = dev.messages.get(msg_id)
        msg = TcIotMessage(
            message_id=msg_id,
            timestamp=timestamp,
            text=text,
            message_type=msg_type,
            acknowledged=ack_text is not None,
            acknowledgement_text=ack_text,
        )
        dev.messages[msg_id] = msg

        if len(dev.messages) > MAX_MESSAGES_PER_DEVICE:
            oldest_key = next(iter(dev.messages))
            dev.messages.pop(oldest_key, None)

        if ack_text is not None:
            if existing and not existing.acknowledged:
                _LOGGER.debug("PLC message %s acknowledged on %s", msg_id, dev.device_name)
                self._notify_message_callbacks(dev.device_name, "acknowledged", msg)
        elif existing is None:
            _LOGGER.info(
                "PLC message received on %s: id=%s, type=%s, text=%s",
                dev.device_name, msg_id, msg_type, text,
            )
            self._notify_message_callbacks(dev.device_name, "received", msg)

    def _notify_message_callbacks(
        self, device_name: str, event_type: str, msg: TcIotMessage,
    ) -> None:
        """Invoke all registered message callbacks for a device."""
        for cb in self._message_callbacks.get(device_name, []):
            self._safe_invoke(cb, event_type, msg)

    # ── discovery & reconciliation ──────────────────────────────────

    @staticmethod
    def _build_field_meta_index(
        metadata: dict[str, Any],
    ) -> dict[str, dict[str, dict[str, str]]]:
        """Build a prefix index for field-level metadata lookups.

        Returns {widget_path: {field_name: {meta_key: meta_val}}}
        so that field metadata can be retrieved in O(1) per widget
        instead of scanning every metadata key.
        """
        index: dict[str, dict[str, dict[str, str]]] = {}
        for mk, mv in metadata.items():
            if not isinstance(mv, dict):
                continue
            dot_pos = mk.rfind(".")
            if dot_pos < 0:
                continue
            parent = mk[:dot_pos]
            field_name = mk[dot_pos + 1:]
            if parent not in index:
                index[parent] = {}
            index[parent][field_name] = mv
        return index

    def _discover_widgets(
        self,
        dev: DeviceContext,
        values: dict[str, Any],
        metadata: dict[str, Any],
        path_accumulator: set[str] | None = None,
        meta_changed_paths: set[str] | None = None,
    ) -> int:
        """Discover new widgets from a Tx/Data message (additive only).

        Safe for both full snapshots and partial OnChange payloads: existing
        widgets are updated in place, and only genuinely new widgets are added.
        No widgets are ever removed or marked stale by this method.
        If path_accumulator is provided, all discovered widget paths are added
        to it (used during snapshot windows to collect the full widget set).
        If meta_changed_paths is provided, widget paths whose metadata was
        updated in-place are collected so the caller can notify listeners
        after value merging is complete.
        Returns the number of widgets whose metadata changed.
        """
        new_widgets: dict[Platform, list[WidgetData]] = {}
        skipped_types: dict[str, int] = {}
        field_index = self._build_field_meta_index(metadata)
        mc: list[int] = [0]
        self._walk_values(
            dev, values, metadata, "", new_widgets, [],
            incoming_paths=path_accumulator,
            skipped_types=skipped_types, field_meta_index=field_index,
            meta_changed=mc, meta_changed_paths=meta_changed_paths,
        )
        self._notify_new_widgets(dev, new_widgets, skipped_types)
        return mc[0]

    def _notify_new_widgets(
        self,
        dev: DeviceContext,
        new_widgets: dict[Platform, list[WidgetData]],
        skipped_types: dict[str, int] | None = None,
    ) -> None:
        """Notify platform callbacks about newly discovered widgets."""
        total = sum(len(w) for w in new_widgets.values())
        if total:
            summary = ", ".join(
                f"{len(ws)} {p.value}" for p, ws in new_widgets.items() if ws
            )
            _LOGGER.info(
                "Discovered %d new widget(s) on %s: %s",
                total, dev.device_name, summary,
            )
        if skipped_types:
            skip_summary = ", ".join(
                f"{cnt} {wtype}" for wtype, cnt in sorted(skipped_types.items())
            )
            _LOGGER.debug(
                "Skipped %d widget(s) with unmapped widget type on %s: %s",
                sum(skipped_types.values()), dev.device_name, skip_summary,
            )
        for platform, widgets in new_widgets.items():
            if widgets:
                cb = self._new_widget_callbacks.get(platform)
                if cb:
                    self._safe_invoke(cb, dev.device_name, widgets)

    def _mark_children_stale(self, dev: DeviceContext, view_path: str) -> None:
        """Mark all known widgets under a view path as stale."""
        dev.denied_view_paths.add(view_path)
        prefix = f"{view_path}."
        affected = {
            p for p in dev.known_widget_paths
            if p.startswith(prefix) and p not in dev.stale_widget_paths
        }
        if affected:
            dev.stale_widget_paths |= affected
            _LOGGER.info(
                "View %s on %s no longer permitted – marking %d child widget(s) stale",
                view_path, dev.device_name, len(affected),
            )
            self._notify_widget_listeners(dev, affected)
            self.reconcile_stale_device_repair()

    def _recover_children(self, dev: DeviceContext, view_path: str) -> None:
        """Recover stale widgets under a view path whose permission was restored.

        Only recovers children that were made stale by a view permission
        denial (_mark_children_stale).  Widgets that are stale because they
        were absent from a full snapshot are never touched here.
        """
        if view_path not in dev.denied_view_paths:
            return
        dev.denied_view_paths.discard(view_path)
        prefix = f"{view_path}."
        recovered = {
            p for p in dev.stale_widget_paths if p.startswith(prefix)
        }
        if recovered:
            dev.stale_widget_paths -= recovered
            _LOGGER.info(
                "View %s on %s permission restored – recovering %d child widget(s)",
                view_path, dev.device_name, len(recovered),
            )
            self._notify_widget_listeners(dev, recovered)
            self.reconcile_stale_device_repair()

    def _walk_values(
        self,
        dev: DeviceContext,
        values: dict[str, Any],
        metadata: dict[str, Any],
        prefix: str,
        new_widgets: dict[Platform, list[WidgetData]],
        view_names: list[str],
        incoming_paths: set[str] | None = None,
        parent_read_only: bool = False,
        parent_view_path: str | None = None,
        *,
        skipped_types: dict[str, int] | None = None,
        field_meta_index: dict[str, dict[str, dict[str, str]]] | None = None,
        meta_changed: list[int] | None = None,
        meta_changed_paths: set[str] | None = None,
    ) -> None:
        """Recursively walk the Values tree and create or update widgets.

        Entries with iot.WidgetType in their MetaData are treated as widgets;
        all others are treated as views and recursed into. When incoming_paths
        is provided, discovered widget paths are collected for reconciliation.
        ReadOnly is inherited: if any parent view is read-only, all descendant
        widgets are treated as read-only regardless of their own metadata.

        Views are collected in dev.views. When a widget is found, its immediate
        parent view is recorded in dev.widget_parent_view for area assignment.
        """
        for key, val in values.items():
            full_path = f"{prefix}.{key}" if prefix else key

            if not isinstance(val, dict):
                if isinstance(val, list):
                    self._try_discover_array(
                        dev, key, val, full_path, metadata, new_widgets,
                        view_names, incoming_paths, parent_read_only,
                        parent_view_path,
                        skipped_types=skipped_types,
                    )
                else:
                    self._try_discover_datatype(
                        dev, key, val, full_path, metadata, new_widgets,
                        view_names, incoming_paths, parent_read_only,
                        parent_view_path,
                        skipped_types=skipped_types,
                    )
                continue

            meta_entry = metadata.get(full_path, {})
            if not isinstance(meta_entry, dict):
                meta_entry = {}

            if META_WIDGET_TYPE in meta_entry:
                if not self._is_user_permitted(meta_entry.get(META_PERMITTED_USERS)):
                    if full_path in dev.known_widget_paths and full_path not in dev.stale_widget_paths:
                        dev.stale_widget_paths.add(full_path)
                        _LOGGER.info(
                            "Widget %s on %s no longer permitted – marking stale",
                            full_path, dev.device_name,
                        )
                        self._notify_widget_listeners(dev, {full_path})
                        self.reconcile_stale_device_repair()
                    continue

                if full_path in dev.stale_widget_paths:
                    dev.stale_widget_paths.discard(full_path)
                    _LOGGER.info(
                        "Widget %s on %s permission restored – recovering",
                        full_path, dev.device_name,
                    )
                    self._notify_widget_listeners(dev, {full_path})
                    self.reconcile_stale_device_repair()

                if incoming_paths is not None:
                    incoming_paths.add(full_path)

                if parent_view_path is not None:
                    dev.widget_parent_view[full_path] = parent_view_path

                widget_meta = parse_metadata(meta_entry)
                if parent_read_only:
                    widget_meta.read_only = True
                vprefix = " ".join(view_names)
                # sDisplayName in Values overrides iot.DisplayName from MetaData.
                runtime_name = str(val.get(VAL_DISPLAY_NAME) or "")
                widget_display = runtime_name or widget_meta.display_name or key
                friendly = f"{vprefix} {widget_display}".strip() if vprefix else widget_display

                field_meta: dict[str, dict[str, str]] = (
                    field_meta_index.get(full_path, {}) if field_meta_index is not None
                    else {
                        mk[len(full_path) + 1:]: mv
                        for mk, mv in metadata.items()
                        if mk.startswith(f"{full_path}.") and isinstance(mv, dict)
                    }
                )

                existing = dev.widgets.get(full_path)
                if existing:
                    meta_is_different = (
                        existing.metadata != widget_meta
                        or existing.view_prefix != vprefix
                        or existing.friendly_path != friendly
                        or existing.field_metadata != field_meta
                    )
                    if meta_is_different:
                        if meta_changed is not None:
                            meta_changed[0] += 1
                        if meta_changed_paths is not None:
                            meta_changed_paths.add(full_path)
                        existing.metadata = widget_meta
                        existing.view_prefix = vprefix
                        existing.friendly_path = friendly
                        existing.field_metadata = field_meta
                else:
                    widget = WidgetData(
                        widget_id=key,
                        path=full_path,
                        metadata=widget_meta,
                        values=dict(val),
                        view_prefix=vprefix,
                        friendly_path=friendly,
                        field_metadata=field_meta,
                    )
                    dev.widgets[full_path] = widget

                    parts = full_path.split(".")
                    for i in range(1, len(parts)):
                        dev.widget_path_prefixes.add(".".join(parts[:i]))
                    if full_path not in dev.known_widget_paths:
                        dev.known_widget_paths.add(full_path)
                    self._route_widget_to_platforms(
                        widget_meta.widget_type, widget, new_widgets, full_path,
                        skipped_types=skipped_types,
                    )
            else:
                if not self._is_user_permitted(meta_entry.get(META_PERMITTED_USERS)):
                    self._mark_children_stale(dev, full_path)
                    continue
                self._recover_children(dev, full_path)
                # Prefer iot.DisplayName from MetaData; fall back to the
                # cached name from a previous full-snapshot discovery so that
                # additive onchange runs (which omit parent-view MetaData)
                # don't overwrite the view name with the raw struct key.
                cached_view = dev.views.get(full_path)
                view_display = (
                    meta_entry.get(META_DISPLAY_NAME)
                    or (cached_view.display_name if cached_view else None)
                    or key
                )
                view_read_only = parent_read_only or metadata_bool(
                    meta_entry.get(META_READ_ONLY)
                )
                dev.views[full_path] = ViewData(
                    path=full_path,
                    display_name=view_display,
                    icon=meta_entry.get(META_NESTED_STRUCT_ICON, ""),
                    parent_path=parent_view_path,
                    permitted_users=meta_entry.get(META_PERMITTED_USERS),
                    read_only=view_read_only,
                )
                self._walk_values(
                    dev, val, metadata, full_path, new_widgets,
                    [*view_names, view_display], incoming_paths, view_read_only,
                    parent_view_path=full_path,
                    skipped_types=skipped_types,
                    field_meta_index=field_meta_index,
                    meta_changed=meta_changed,
                    meta_changed_paths=meta_changed_paths,
                )

    def _route_widget_to_platforms(
        self,
        widget_type: str,
        widget: WidgetData,
        new_widgets: dict[Platform, list[WidgetData]],
        full_path: str,
        *,
        skipped_types: dict[str, int] | None = None,
    ) -> None:
        """Route a widget to the correct platform(s) via WIDGET_PLATFORM_MAP."""
        platform = WIDGET_PLATFORM_MAP.get(widget_type)
        if platform is not None:
            new_widgets.setdefault(platform, []).append(widget)
            return

        multi = WIDGET_MULTI_PLATFORM_MAP.get(widget_type)
        if multi is not None:
            for p in multi:
                new_widgets.setdefault(p, []).append(widget)
            return

        if skipped_types is not None:
            skipped_types[widget_type] = skipped_types.get(widget_type, 0) + 1

    def _try_discover_datatype(
        self,
        dev: DeviceContext,
        key: str,
        val: Any,
        full_path: str,
        metadata: dict[str, Any],
        new_widgets: dict[Platform, list[WidgetData]],
        view_names: list[str],
        incoming_paths: set[str] | None,
        parent_read_only: bool,
        parent_view_path: str | None,
        *,
        skipped_types: dict[str, int] | None = None,
    ) -> None:
        """Discover a scalar PLC datatype value (BOOL/INT/REAL/STRING).

        Type is determined from the JSON value type, not from the PLC
        variable name.  This makes detection independent of naming
        conventions.
        """
        meta_entry = metadata.get(full_path, {})
        if not isinstance(meta_entry, dict) or META_DISPLAY_NAME not in meta_entry:
            return

        if isinstance(val, bool):
            synthetic_type = DATATYPE_BOOL
        elif isinstance(val, (int, float)):
            synthetic_type = DATATYPE_NUMBER
        elif isinstance(val, str):
            synthetic_type = DATATYPE_STRING
        else:
            return

        if not self._is_user_permitted(meta_entry.get(META_PERMITTED_USERS)):
            if full_path in dev.known_widget_paths and full_path not in dev.stale_widget_paths:
                dev.stale_widget_paths.add(full_path)
                _LOGGER.info(
                    "Datatype widget %s on %s no longer permitted – marking stale",
                    full_path, dev.device_name,
                )
                self._notify_widget_listeners(dev, {full_path})
                self.reconcile_stale_device_repair()
            return

        if full_path in dev.stale_widget_paths:
            dev.stale_widget_paths.discard(full_path)
            _LOGGER.info(
                "Datatype widget %s on %s permission restored – recovering",
                full_path, dev.device_name,
            )
            self._notify_widget_listeners(dev, {full_path})
            self.reconcile_stale_device_repair()

        if incoming_paths is not None:
            incoming_paths.add(full_path)

        if parent_view_path is not None:
            dev.widget_parent_view[full_path] = parent_view_path

        widget_meta = parse_metadata(meta_entry)
        if parent_read_only:
            widget_meta.read_only = True
        widget_meta.widget_type = synthetic_type

        widget_display = widget_meta.display_name or key
        friendly = " ".join([*view_names, widget_display])

        existing = dev.widgets.get(full_path)
        if existing:
            existing.metadata = widget_meta
            existing.friendly_path = friendly
        else:
            widget = WidgetData(
                widget_id=key,
                path=full_path,
                metadata=widget_meta,
                values={"value": val},
                friendly_path=friendly,
            )
            dev.widgets[full_path] = widget

            parts = full_path.split(".")
            for i in range(1, len(parts)):
                dev.widget_path_prefixes.add(".".join(parts[:i]))
            if full_path not in dev.known_widget_paths:
                dev.known_widget_paths.add(full_path)
            self._route_widget_to_platforms(
                synthetic_type, widget, new_widgets, full_path,
                skipped_types=skipped_types,
            )

    def _try_discover_array(
        self,
        dev: DeviceContext,
        key: str,
        val: list[Any],
        full_path: str,
        metadata: dict[str, Any],
        new_widgets: dict[Platform, list[WidgetData]],
        view_names: list[str],
        incoming_paths: set[str] | None,
        parent_read_only: bool,
        parent_view_path: str | None,
        *,
        skipped_types: dict[str, int] | None = None,
    ) -> None:
        """Discover a one-dimensional PLC array (ARRAY OF BOOL/INT/REAL/STRING)."""
        meta_entry = metadata.get(full_path, {})
        if not isinstance(meta_entry, dict) or META_DISPLAY_NAME not in meta_entry:
            return
        if not val:
            return

        first = val[0]
        if isinstance(first, bool):
            synthetic_type = DATATYPE_ARRAY_BOOL
        elif isinstance(first, (int, float)):
            synthetic_type = DATATYPE_ARRAY_NUMBER
        elif isinstance(first, str):
            synthetic_type = DATATYPE_ARRAY_STRING
        else:
            return

        if not self._is_user_permitted(meta_entry.get(META_PERMITTED_USERS)):
            if full_path in dev.known_widget_paths and full_path not in dev.stale_widget_paths:
                dev.stale_widget_paths.add(full_path)
                _LOGGER.info(
                    "Array widget %s on %s no longer permitted – marking stale",
                    full_path, dev.device_name,
                )
                self._notify_widget_listeners(dev, {full_path})
                self.reconcile_stale_device_repair()
            return

        if full_path in dev.stale_widget_paths:
            dev.stale_widget_paths.discard(full_path)
            _LOGGER.info(
                "Array widget %s on %s permission restored – recovering",
                full_path, dev.device_name,
            )
            self._notify_widget_listeners(dev, {full_path})
            self.reconcile_stale_device_repair()

        if incoming_paths is not None:
            incoming_paths.add(full_path)

        if parent_view_path is not None:
            dev.widget_parent_view[full_path] = parent_view_path

        widget_meta = parse_metadata(meta_entry)
        widget_meta.read_only = True
        widget_meta.widget_type = synthetic_type

        widget_display = widget_meta.display_name or key
        friendly = " ".join([*view_names, widget_display])

        existing = dev.widgets.get(full_path)
        if existing:
            existing.metadata = widget_meta
            existing.friendly_path = friendly
        else:
            widget = WidgetData(
                widget_id=key,
                path=full_path,
                metadata=widget_meta,
                values={"value": val},
                friendly_path=friendly,
            )
            dev.widgets[full_path] = widget

            parts = full_path.split(".")
            for i in range(1, len(parts)):
                dev.widget_path_prefixes.add(".".join(parts[:i]))
            if full_path not in dev.known_widget_paths:
                dev.known_widget_paths.add(full_path)
            self._route_widget_to_platforms(
                synthetic_type, widget, new_widgets, full_path,
                skipped_types=skipped_types,
            )

    # ── view → area mapping ────────────────────────────────────────

    def _create_areas_from_views(self, dev: DeviceContext) -> None:
        """Create HA Areas for views that directly contain widgets.

        Runs once per device on the initial snapshot.
        Existing areas (by name) are reused, never modified.
        """
        if not self._create_areas:
            return
        if dev.areas_from_views_done:
            return
        dev.areas_from_views_done = True

        bearing_paths = set(dev.widget_parent_view.values())
        if not bearing_paths:
            self._flush_area_callbacks()
            return

        area_reg = ar.async_get(self.hass)
        resolved = self._resolve_area_names(dev, bearing_paths)

        for path, area_name in resolved.items():
            view = dev.views.get(path)
            if view is None:
                continue
            scoped_key = f"{dev.device_name}.{path}"
            mdi_icon = TCIOT_ICON_MAP.get(view.icon)

            existing = area_reg.async_get_area_by_name(area_name)
            if existing:
                self._view_area_map[scoped_key] = existing.id
            else:
                area = area_reg.async_create(area_name, icon=mdi_icon)
                self._view_area_map[scoped_key] = area.id
                if area_name != view.display_name:
                    area_reg.async_update(area.id, aliases={view.display_name})

        _LOGGER.info(
            "Mapped %d view(s) to HA areas on %s",
            len(resolved), dev.device_name,
        )

        self._flush_area_callbacks()

    def _flush_area_callbacks(self) -> None:
        """Fire pending area-ready callbacks; keep those that returned False."""
        remaining: list[Callable[[], bool]] = []
        for cb in self._areas_ready_callbacks:
            try:
                if not cb():
                    remaining.append(cb)
            except Exception:
                _LOGGER.exception("Area-ready callback %s raised", cb)
        self._areas_ready_callbacks[:] = remaining

    def _resolve_area_names(
        self, dev: DeviceContext, bearing_paths: set[str],
    ) -> dict[str, str]:
        """Resolve final area names for widget-bearing views.

        Detects duplicate DisplayNames among the bearing views and
        disambiguates by prepending parent view names.
        """
        name_groups: dict[str, list[str]] = {}
        for path in bearing_paths:
            view = dev.views.get(path)
            if view is None:
                continue
            name_groups.setdefault(view.display_name, []).append(path)

        resolved: dict[str, str] = {}
        for name, paths in name_groups.items():
            if len(paths) == 1:
                resolved[paths[0]] = name
            else:
                for p in paths:
                    resolved[p] = self._disambiguate_name(dev, p, bearing_paths)

        return resolved

    def _disambiguate_name(
        self, dev: DeviceContext, view_path: str, all_paths: set[str],
    ) -> str:
        """Build a unique area name by prepending parent DisplayNames.

        Walks up the parent chain until the resulting name is unique among
        all_paths. Falls back to a numeric suffix if no parent exists.
        """
        view = dev.views[view_path]
        parts = [view.display_name]
        current = view

        while True:
            parent_path = current.parent_path
            if parent_path is None:
                break
            parent = dev.views.get(parent_path)
            if parent is None:
                break
            parts.insert(0, parent.display_name)
            candidate = " ".join(parts)

            collision = False
            for other_path in all_paths:
                if other_path == view_path:
                    continue
                other = dev.views.get(other_path)
                if other is None:
                    continue
                other_candidate = self._build_name_with_ancestors(
                    dev, other_path, len(parts),
                )
                if other_candidate == candidate:
                    collision = True
                    break

            if not collision:
                return candidate
            current = parent

        candidate = " ".join(parts)
        # If still not unique (no more parents), append numeric suffix
        existing_names = {
            self._build_name_with_ancestors(dev, p, len(parts))
            for p in all_paths if p != view_path and dev.views.get(p)
        }
        if candidate not in existing_names:
            return candidate

        counter = 2
        while f"{candidate} {counter}" in existing_names:
            counter += 1
        return f"{candidate} {counter}"

    def _build_name_with_ancestors(
        self, dev: DeviceContext, view_path: str, depth: int,
    ) -> str:
        """Build a name from a view and its ancestors up to *depth* levels."""
        view = dev.views.get(view_path)
        if view is None:
            return view_path
        parts = [view.display_name]
        current = view
        while len(parts) < depth:
            parent_path = current.parent_path
            if parent_path is None:
                break
            parent = dev.views.get(parent_path)
            if parent is None:
                break
            parts.insert(0, parent.display_name)
            current = parent
        return " ".join(parts)

    def get_area_for_widget(self, device_name: str, widget_path: str) -> str | None:
        """Return the HA area_id for a widget based on its parent view."""
        dev = self.devices.get(device_name)
        if dev is None:
            return None
        view_path = dev.widget_parent_view.get(widget_path)
        if view_path is None:
            return None
        scoped_key = f"{device_name}.{view_path}"
        return self._view_area_map.get(scoped_key)

    @callback
    def on_areas_ready(self, cb: Callable[[], bool]) -> Callable[[], None]:
        """Register a callback to fire once areas have been created.

        If at least one device has already finished area creation the callback
        fires immediately.  On success (True) a no-op unregister is returned.
        On failure the callback is kept in the pending list so it can be
        retried when the next device finishes its area creation.
        """
        if self._areas_created:
            try:
                if cb():
                    def _noop() -> None:
                        pass
                    return _noop
            except Exception:
                _LOGGER.exception("Area-ready callback %s raised", cb)

        self._areas_ready_callbacks.append(cb)

        def _unregister() -> None:
            if cb in self._areas_ready_callbacks:
                self._areas_ready_callbacks.remove(cb)

        return _unregister

    # ── state updates ───────────────────────────────────────────────

    _UPDATE_LOG_CAP = 15

    def _update_widgets(
        self, dev: DeviceContext, values: dict[str, Any],
        prefix: str = "",
        _log_budget: list[int] | None = None,
        _change_lines: list[str] | None = None,
        also_notify: set[str] | None = None,
    ) -> tuple[int, int]:
        """Merge incoming values into known widgets and notify listeners.

        Only the keys present in the incoming values dict are merged; existing
        widget values are preserved (safe for partial payloads).
        Uses widget_path_prefixes to skip subtrees with no known widgets.
        If also_notify is provided, widgets whose paths are in the set are
        notified even when their values did not change (used for metadata-only
        changes detected by _discover_widgets). Paths are consumed from the
        set once notified to avoid double-notification.
        Returns (hit_count, changed_count).
        At most _UPDATE_LOG_CAP changed-value lines are collected.
        """
        verbose = _LOGGER.isEnabledFor(logging.DEBUG)
        if _log_budget is None:
            _log_budget = [self._UPDATE_LOG_CAP]
        if _change_lines is None:
            _change_lines = []
        hit_count = 0
        changed_count = 0
        for key, val in values.items():
            full_path = f"{prefix}.{key}" if prefix else key

            if not isinstance(val, dict):
                if full_path in dev.widgets:
                    hit_count += 1
                    widget = dev.widgets[full_path]
                    if "value" not in widget.values:
                        _LOGGER.debug(
                            "Ignoring scalar update for structured widget %s on %s",
                            full_path, dev.device_name,
                        )
                        continue
                    val_changed = widget.values.get("value") != val
                    if val_changed:
                        changed_count += 1
                        widget.values["value"] = val
                        if verbose and _log_budget[0] > 0:
                            _log_budget[0] -= 1
                            _change_lines.append(f"{full_path} = {val}")
                    needs_notify = val_changed or (
                        also_notify is not None and full_path in also_notify
                    )
                    if needs_notify:
                        if also_notify is not None:
                            also_notify.discard(full_path)
                        listener_key = f"{dev.device_name}/{full_path}"
                        for fn in self._listeners.get(listener_key, []):
                            self._safe_invoke(fn, widget)
                continue

            if full_path in dev.widgets:
                hit_count += 1
                widget = dev.widgets[full_path]
                changed = {k: v for k, v in val.items() if widget.values.get(k) != v}
                if changed:
                    changed_count += 1
                    if verbose and _log_budget[0] > 0:
                        _log_budget[0] -= 1
                        _change_lines.extend(
                            f"{full_path}.{k} = {v!r}" for k, v in changed.items()
                        )
                    display_name_val = changed.get(VAL_DISPLAY_NAME)
                    widget.values.update(changed)
                    if display_name_val is not None:
                        new_name = (
                            str(display_name_val or "")
                            or widget.metadata.display_name
                            or widget.widget_id
                        )
                        widget.friendly_path = (
                            f"{widget.view_prefix} {new_name}".strip()
                            if widget.view_prefix else new_name
                        )
                needs_notify = bool(changed) or (
                    also_notify is not None and full_path in also_notify
                )
                if needs_notify:
                    if also_notify is not None:
                        also_notify.discard(full_path)
                    listener_key = f"{dev.device_name}/{full_path}"
                    for fn in self._listeners.get(listener_key, []):
                        self._safe_invoke(fn, widget)
            elif full_path in dev.widget_path_prefixes:
                sub_hit, sub_changed = self._update_widgets(
                    dev, val, prefix=full_path,
                    _log_budget=_log_budget,
                    _change_lines=_change_lines,
                    also_notify=also_notify,
                )
                hit_count += sub_hit
                changed_count += sub_changed
        return hit_count, changed_count

    # ── public API ──────────────────────────────────────────────────

    def get_device(self, device_name: str) -> DeviceContext | None:
        """Return the DeviceContext for a device name, or None."""
        return self.devices.get(device_name)

    def is_device_removable(self, device_name: str) -> bool:
        """Return True if the Hub Device can be safely removed.

        A Hub Device is removable when it is not actively communicating:
        not tracked by the coordinator (never appeared after startup),
        or tracked but offline (Desc watchdog expired / PLC reported offline).
        """
        dev = self.devices.get(device_name)
        if dev is None:
            return True
        return not dev.online

    def get_stale_device_names(self) -> set[str]:
        """Return Hub Device names present in the HA registry but removable."""
        dev_reg = dr.async_get(self.hass)
        prefix = f"{self.entry.entry_id}_"
        stale: set[str] = set()
        for device in dr.async_entries_for_config_entry(dev_reg, self.entry.entry_id):
            if device.via_device_id is not None:
                continue
            for domain, ident in device.identifiers:
                if domain == DOMAIN and ident.startswith(prefix):
                    name = ident.removeprefix(prefix)
                    if self.is_device_removable(name):
                        stale.add(name)
        return stale

    def is_widget_removable(self, device_name: str, widget_path: str) -> bool:
        """Return True if a Widget Sub-Device can be safely removed.

        A widget is removable when its Hub Device is gone/offline,
        or the widget path is in the device's stale set (absent from
        the last full snapshot).
        """
        dev = self.devices.get(device_name)
        if dev is None:
            return True
        if not dev.online:
            return True
        return widget_path in dev.stale_widget_paths

    def get_stale_widget_info(self) -> list[tuple[str, str]]:
        """Return (device_name, widget_path) pairs for all stale widgets."""
        result: list[tuple[str, str]] = []
        for dev in self.devices.values():
            for path in dev.stale_widget_paths:
                result.append((dev.device_name, path))
        return result

    async def async_remove_widget(self, device_name: str, widget_path: str) -> None:
        """Remove a single widget from coordinator state."""
        dev = self.devices.get(device_name)
        if dev is None:
            return
        dev.widgets.pop(widget_path, None)
        dev.known_widget_paths.discard(widget_path)
        dev.stale_widget_paths.discard(widget_path)
        dev.widget_parent_view.pop(widget_path, None)
        listener_key = f"{device_name}/{widget_path}"
        self._listeners.pop(listener_key, None)
        _LOGGER.info("Removed widget %s from device %s", widget_path, device_name)

    @callback
    def reconcile_stale_device_repair(self) -> None:
        """Create or remove the stale-devices repair issue.

        Only stale Widget Sub-Devices trigger a repair issue.  Hub Devices
        going offline is normal operation (PLC restart, maintenance) and
        must not appear in repairs — they are only removable manually via
        the device page.
        """
        stale_widgets = self.get_stale_widget_info()
        total = len(stale_widgets)

        if total > 0:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "stale_devices",
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="stale_devices",
                translation_placeholders={
                    "count": str(total),
                },
                data={"entry_id": self.entry.entry_id},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "stale_devices")

    def register_new_widget_callback(self, platform: Platform, cb: NewWidgetCallback) -> None:
        """Register a callback invoked when new widgets are discovered for a platform."""
        self._new_widget_callbacks[platform] = cb

    def register_new_device_callback(self, cb: NewDeviceCallback) -> None:
        """Register a callback invoked when a new PLC device is discovered."""
        self._new_device_callbacks.append(cb)

    def register_listener(
        self, device_name: str, widget_path: str, callback_fn: WidgetCallback,
    ) -> Callable[[], None]:
        """Register a per-widget update listener and return an unregister callable."""
        key = f"{device_name}/{widget_path}"
        self._listeners.setdefault(key, []).append(callback_fn)

        def _unregister() -> None:
            listeners = self._listeners.get(key, [])
            if callback_fn in listeners:
                listeners.remove(callback_fn)

        return _unregister

    def register_hub_status_callback(
        self, device_name: str, cb: Callable[[], None],
    ) -> Callable[[], None]:
        """Register a callback invoked when a device's hub status changes.

        Returns an unregister callable.
        """
        self._hub_status_callbacks.setdefault(device_name, []).append(cb)

        def _unregister() -> None:
            listeners = self._hub_status_callbacks.get(device_name, [])
            if cb in listeners:
                listeners.remove(cb)

        return _unregister

    def _notify_hub_status(self, device_name: str) -> None:
        """Invoke all hub-status callbacks for a device."""
        for cb in self._hub_status_callbacks.get(device_name, []):
            self._safe_invoke(cb)

    async def async_request_full_update(self, device_name: str) -> None:
        """Re-publish active=1 for a device to trigger a full JSON resend.

        NOTE: On the PLC side, FB_IotCommunicator.bNewAppSubscribe fires briefly
        when active=1 is received. The PLC must act on this flag to publish the
        full JSON immediately. This is a PLC-side
        configuration responsibility.
        """
        if self._client is None:
            _LOGGER.warning("Cannot request full update: MQTT not connected")
            return
        dev = self.devices.get(device_name)
        if dev is None:
            _LOGGER.warning("Cannot request full update: device %s not found", device_name)
            return
        if not dev.registered:
            _LOGGER.warning("Cannot request full update: device %s not registered", device_name)
            return

        self._begin_snapshot_window(dev)
        try:
            await self._client.publish(
                self._comm_active_topic(device_name),
                payload="1", qos=1, retain=False,
            )
        except aiomqtt.MqttError:
            _LOGGER.warning("Failed to publish active=1 for %s", device_name)
            return
        _LOGGER.info("Full update requested for device %s", device_name)

    def register_message_callback(
        self, device_name: str, cb: MessageCallback,
    ) -> Callable[[], None]:
        """Register a callback invoked on message events (received/acknowledged/deleted)."""
        self._message_callbacks.setdefault(device_name, []).append(cb)

        def _unregister() -> None:
            listeners = self._message_callbacks.get(device_name, [])
            if cb in listeners:
                listeners.remove(cb)

        return _unregister

    def _next_message_id(self, dev: DeviceContext) -> str:
        """Return the next available numeric message ID for a device."""
        max_id = 0
        for mid in dev.messages:
            with contextlib.suppress(ValueError):
                max_id = max(max_id, int(mid))
        return str(max_id + 1)

    async def async_send_message(
        self, device_name: str, text: str,
        message_type: str = MSG_TYPE_DEFAULT,
    ) -> None:
        """Publish a new message to the PLC Messages topic.

        Automatically assigns the next available numeric message ID.
        """
        if self._client is None:
            _LOGGER.warning("Cannot send message: MQTT not connected")
            return

        if not _is_safe_topic_segment(device_name):
            _LOGGER.warning("Rejected unsafe device_name in send: %s", device_name)
            return

        dev = self.devices.get(device_name)
        if dev is None:
            _LOGGER.warning("Cannot send message: device %s not found", device_name)
            return

        message_id = self._next_message_id(dev)
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        payload = json.dumps({
            MSG_TIMESTAMP: now,
            MSG_MESSAGE: text,
            MSG_TYPE: message_type,
            MSG_SENT: True,
        })
        topic = self._message_topic(device_name, message_id)
        await self._client.publish(topic, payload=payload, qos=1, retain=True)
        _LOGGER.info("Message %s sent to %s (type=%s)", message_id, device_name, message_type)

    async def async_acknowledge_message(
        self, device_name: str, message_id: str, acknowledgement: str,
    ) -> None:
        """Publish an acknowledgement for a PLC message."""
        if self._client is None:
            _LOGGER.warning("Cannot acknowledge message: MQTT not connected")
            return

        if not _is_safe_topic_segment(device_name) or not _is_safe_topic_segment(message_id):
            _LOGGER.warning("Rejected unsafe device/message_id in acknowledge: %s/%s", device_name, message_id)
            return

        dev = self.devices.get(device_name)
        msg = dev.messages.get(message_id) if dev else None
        if msg is None:
            _LOGGER.warning("Message %s not found on device %s", message_id, device_name)
            return

        payload = json.dumps({
            MSG_TIMESTAMP: msg.timestamp,
            MSG_MESSAGE: msg.text,
            MSG_TYPE: msg.message_type,
            MSG_SENT: False,
            MSG_ACKNOWLEDGEMENT: acknowledgement,
        })
        topic = self._message_topic(device_name, message_id)
        await self._client.publish(topic, payload=payload, qos=1, retain=True)
        _LOGGER.info("PLC message %s acknowledged on %s", message_id, device_name)

    async def async_delete_message(self, device_name: str, message_id: str) -> None:
        """Delete a PLC message by clearing its retained MQTT topic."""
        if self._client is None:
            _LOGGER.warning("Cannot delete message: MQTT not connected")
            return

        if not _is_safe_topic_segment(device_name) or not _is_safe_topic_segment(message_id):
            _LOGGER.warning("Rejected unsafe device/message_id in delete: %s/%s", device_name, message_id)
            return

        topic = self._message_topic(device_name, message_id)
        await self._client.publish(topic, payload=b"", qos=1, retain=True)
        _LOGGER.info("PLC message %s deleted on %s", message_id, device_name)

    async def async_send_command(self, device_name: str, commands: dict[str, Any]) -> None:
        """Publish command(s) to the Rx topic of a specific device.

        The PLC expects one value per MQTT message, so each key-value pair
        is published as a separate message using the TC3 IoT Communicator
        structure path:
        {"Values": {"stWidgetsOverview.stWidgetsOverviewSub.stLighting.nLight": 17}}
        """
        if self._client is None:
            raise HomeAssistantError("Cannot send command: MQTT not connected")

        if not _is_safe_topic_segment(device_name):
            _LOGGER.warning("Rejected unsafe device_name in send_command: %s", device_name)
            raise HomeAssistantError(f"Unsafe device name: {device_name}")

        rx = self._rx_topic(device_name)
        coros = []
        for key, value in commands.items():
            try:
                payload = json.dumps({"Values": {key: value}}, allow_nan=False)
            except (TypeError, ValueError) as err:
                raise HomeAssistantError(
                    f"Cannot encode command value for {key}: {err}"
                ) from err
            coros.append(self._client.publish(rx, payload=payload, qos=1))
        if not coros:
            return
        try:
            await asyncio.gather(*coros)
        except aiomqtt.MqttError as err:
            raise HomeAssistantError(f"MQTT publish failed: {err}") from err
        lines = "\n  ".join(f"{k} = {v!r}" for k, v in commands.items())
        _LOGGER.debug(
            "Rx/Data command for %s (%d key(s)):\n  %s",
            device_name, len(commands), lines,
        )
