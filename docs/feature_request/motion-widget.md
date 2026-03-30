# Feature Request: Motion-Widget (Bewegungsmelder) für TwinCAT IoT Communicator

## Zusammenfassung

Erweiterung des TwinCAT IoT Communicator (TF6730 / TF6735) um ein **Motion-Widget** zur Anzeige und Parametrierung von Bewegungsmeldern in der Gebäudeautomation. Das Widget enthält **keine eigene Logik** — es zeigt PLC-Werte an und sendet Benutzerbefehle zurück. Die gesamte Auswertung (Modi, Schwellwerte, Nachlauf etc.) erfolgt ausschließlich in der PLC.

## Vorgeschlagener Widget-Typ: `Motion`

### PLC-Attribute

```
{attribute 'iot.ReadOnly' := 'false'}
{attribute 'iot.DisplayName' := 'Name for Widget'}
{attribute 'iot.WidgetType' := 'Motion'}
{attribute 'iot.MotionWidgetIcon' := 'Motion'}
{attribute 'iot.MotionStatusVisible' := 'true'}
{attribute 'iot.MotionActiveVisible' := 'true'}
{attribute 'iot.MotionOnSwitchVisible' := 'true'}
{attribute 'iot.MotionHoldTimeVisible' := 'true'}
{attribute 'iot.MotionBrightnessVisible' := 'true'}
{attribute 'iot.MotionRangeVisible' := 'true'}
{attribute 'iot.MotionSensitivityVisible' := 'true'}
{attribute 'iot.MotionBatteryVisible' := 'false'}
{attribute 'iot.MotionModeVisible' := 'true'}
{attribute 'iot.MotionModeChangeable' := 'true'}
stMotionWidgetSample : ST_MotionWidgetSample;
```

| Attribut | Datentyp | Beschreibung |
|----------|----------|--------------|
| `iot.ReadOnly` | BOOL | Nur-Lese-Zugriff (`TRUE`) oder auch Schreibzugriff (`FALSE`). |
| `iot.DisplayName` | STRING | Anzeigename des Widgets in der App. Wird durch `sDisplayName` überschrieben. |
| `iot.WidgetType` | STRING | Typ-Bezeichnung: `Motion`. |
| `iot.MotionWidgetIcon` | STRING | Icon-Name (z.B. `Motion`, `Motion_Off`, `Eye`, `Radar`). |
| `iot.MotionStatusVisible` | BOOL | Sensorstatus (Bewegung erkannt) anzeigen (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionActiveVisible` | BOOL | Ausgang (nach PLC-Auswertung) anzeigen (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionOnSwitchVisible` | BOOL | Ein/Aus-Switch (Übersteuerung) sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionHoldTimeVisible` | BOOL | Nachlaufzeit-Einstellung sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionBrightnessVisible` | BOOL | Helligkeitsschwelle-Einstellung sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionRangeVisible` | BOOL | Reichweite-Einstellung sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionSensitivityVisible` | BOOL | Empfindlichkeit-Einstellung sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). |
| `iot.MotionBatteryVisible` | BOOL | Batteriestatus anzeigen (`TRUE`) oder nicht (`FALSE`). Für Funk-Melder. |
| `iot.MotionModeVisible` | BOOL | Betriebsmodus anzeigen (`TRUE`) oder nicht (`FALSE`). |
| `iot.MotionModeChangeable` | BOOL | Betriebsmodus änderbar (`TRUE`) oder nicht (`FALSE`). |

### PLC-Strukturdefinition

```
TYPE ST_MotionWidgetSample :
STRUCT
    sDisplayName    : STRING := '';
    bMotion         : BOOL := FALSE;    // Sensorstatus — Bewegung erkannt (PLC → App, read-only)
    bActive         : BOOL := FALSE;    // Ausgang aktiv — nach PLC-Auswertung (PLC → App, read-only)
    bOn             : BOOL := FALSE;    // Ein/Aus / Übersteuerung (Bidirektional)
    nHoldTime   : INT := 300;       // Nachlaufzeit in Sekunden (Bidirektional)
    nBrightness     : INT := 50;        // Helligkeitsschwelle in Lux (Bidirektional)
    nRange          : INT := 100;       // Reichweite in % (Bidirektional)
    nSensitivity    : INT := 80;        // Empfindlichkeit in % (Bidirektional)
    nBattery        : INT := 100;       // Batteriestatus in % (PLC → App, read-only)
    sMode           : STRING := 'Auto'; // Betriebsmodus (Bidirektional)
    aModes          : ARRAY[0..3] OF STRING := ['Auto', 'Manuell', 'Test', 'Aus'];
END_STRUCT
END_TYPE
```

| Feld | Datentyp | Richtung | Beschreibung | Anzeige im Widget |
|------|----------|----------|--------------|-------------------|
| `sDisplayName` | STRING | — | Anzeigename, überschreibt `iot.DisplayName`. | Titel des Widgets. |
| `bMotion` | BOOL | PLC → App | Sensorstatus — Bewegung erkannt (`TRUE`) oder nicht (`FALSE`). Read-only. | Sensor-Icon / Statusanzeige (wenn `iot.MotionStatusVisible`). |
| `bActive` | BOOL | PLC → App | Ausgang aktiv (`TRUE`) nach PLC-Auswertung. Read-only. | Ausgang-Icon / Statusanzeige (wenn `iot.MotionActiveVisible`). |
| `bOn` | BOOL | Bidirektional | Ein/Aus / Übersteuerung. Auswertung erfolgt in der PLC. | Toggle-Switch (wenn `iot.MotionOnSwitchVisible`). |
| `nHoldTime` | INT | Bidirektional | Nachlaufzeit in Sekunden. Auswertung erfolgt in der PLC. | Slider / Eingabefeld (wenn `iot.MotionHoldTimeVisible`). |
| `nBrightness` | INT | Bidirektional | Helligkeitsschwelle in Lux. Auswertung erfolgt in der PLC. | Slider (wenn `iot.MotionBrightnessVisible`). |
| `nRange` | INT | Bidirektional | Reichweite in % (0–100). Auswertung erfolgt in der PLC. | Slider (wenn `iot.MotionRangeVisible`). |
| `nSensitivity` | INT | Bidirektional | Empfindlichkeit in % (0–100). Auswertung erfolgt in der PLC. | Slider (wenn `iot.MotionSensitivityVisible`). |
| `nBattery` | INT | PLC → App | Batteriestatus in % (0–100). Read-only. | Batterie-Icon / Prozentwert (wenn `iot.MotionBatteryVisible`). |
| `sMode` | STRING | Bidirektional | Aktueller Betriebsmodus. | Modus-Anzeige unten. |
| `aModes` | ARRAY [0..n] OF STRING | PLC → App | Verfügbare Modi. | Modus-Auswahl per Tippen. |

### Modi (Referenz — Auswertung erfolgt in der PLC)

Das Widget zeigt den aktuellen Modus an und sendet Modus-Änderungen an die PLC. Die Modi selbst werden frei per `aModes` definiert und haben keine Widget-seitige Logik. Typische Modi:

| Modus | Typische PLC-Auswertung |
|-------|-------------------------|
| `Auto` | Normalbetrieb. |
| `Manuell` | Ausgang über `bOn` gesteuert. |
| `Test` | Walk-Test mit verkürzter Nachlaufzeit. |
| `Aus` | Melder deaktiviert. |

### Beispiel JSON (Full-Feature)

```json
{
  "Timestamp": "2026-03-25T14:32:10.512",
  "GroupName": "Homeassistant",
  "Values": {
    "stMotion": {
      "sDisplayName": "Flur EG",
      "bMotion": true,
      "bActive": true,
      "bOn": false,
      "nHoldTime": 300,
      "nBrightness": 50,
      "nRange": 100,
      "nSensitivity": 80,
      "nBattery": 87,
      "sMode": "Auto",
      "aModes": [
        "Auto",
        "Manuell",
        "Test",
        "Aus"
      ]
    }
  },
  "MetaData": {
    "stMotion": {
      "iot.DisplayName": "Flur EG",
      "iot.ReadOnly": "false",
      "iot.WidgetType": "Motion",
      "iot.MotionWidgetIcon": "Motion",
      "iot.MotionStatusVisible": "true",
      "iot.MotionActiveVisible": "true",
      "iot.MotionOnSwitchVisible": "true",
      "iot.MotionHoldTimeVisible": "true",
      "iot.MotionBrightnessVisible": "true",
      "iot.MotionRangeVisible": "true",
      "iot.MotionSensitivityVisible": "true",
      "iot.MotionBatteryVisible": "false",
      "iot.MotionModeVisible": "true",
      "iot.MotionModeChangeable": "true",
      "iot.PermittedUsers": "*"
    },
    "stMotion.nHoldTime": {
      "iot.Unit": "s",
      "iot.MinValue": "0",
      "iot.MaxValue": "3600"
    },
    "stMotion.nBrightness": {
      "iot.Unit": "lx",
      "iot.MinValue": "0",
      "iot.MaxValue": "1000"
    }
  },
  "ForceUpdate": false
}
```

### MQTT-Kommandos

Kommandos folgen dem bestehenden Rx/Data-Format:

Einschalten:
```json
{"Values": {"stWidgets.stMotion.bOn": true}}
```

Ausschalten:
```json
{"Values": {"stWidgets.stMotion.bOn": false}}
```

Nachlaufzeit ändern (600 Sekunden):
```json
{"Values": {"stWidgets.stMotion.nHoldTime": 600}}
```

Helligkeitsschwelle ändern (100 Lux):
```json
{"Values": {"stWidgets.stMotion.nBrightness": 100}}
```

Reichweite ändern (75%):
```json
{"Values": {"stWidgets.stMotion.nRange": 75}}
```

Empfindlichkeit ändern (50%):
```json
{"Values": {"stWidgets.stMotion.nSensitivity": 50}}
```

Modus ändern:
```json
{"Values": {"stWidgets.stMotion.sMode": "Test"}}
```

### Home Assistant Entity-Mapping

Das Motion-Widget wird über `WIDGET_MULTI_PLATFORM_MAP` auf mehrere HA-Plattformen verteilt:

```python
WIDGET_TYPE_MOTION = "Motion"

WIDGET_MULTI_PLATFORM_MAP[WIDGET_TYPE_MOTION] = [
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SELECT,
]
```

| HA-Plattform | Feld(er) | DeviceClass | Beschreibung |
|--------------|----------|-------------|--------------|
| `binary_sensor` | `bMotion` | `BinarySensorDeviceClass.MOTION` | Sensorstatus — Bewegung erkannt. |
| `binary_sensor` | `bActive` | `BinarySensorDeviceClass.OCCUPANCY` | Ausgang aktiv (nach PLC-Auswertung). |
| `switch` | `bOn` | `SwitchDeviceClass.SWITCH` | Ein/Aus / Übersteuerung. |
| `number` | `nHoldTime` | — | Nachlaufzeit (Slider, 0–3600 s). |
| `number` | `nBrightness` | — | Helligkeitsschwelle (Slider, 0–1000 lx). |
| `number` | `nRange` | — | Reichweite (Slider, 0–100 %). |
| `number` | `nSensitivity` | — | Empfindlichkeit (Slider, 0–100 %). |
| `sensor` | `nBattery` | `SensorDeviceClass.BATTERY` | Batteriestatus in % (wenn `iot.MotionBatteryVisible`). |
| `select` | `sMode` / `aModes` | — | Betriebsmodus-Auswahl (Auto, Manuell, Test, Aus). |
