# Changelog

## 0.0.15

### Added

- **Stale widget detection & cleanup**: widgets no longer present in the PLC payload are detected as stale and can be removed — individually from the device page, in bulk via HA Repairs, or via the new `remove_stale_widgets` service.
- **Repair issue for stale widgets**: appears automatically under Settings > Repairs when stale widgets are found. Includes a confirmation step before deletion.
- **Service `request_snapshot`**: trigger a full PLC data snapshot on demand (`active=1`).
- **Service `remove_stale_widgets`**: remove all stale widgets of a device at once.
- **Service `send_message`**: send a message to the PLC with auto-incrementing ID and optional type (Default/Info/Warning/Error/Critical).
- **Guarded device removal**: active, online devices are protected from accidental deletion.

### Fixed

- **Stale detection across HA restarts**: widget paths are now seeded from the device registry on startup so the first snapshot correctly identifies missing widgets.
- **Permission recovery no longer clears snapshot staleness**: `_recover_children` and the Desc handler only recover widgets that were stale due to a permission denial, not those absent from a snapshot. Tracked via `denied_view_paths`.
- **`request_snapshot` delivery**: changed from `retain=True` to `retain=False` to ensure the broker forwards the message to the PLC.
- **Repair issue on permission changes**: `_mark_children_stale`, `_recover_children`, and all per-widget permission checks now trigger `reconcile_stale_device_repair()`.
- **Repair flow entry_id fallback**: single-entry setups no longer fail when `issue.data` is missing the `entry_id`.

## 0.0.14

### Fixed

- **No more UI bounce-back after commands**: Sliders, switches, color pickers, etc. no longer briefly snap back to the old value before settling on the new one. The new value is now applied to the UI immediately without waiting for the PLC round-trip (optimistic update). Affects: Light, Switch, Climate, Fan, Select, Number, Text, Time, Date.
- **Color picker stays stable**: On RGBW lights the color wheel no longer flickers back to the previous position, because derived color values (RGB ↔ HS) are now set optimistically as well.
- **Black color (0,0,0) rejected**: When the color brightness slider is set to zero, a clear error notification is shown instead of silently ignoring the command.
- **Multi-device listener collision**: In setups with multiple PLC devices under one config entry, widgets with identical structural paths could receive state updates from the wrong device. Listener keys are now qualified with the device name, ensuring each entity only receives updates from its own PLC device.
- **Device removal cleanup**: Removing a PLC device no longer leaves behind orphaned watchdog timers, snapshot timers, and probe tasks. Previously these could fire after the device was already gone, causing ghost updates or errors.
- **Command failure on MQTT disconnect**: When the MQTT connection is down, commands now show a clear error instead of silently succeeding in the UI while the PLC never receives them. Optimistic state changes are rolled back automatically.
- **Fan: unguarded commands**: `turn_off` no longer sends a command when the on/off feature is not supported. `set_percentage` is now blocked when the speed slider is not available. `turn_on` with a preset now validates the mode before sending it to the PLC.
- **Climate: turn_on with unsupported mode**: If the PLC does not expose any supported HVAC mode (Auto, Heat, Cool, etc.), `turn_on` now raises a clear error instead of blindly requesting Auto mode and failing unexpectedly.
- **Climate: wrong error message for HVAC mode**: Setting an invalid HVAC mode previously showed a "preset mode" error message. It now correctly identifies the error as an invalid HVAC mode.
- **Date entity crash on bad PLC data**: Malformed date values from the PLC no longer crash the entity update. Invalid values are now handled gracefully, returning `None` instead of raising an exception.
- **Select: invalid option accepted**: `async_select_option` now validates the requested option against the allowed list before sending it to the PLC. Previously, any arbitrary string could be written.
- **Number: out-of-range values accepted**: `async_set_native_value` now clamps values to the configured min/max range. Programmatic service calls that bypass the frontend slider could previously send values outside the PLC's valid range.
- **Fan: broken error message for invalid preset**: The "invalid preset mode" error message was missing the `{mode}` and `{allowed}` placeholders, resulting in a malformed notification. All placeholders are now populated correctly.
- **JWT: crash on non-numeric exp claim**: `jwt_is_expired` and `jwt_remaining_seconds` now validate that the `exp` claim is a number before comparing it. A string or unexpected type no longer causes a `TypeError`.
- **OAuth redirect_uri not URL-encoded**: In the direct-token OAuth flow, the `redirect_uri` (which contains query parameters) is now properly URL-encoded to prevent the auth server from misinterpreting the nested `?flow_id=` parameter.
- **Snapshot probe lost after reconnect**: When the MQTT connection dropped during the initial snapshot capability probe, devices with unknown support (`None`) were never re-probed after reconnect. They are now automatically re-probed.
- **MQTT publish error not caught**: When the MQTT connection dropped during a command publish, the resulting `MqttError` was not caught by the optimistic rollback handler. The error is now wrapped in `HomeAssistantError` so the UI correctly rolls back and shows an error notification.
- **Light: crash on non-numeric color mode**: A non-numeric `nColorMode` value from the PLC no longer crashes the light entity. Invalid values now gracefully return `None` instead of raising a `ValueError`.

## 0.0.13

### Fixed

- **Area assignment broken for multi-device setups**: when multiple PLC devices were configured in the same integration entry, only the first device to finish its snapshot had its widget devices assigned to HA areas. A global once-only guard (`_areas_created`) blocked all subsequent devices from populating the area map. Area creation now runs independently per device.
- **Area-ready callbacks discarded prematurely**: `_safe_invoke` swallowed the `bool` return value of assignment callbacks, and the callback list was cleared unconditionally after the first device. Failed callbacks (device not yet mapped) are now retained and retried when the next device finishes.
- **`on_areas_ready` gave no second chance**: when called after the first device had already finished, the callback fired immediately but on failure returned a no-op unregister — the entity could never retry. On failure the callback is now kept in the pending list.

### Added

- **New config option "Assign devices to areas"**: a separate toggle (independent of "Create areas") controls whether new widget devices are automatically assigned to their matching HA area. Both options are available during initial setup and reconfiguration. Devices that already have an area assignment are never overwritten.
- **RGBW light: `color_palette_mode` attribute**: exposes the PLC's `sLightColorPaletteMode` value ("RGB" or "HS") as a state attribute, indicating which color data format is used for PLC communication.

## 0.0.12

### Fixed

- **Mode display with empty mode arrays**: across all widget platforms, when the PLC provides a current mode value (`sMode`) but the available-modes array (`aModes`) is empty, the current mode is now used as a fallback so the entity resolves and displays the correct state. Previously, an empty `aModes` caused features to be missing or entities to not be created at all. Affected platforms:
  - **Climate** — HVAC mode (`sMode`/`aModes`): already fixed in 0.0.11.
  - **Climate** — fan/strength mode (`sMode_Strength`/`aModes_Strength`): `fan_mode` now resolves from the current strength value; `FAN_MODE` feature is set when changeable.
  - **Climate** — swing/lamella mode (`sMode_Lamella`/`aModes_Lamella`): `swing_mode` now resolves from the current lamella value; `SWING_MODE` feature is set when changeable.
  - **Fan** — preset mode (`sMode`/`aModes`): `preset_modes` now includes the current mode; `PRESET_MODE` feature is set when changeable.
  - **Light** — effect (`sMode`/`aModes` for Lighting and RGBW widgets): `effect_list` now includes the current mode; `EFFECT` feature is set when changeable.
  - **Light** — General Light effect (`sMode1`/`aModes1`): same fix as above for General widget lights.
  - **Select** — General, TimeSwitch, Lock, Motion mode selectors: the entity is now created with the current `sMode` as a single option instead of being skipped entirely.
- **Climate HVAC mode map missing German noun forms**: `HVAC_MODE_MAP` only contained verb forms like "Heizen", "Kühlen", "Lüften" but not the common noun forms "Heizung", "Kühlung", "Lüftung", "Trocknung" (and their umlaut-free variants). A PLC sending `sMode := 'Heizung'` could not be mapped, causing the entity to fall back to "Off" even though the mode was set. All common German noun forms are now recognized.

## 0.0.11

### Fixed

- **Climate mode derived from `nAcMode` when hidden**: when `iot.ACModeVisible` is `false`, the climate entity now derives its HVAC state from `nAcMode` (the physical AC operating state: 0=Off, 1/4=Cool, 2/5=Fan, 3/6=Heat) instead of the `sMode` string array which may be empty. The previous fallback `[HVACMode.OFF]` incorrectly showed the entity as "Off" even when the device was actively heating or cooling. The `hvac_modes` list now contains only the current nAcMode-derived mode, so the HA frontend displays the correct state (e.g., "Heat") with no selectable dropdown.

## 0.0.10

### Changed

- **Motion switch renamed to Bypass**: the `motion_on` switch translation was renamed from "Enabled" / "Aktiviert" to "Bypass" / "Überbrückung". The switch controls the bypass state of the motion sensor (`bOutputBypassState` in the PLC), not a generic enable flag.
- **Motion active sensor reverted to Active**: the `motion_active` binary sensor translation (incorrectly renamed to "Bypass" in 0.0.9) is restored to "Active" / "Aktiv". This sensor shows the computed output (`bOutput`: Auto=sensor+holdtimer, Manual=bypass, Off=FALSE, On=TRUE).
- **Motion active device class removed**: `TcIotMotionActiveSensor` no longer uses the `occupancy` device class. The active output is a generic computed state, not an occupancy sensor. The raw `motion` binary sensor retains `BinarySensorDeviceClass.MOTION`.

### Fixed

- **Climate mode maps leaked when not visible**: when `iot.ACModeVisible`, `iot.ACModeStrengthVisible`, or `iot.ACModeLamellaVisible` was `false`, the internal mode lookup maps (`_hvac_map`, `_fan_mode_map`, `_swing_mode_map`) were still populated from the PLC's mode arrays. This caused the `hvac_mode`, `fan_mode`, and `swing_mode` properties to return mapped values instead of their defaults, making Home Assistant display mode selectors even though the modes were hidden. The maps are now only populated when the corresponding visibility flag is `true`.

## 0.0.9

### Changed

- **Motion active sensor renamed to Bypass**: the `motion_active` binary sensor translation was renamed from "Active" / "Aktiv" to "Bypass" / "Überbrückung" to accurately reflect its function — it shows the bypass state of the motion sensor, not a generic active flag.

## 0.0.8

### Changed

- **Read-only datatype entities disabled by default**: when a scalar PLC datatype widget (BOOL, NUMBER, STRING) has `iot.ReadOnly` set to `true`, the controllable entity (Switch, Number, Text) is now created as **disabled** in the entity registry. The read-only companion (Sensor / Binary Sensor) remains active by default. Users can re-enable the controllable entity manually if needed.
- **AC visible attributes exposed**: the climate entity now includes `mode_visible`, `strength_visible`, and `lamella_visible` in `extra_state_attributes` alongside the existing changeable flags, allowing automations to react to PLC visibility settings.
- **AC mode sensor labels**: the "(off)" suffix for inactive operating states (e.g. "Cooling (off)") has been renamed to "(inactive)" / "(inaktiv)" for clarity — the AC is not off, the mode is just not actively running.

### Fixed

- **DecimalPrecision handling**: `TcIotGeneralNumber` (General widget nValue2/nValue3 sliders) no longer hardcodes `step=0.01` / 2 decimal places — values are always INT in the PLC, so the default is now `step=1` / 0 decimals. `iot.DecimalPrecision` from field metadata is honored when present. Write commands now send `int` instead of `float` for integer fields. `TcIotDatatypeSensor` (companion sensor for REAL/LREAL) and `TcIotDatatypeArrayNumber` (array elements) now read `iot.DecimalPrecision` for correct display rounding.
- **General Number integer display**: `TcIotGeneralNumber.native_value` now returns `int` instead of `float` when `native_step >= 1`, preventing the activity log from showing "0,0" instead of "0" for integer values.
- **AC preset mode no longer shows OFF**: when the active PLC mode is a custom preset (not mapped to a standard HVAC mode), `hvac_mode` now returns `None` instead of `OFF`. This prevents the confusing dual state where the climate card showed "Off" while a preset was active.

## 0.0.7

### Added

- **Lock widget**: new `Lock` widget type exposed as a Lock entity with lock/unlock/open commands. Feedback via `bLocked`, `bJammed`, and `bOpened`. The `OPEN` feature is dynamically enabled based on `iot.LockOpenVisible`. Optionally creates a state sensor (`sState`) and a mode selector (`sMode`/`aModes`), each controlled by their visibility flags. *Note: The Lock widget type is not yet available in the official TwinCAT IoT Communicator release — this prepares Home Assistant for the upcoming PLC-side implementation.*
- **Motion widget**: new `Motion` widget type creating up to nine entities: motion binary sensor (`bMotion`), active binary sensor (`bActive`), on/off switch (`bOn`), configurable number entities (`nHoldTime`, `nBrightness`, `nRange`, `nSensitivity`), battery sensor (`nBattery`), and mode selector (`sMode`/`aModes`). All sub-entities respect their individual visibility flags. *Note: The Motion widget type is not yet available in the official TwinCAT IoT Communicator release — this prepares Home Assistant for the upcoming PLC-side implementation.*
- **Datatype companion sensors**: scalar NUMBER and STRING datatype widgets now automatically create a read-only Sensor companion entity alongside their primary entity (Number / Text). The sensor `device_class` is resolved from the PLC `iot.Icon` attribute first, then from `iot.Unit`, with `state_class: measurement` set when a device class is determined.
- **BOOL companion binary sensor**: scalar BOOL datatype widgets additionally create a read-only Binary Sensor companion. Its `device_class` is derived from the PLC `iot.Icon` attribute (e.g. `Door_Open` → `door`, `Window_Closed` → `window`).
- **AC mode sensor**: AC (climate) widgets now additionally create an enum Sensor entity (`nAcMode`) that exposes the PLC's `E_IoT_AcMode` operating state (None, Cooling, Ventilation, Heating, and their "off" variants). This enables automations based on the actual HVAC operating state — for example, color-coded status indicators or notifications when heating/cooling activates.
- **General widget value sensors**: General widgets now create read-only Sensor entities for `nValue2`/`nValue3` when `iot.GeneralValue2Visible`/`iot.GeneralValue3Visible` is `true`. The unit is taken from field metadata; no `device_class` is assumed (the value is generic). The Number (slider) entities are now correctly gated by `iot.GeneralValue2SliderVisible`/`iot.GeneralValue3SliderVisible` instead of the visibility flag alone.

### Fixed

- **Visibility/changeable guard enforcement**: when a PLC visibility flag (`*ModeVisible`, `*StrengthVisible`, `*LamellaVisible`) was `false`, the corresponding mode list could still be exposed in Home Assistant and the changeable guard could be bypassed via service calls. The invariant `_changeable = visible AND changeable` is now enforced consistently across all platforms: Climate (HVAC modes, fan/strength, swing/lamella), Fan (preset modes), and Light (effects/modes for Lighting, RGBW, EL2564, and General widgets). When a mode is not visible, no selector is shown, the state still reflects the actual PLC value, and write attempts are blocked.
- **Removed dead `ForceUpdate` handling**: the PLC's `ForceUpdate` JSON flag was parsed but had no effect — the `elif force_update` branch was identical to the normal discovery path. This integration processes every incoming MQTT message fully (metadata + values) regardless of the flag. `ForceUpdate` is a signal for the TwinCAT IoT Communicator app to refresh its cached UI, which is not applicable to Home Assistant.

## 0.0.6

### Fixed

- **Effect without auto-on**: setting an effect/mode on a light no longer automatically turns the light on. Only the mode command is sent to the PLC. Affects Lighting, RGBW, and General Light widgets.

## 0.0.5

### Added

- **Desc watchdog**: detects PLC offline when Desc messages stop arriving (3-message calibration, 3× interval timeout, retained `Online: false` publish to broker). Recovers automatically on next Desc.
- **Heartbeat interval sensor**: new diagnostic sensor per device (`sensor.heartbeat_interval`) showing the measured Desc interval in seconds. Value is `None` until calibration completes.
- **Entity translations (de)**: all sub-entity names are now translatable via `translation_key`. German translations included for all widget entities (sensors, buttons, switches, time/date, select, light, number). Affected widgets: ChargingStation, EnergyMonitoring, TimeSwitch, General, RGBW.
- **Bulk message actions**: `acknowledge_message` and `delete_message` services now accept an optional `message_id`. When omitted, all messages on the device are processed.

### Fixed

- **Device names with spaces**: names like "Widgets Overview" are now accepted. Only true MQTT wildcards (`#`, `+`) and null bytes are rejected.
- **Latin-1 payload encoding**: PLCs that send characters like `°` as single Latin-1 bytes (e.g. `0xB0`) instead of multi-byte UTF-8 no longer cause decode errors. UTF-8-SIG is tried first, Latin-1 as fallback.
- **Error messages showing `UndefinedType`**: error messages for read-only or locked entities now show the correct widget name instead of `UndefinedType._singleton`. Affected: climate, light, select, fan, and the base entity `_check_read_only`.

### Changed

- **Snapshot finalization speed**: devices that send complete snapshots at high frequency (e.g. every 500ms) no longer wait 65s for finalization. A new 3-tier timer (10s quiet → 3s stable → 65s max) reduces typical finalization from 65s to ~4.5s for high-frequency single-group PLCs.

## 0.0.4

### Added

- **ChargingStation widget**: fully supported with start/stop/reserve buttons and sensors for status, battery level, power, energy, charging time, and per-phase voltage/current/power. Phase visibility is controlled by `iot.ChargingStationPhase2Visible` / `Phase3Visible`.
- **TimeSwitch widget**: fully supported with power toggle, start/end time, start/end date, yearly flag, weekday toggles (Mon–Sun), and mode selector. All fields respect their `iot.TimeSwitch*Visible` metadata flags. Mode changeability is enforced via `iot.TimeSwitchModeChangeable`.
- **PLC array support**: one-dimensional arrays of BOOL, INT/REAL, and STRING values are now auto-discovered from the JSON payload. Each array element becomes its own entity (Switch, Number, or Text). Arrays are always read-only.

### Fixed

- **Active probe deferred for offline devices**: when a device is offline at startup, the probe timeout no longer permanently disables periodic snapshot refresh. A re-probe is automatically triggered when the device comes back online.
- **HVAC mode validation**: setting an unmapped HVAC mode on a Climate entity now raises a clear error instead of failing silently.
- **General Light effect validation**: setting an invalid effect now raises an error instead of sending an unknown string to the PLC.
- **Defensive value parsing**: time, sensor, and array entities now gracefully handle malformed PLC values (unexpected types, None elements) instead of crashing.
- **MQTT publish race condition**: heartbeat and snapshot loops no longer crash if the MQTT connection drops while publishing.
- **Device removal guard**: removing a device no longer crashes if the config entry was never fully loaded.

### Changed

- **Widget sub-devices**: each widget is now its own device in Home Assistant, grouped under the PLC hub device via `via_device`. This replaces the previous flat structure where all entities belonged to a single device. Existing automations and entity IDs are unaffected.
- **Areas are assigned to devices**: area assignment from the PLC view structure now targets the widget device instead of individual entities.
- **Device names update dynamically**: when the PLC changes a widget's display name, the corresponding device name in Home Assistant updates automatically.
- **Readable device models**: raw PLC datatype widgets now show human-readable model names (e.g. "PLC BOOL", "PLC Numeric", "PLC STRING") instead of internal type identifiers.
- **Device removal cleanup**: removing a PLC hub device now also removes all its widget sub-devices. Widget sub-devices cannot be removed individually.
- **Datatype detection by JSON value**: scalar datatype widgets (BOOL, INT/REAL, STRING) are now detected by the actual JSON value type instead of the PLC variable name suffix. This makes discovery independent of naming conventions — variables no longer need to follow `bBOOL`/`nINT`/`fREAL`/`sSTRING` prefixes.

## 0.0.3

### Added

- **Area creation toggle**: automatic area creation from the PLC view structure can now be enabled or disabled during device setup and reconfiguration. Enabled by default.
- **Climate (AC widget)**: all three mode groups are now fully supported.
  - HVAC mode, fan strength, and lamella swing are each mapped to their HA equivalent with DE/EN auto-detection.
  - Visibility and changeability flags from the PLC are respected — attempting to change a locked mode returns a clear error message.
- **Fan widget**: the ventilation mode changeable flag is now enforced. Attempting to change a locked mode returns an error.
- **Light / Select widgets**: attempting to change a locked mode now returns an error instead of being silently ignored.

### Fixed

- **Cover movement detection** no longer flickers during operation. Direction is now derived from position changes and held until the cover stops moving (5-second timeout).
- **Climate**: the read-only display icon value is no longer accidentally overwritten when switching modes.
- **ForceUpdate payloads** now correctly update widget values in addition to metadata. Previously, values could be silently dropped.
- Fixed a crash that could occur when creating areas on the first snapshot after startup.

### Changed

- **Simplified availability logic**: widgets are now only marked unavailable after an explicit full-snapshot request to the PLC (at startup and every 15 minutes). Normal value updates never affect availability.
  - On startup, each device is probed to check whether the PLC firmware supports full-snapshot requests. If not supported, periodic availability checks are skipped for that device.
  - New widgets appearing in any payload are always added to Home Assistant automatically.
- **Improved performance**: entity updates are now skipped when nothing actually changed, significantly reducing unnecessary processing on large installations (400+ widgets).
- Service action `acknowledge_message`: the acknowledgement text field is now correctly shown as optional in the UI.
- Added missing `invalid_auth` abort translation for the config flow.
- Various internal robustness improvements (parallel MQTT operations, memory bounds, cleanup on unload).

## 0.0.2

- Initial release.
