# Feature Request: RGBW-Widget Erweiterung — Native RGB + PLC Color Mode

## Zusammenfassung

Erweiterung des bestehenden **RGBW-Widgets** im TwinCAT IoT Communicator (TF6730 / TF6735) um **native RGB-Kanäle** und einen **PLC-gemeldeten Farbmodus** (`nColorMode`). Eliminiert HS↔RGB Rundungsfehler und client-seitiges Color-Mode-Raten.

## Neue Felder (additiv zum bestehenden RGBW)

### Neues PLC-Attribut

```
{attribute 'iot.LightColorPaletteMode' := 'HS'} oder {attribute 'iot.LightColorPaletteMode' := 'RGB'}
```

| Attribut | Wert | Beschreibung |
|----------|------|--------------|
| `iot.LightColorPaletteMode` | `HS` oder fehlend | `nHueValue` + `nSaturation` werden gelesen/gesendet (Default). |
| `iot.LightColorPaletteMode` | `RGB` | `nRed`, `nGreen`, `nBlue` werden gelesen/gesendet. |


### Neue Value-Felder

| Feld | Datentyp | Richtung | Beschreibung |
|------|----------|----------|--------------|
| `nRed` | INT (0–255) | Bidirektional | Rot-Kanal (nativ). |
| `nGreen` | INT (0–255) | Bidirektional | Grün-Kanal (nativ). |
| `nBlue` | INT (0–255) | Bidirektional | Blau-Kanal (nativ). |
| `nColorMode` | INT (Bitmask) | PLC → App | Aktiver Farbmodus, von der SPS gemeldet. |

### `nColorMode` Bitmask

Wird nur ausgewertet wenn `nColorMode` im JSON vorhanden ist.

| Bit | Wert | Beschreibung |
|-----|------|--------------|
| 0 | 1 | `bLight` getoggelt. Keine visuelle Auswirkung auf Slider/Picker. |
| 1 | 2 | `nLight` geändert. Keine visuelle Auswirkung auf Slider/Picker. |
| 2 | 4 | `nColorTemperature` aktiv — Farbtemperatur-Slider wird aktiv angezeigt, Farbpalette grau. |
| 3 | 8 | `nHueValue` + `nSaturation` aktiv — Farbpalette wird aktiv angezeigt (HS-Picker), Farbtemperatur-Slider grau. |
| 4 | 16 | `nRed` + `nGreen` + `nBlue` aktiv — Farbpalette wird aktiv angezeigt (RGB-Picker), Farbtemperatur-Slider grau. |
| 5 | 32 | `nWhite` geändert. Keine visuelle Auswirkung auf Slider/Picker. |
| 4+5 | 48 | `nRed` + `nGreen` + `nBlue` + `nWhite` aktiv — Farbpalette wird aktiv angezeigt (RGBW), Farbtemperatur-Slider grau. |

### Beispiel JSON (RGBW Future)

```json
{
  "Timestamp": "2026-02-19T08:46:23.247",
  "GroupName": "Homeassistant",
  "Values": {
    "stRGBW": {
      "sDisplayName": "Dusche Himmel",
      "bLight": false,
      "nLight": 0,
      "nHueValue": 0,
      "nSaturation": 100,
      "nRed": 0,
      "nGreen": 0,
      "nBlue": 0,
      "nWhite": 0,
      "nColorTemperature": 2000,
      "nColorMode": 0,
      "sMode": "Raumszenen",
      "aModes": [
        "Raumszenen",
        "Keine Szenen",
        "Szene 1",
        "Szene 2",
        "Szene 3",
        "Szene 4",
        "Szene 5"
      ]
    }
  },
  "MetaData": {
    "stRGBW": {
      "iot.DisplayName": "Dusche Himmel",
      "iot.ReadOnly": "false",
      "iot.WidgetType": "RGBW",
      "iot.LightValueVisible": "true",
      "iot.LightSliderVisible": "true",
      "iot.LightColorPaletteVisible": "true",
      "iot.LightColorPaletteMode": "RGB",
      "iot.LightColorTemperatureSliderVisible": "false",
      "iot.LightWhiteSliderVisible": "false",
      "iot.LightModeVisible": "true",
      "iot.LightModeChangeable": "true",
      "iot.PermittedUsers": "*"
    },
    "stRGBW.nLight": {
      "iot.Unit": "%",
      "iot.MinValue": "0",
      "iot.MaxValue": "100"
    },
    "stRGBW.nColorTemperature": {
      "iot.MinValue": "2000",
      "iot.MaxValue": "6500"
    }
  },
  "ForceUpdate": false
}
```
