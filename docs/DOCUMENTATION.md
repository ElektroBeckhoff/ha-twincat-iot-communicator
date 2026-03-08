# TwinCAT IoT Communicator

Connect Home Assistant to Beckhoff TwinCAT PLCs via the IoT Communicator (TF6730) MQTT interface.

| | |
|---|---|
| **IoT Class** | Local Push |
| **Integration Type** | Hub |
| **Config Flow** | Yes |
| **Quality Scale** | Bronze |
| **Platforms** | Binary Sensor, Button, Climate, Cover, Date, Diagnostics, Event, Fan, Light, Number, Select, Sensor, Switch, Text, Time |

---

The **TwinCAT IoT Communicator** integration connects Home Assistant to [Beckhoff](https://www.beckhoff.com/) TwinCAT PLCs using the [TF6730 IoT Communicator](https://www.beckhoff.com/en-en/products/automation/twincat/tfxxxx-twincat-3-functions/tf6xxx-connectivity/tf6730.html) MQTT interface.

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
| AC                  | Climate                | Temperature, HVAC modes, fan speed, swing/lamella |
| Ventilation         | Fan                    | On/off, speed percentage, preset modes |
| EnergyMonitoring    | Sensor                 | Power, energy, power factor, per-phase voltage/current/power |
| ChargingStation     | Button, Sensor         | Start/stop/reserve buttons, status, battery level, power, energy, charging time, per-phase voltage/current/power |
| TimeSwitch          | Switch, Date, Time, Select | Power toggle, start/end time, start/end date, yearly flag, weekday toggles (Mon–Sun), mode selector |
| General             | Switch, Light, Number, Select | Configurable multi-entity widget (on/off, modes, values) |

### Supported raw PLC datatypes

Scalar PLC values that are not part of a widget are auto-discovered by their JSON value type and mapped to the appropriate platform. Variable names in the PLC do not matter — only the actual data type in the JSON payload is used for detection. Every datatype gets a single entity regardless of read-only status — read-only protection is enforced at command time, not at entity creation.

| JSON value type    | Home Assistant platform |
| ------------------ | ---------------------- |
| Boolean            | Switch                 |
| Integer / Float    | Number                 |
| String             | Text                   |
| Array of booleans  | Switch (one per element, read-only) |
| Array of numbers   | Number (one per element, read-only) |
| Array of strings   | Text (one per element, read-only)   |

### Ignored widget types

The following widget types are discovered but intentionally do not create entities:

- **BarChart** — array/chart data with no sensible HA entity

## Prerequisites

- A Beckhoff TwinCAT 3 PLC with the TF6730 IoT Communicator licensed and configured.
- An MQTT broker reachable by both the PLC and Home Assistant (for example, Mosquitto, [Cedalo](https://cedalo.com/), [EMQX](https://www.emqx.io/), or any standard MQTT broker).
- The PLC must be configured to publish to the broker with a known **main topic** (for example, `IotApp.Sample`).
- **For OAuth authentication only:** An OIDC-compliant identity provider (for example, [Keycloak](https://www.keycloak.org/), Azure AD, Auth0, or Authentik) with a public OAuth client configured.

## Installation

This integration is configured entirely through the Home Assistant UI:

**Settings** → **Devices & services** → **Add integration** → search for **TwinCAT IoT Communicator**.

## Configuration parameters

The integration is set up entirely through the UI. The setup flow consists of four steps:

### Step 1: MQTT broker

| Parameter | Description |
|-----------|-------------|
| **Host** | Hostname or IP address of the MQTT broker. |
| **Port** | MQTT broker port (default: `1883`, or `8883` for TLS). |
| **Use TLS** | Enable TLS encryption for the broker connection. |

### Step 2: Authentication method

After entering the broker details, a menu lets you choose one of three authentication methods:

- **No authentication (anonymous)** — connect without credentials. Use this if your broker does not require authentication.
- **Username and password** — provide a broker username and password. Both fields are optional — leave them empty for brokers that accept anonymous connections but still require the credentials step.
- **External login (OAuth / JWT)** — authenticate via an external OAuth login page. See [Authentication: OAuth / JWT](#authentication-oauth--jwt) below.

### Step 3: Main topic

| Parameter | Description |
|-----------|-------------|
| **Main topic** | The MQTT main topic configured in the PLC (for example, `IotApp.Sample`). |

After entering the topic, the integration scans the broker for devices publishing on that topic.

### Step 4: Device selection

| Parameter | Description |
|-----------|-------------|
| **Devices** | Select which discovered PLC devices to integrate. |
| **Create areas** | Automatically create Home Assistant areas from the PLC view structure (default: enabled). |

Devices that are already configured in another config entry for the same topic are excluded automatically.

### Reconfiguring devices

To add or remove individual PLC devices after initial setup, select the integration in **Settings** > **Devices & services** and choose **Reconfigure**. The integration rescans the broker and shows all available devices. Deselected devices are removed; newly selected devices are added. The **Create areas** toggle can also be changed during reconfiguration. To change the broker address or main topic, remove and re-add the integration.

### Authentication: OAuth / JWT

Selecting **External login (OAuth / JWT)** in the authentication menu opens the OAuth setup flow. This avoids storing passwords in Home Assistant and allows centralized user management through an identity provider.

> **Tip:** This method works with any OIDC-compliant provider, including Keycloak, Azure AD, Auth0, and Authentik. The integration discovers endpoints automatically via OIDC Discovery.

**Setup flow:**

1. Enter the **Issuer URL** — this is the OIDC issuer URL of your identity provider (for example, `https://auth.example.com/realms/myrealm`). Do not enter the full authorization endpoint; the integration discovers it automatically.
2. Enter the **Client ID** registered at the identity provider (default: `tc_iot_communicator`). The client must be a public client (no client secret).
3. A browser window opens, prompting you to log in at the identity provider.
4. After successful login, Home Assistant receives an authorization code and securely exchanges it for a JWT access token using the **Authorization Code flow with PKCE**.
5. The integration decodes the JWT locally and extracts the MQTT username from the `preferred_username` claim (falls back to `sub`).
6. The MQTT connection uses the decoded claim as the username and the full JWT as the password.

The JWT is stored in the config entry. You do not need to log in again until the token expires. When the token expires, Home Assistant automatically triggers a re-authentication flow (see [Re-authentication](#re-authentication)).

> **Note:** The MQTT broker must be configured to accept JWT access tokens as passwords. The broker is responsible for validating the token signature, expiration, and permissions. See [Implementing the OAuth backend](#implementing-the-oauth-backend) for details.

> **Tip:** If your auth server does not support OIDC Discovery, the integration falls back to direct token delivery mode. In this case, the auth server must redirect back with `?access_token=JWT` or `#access_token=JWT` in the URL.

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

Lighting, RGBW, and RGBWEL2564 widgets are exposed as Light entities.

- **Lighting**: On/off, brightness (if `iot.LightSliderVisible`), effects/modes.
- **RGBW**: On/off, brightness (`nLight`), RGBW color mode (if `iot.LightColorPaletteVisible` and `iot.LightWhiteSliderVisible`), HS color mode (if only `iot.LightColorPaletteVisible`), color temperature mode (if `iot.LightColorTemperatureSliderVisible`), effects/modes. The PLC natively uses Hue/Saturation — the integration converts RGB↔HS transparently. The white channel (`nWhite`, PLC 0–100, HA 0–255) is included in the RGBW color tuple. When the user picks a color in the RGBW picker, R/G/B are converted to Hue/Saturation and sent alongside the white value.
- **RGBWEL2564**: On/off, RGBW color control for 4-channel Beckhoff EL2564 LED terminals. Each color channel (red, green, blue, white) is scaled from the PLC range (0–32767) to the Home Assistant range (0–255). Effects/modes if configured.

#### Cover

Blinds and SimpleBlinds widgets are exposed as Cover entities.

- **Blinds**: Open / close / stop, position control (0–100%), tilt angle control (if `iot.BlindsAngleSliderVisible`).
- **SimpleBlinds**: Open / close only. Current position is reported (if `nPositionValue` is published by the PLC), but position cannot be commanded. No stop or tilt support.

#### Switch

Plug widgets are exposed as Switch entities with `outlet` device class:

- On/off control via `bOn`
- Current mode exposed as state attribute (if `iot.PlugModeVisible`)

#### Climate

AC widgets are exposed as Climate entities with support for:

- **Current temperature** from `nTemperature` and **target temperature** from `nTemperatureRequest`
- **HVAC modes** mapped from the PLC's `aModes` array. The following PLC mode strings are recognized (case-insensitive): Auto/Automatisch/Automatic → `auto`, Heizen/Heat/Heating → `heat`, Kühlen/Kuehlen/Cool/Cooling → `cool`, Aus/Off → `off`, heat_cool → `heat_cool`, fan_only → `fan_only`, dry → `dry`. Modes that don't match any of these become **preset modes**.
- **Fan mode** from `aModes_Strength` (if `iot.ACModeStrengthVisible`)
- **Swing mode** from `aModes_Lamella` (if `iot.ACModeLamellaVisible`)
- Temperature unit auto-detected from `iot.Unit` on the temperature field (°C or °F)
- Min/max temperature from `iot.MinValue`/`iot.MaxValue`

#### Fan

Ventilation widgets are exposed as Fan entities with support for:

- On/off control (if `iot.VentilationOnSwitchVisible`)
- Speed percentage from `nValueRequest`, scaled from PLC min/max to 0–100% (if `iot.VentilationSliderVisible`)
- Preset modes from `aModes` (if `iot.VentilationModeVisible`)
- Current sensor reading (`nValue`) and its unit exposed as state attributes

#### Sensor (EnergyMonitoring)

EnergyMonitoring widgets create multiple Sensor entities per widget:

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

General widgets are a configurable multi-purpose widget in the TwinCAT IoT Communicator. Each General widget can produce up to seven entities, depending on which features the PLC enables via metadata flags:

| Entity | Platform | PLC value | Condition |
| ------ | -------- | --------- | --------- |
| Switch | Switch   | `bValue1` | `iot.GeneralValue1SwitchVisible` is `true` |
| Light  | Light    | `bValue1` | `iot.GeneralValue1SwitchVisible` is `true` |
| Value 2 | Number  | `nValue2` / `nValue2Request` | `iot.GeneralValue2Visible` is `true` |
| Value 3 | Number  | `nValue3` / `nValue3Request` | `iot.GeneralValue3Visible` is `true` |
| Mode 1 | Select   | `sMode1` / `aModes1` | `iot.GeneralMode1Visible` is `true` |
| Mode 2 | Select   | `sMode2` / `aModes2` | `iot.GeneralMode2Visible` is `true` |
| Mode 3 | Select   | `sMode3` / `aModes3` | `iot.GeneralMode3Visible` is `true` |

The **Light** entity duplicates the switch function (`bValue1`) but additionally exposes the widget's modes as effects. This allows the Home Assistant voice assistant to control General widget modes via the standard "set effect" interface.

The **Number** entities use `nValue2Request` / `nValue3Request` for commands and display the current value from `nValue2` / `nValue3`. Min/max are taken from the field metadata.

The **Select** entities expose each mode slot (Mode 1–3) as a dropdown. Whether the select is changeable depends on `iot.GeneralMode1Changeable` (and equivalents for Mode 2/3).

#### Select

Select entities are currently only created for General widgets (see [General (multi-entity)](#general-multi-entity) above). Each visible mode slot (`sMode1`–`sMode3`) becomes a Select entity. The available options are taken from the corresponding `aModes1`–`aModes3` array.

### Raw PLC datatype entities

In addition to structured widgets, the integration discovers scalar PLC values (BOOL, INT, REAL, STRING, etc.) and creates entities for them. All datatypes are mapped to a single entity platform regardless of read-only status — the `iot.ReadOnly` flag is enforced at command time, not at entity creation. This design allows the PLC to change read-only status at runtime without recreating entities.

#### Switch (BOOL)

BOOL values become Switch entities. Turning on sends `true`, turning off sends `false` to the PLC. If the value is marked `iot.ReadOnly`, the entity is displayed but any control attempt raises an error.

#### Number (numeric)

INT and REAL values become Number entities with:

- Min/max from `iot.MinValue`/`iot.MaxValue`
- Step: `1` for integer types, `0.01` for REAL/LREAL. When `iot.DecimalPrecision` is set, the step is `10^-precision` and the display precision matches (for example, `iot.DecimalPrecision=1` → step 0.1, 1 decimal place).
- Unit from `iot.Unit`

#### Text (STRING)

STRING values become Text entities that can be edited from the Home Assistant UI. Values are limited to 255 characters (matching the PLC `STRING` type maximum).

### Access control

If the PLC configures `iot.PermittedUsers` on a widget, that widget is only visible to the listed users. Widgets not assigned to the current MQTT user are hidden automatically.

### Read-only widgets

Widgets marked with `iot.ReadOnly` in the PLC cannot be controlled from Home Assistant. Attempting to control a read-only widget raises an error. Read-only status is also inherited: if a parent view in the PLC structure is marked read-only, all descendant widgets are treated as read-only.

### Icons

Widget icons are auto-mapped from the PLC's `iot.Icon` metadata to [Material Design Icons](https://materialdesignicons.com/). Over 50 Beckhoff icon names are supported (for example, `Lightbulb` → `mdi:lightbulb`, `Heat` → `mdi:radiator`, `Blinds` → `mdi:blinds`). Device-level icons from the Desc message are also mapped for the hub status entity.

### Automatic area assignment

The PLC's view hierarchy (nested `iot.NestedStructIcon` structures) can be automatically mapped to Home Assistant areas. When enabled (the **Create areas** checkbox during setup), widgets inside a named PLC view are assigned to a matching Home Assistant area. This means rooms and zones defined in the TwinCAT project appear automatically in Home Assistant. This option can be toggled during device setup and reconfiguration.

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
          {{ trigger.to_state.state not in ['unknown', 'unavailable'] }}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            TcIoT [{{ trigger.to_state.attributes.type }}]
          message: >
            {{ trigger.to_state.attributes.text }}
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
          {{ trigger.to_state.state not in ['unknown', 'unavailable']
             and trigger.to_state.attributes.type in ['Error', 'Critical'] }}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            TcIoT {{ trigger.to_state.attributes.type }}
          message: >
            {{ trigger.to_state.attributes.text }}
      - action: twincat_iot_communicator.acknowledge_message
        data:
          device_name: "Usermode"
          message_id: >
            {{ trigger.to_state.attributes.message_id }}
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
          {{ trigger.to_state.state not in ['unknown', 'unavailable'] }}
    action:
      - action: notify.mobile_app_christian
        data:
          title: >
            TcIoT [{{ trigger.to_state.attributes.type }}]
          message: >
            {{ trigger.to_state.attributes.text }}
      - action: twincat_iot_communicator.delete_message
        data:
          device_name: "Usermode"
          message_id: >
            {{ trigger.to_state.attributes.message_id }}
```

## Re-authentication

When using OAuth/JWT authentication, the integration monitors the token validity. If the JWT expires or the MQTT broker rejects the credentials, the integration automatically triggers a re-authentication flow:

1. A notification appears in Home Assistant: **"TwinCAT IoT Communicator requires attention"**.
2. A red badge is shown on the integration in **Settings** > **Devices & services**.
3. Selecting the integration shows a confirmation dialog explaining that the token has expired.
4. After confirmation, a browser window opens for a new OAuth login.
5. After successful login, the token is updated and the integration reloads automatically.

The integration checks token validity:

- When the integration loads (startup/restart).
- Before each MQTT reconnection attempt.
- When the MQTT broker rejects the connection (CONNACK rc=5).

> **Tip:** To avoid frequent re-authentication, configure an appropriate token lifetime on your identity provider. For production use, 8–24 hours is recommended. For long-running installations, consider 7–180 days.

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

> **Important:** The client (Home Assistant) does **not** verify the JWT signature. It only decodes the payload to extract the username. All signature and claims validation must happen on the MQTT broker.

### MQTT broker configuration

The MQTT broker must:

- Accept the **full JWT access token** as the MQTT password.
- **Verify the JWT signature** against the identity provider's public key (JWKS endpoint).
- **Check the `exp` claim** and reject expired tokens.
- Optionally check `iss`, `aud`, and `roles` for fine-grained access control.
- Map publish/subscribe permissions based on the username and/or roles.

<details>
<summary>Broker-specific setup examples</summary>

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

</details>

<details>
<summary>Keycloak setup (step-by-step)</summary>

1. **Create a realm** (or use an existing one).
2. **Create a client:**
   - Client ID: `tc_iot_communicator`
   - Client type: OpenID Connect
   - Client authentication: **Off** (public client)
   - Standard flow: **Enabled**
   - Direct access grants: Disabled
3. **Set redirect URIs:**
   ```
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

</details>

## Diagnostics

This integration provides diagnostics data for troubleshooting via **Settings** > **Devices & services**. The diagnostics include:

- Connection status and broker details (hostname, main topic, device count, listener count).
- Per-device information: online status, registration state, icon, widget count, known and stale widget paths, message count, snapshot state.
- Configuration entry data (credentials and permitted users are redacted).

## Known limitations

- The **BarChart** widget type is discovered but does not create entities.
- This integration communicates through an MQTT broker — it does not connect directly to the PLC via ADS. For direct ADS communication, see the [ADS integration](https://www.home-assistant.io/integrations/ads/).
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

To remove the integration:

1. Go to **Settings** > **Devices & services**.
2. Select the **TwinCAT IoT Communicator** integration.
3. Click the three-dot menu (⋮) and select **Delete**.

All associated entities and devices will be removed from Home Assistant.
