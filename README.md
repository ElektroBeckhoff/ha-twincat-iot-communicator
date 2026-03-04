# TwinCAT IoT Communicator for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/Version-0.0.2-blue.svg)

Unofficial Home Assistant integration for the [Beckhoff TwinCAT IoT Communicator (TF6730)](https://www.beckhoff.com/en-en/products/automation/twincat/tfxxxx-twincat-3-functions/tf6xxx-connectivity/tf6730.html).

Connects Home Assistant to Beckhoff TwinCAT PLCs via MQTT. The integration auto-discovers all devices and widgets (lights, blinds, climate, fans, switches, sensors, and more) and exposes them as native Home Assistant entities.

## Features

- Auto-discovery of PLC devices and widgets via MQTT
- Supports Lighting, RGBW, Blinds, Plug, AC, Ventilation, EnergyMonitoring, General widgets
- Raw PLC datatype support (BOOL, INT, REAL, STRING)
- PLC push messages with acknowledge/delete actions
- OAuth / JWT authentication (PKCE)
- Blueprint automations included

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "TwinCAT IoT Communicator" and install
3. Restart Home Assistant
4. Go to **Settings** > **Devices & services** > **Add integration** > **TwinCAT IoT Communicator**

### Manual

1. Copy `custom_components/twincat_iot_communicator/` to your `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings** > **Devices & services** > **Add integration** > **TwinCAT IoT Communicator**

## Documentation

For detailed documentation (configuration, entities, actions, OAuth setup, troubleshooting), see [`docs/twincat_iot_communicator.markdown`](docs/twincat_iot_communicator.markdown).

> **Note:** This file is formatted for the official Home Assistant documentation site and uses custom formatting tags that may not render correctly on GitHub.

## Disclaimer

This project is an unofficial Home Assistant integration for the TwinCAT IoT Communicator (TF6730).

This project is not affiliated with or endorsed by Beckhoff Automation GmbH.

## License

See [LICENSE](LICENSE) for details.
