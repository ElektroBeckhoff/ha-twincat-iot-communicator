# Feature Request: Pump-Widget — Pumpensteuerung mit Modus, Drehzahl und Betriebsdaten

## Zusammenfassung

Neues **Pump-Widget** im TwinCAT IoT Communicator (TF6730 / TF6735) zur Visualisierung und Steuerung von Pumpen. Zeigt Status, Drehzahl, Betriebsstunden, Schaltzyklen sowie Anforderungs- und Blockierschutzmodus an. Unterstützt Auto/Hand-Umschaltung und manuelle Drehzahlvorgabe.

## Zustände

| Zustand | Status-Text | Indikator | Modus | Drehzahl |
|---------|-------------|-----------|-------|----------|
| Aus (Auto) | `Aus` | Grau | Auto | 0 RPM |
| Ein (Auto) | `Ein` | Grün | Auto | > 0 RPM |
| Handbetrieb Ein | `Handbetrieb Ein` | Orange | Hand Ein | > 0 RPM |
| Handbetrieb Aus | `Handbetrieb Aus` | Orange | Hand Aus | 0 RPM |

## Value-Felder

| Feld | Datentyp | Richtung | Beschreibung |
|------|----------|----------|--------------|
| `sDisplayName` | STRING | PLC → App | Anzeigename des Widgets. |
| `bOn` | BOOL | PLC → App | Pumpenstatus Ein/Aus. |
| `bEnabled` | BOOL | Bidirektional | Pumpe für automatische Anforderung freigegeben. |
| `bManualMode` | BOOL | PLC → App | Handbetrieb aktiv (true/false). |
| `nSpeed` | REAL | Bidirektional | Aktuelle Drehzahl in RPM. |
| `nOperatingHours` | REAL | PLC → App | Gesamtlaufzeit der Pumpe in Stunden. |
| `nSwitchCount` | INT | PLC → App | Anzahl der Ein/Aus-Schaltvorgänge. |
| `sMode` | STRING | PLC → App | Aktueller Modus (z.B. `Auto`, `Hand Ein`, `Hand Aus`). |
| `aModes` | ARRAY OF STRING | PLC → App | Verfügbare Modi. |
| `sRequestMode` | STRING | Bidirektional | Aktueller Anforderungsmodus. |
| `aRequestModes` | ARRAY OF STRING | PLC → App | Verfügbare Anforderungsmodi. |
| `sAntiBlockingMode` | STRING | Bidirektional | Aktueller Blockierschutzmodus. |
| `aAntiBlockingModes` | ARRAY OF STRING | PLC → App | Verfügbare Blockierschutzmodi. |

## Hinweise

- **Pumpe freigegeben**: Pumpe für automatische Anforderung freigeben.
- **Handbetrieb**: Manuelle Steuerung der Pumpe (Ein/Aus und Drehzahl).
- **Drehzahl**: Aktuelle Drehzahl in RPM.
- **Betriebsstunden**: Gesamtlaufzeit der Pumpe in Stunden.
- **Schaltzyklen**: Anzahl der Ein/Aus-Schaltvorgänge.
- **Anforderungsmodus**: Bedingung für die Automatik.
- **Blockierschutzmodus**: Verhindert Blockierung bei Stillstand.

## Beispiel JSON

```json
{
  "Timestamp": "2026-04-21T10:00:00.000",
  "GroupName": "Homeassistant",
  "Values": {
    "stPump": {
      "sDisplayName": "Fully Featured Pump Widget",
      "bOn": false,
      "bEnabled": false,
      "bManualMode": false,
      "nSpeed": 0.0,
      "nOperatingHours": 0.0,
      "nSwitchCount": 0,
      "sMode": "Auto",
      "aModes": ["Auto", "Hand Aus", "Hand Ein"],
      "sRequestMode": "keine Automatik",
      "aRequestModes": [
        "keine Automatik",
        "Wit T > Niedrig Limit",
        "Wit T > Hoch Limit",
        "Ventil > Hoch Limit",
        "Wit T > Niedrig Limit oder Ventil > Hoch Limit",
        "Wit T > Hoch Limit oder Ventil > Hoch Limit",
        "Wit T > Niedrig und Ventil > Hoch Limit",
        "Wit T > Hoch Limit und Ventil > Hoch Limit"
      ],
      "sAntiBlockingMode": "Aus",
      "aAntiBlockingModes": ["Aus", "Stillstandszeit", "Woechentlich"]
    }
  },
  "MetaData": {
    "stPump": {
      "iot.DisplayName": "Fully Featured Pump Widget",
      "iot.ReadOnly": "false",
      "iot.WidgetType": "Pump"
    },
    "stPump.nSpeed": {
      "iot.Unit": "RPM",
      "iot.MinValue": "0",
      "iot.MaxValue": "3000"
    }
  },
  "ForceUpdate": false
}
```
