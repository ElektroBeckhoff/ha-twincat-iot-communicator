# Changelog

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
