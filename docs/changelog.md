# Changelog

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
