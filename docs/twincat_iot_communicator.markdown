---
title: TwinCAT IoT Communicator
description: Connect Home Assistant to Beckhoff TwinCAT PLCs via the IoT Communicator (TF6730) MQTT interface.
ha_category:
  - Binary sensor
  - Button
  - Climate
  - Cover
  - Date
  - Event
  - Fan
  - Hub
  - Light
  - Lock
  - Number
  - Select
  - Sensor
  - Switch
  - Text
  - Time
ha_release: "2026.3"
ha_iot_class: Local Push
ha_config_flow: true
ha_domain: twincat_iot_communicator
ha_platforms:
  - binary_sensor
  - button
  - climate
  - cover
  - date
  - diagnostics
  - event
  - fan
  - light
  - lock
  - number
  - select
  - sensor
  - switch
  - text
  - time
ha_integration_type: hub
ha_codeowners:
  - "@christian9712"
ha_quality_scale: bronze
---

The **TwinCAT IoT Communicator** {% term integration %} connects Home Assistant to [Beckhoff](https://www.beckhoff.com/) TwinCAT PLCs using the [TF6730 IoT Communicator](https://www.beckhoff.com/en-en/products/automation/twincat/tfxxxx-twincat-3-functions/tf6xxx-connectivity/tf6730.html) MQTT interface.

The TwinCAT IoT Communicator publishes widget data (lights, blinds, climate, fans, switches, sensors, and more) from the PLC to an MQTT broker. This integration subscribes to those topics, auto-discovers all devices and widgets, and exposes them as Home Assistant entities. Commands are sent back to the PLC via MQTT.

In addition to structured widgets, the integration also discovers raw PLC datatype values (BOOL, INT, REAL, STRING, etc.) and maps them to appropriate Home Assistant platforms automatically.

## Supported devices

Any Beckhoff TwinCAT 3 PLC running the TF6730 (IoT Communicator) or TF6735 (IoT Communicator App) function. Multiple PLC devices on the same MQTT broker are supported and auto-discovered.

### Supported widget types

| TwinCAT widget type | Home Assistant platform | Features |
| ------------------- | ---------------------- | -------- |
| Lighting            | Light                  | On/off, brightness, modes |
| RGBW                | Light                  | On/off, brightness, RGBW color (HS+White), color temperature, modes |
| RGBWEL2564          | Light                  | On/off, RGBW color (4-channel EL2564 LED), modes |
| Blinds              | Cover                  | Open/close/stop, position, tilt angle |
| SimpleBlinds        | Cover                  | Open/close |
| Plug                | Switch                 | On/off, modes |
| AC                  | Climate, Sensor        | Temperature, HVAC modes, fan speed, swing/lamella, AC mode sensor |
| Ventilation         | Fan                    | On/off, speed percentage, preset modes |
| EnergyMonitoring    | Sensor                 | Power, energy, power factor, per-phase voltage/current/power |
| ChargingStation     | Button, Sensor         | Start/stop/reserve buttons, status, battery level, power, energy, charging time, per-phase voltage/current/power |
| TimeSwitch          | Switch, Date, Time, Select | Power toggle, start/end time, start/end date, yearly flag, weekday toggles (Mon–Sun), mode selector |
| General             | Switch, Light, Number, Sensor, Select | Configurable multi-entity widget (on/off, modes, values, read-only sensors) |
| Lock *(upcoming)*   | Lock, Sensor, Select   | Lock/unlock/open, jammed detection, state sensor, modes |
| Motion *(upcoming)* | Binary Sensor, Switch, Number, Sensor, Select | Motion detection, active output, on/off, hold time, brightness, range, sensitivity, battery, modes |

{% note %}
The Lock and Motion widget types are not yet available in the official TwinCAT IoT Communicator (TF6730) release. Home Assistant support is prepared ahead of time and will become functional once the corresponding PLC-side widget types are shipped in a future TwinCAT update.
{% endnote %}

### Supported raw PLC datatypes

Scalar PLC values that are not part of a widget are auto-discovered by their JSON value type and mapped to the appropriate platform. Variable names in the PLC do not matter — only the actual data type in the JSON payload is used for detection. When `iot.ReadOnly` is `true`, the controllable entity (Switch / Number / Text) is created **disabled by default** — only the read-only companion entity (Sensor / Binary Sensor) is active. The controllable entity can be re-enabled manually from the entity registry if needed. Write commands are always blocked dynamically when `iot.ReadOnly` is set.

Numeric and string scalar datatypes additionally create a companion {% term sensor %} entity. This read-only sensor mirrors the current value and integrates with Home Assistant statistics and the energy dashboard. The sensor's {% term device_class %} is automatically derived from the widget's `iot.Icon` metadata (for example, the `Temperature` icon sets the sensor to temperature class). If no icon match is found, the `iot.Unit` is used as fallback. Boolean datatypes additionally create a {% term binary_sensor %} companion whose {% term device_class %} is derived from `iot.Icon` (e.g. `Door_Open` → door, `Window_Closed` → window).

| JSON value type    | Home Assistant platform |
| ------------------ | ---------------------- |
| Boolean            | Switch + Binary Sensor |
| Integer / Float    | Number + Sensor        |
| String             | Text + Sensor          |
| Array of booleans  | Switch (one per element, read-only) |
| Array of numbers   | Number (one per element, read-only) |
| Array of strings   | Text (one per element, read-only)   |

### Ignored widget types

The following widget types are discovered but intentionally do not create entities:

- **BarChart** — array/chart data with no sensible HA entity

## Prerequisites

- A Beckhoff TwinCAT 3 PLC with the TF6730 IoT Communicator licensed and configured.
- An MQTT broker reachable by both the PLC and Home Assistant (for example, [Mosquitto](/integrations/mqtt/), [Cedalo](https://cedalo.com/), [EMQX](https://www.emqx.io/), or any standard MQTT broker).
- The PLC must be configured to publish to the broker with a known **main topic** (for example, `IotApp.Sample`).
- **For OAuth authentication only:** An OIDC-compliant identity provider (for example, [Keycloak](https://www.keycloak.org/), Azure AD, Auth0, or Authentik) with a public OAuth client configured.

{% include integrations/config_flow.md %}

## Configuration parameters

The integration is set up entirely through the UI. The setup flow consists of four steps:

### Step 1: MQTT broker

{% configuration_basic %}
Host:
  description: "Hostname or IP address of the MQTT broker."
Port:
  description: "MQTT broker port (default: `1883`, or `8883` for TLS)."
Use TLS:
  description: "Enable TLS encryption for the broker connection."
{% endconfiguration_basic %}

### Step 2: Authentication method

After entering the broker details, a menu lets you choose one of three authentication methods:

- **No authentication (anonymous)** — connect without credentials. Use this if your broker does not require authentication.
- **Username and password** — provide a broker username and password. Both fields are optional — leave them empty for brokers that accept anonymous connections but still require the credentials step.
- **External login (OAuth / JWT)** — authenticate via an external OAuth login page. See [Authentication: OAuth / JWT](#authentication-oauth--jwt) below.

### Step 3: Main topic

{% configuration_basic %}
Main topic:
  description: "The MQTT main topic configured in the PLC (for example, `IotApp.Sample`)."
{% endconfiguration_basic %}

After entering the topic, the integration scans the broker for devices publishing on that topic.

### Step 4: Device selection

{% configuration_basic %}
Devices:
  description: "Select which discovered PLC devices to integrate."
Create areas:
  description: "Automatically create Home Assistant areas from the PLC view structure (default: enabled). Existing area names are reused."
Assign devices to areas:
  description: "Automatically assign new widget devices to the matching area based on their parent view (default: enabled). Devices that already have an area assignment are never overwritten."
{% endconfiguration_basic %}

Devices that are already configured in another config entry for the same topic are excluded automatically.

### Reconfiguring devices

To add or remove individual PLC devices after initial setup, select the integration in {% my integrations title="**Settings** > **Devices & services**" %} and choose **Reconfigure**. The integration rescans the broker and shows all available devices. Deselected devices are removed; newly selected devices are added. The **Create areas** and **Assign devices to areas** toggles can also be changed during reconfiguration. To change the broker address or main topic, remove and re-add the integration.

### Authentication: OAuth / JWT

Selecting **External login (OAuth / JWT)** in the authentication menu opens the OAuth setup flow. This avoids storing passwords in Home Assistant and allows centralized user management through an identity provider.

{% tip %}
This method works with any OIDC-compliant provider, including Keycloak, Azure AD, Auth0, and Authentik. The integration discovers endpoints automatically via OIDC Discovery.
{% endtip %}

**Setup flow:**

1. Enter the **Issuer URL** — this is the OIDC issuer URL of your identity provider (for example, `https://auth.example.com/realms/myrealm`). Do not enter the full authorization endpoint; the integration discovers it automatically.
2. Enter the **Client ID** registered at the identity provider (default: `tc_iot_communicator`). The client must be a public client (no client secret).
3. A browser window opens, prompting you to log in at the identity provider.
4. After successful login, Home Assistant receives an authorization code and securely exchanges it for a JWT access token using the **Authorization Code flow with PKCE**.
5. The integration decodes the JWT locally and extracts the MQTT username from the `preferred_username` claim (falls back to `sub`).
6. The MQTT connection uses the decoded claim as the username and the full JWT as the password.

The JWT is stored in the config entry. You do not need to log in again until the token expires. When the token expires, Home Assistant automatically triggers a re-authentication flow (see [Re-authentication](#re-authentication)).

{% note %}
The MQTT broker must be configured to accept JWT access tokens as passwords. The broker is responsible for validating the token signature, expiration, and permissions. See [Implementing the OAuth backend](#implementing-the-oauth-backend) for details.
{% endnote %}

{% tip %}
If your auth server does not support OIDC Discovery, the integration falls back to direct token delivery mode. In this case, the auth server must redirect back with `?access_token=JWT` or `#access_token=JWT` in the URL.
{% endtip %}

## Entities

### Per-device diagnostic entities

Each discovered PLC device automatically gets the following diagnostic entities:

| Entity            | Platform      | Description |
| ----------------- | ------------- | ----------- |
| Status            | Binary sensor | Connectivity status (online/offline) of the PLC device. |
| Last update       | Sensor        | Timestamp of the last Desc message from the PLC. |
| PLC messages      | Event         | Fires an event when the PLC sends a push message. |
| Last message      | Sensor        | Text of the most recent PLC push message. |
| Last message type | Sensor        | Severity of the most recent message (Info, Warning, Error, Critical). |
| Unread messages   | Sensor        | Number of unacknowledged PLC push messages. |

### Widget entities

Widgets are auto-discovered from the PLC's MQTT messages. Each widget becomes one or more entities depending on its type.

#### Light

Lighting, RGBW, and RGBWEL2564 widgets are exposed as {% term light %} entities.

- **Lighting**: On/off, brightness (if `iot.LightSliderVisible`), effects/modes.
- **RGBW**: On/off, brightness (`nLight`), RGBW color mode (if `iot.LightColorPaletteVisible` and `iot.LightWhiteSliderVisible`), HS color mode (if only `iot.LightColorPaletteVisible`), color temperature mode (if `iot.LightColorTemperatureSliderVisible`), effects/modes. The PLC natively uses Hue/Saturation — the integration converts RGB↔HS transparently. The white channel (`nWhite`, PLC 0–100, HA 0–255) is included in the RGBW color tuple. When the user picks a color in the RGBW picker, R/G/B are converted to Hue/Saturation and sent alongside the white value.
- **RGBWEL2564**: On/off, RGBW color control for 4-channel Beckhoff EL2564 LED terminals. Each color channel (red, green, blue, white) is scaled from the PLC range (0–32767) to the Home Assistant range (0–255). Effects/modes if configured.

#### Cover

Blinds and SimpleBlinds widgets are exposed as {% term cover %} entities.

- **Blinds**: Open / close / stop, position control (0–100%), tilt angle control (if `iot.BlindsAngleSliderVisible`).
- **SimpleBlinds**: Open / close only. Current position is reported (if `nPositionValue` is published by the PLC), but position cannot be commanded. No stop or tilt support.

#### Switch

Plug widgets are exposed as {% term switch %} entities with `outlet` device class:

- On/off control via `bOn`
- Current mode exposed as state attribute (if `iot.PlugModeVisible`)

#### Climate

AC widgets are exposed as {% term climate %} entities with support for:

- **Current temperature** from `nTemperature` and **target temperature** from `nTemperatureRequest`
- **HVAC modes** mapped from the PLC's `aModes` array. The following PLC mode strings are recognized (case-insensitive): Auto/Automatisch/Automatic → `auto`, Heizen/Heat/Heating → `heat`, Kühlen/Kuehlen/Cool/Cooling → `cool`, Aus/Off → `off`, heat_cool → `heat_cool`, fan_only → `fan_only`, dry → `dry`. Modes that don't match any of these become **preset modes**.
- **Fan mode** from `aModes_Strength` (if `iot.ACModeStrengthVisible`)
- **Swing mode** from `aModes_Lamella` (if `iot.ACModeLamellaVisible`)
- Temperature unit auto-detected from `iot.Unit` on the temperature field (°C or °F)
- Min/max temperature from `iot.MinValue`/`iot.MaxValue`
- **AC mode sensor** (`nAcMode`): a separate {% term sensor %} entity (device class `enum`) exposing the PLC's `E_IoT_AcMode` operating state. Possible values: `none`, `cooling`, `ventilation`, `heating`, `cooling_off`, `ventilation_off`, `heating_off`. This sensor is always created for AC widgets and enables automations based on the actual HVAC operating mode.

#### Fan

Ventilation widgets are exposed as {% term fan %} entities with support for:

- On/off control (if `iot.VentilationOnSwitchVisible`)
- Speed percentage from `nValueRequest`, scaled from PLC min/max to 0–100% (if `iot.VentilationSliderVisible`)
- Preset modes from `aModes` (if `iot.VentilationModeVisible`)
- Current sensor reading (`nValue`) and its unit exposed as state attributes

#### Sensor (EnergyMonitoring)

EnergyMonitoring widgets create multiple {% term sensor %} entities per widget:

| Sub-entity | Device class | Description |
| ---------- | ------------ | ----------- |
| Status     | —            | Text status of the energy monitor |
| Power      | `power`      | Current power consumption with unit from `sPowerUnit` |
| Energy     | `energy`     | Total energy consumption with unit from `sEnergyUnit` |
| Power Factor | `power_factor` | Power quality factor |
| L1/L2/L3 Power | `power`  | Per-phase power (L2/L3 conditional on `iot.EnergyMonitoringPhase2Visible`/`Phase3Visible`) |
| L1/L2/L3 Voltage | `voltage` | Per-phase voltage |
| L1/L2/L3 Current | `current` | Per-phase amperage |

#### General (multi-entity)

General widgets are a configurable multi-purpose widget in the TwinCAT IoT Communicator. Each General widget can produce up to nine entities, depending on which features the PLC enables via metadata flags:

| Entity | Platform | PLC value | Condition |
| ------ | -------- | --------- | --------- |
| Switch | Switch   | `bValue1` | `iot.GeneralValue1SwitchVisible` is `true` |
| Light  | Light    | `bValue1` | `iot.GeneralValue1SwitchVisible` is `true` |
| Value 2 (sensor) | Sensor | `nValue2` | `iot.GeneralValue2Visible` is `true` |
| Value 2 (slider) | Number | `nValue2Request` | `iot.GeneralValue2SliderVisible` is `true` |
| Value 3 (sensor) | Sensor | `nValue3` | `iot.GeneralValue3Visible` is `true` |
| Value 3 (slider) | Number | `nValue3Request` | `iot.GeneralValue3SliderVisible` is `true` |
| Mode 1 | Select   | `sMode1` / `aModes1` | `iot.GeneralMode1Visible` is `true` |
| Mode 2 | Select   | `sMode2` / `aModes2` | `iot.GeneralMode2Visible` is `true` |
| Mode 3 | Select   | `sMode3` / `aModes3` | `iot.GeneralMode3Visible` is `true` |

The **Light** entity duplicates the switch function (`bValue1`) but additionally exposes the widget's modes as effects. This allows the Home Assistant voice assistant to control General widget modes via the standard "set effect" interface.

The **Sensor** entities display the read-only current value (`nValue2` / `nValue3`) from the PLC. The unit is taken from the field metadata (`iot.Unit`). No `device_class` is assigned because the unit is generic (e.g. `%` could mean humidity, window position, dimmer level, etc.).

The **Number** entities are created when the slider is enabled (`SliderVisible`) and use `nValue2Request` / `nValue3Request` for commands. Min/max are taken from the field metadata.

The **Select** entities expose each mode slot (Mode 1–3) as a dropdown. Whether the select is changeable depends on `iot.GeneralMode1Changeable` (and equivalents for Mode 2/3).

#### Lock *(upcoming)*

Lock widgets are exposed as {% term lock %} entities with lock, unlock, and open commands. The PLC uses momentary booleans (`bLock`, `bUnlock`, `bOpen`) for commands and feedback booleans (`bLocked`, `bJammed`, `bOpened`) for state.

- **Lock/Unlock**: always available.
- **Open** (unlatch): only available if `iot.LockOpenVisible` is `true`. The `OPEN` feature flag is updated dynamically when metadata changes.
- **Jammed detection**: reported if `iot.LockJammedVisible` is `true`.
- **Door open/closed**: reported via the native `is_open` property if `iot.LockOpenVisible` is `true`.
- **State sensor** (`sState`): a separate {% term sensor %} entity showing the PLC's textual lock state. Only created if `iot.LockStateVisible` is `true`.
- **Mode selector** (`sMode`/`aModes`): a {% term select %} entity for operating modes. Only created if `iot.LockModeVisible` is `true`. Changeability controlled by `iot.LockModeChangeable`.

The PLC-side `sState` value is also exposed as the `lock_state` extra state attribute on the Lock entity itself.

{% note %}
The Lock widget type is not yet available in the official TwinCAT IoT Communicator release. This platform is prepared for the upcoming PLC-side implementation.
{% endnote %}

#### Motion *(upcoming)*

Motion widgets create up to nine entities depending on PLC visibility flags:

| Entity | Platform | PLC value | Condition |
| ------ | -------- | --------- | --------- |
| Motion | Binary Sensor | `bMotion` | `iot.MotionStatusVisible` is `true` |
| Active | Binary Sensor | `bActive` | `iot.MotionActiveVisible` is `true` |
| Bypass | Switch | `bOn` | `iot.MotionOnSwitchVisible` is `true` |
| Hold Time | Number | `nHoldTime` | `iot.MotionHoldTimeVisible` is `true` |
| Brightness | Number | `nBrightness` | `iot.MotionBrightnessVisible` is `true` |
| Range | Number | `nRange` | `iot.MotionRangeVisible` is `true` |
| Sensitivity | Number | `nSensitivity` | `iot.MotionSensitivityVisible` is `true` |
| Battery | Sensor | `nBattery` | `iot.MotionBatteryVisible` is `true` |
| Mode | Select | `sMode`/`aModes` | `iot.MotionModeVisible` is `true` |

The **Motion** binary sensor uses the `motion` device class. The **Active** binary sensor has no device class — it represents a generic computed output, not an occupancy state. Number entities derive min/max/unit from field metadata. The mode selector's changeability is controlled by `iot.MotionModeChangeable`.

{% note %}
The Motion widget type is not yet available in the official TwinCAT IoT Communicator release. This platform is prepared for the upcoming PLC-side implementation.
{% endnote %}

#### Select

Select entities are created for General, Lock, and Motion widgets. For General widgets, each visible mode slot (`sMode1`–`sMode3`) becomes a {% term select %} entity with options from `aModes1`–`aModes3`. For Lock and Motion widgets, a single mode selector is created from `sMode`/`aModes` when the corresponding visibility flag is enabled.

### Raw PLC datatype entities

In addition to structured widgets, the integration discovers scalar PLC values (BOOL, INT, REAL, STRING, etc.) and creates entities for them. All datatypes are mapped to a controllable entity platform regardless of read-only status — the `iot.ReadOnly` flag is enforced at command time, not at entity creation. This design allows the PLC to change read-only status at runtime without recreating entities.

Each scalar datatype also creates a companion {% term sensor %} entity. This read-only sensor mirrors the current value and integrates with Home Assistant statistics and the energy dashboard. The sensor's {% term device_class %} is resolved in order:

1. `iot.Icon` metadata → icon-to-device-class mapping (e.g. `Temperature` icon → temperature sensor)
2. `iot.Unit` metadata → unit-to-device-class mapping (e.g. `%` → humidity sensor)
3. No device class (plain sensor)

When a {% term device_class %} is resolved, the sensor additionally sets `state_class: measurement` so Home Assistant records long-term statistics for the value.

#### Switch (BOOL)

BOOL values become {% term switch %} entities. Turning on sends `true`, turning off sends `false` to the PLC. If the value is marked `iot.ReadOnly`, the entity is displayed but any control attempt raises an error. A companion {% term sensor %} entity and a {% term binary_sensor %} entity are also created. The binary sensor's {% term device_class %} is derived from the widget's `iot.Icon` (e.g. `Door_Open` → door, `Window_Closed` → window, `Motion` → motion).

#### Number (numeric)

INT and REAL values become {% term number %} entities with:

- Min/max from `iot.MinValue`/`iot.MaxValue`
- Step: `1` for integer types, `0.01` for REAL/LREAL. When `iot.DecimalPrecision` is set, the step is `10^-precision` and the display precision matches (for example, `iot.DecimalPrecision=1` → step 0.1, 1 decimal place).
- Unit from `iot.Unit`

A companion {% term sensor %} entity is also created. If the PLC sets `iot.Icon` to a recognized icon name (e.g. `Temperature`, `Droplet`), the sensor automatically uses the matching Home Assistant {% term device_class %}.

#### Text (STRING)

STRING values become {% term text %} entities that can be edited from the Home Assistant UI. Values are limited to 255 characters (matching the PLC `STRING` type maximum). A companion {% term sensor %} entity is also created.

### Access control

If the PLC configures `iot.PermittedUsers` on a widget, that widget is only visible to the listed users. Widgets not assigned to the current MQTT user are hidden automatically.

### Read-only widgets

Widgets marked with `iot.ReadOnly` in the PLC cannot be controlled from Home Assistant. Attempting to control a read-only widget raises an error. Read-only status is also inherited: if a parent view in the PLC structure is marked read-only, all descendant widgets are treated as read-only.

### Icons

Widget icons are auto-mapped from the PLC's `iot.Icon` metadata to [Material Design Icons](https://materialdesignicons.com/). Over 50 Beckhoff icon names are supported (for example, `Lightbulb` → `mdi:lightbulb`, `Heat` → `mdi:radiator`, `Blinds` → `mdi:blinds`). Device-level icons from the Desc message are also mapped for the hub status entity.

### Automatic area assignment

The PLC's view hierarchy (nested `iot.NestedStructIcon` structures) can be automatically mapped to Home Assistant areas. Two separate toggles control this behavior:

- **Create areas** creates Home Assistant areas from the PLC view structure. Existing areas with the same name are reused.
- **Assign devices to areas** assigns new widget devices to their matching area based on the parent view. Devices that already have an area assignment are never overwritten — only newly created devices are assigned.

Both options default to enabled and can be toggled during initial setup and reconfiguration.

### State attributes

All widget entities expose the following state attributes:

| Attribute              | Description |
| ---------------------- | ----------- |
| `read_only`            | Whether the widget is read-only in the PLC. |
| `value_text_color`     | Text color from `iot.ValueTextColor` (if set). |
| `value_text_color_dark`| Dark mode text color from `iot.ValueTextColorDark` (if set). |

Individual platforms expose additional attributes (for example, `min_value`/`max_value` on sensors, `mode` on covers and switches).

## PLC messages

The TwinCAT IoT Communicator supports push messages from the PLC via the `SendMessage` and `SendMessageEx` methods. These messages are published to MQTT topics under `Messages/`.

### Message types

| Type     | Description |
| -------- | ----------- |
| Default  | Simple message (no category). |
| Info     | Informational message. |
| Warning  | Warning message. |
| Error    | Error message. |
| Critical | Critical/urgent message. |

The **Last message** sensor shows the most recent message text. The **Last message type** sensor shows its severity. Use these in automations to forward messages as push notifications.

## Actions

The integration provides the following actions.

### Acknowledge message

The `twincat_iot_communicator.acknowledge_message` action acknowledges a PLC push message. The acknowledgement text is sent back to the PLC and is visible in the TwinCAT IoT Communicator app.

| Data attribute  | Required | Description |
| --------------- | -------- | ----------- |
| `device_name`   | Yes      | Name of the PLC device (for example, `Usermode`). |
| `message_id`    | Yes      | ID of the message to acknowledge (for example, `1`). |
| `acknowledgement` | No     | Text sent back to the PLC as acknowledgement (default: `Acknowledged`). |

```yaml
action: twincat_iot_communicator.acknowledge_message
data:
  device_name: "Usermode"
  message_id: "1"
  acknowledgement: "Read by Christian"
```

### Delete message

The `twincat_iot_communicator.delete_message` action deletes a PLC push message by clearing its retained MQTT topic.

| Data attribute | Required | Description |
| -------------- | -------- | ----------- |
| `device_name`  | Yes      | Name of the PLC device (for example, `Usermode`). |
| `message_id`   | Yes      | ID of the message to delete (for example, `1`). |

```yaml
action: twincat_iot_communicator.delete_message
data:
  device_name: "Usermode"
  message_id: "1"
```

## Examples

### Forward all PLC messages as push notifications

```yaml
automation:
  - alias: "Forward PLC messages"
    trigger:
      - platform: state
        entity_id: event.tciot_usermode_messages
    condition:
      - condition: template
        value_template: >
          {% raw %}{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}{% endraw %}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            {% raw %}TcIoT [{{ trigger.to_state.attributes.type }}]{% endraw %}
          message: >
            {% raw %}{{ trigger.to_state.attributes.text }}{% endraw %}
```

### Forward only errors and auto-acknowledge

```yaml
automation:
  - alias: "Forward PLC errors and acknowledge"
    trigger:
      - platform: state
        entity_id: event.tciot_usermode_messages
    condition:
      - condition: template
        value_template: >
          {% raw %}{{ trigger.to_state.state not in ['unknown', 'unavailable']
             and trigger.to_state.attributes.type in ['Error', 'Critical'] }}{% endraw %}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            {% raw %}TcIoT {{ trigger.to_state.attributes.type }}{% endraw %}
          message: >
            {% raw %}{{ trigger.to_state.attributes.text }}{% endraw %}
      - action: twincat_iot_communicator.acknowledge_message
        data:
          device_name: "Usermode"
          message_id: >
            {% raw %}{{ trigger.to_state.attributes.message_id }}{% endraw %}
          acknowledgement: "Forwarded to Christian"
```

### Forward all messages and auto-delete

```yaml
automation:
  - alias: "Forward and delete PLC messages"
    trigger:
      - platform: state
        entity_id: event.tciot_usermode_messages
    condition:
      - condition: template
        value_template: >
          {% raw %}{{ trigger.to_state.state not in ['unknown', 'unavailable'] }}{% endraw %}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            {% raw %}TcIoT [{{ trigger.to_state.attributes.type }}]{% endraw %}
          message: >
            {% raw %}{{ trigger.to_state.attributes.text }}{% endraw %}
      - action: twincat_iot_communicator.delete_message
        data:
          device_name: "Usermode"
          message_id: >
            {% raw %}{{ trigger.to_state.attributes.message_id }}{% endraw %}
```

## Re-authentication

When using OAuth/JWT authentication, the integration monitors the token validity. If the JWT expires or the MQTT broker rejects the credentials, the integration automatically triggers a re-authentication flow:

1. A notification appears in Home Assistant: **"TwinCAT IoT Communicator requires attention"**.
2. A red badge is shown on the integration in {% my integrations title="**Settings** > **Devices & services**" %}.
3. Selecting the integration shows a confirmation dialog explaining that the token has expired.
4. After confirmation, a browser window opens for a new OAuth login.
5. After successful login, the token is updated and the integration reloads automatically.

The integration checks token validity:

- When the integration loads (startup/restart).
- Before each MQTT reconnection attempt.
- When the MQTT broker rejects the connection (CONNACK rc=5).

{% tip %}
To avoid frequent re-authentication, configure an appropriate token lifetime on your identity provider. For production use, 8–24 hours is recommended. For long-running installations, consider 7–180 days.
{% endtip %}

## Data updates

This integration uses **MQTT push** — the PLC publishes state changes to the broker, and Home Assistant receives them instantly. There is no polling.

A heartbeat is sent every second to keep the PLC connection alive. Every 15 minutes, the integration requests a full data refresh from the PLC (`active=1`) to reconcile the widget set — widgets that are no longer published become unavailable, and previously missing widgets recover automatically. When the MQTT connection is lost, the integration automatically reconnects.

## Implementing the OAuth backend

This section is for system integrators who want to set up the server-side OAuth flow for JWT-based MQTT authentication.

### Protocol overview

The integration uses the **OAuth 2.0 Authorization Code flow with PKCE** — the same secure flow used by mobile apps and single-page applications.

1. Home Assistant discovers the authorization and token endpoints via **OIDC Discovery** (`/.well-known/openid-configuration`).
2. The user is redirected to the identity provider's login page with PKCE parameters (`code_challenge`, `code_challenge_method=S256`).
3. After successful login, the identity provider redirects back with an **authorization code**.
4. Home Assistant exchanges the code for a **JWT access token** at the token endpoint using the PKCE `code_verifier`.
5. The JWT is decoded to extract the username, then used for the MQTT connection.

### Identity provider requirements

| Requirement | Description |
| ----------- | ----------- |
| OIDC Discovery | The `/.well-known/openid-configuration` endpoint must be reachable. |
| Authorization Code flow | The standard OAuth2 flow must be enabled. |
| PKCE (S256) | Proof Key for Code Exchange must be supported. |
| Public client | No client secret — the client runs on user devices. |
| Redirect URI | Must allow `https://<ha-host>/auth/tc_iot/callback*`. |

### JWT requirements

The issued JWT must contain the following claims:

| Claim                | Required | Description |
| -------------------- | -------- | ----------- |
| `preferred_username` | Yes*     | MQTT username (for example, `max.mustermann`). Primary lookup. |
| `sub`                | Yes*     | Subject identifier. Used as fallback if `preferred_username` is absent. |
| `exp`                | Yes      | Expiration timestamp (Unix epoch, seconds). |

\* At least one of `preferred_username` or `sub` must be present.

Recommended additional claims: `iat`, `iss`, `aud`, and `roles` for broker-side access control.

{% important %}
The client (Home Assistant) does **not** verify the JWT signature. It only decodes the payload to extract the username. All signature and claims validation must happen on the MQTT broker.
{% endimportant %}

### MQTT broker configuration

The MQTT broker must:

- Accept the **full JWT access token** as the MQTT password.
- **Verify the JWT signature** against the identity provider's public key (JWKS endpoint).
- **Check the `exp` claim** and reject expired tokens.
- Optionally check `iss`, `aud`, and `roles` for fine-grained access control.
- Map publish/subscribe permissions based on the username and/or roles.

{% details "Broker-specific setup examples" %}

#### Cedalo (Management Center)

1. Go to **Security** > **Authentication** > **JWT**.
2. Configure the **JWKS URL** of your identity provider.
3. Set **Username claim** to `preferred_username`.
4. Configure topic ACLs per user or role.

#### EMQX

1. Enable the **JWT Authentication** plugin.
2. Set `auth.jwt.from` to `password`.
3. Set `auth.jwt.verify_claims.username` to `%u`.
4. Configure the JWKS endpoint or public key.

#### Mosquitto (with auth plugin)

Mosquitto does not natively support JWT. Use a plugin such as [mosquitto-go-auth](https://github.com/iegomez/mosquitto-go-auth) with the JWT backend enabled.

{% enddetails %}

{% details "Keycloak setup (step-by-step)" %}

1. **Create a realm** (or use an existing one).
2. **Create a client:**
   - Client ID: `tc_iot_communicator`
   - Client type: OpenID Connect
   - Client authentication: **Off** (public client)
   - Standard flow: **Enabled**
   - Direct access grants: Disabled
3. **Set redirect URIs:**
   ```text
   https://<your-ha-host>:8123/auth/tc_iot/callback*
   ```
4. **Configure token lifetime:** Under Advanced Settings, set the Access Token Lifespan.
5. **Create users:** The `preferred_username` in Keycloak becomes the MQTT username.
6. **Optional — Audience mapper:** Add a protocol mapper of type `oidc-audience-mapper` to include `tc_iot_communicator` in the `aud` claim if your broker validates audiences.
7. **Test OIDC Discovery:**
   ```bash
   curl https://auth.example.com/realms/myrealm/.well-known/openid-configuration
   ```
   The response must contain `authorization_endpoint` and `token_endpoint`.

{% enddetails %}

## Diagnostics

This integration provides diagnostics data for troubleshooting via {% my integrations title="**Settings** > **Devices & services**" %}. The diagnostics include:

- Connection status and broker details (hostname, main topic, device count, listener count).
- Per-device information: online status, registration state, icon, widget count, known and stale widget paths, message count, snapshot state.
- Configuration entry data (credentials and permitted users are redacted).

## Known limitations

- The **BarChart** widget type is discovered but does not create entities.
- This integration communicates through an MQTT broker — it does not connect directly to the PLC via ADS. For direct ADS communication, see the [ADS integration](/integrations/ads/).
- When the PLC configuration changes (widgets added or removed), the integration automatically reconciles after an `active=1` refresh cycle — new widgets are added and missing widgets become unavailable. Widget paths should remain stable across PLC restarts for reliable entity identification.

## Troubleshooting

### No devices found during setup

- Verify the PLC is online and publishing to the MQTT broker.
- Check that the **main topic** matches the topic configured in the TwinCAT IoT Communicator (for example, `IotApp.Sample`).
- Use an MQTT client (for example, [MQTT Explorer](https://mqtt-explorer.com/)) to verify messages appear on `<main_topic>/+/TcIotCommunicator/Json/Tx/Data`.

### Entities show as unavailable

- Check the **Status** binary sensor — if it shows offline, the PLC or broker connection is down.
- If specific entities are unavailable while the device is online, the PLC may have removed those widgets from its configuration.

### Cannot connect to the MQTT broker

- Verify the hostname, port, and TLS settings.
- Check the Home Assistant logs for detailed error messages:
  - `Connection refused` — the port is closed or firewalled.
  - `TLS/SSL error` — certificate issues (expired, wrong hostname).
  - `MQTT error rc=5` — authentication failed (wrong username/password or invalid JWT).

### OAuth login window does not close

- Verify the identity provider is configured to redirect to the correct Home Assistant URL. The redirect URI pattern is `https://<your-ha-host>/auth/tc_iot/callback?flow_id=<id>`.
- If the auth server returns the token in the URL fragment (`#access_token=...`), JavaScript must be enabled in the browser.
- Check the Home Assistant logs for `twincat_iot_communicator` entries.

### Re-authentication keeps triggering

- The JWT token lifetime may be too short. Check the `exp` claim in your token and increase the lifetime on the identity provider.
- If the MQTT broker rejects the token (rc=5), verify that the broker's JWT validation is configured correctly (JWKS URL, audience, issuer).

### Messages not appearing

- Verify the PLC is calling `SendMessage` or `SendMessageEx` on the `FB_IotCommunicator` function block.
- Check that retained messages exist on `<main_topic>/<device>/TcIotCommunicator/Messages/+` using an MQTT client.

## Removing the integration

This integration follows standard integration removal.

{% include integrations/remove_device_service.md %}
