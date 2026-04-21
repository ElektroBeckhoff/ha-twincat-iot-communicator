# TwinCAT IoT Communicator for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/Version-0.0.15-blue.svg)
[![HACS Validation](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/validate.yaml/badge.svg)](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/validate.yaml)
[![hassfest Validation](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/hassfest.yaml)

Unofficial Home Assistant integration for the [Beckhoff TwinCAT IoT Communicator (TF6730)](https://www.beckhoff.com/en-en/products/automation/twincat/tfxxxx-twincat-3-functions/tf6xxx-connectivity/tf6730.html).

This integration bridges Home Assistant and Beckhoff TwinCAT PLCs over MQTT. It implements the TwinCAT IoT Communicator (TF6730) protocol and automatically discovers all PLCs, widgets, and data fields, exposing them as native Home Assistant entities—with no manual entity configuration required.

## Features

- **Automatic discovery** — all PLCs on the configured main topic are discovered automatically; published widgets and data fields are mapped to the appropriate Home Assistant platforms
- **Comprehensive widget support** — lighting (dimming, RGBW, EL2564), shading, outlets, HVAC, ventilation, energy monitoring, EV charging, time programs, locks, motion, and all other widget types exposed by the IoT Communicator
- **Raw PLC values** — BOOL, numeric, and string scalars as well as one-dimensional arrays are mapped to matching Home Assistant platforms; `iot.ReadOnly` is respected
- **Area mapping** — areas and device assignments are created optionally based on the TwinCAT view hierarchy published by the PLC
- **Availability monitoring** — loss of descriptor traffic is detected and reported per device (watchdog) with dedicated diagnostic entities
- **PLC messaging** — inbound PLC notifications are forwarded as Home Assistant events; acknowledgement and deletion are available as integration services, with blueprint examples included
- **Broker security** — TLS support with anonymous access, username/password, or OAuth / JWT (PKCE) authentication
- **UI-driven configuration** — setup, reconfiguration, and integration diagnostics are fully managed through the Home Assistant UI; sensitive values are redacted in diagnostic output

## Installation

### HACS (recommended)

[HACS](https://hacs.xyz/) (Home Assistant Community Store) is a custom integration manager for Home Assistant. It lets you install, update, and manage third-party integrations directly from the HA UI. If you don't have HACS yet, follow the [official installation guide](https://hacs.xyz/docs/use/download/download/).

1. Open HACS in your Home Assistant instance
2. Search for "TwinCAT IoT Communicator" and install
3. Restart Home Assistant
4. Go to **Settings** > **Devices & services** > **Add integration** > **TwinCAT IoT Communicator**

Updates are detected automatically by HACS and appear under **Settings** > **Updates**.

### Manual

1. Copy `custom_components/twincat_iot_communicator/` to your `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings** > **Devices & services** > **Add integration** > **TwinCAT IoT Communicator**

## Documentation

- [Documentation](docs/DOCUMENTATION.md) — full setup guide, entities, actions, OAuth, troubleshooting
- [Changelog](docs/changelog.md) — release history
- [HA docs source](docs/twincat_iot_communicator.markdown) — formatted for the official Home Assistant documentation site

## Disclaimer

This project is an unofficial Home Assistant integration for the TwinCAT IoT Communicator (TF6730).

This project is not affiliated with or endorsed by Beckhoff Automation GmbH.

## License

See [LICENSE](LICENSE) for details.
