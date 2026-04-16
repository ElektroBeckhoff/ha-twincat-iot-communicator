# TwinCAT IoT Communicator for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/Version-0.0.14-blue.svg)
[![HACS Validation](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/validate.yaml/badge.svg)](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/validate.yaml)
[![hassfest Validation](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/ElektroBeckhoff/ha-twincat-iot-communicator/actions/workflows/hassfest.yaml)

Unofficial Home Assistant integration for the [Beckhoff TwinCAT IoT Communicator (TF6730)](https://www.beckhoff.com/en-en/products/automation/twincat/tfxxxx-twincat-3-functions/tf6xxx-connectivity/tf6730.html).

Connects Home Assistant to Beckhoff TwinCAT PLCs via MQTT. The integration auto-discovers all devices and widgets (lights, blinds, climate, fans, switches, sensors, and more) and exposes them as native Home Assistant entities.

## Features

- Auto-discovery of PLC devices and widgets via MQTT
- Supported widgets: Lighting, RGBW, RGBW_EL2564, Blinds, SimpleBlinds, Plug, AC, Ventilation, EnergyMonitoring, ChargingStation, TimeSwitch, BarChart, General
- Raw PLC datatype support (BOOL, INT, REAL, STRING) incl. one-dimensional arrays
- Widget sub-devices with automatic area assignment from PLC view hierarchy
- Desc watchdog — automatic PLC offline detection when Desc messages stop
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

- [Documentation](docs/DOCUMENTATION.md) — full setup guide, entities, actions, OAuth, troubleshooting
- [Changelog](docs/changelog.md) — release history
- [HA docs source](docs/twincat_iot_communicator.markdown) — formatted for the official Home Assistant documentation site

## Disclaimer

This project is an unofficial Home Assistant integration for the TwinCAT IoT Communicator (TF6730).

This project is not affiliated with or endorsed by Beckhoff Automation GmbH.

## License

See [LICENSE](LICENSE) for details.
