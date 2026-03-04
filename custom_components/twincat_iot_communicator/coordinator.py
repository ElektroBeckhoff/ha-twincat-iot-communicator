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
from typing import Any
import uuid

import aiomqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar

from .const import (
    AUTH_MODE_CREDENTIALS,
    AUTH_MODE_ONLINE,
    CONF_AUTH_MODE,
    CONF_JWT_TOKEN,
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    CONF_USE_TLS,
    DESC_ICON,
    DESC_ONLINE,
    DESC_PERMITTED_USERS,
    DESC_TIMESTAMP,
    HEARTBEAT_INTERVAL,
    JSON_FORCE_UPDATE,
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
    TOPIC_MESSAGE,
    TOPIC_RX,
    TOPIC_SUB_DESC,
    TOPIC_SUB_MESSAGES,
    TOPIC_SUB_TX,
    WIDGET_MULTI_PLATFORM_MAP,
    WIDGET_PLATFORM_MAP,
    DATATYPE_FIELD_MAP,
)
from .jwt_helper import jwt_expiry_summary, jwt_is_expired
from .models import DeviceContext, TcIotMessage, ViewData, WidgetData, parse_metadata

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5
MAX_MESSAGES_PER_DEVICE = 200
JSON_PARSE_EXECUTOR_THRESHOLD = 50_000

type WidgetCallback = Callable[[WidgetData], None]
type NewWidgetCallback = Callable[[str, list[WidgetData]], None]
type NewDeviceCallback = Callable[[DeviceContext], None]
type MessageCallback = Callable[[str, TcIotMessage], None]


_SAFE_TOPIC_SEGMENT = re.compile(r"^[\w.=\-]+$")


def _is_safe_topic_segment(segment: str) -> bool:
    """Validate that a string is safe for MQTT topic interpolation.

    Rejects segments containing MQTT wildcards (#, +), path separators (/),
    or other control characters.
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
        self._stop_event: asyncio.Event = asyncio.Event()
        self._connected: bool = False

        self._client_id: str = str(uuid.uuid5(uuid.NAMESPACE_URL, entry.entry_id))

        self._view_area_map: dict[str, str] = {}
        self._areas_created: bool = False
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
    def _strip_nulls(payload: bytes | bytearray | str) -> bytes | bytearray | str:
        """Strip null bytes from a payload."""
        if isinstance(payload, (bytes, bytearray)):
            return payload.replace(b"\x00", b"")
        return payload

    async def _async_parse_json_payload(
        self, payload: bytes | bytearray | str, topic: str,
    ) -> dict[str, Any] | None:
        """Strip null bytes, parse JSON, and return dict or None on failure.

        Offloads to the executor for payloads exceeding the threshold to
        avoid blocking the event loop with large PLC snapshots (~230 KB).
        """
        try:
            raw = self._strip_nulls(payload)
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
            raw = self._strip_nulls(payload)
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            _LOGGER.debug("Discarding non-JSON payload on %s", topic)
            return None

    def _notify_widget_listeners(self, dev: DeviceContext, paths: set[str]) -> None:
        """Invoke all widget listeners for the given paths."""
        for path in paths:
            widget = dev.widgets.get(path)
            if widget:
                for fn in self._listeners.get(path, []):
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
        for dev in self.devices.values():
            dev.initial_snapshot_received = False

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

                    for dev in self.devices.values():
                        await self._register_communicator(dev.device_name)

                    self._heartbeat_task = self.hass.async_create_background_task(
                        self._heartbeat_loop(),
                        f"twincat_iot_heartbeat_{self._main_topic}",
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
        self._ignored_devices.add(device_name)

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
                if self._client is not None:
                    for dev in self.devices.values():
                        if dev.registered:
                            try:
                                await self._client.publish(
                                    self._comm_heartbeat_topic(dev.device_name),
                                    payload="1", qos=1, retain=True,
                                )
                            except aiomqtt.MqttError:
                                _LOGGER.debug(
                                    "Heartbeat publish failed for %s, will retry",
                                    dev.device_name,
                                )
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Heartbeat loop terminated unexpectedly", exc_info=True)

    async def _stop_heartbeat(self) -> None:
        """Cancel the heartbeat background task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        self._heartbeat_task = None

    # ── device auto-discovery ───────────────────────────────────────

    def _get_or_create_device(self, device_name: str) -> tuple[DeviceContext, bool]:
        """Return existing DeviceContext or create a new one. Returns (ctx, is_new)."""
        if device_name in self.devices:
            return self.devices[device_name], False

        dev = DeviceContext(device_name=device_name)
        self.devices[device_name] = dev
        _LOGGER.info("Discovered new device: %s", device_name)
        return dev, True

    def _on_new_device(self, dev: DeviceContext) -> None:
        """Notify callbacks about a newly discovered device."""
        for cb in self._new_device_callbacks:
            self._safe_invoke(cb, dev)
        self.hass.async_create_background_task(
            self._register_communicator(dev.device_name),
            f"twincat_iot_register_{dev.device_name}",
        )

    # ── message dispatch ────────────────────────────────────────────

    async def _async_dispatch_message(self, msg: aiomqtt.Message) -> None:
        """Route an incoming MQTT message to the right per-device handler.

        Tx/Data source classification (full vs onchange): the nested values
        tree is counted recursively for leaf widgets.  If the count matches
        the known widget count → full snapshot (PLC SendDataAsString).
        Fewer leaves → OnChange delta (PLC SendDataAsString_OnChange).

        Discovery/reconciliation is driven by MetaData presence and payload shape:
        - MetaData present + first message → initial full-snapshot discovery
        - MetaData present + full payload  → reconciliation (stale/recovery)
        - MetaData present + onchange payload → additive metadata merge only
        - No MetaData → pure value-only update, merged via _update_widgets
        - ForceUpdate marks metadata freshness only; it does not imply full payload
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

        if not self._is_user_permitted(dev.permitted_users):
            return

        values: dict[str, Any] = data.get(JSON_VALUES) or {}
        metadata: dict[str, Any] = data.get(JSON_METADATA) or {}
        force_update: bool = data.get(JSON_FORCE_UPDATE, False)

        # Classify pre-merge payload shape for metadata routing.
        n_known_pre = len(dev.known_widget_paths)
        leaf_count_pre = self._count_value_leaves(dev, values)
        is_full_pre = n_known_pre > 0 and leaf_count_pre >= n_known_pre
        source_pre = "full" if is_full_pre else "onchange"

        meta_changed = 0
        if metadata:
            if not dev.initial_snapshot_received:
                # Guard against a partial onchange arriving before the full
                # snapshot after a reconnect (e.g. if the PLC sends
                # SendDataAsString_OnChange with MetaData=true before
                # SendDataAsString). Only promote to initial_snapshot_received
                # and run full reconciliation on a genuine full payload; treat
                # a partial post-reconnect onchange as additive discovery so
                # we never incorrectly mark missing widgets as stale.
                if is_full_pre or not dev.known_widget_paths:
                    dev.initial_snapshot_received = True
                    if dev.known_widget_paths:
                        meta_changed = self._reconcile_widgets(dev, values, metadata)
                    else:
                        meta_changed = self._discover_widgets(dev, values, metadata)
                    self._create_areas_from_views(dev)
                else:
                    _LOGGER.debug(
                        "Post-reconnect onchange (%d/%d widget leaves) on %s "
                        "– deferring reconciliation until full snapshot arrives",
                        leaf_count_pre, n_known_pre, dev.device_name,
                    )
                    meta_changed = self._discover_widgets(dev, values, metadata)
            elif source_pre == "full":
                meta_changed = self._reconcile_widgets(dev, values, metadata)
            else:
                if force_update:
                    _LOGGER.debug(
                        "ForceUpdate metadata refresh received as onchange (%d/%d widget leaves) "
                        "on %s – running additive discovery only",
                        leaf_count_pre, n_known_pre, dev.device_name,
                    )
                meta_changed = self._discover_widgets(dev, values, metadata)

        n_known = len(dev.known_widget_paths)
        n_mapped = sum(
            1 for w in dev.widgets.values()
            if w.metadata.widget_type in WIDGET_PLATFORM_MAP
            or w.metadata.widget_type in WIDGET_MULTI_PLATFORM_MAP
        )
        n_unmapped = n_known - n_mapped
        leaf_count = self._count_value_leaves(dev, values)
        is_full = n_known > 0 and leaf_count >= n_known
        source = "full" if is_full else "onchange"

        log_budget: list[int] = [self._UPDATE_LOG_CAP]
        change_lines: list[str] = []
        hit_count, changed_count = self._update_widgets(
            dev, values, source=source, _log_budget=log_budget,
            _change_lines=change_lines,
        )
        if source == "full":
            _LOGGER.debug(
                "Tx/Data full %s: %d/%d w (%d map, %d unmap, %d v) "
                "— %d changed, %d meta",
                dev.device_name, hit_count, n_known,
                n_mapped, n_unmapped, len(dev.views),
                changed_count, meta_changed,
            )
        elif changed_count > 0 or meta_changed > 0:
            _LOGGER.debug(
                "Tx/Data onchange %s: %d/%d w — %d changed, %d meta",
                dev.device_name, hit_count, n_known,
                changed_count, meta_changed,
            )

    # ── Desc handlers ──────────────────────────────────────────────

    def _handle_desc(self, dev: DeviceContext, data: dict[str, Any]) -> None:
        """Process a Desc message and update the device context."""
        was_online = dev.online
        online = data.get(DESC_ONLINE, True)
        if not online and self._connected:
            _LOGGER.warning("Device %s reported offline", dev.device_name)
        dev.online = bool(online)
        dev.icon_name = data.get(DESC_ICON)
        dev.permitted_users = data.get(DESC_PERMITTED_USERS)
        dev.desc_timestamp = data.get(DESC_TIMESTAMP)
        _LOGGER.debug(
            "Device descriptor updated for %s: online=%s, icon=%s",
            dev.device_name, dev.online, dev.icon_name,
        )

        permitted = self._is_user_permitted(dev.permitted_users)

        if not permitted and dev.known_widget_paths:
            newly_stale = dev.known_widget_paths - dev.stale_widget_paths
            if newly_stale:
                dev.stale_widget_paths |= newly_stale
                _LOGGER.info(
                    "Device %s not permitted for user %s – marking %d widget(s) stale",
                    dev.device_name, self._username, len(newly_stale),
                )
                self._notify_widget_listeners(dev, newly_stale)
        elif permitted and dev.stale_widget_paths:
            recovered = set(dev.stale_widget_paths)
            dev.stale_widget_paths.clear()
            dev.initial_snapshot_received = False
            _LOGGER.info(
                "Device %s permission restored for user %s – recovering %d widget(s)",
                dev.device_name, self._username, len(recovered),
            )
            self._notify_widget_listeners(dev, recovered)

        if was_online != dev.online:
            if dev.online:
                dev.initial_snapshot_received = False
                _LOGGER.debug(
                    "Device %s back online; scheduling full reconciliation",
                    dev.device_name,
                )
            self._notify_widget_listeners(dev, set(dev.widgets.keys()))

        self._notify_hub_status(dev.device_name)

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
        self, dev: DeviceContext, values: dict[str, Any], metadata: dict[str, Any],
    ) -> int:
        """Discover new widgets from a Tx/Data message (additive only).

        Safe for both full snapshots and partial OnChange payloads: existing
        widgets are updated in place, and only genuinely new widgets are added.
        No widgets are ever removed or marked stale by this method.
        Returns the number of widgets whose metadata changed.
        """
        new_widgets: dict[Platform, list[WidgetData]] = {}
        skipped_types: dict[str, int] = {}
        field_index = self._build_field_meta_index(metadata)
        mc: list[int] = [0]
        self._walk_values(
            dev, values, metadata, "", new_widgets, [],
            skipped_types=skipped_types, field_meta_index=field_index,
            meta_changed=mc,
        )
        self._notify_new_widgets(dev, new_widgets, skipped_types)
        return mc[0]

    def _reconcile_widgets(
        self, dev: DeviceContext, values: dict[str, Any], metadata: dict[str, Any],
    ) -> int:
        """Reconcile the full widget set on a full metadata payload.

        Only called after the initial snapshot has been received. Compares the
        incoming widget paths against the known set to add new widgets, mark
        missing ones as stale, and recover previously stale ones that reappear.
        Skips stale-marking if the incoming set is empty (malformed message).
        Returns the number of widgets whose metadata changed.
        """
        new_widgets: dict[Platform, list[WidgetData]] = {}
        incoming_paths: set[str] = set()

        skipped_types: dict[str, int] = {}
        field_index = self._build_field_meta_index(metadata)
        mc: list[int] = [0]
        self._walk_values(
            dev, values, metadata, "", new_widgets, [], incoming_paths,
            skipped_types=skipped_types, field_meta_index=field_index,
            meta_changed=mc,
        )

        if not incoming_paths:
            _LOGGER.warning(
                "ForceUpdate for %s contained no widgets – skipping stale marking",
                dev.device_name,
            )
            self._notify_new_widgets(dev, new_widgets, skipped_types)
            return mc[0]

        # --- stale: previously known but no longer in snapshot ---
        newly_stale = dev.known_widget_paths - incoming_paths - dev.stale_widget_paths
        if newly_stale:
            dev.stale_widget_paths |= newly_stale
            _LOGGER.info(
                "Marking %d widget(s) stale on %s", len(newly_stale), dev.device_name,
            )
            if _LOGGER.isEnabledFor(logging.DEBUG):
                items = sorted(newly_stale)
                shown = items[:10]
                for path in shown:
                    w = dev.widgets.get(path)
                    name = (w.friendly_path or w.metadata.display_name or w.widget_id) if w else "?"
                    _LOGGER.debug("  stale: %s (%s)", name, path)
                if len(items) > 10:
                    _LOGGER.debug("  ... and %d more stale widget(s)", len(items) - 10)
            self._notify_widget_listeners(dev, newly_stale)

        # --- recovered: was stale but reappeared ---
        recovered = dev.stale_widget_paths & incoming_paths
        if recovered:
            dev.stale_widget_paths -= recovered
            _LOGGER.info(
                "Recovered %d previously stale widget(s) on %s",
                len(recovered), dev.device_name,
            )
            if _LOGGER.isEnabledFor(logging.DEBUG):
                items = sorted(recovered)
                shown = items[:10]
                for path in shown:
                    w = dev.widgets.get(path)
                    name = (w.friendly_path or w.metadata.display_name or w.widget_id) if w else "?"
                    _LOGGER.debug("  recovered: %s (%s)", name, path)
                if len(items) > 10:
                    _LOGGER.debug("  ... and %d more recovered widget(s)", len(items) - 10)
            self._notify_widget_listeners(dev, recovered)

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

    def _recover_children(self, dev: DeviceContext, view_path: str) -> None:
        """Recover stale widgets under a view path whose permission was restored."""
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
                self._try_discover_datatype(
                    dev, key, val, full_path, metadata, new_widgets,
                    view_names, incoming_paths, parent_read_only, parent_view_path,
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
                    continue

                if full_path in dev.stale_widget_paths:
                    dev.stale_widget_paths.discard(full_path)
                    _LOGGER.info(
                        "Widget %s on %s permission restored – recovering",
                        full_path, dev.device_name,
                    )
                    self._notify_widget_listeners(dev, {full_path})

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
                    if meta_changed is not None and (
                        existing.metadata != widget_meta
                        or existing.friendly_path != friendly
                        or existing.field_metadata != field_meta
                    ):
                        meta_changed[0] += 1
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

                    if full_path not in dev.known_widget_paths:
                        dev.known_widget_paths.add(full_path)
                        parts = full_path.split(".")
                        for i in range(1, len(parts)):
                            dev.widget_path_prefixes.add(".".join(parts[:i]))
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
                view_read_only = parent_read_only or meta_entry.get(META_READ_ONLY, "false").lower() == "true"
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
        """Discover a scalar PLC datatype value (BOOL/INT/REAL/STRING)."""
        meta_entry = metadata.get(full_path, {})
        if not isinstance(meta_entry, dict) or META_DISPLAY_NAME not in meta_entry:
            return
        if not self._is_user_permitted(meta_entry.get(META_PERMITTED_USERS)):
            if full_path in dev.known_widget_paths and full_path not in dev.stale_widget_paths:
                dev.stale_widget_paths.add(full_path)
                _LOGGER.info(
                    "Datatype widget %s on %s no longer permitted – marking stale",
                    full_path, dev.device_name,
                )
                self._notify_widget_listeners(dev, {full_path})
            return

        if full_path in dev.stale_widget_paths:
            dev.stale_widget_paths.discard(full_path)
            _LOGGER.info(
                "Datatype widget %s on %s permission restored – recovering",
                full_path, dev.device_name,
            )
            self._notify_widget_listeners(dev, {full_path})

        field_suffix = key.rsplit(".", 1)[-1] if "." in key else key
        dt_category = DATATYPE_FIELD_MAP.get(field_suffix)
        if dt_category is None:
            return

        if incoming_paths is not None:
            incoming_paths.add(full_path)

        if parent_view_path is not None:
            dev.widget_parent_view[full_path] = parent_view_path

        widget_meta = parse_metadata(meta_entry)
        if parent_read_only:
            widget_meta.read_only = True

        synthetic_type = f"_dt_{dt_category}"
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

            if full_path not in dev.known_widget_paths:
                dev.known_widget_paths.add(full_path)
                parts = full_path.split(".")
                for i in range(1, len(parts)):
                    dev.widget_path_prefixes.add(".".join(parts[:i]))
                self._route_widget_to_platforms(
                    synthetic_type, widget, new_widgets, full_path,
                    skipped_types=skipped_types,
                )

    # ── view → area mapping ────────────────────────────────────────

    def _create_areas_from_views(self, dev: DeviceContext) -> None:
        """Create HA Areas for views that directly contain widgets.

        Runs once per coordinator session on the initial snapshot.
        Existing areas (by name) are reused, never modified.
        """
        if self._areas_created:
            return
        self._areas_created = True

        bearing_paths = set(dev.widget_parent_view.values())
        if not bearing_paths:
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

        for cb in self._areas_ready_callbacks:
            self._safe_invoke(cb)
        self._areas_ready_callbacks.clear()

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

        If areas are already created, the callback fires immediately.
        Returns an unregister callable.
        """
        if self._areas_created:
            cb()

            def _noop() -> None:
                pass

            return _noop

        self._areas_ready_callbacks.append(cb)

        def _unregister() -> None:
            if cb in self._areas_ready_callbacks:
                self._areas_ready_callbacks.remove(cb)

        return _unregister

    # ── value counting ─────────────────────────────────────────────

    def _count_value_leaves(
        self, dev: DeviceContext, values: dict[str, Any], prefix: str = "",
    ) -> int:
        """Count how many leaf entries in the nested values tree match known widgets."""
        count = 0
        for key, val in values.items():
            full_path = f"{prefix}.{key}" if prefix else key
            if not isinstance(val, dict):
                if full_path in dev.widgets:
                    count += 1
            elif full_path in dev.widgets:
                count += 1
            elif full_path in dev.widget_path_prefixes:
                count += self._count_value_leaves(dev, val, prefix=full_path)
        return count

    # ── state updates ───────────────────────────────────────────────

    _UPDATE_LOG_CAP = 15

    def _update_widgets(
        self, dev: DeviceContext, values: dict[str, Any],
        prefix: str = "", *, source: str = "onchange",
        _log_budget: list[int] | None = None,
        _change_lines: list[str] | None = None,
    ) -> tuple[int, int]:
        """Merge incoming values into known widgets and notify listeners.

        Handles partial OnChange payloads: only the keys present in the
        incoming values dict are merged; existing widget values are preserved.
        Uses widget_path_prefixes to skip subtrees that contain no known widgets.
        Returns (hit_count, changed_count) — the number of widgets matched
        and the number that actually had value changes.
        Per-widget detail lines are only collected for "onchange" to avoid
        flooding the log with hundreds of lines on periodic full sends.
        At most _UPDATE_LOG_CAP lines are collected; a summary follows.
        """
        verbose = source == "onchange" and _LOGGER.isEnabledFor(logging.DEBUG)
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
                    if widget.values.get("value") != val:
                        changed_count += 1
                        if verbose and _log_budget[0] > 0:
                            _log_budget[0] -= 1
                            _change_lines.append(
                                f"{full_path} = {val}"
                            )
                    widget.values["value"] = val
                    for fn in self._listeners.get(full_path, []):
                        self._safe_invoke(fn, widget)
                continue

            if full_path in dev.widgets:
                hit_count += 1
                widget = dev.widgets[full_path]
                changed = {k: v for k, v in val.items() if widget.values.get(k) != v}
                if changed:
                    changed_count += 1
                widget.values.update(val)
                # Rebuild friendly_path when the runtime display name changes.
                if VAL_DISPLAY_NAME in changed:
                    new_name = (
                        str(changed[VAL_DISPLAY_NAME] or "")
                        or widget.metadata.display_name
                        or widget.widget_id
                    )
                    widget.friendly_path = (
                        f"{widget.view_prefix} {new_name}".strip()
                        if widget.view_prefix else new_name
                    )
                if verbose and changed and _log_budget[0] > 0:
                    _log_budget[0] -= 1
                    _change_lines.extend(
                        f"{full_path}.{k} = {v!r}" for k, v in changed.items()
                    )
                for fn in self._listeners.get(full_path, []):
                    self._safe_invoke(fn, widget)
            elif full_path in dev.widget_path_prefixes:
                sub_hit, sub_changed = self._update_widgets(
                    dev, val, prefix=full_path, source=source,
                    _log_budget=_log_budget,
                    _change_lines=_change_lines,
                )
                hit_count += sub_hit
                changed_count += sub_changed
        return hit_count, changed_count

    # ── public API ──────────────────────────────────────────────────

    def get_device(self, device_name: str) -> DeviceContext | None:
        """Return the DeviceContext for a device name, or None."""
        return self.devices.get(device_name)

    def register_new_widget_callback(self, platform: Platform, cb: NewWidgetCallback) -> None:
        """Register a callback invoked when new widgets are discovered for a platform."""
        self._new_widget_callbacks[platform] = cb

    def register_new_device_callback(self, cb: NewDeviceCallback) -> None:
        """Register a callback invoked when a new PLC device is discovered."""
        self._new_device_callbacks.append(cb)

    def register_listener(self, widget_path: str, callback_fn: WidgetCallback) -> Callable[[], None]:
        """Register a per-widget update listener and return an unregister callable."""
        self._listeners.setdefault(widget_path, []).append(callback_fn)

        def _unregister() -> None:
            listeners = self._listeners.get(widget_path, [])
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
        """Re-publish active=1 for a device to trigger a full JSON resend."""
        if self._client is None:
            _LOGGER.warning("Cannot request full update: MQTT not connected")
            return
        await self._client.publish(self._comm_active_topic(device_name), payload="1", qos=1, retain=True)
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
            _LOGGER.warning("Cannot send command: MQTT not connected")
            return

        if not _is_safe_topic_segment(device_name):
            _LOGGER.warning("Rejected unsafe device_name in send_command: %s", device_name)
            return

        rx = self._rx_topic(device_name)
        coros = []
        for key, value in commands.items():
            payload = json.dumps({"Values": {key: value}})
            coros.append(self._client.publish(rx, payload=payload, qos=1))
        if not coros:
            return
        await asyncio.gather(*coros)
        lines = "\n  ".join(f"{k} = {v!r}" for k, v in commands.items())
        _LOGGER.debug(
            "Rx/Data command for %s (%d key(s)):\n  %s",
            device_name, len(commands), lines,
        )
