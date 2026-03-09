# Feature Request: Lock-Widget für TwinCAT IoT Communicator

## Zusammenfassung

Erweiterung des TwinCAT IoT Communicator (TF6730 / TF6735) um ein **Lock-Widget** zur Darstellung und Steuerung von Türschlössern, Zutrittssystemen und Verriegelungen in der Gebäudeautomation.

## Vorgeschlagener Widget-Typ: `Lock`

### PLC-Attribute

```
{attribute 'iot.ReadOnly' := 'false'}
{attribute 'iot.DisplayName' := 'Name for Widget'}
{attribute 'iot.WidgetType' := 'Lock'}
{attribute 'iot.LockWidgetIcon' := 'Lock'}
{attribute 'iot.LockLockVisible' := 'true'}
{attribute 'iot.LockUnlockVisible' := 'true'}
{attribute 'iot.LockOpenVisible' := 'true'}
{attribute 'iot.LockJammedVisible' := 'true'}
{attribute 'iot.LockStateVisible' := 'true'}
{attribute 'iot.LockModeVisible' := 'true'}
{attribute 'iot.LockModeChangeable' := 'true'}
stLockWidgetSample : ST_LockWidgetSample;
```

| Attribut | Datentyp | Beschreibung |
|----------|----------|--------------|
| `iot.ReadOnly` | BOOL | Nur-Lese-Zugriff (`TRUE`) oder auch Schreibzugriff (`FALSE`). |
| `iot.DisplayName` | STRING | Anzeigename des Widgets in der App. Wird durch `sDisplayName` überschrieben. |
| `iot.WidgetType` | STRING | Typ-Bezeichnung: `Lock`. |
| `iot.LockWidgetIcon` | STRING | Icon-Name (z.B. `Lock`, `Unlock`, `Key`, `Door_Closed`). |
| `iot.LockLockVisible` | BOOL | Verriegeln-Button sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). Entspricht `bEnableLock` im FB. |
| `iot.LockUnlockVisible` | BOOL | Entriegeln-Button sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). Entspricht `bEnableUnlock` im FB. |
| `iot.LockOpenVisible` | BOOL | Tür-Öffner-Button (E-Öffner/Summer) sichtbar (`TRUE`) oder ausgeblendet (`FALSE`). Entspricht `bEnableOpen` im FB. |
| `iot.LockJammedVisible` | BOOL | Klemmt-Status anzeigen (`TRUE`) oder nicht (`FALSE`). |
| `iot.LockStateVisible` | BOOL | Status-Text (`sState`: Locked, Unlocking, Jammed etc.) anzeigen (`TRUE`) oder nicht (`FALSE`). |
| `iot.LockModeVisible` | BOOL | Betriebsmodus anzeigen (`TRUE`) oder nicht (`FALSE`). |
| `iot.LockModeChangeable` | BOOL | Betriebsmodus änderbar (`TRUE`) oder nicht (`FALSE`). |

### PLC-Strukturdefinition

```
TYPE ST_LockWidgetSample :
STRUCT
    sDisplayName    : STRING := '';
    bLock           : BOOL := FALSE;  // Befehle (App → PLC, momentary)
    bUnlock         : BOOL := FALSE;  // Befehle (App → PLC, momentary)
    bOpen           : BOOL := FALSE;  // Befehle (App → PLC, momentary)
    bLocked         : BOOL := TRUE; // Feedback (PLC → App, read-only)
    bOpened         : BOOL := FALSE; // Feedback (PLC → App, read-only)
    bJammed         : BOOL := FALSE; // Feedback (PLC → App, read-only)
    sState          : STRING := 'Locked';
    sMode           : STRING := 'Auto'; // Modi
    aModes          : ARRAY[0..2] OF STRING := ['Auto', 'Manuell', 'Nacht'];
END_STRUCT
END_TYPE
```

| Feld | Datentyp | Richtung | Beschreibung | Anzeige im Widget |
|------|----------|----------|--------------|-------------------|
| `sDisplayName` | STRING | — | Anzeigename, überschreibt `iot.DisplayName`. | Titel des Widgets. |
| `bLock` | BOOL | App → PLC | Verriegeln-Befehl (momentary). | Lock-Button (wenn `iot.LockLockVisible`). |
| `bUnlock` | BOOL | App → PLC | Entriegeln-Befehl (momentary). | Unlock-Button (wenn `iot.LockUnlockVisible`). |
| `bOpen` | BOOL | App → PLC | Tür-Öffner-Befehl (E-Öffner, Summer, momentary). | Öffnen-Button (wenn `iot.LockOpenVisible`). |
| `bLocked` | BOOL | PLC → App | Schloss verriegelt (`TRUE`) oder entriegelt (`FALSE`). Read-only. | Schloss-Symbol / Status-Anzeige. |
| `bOpened` | BOOL | PLC → App | Tür geöffnet (`TRUE`) oder geschlossen (`FALSE`). Read-only. | Status-Zeile: "Offen" / "Geschlossen" (wenn `iot.LockOpenVisible`). |
| `bJammed` | BOOL | PLC → App | Schloss verklemmt (`TRUE`). Read-only. | Warnsymbol (wenn `iot.LockJammedVisible`). |
| `sState` | STRING | PLC → App | Aktueller Zustand (`Locked`, `Unlocking`, `Jammed` etc.). Read-only. | Status-Text (wenn `iot.LockStateVisible`). |
| `sMode` | STRING | Bidirektional | Aktueller Betriebsmodus. | Modus-Anzeige unten. |
| `aModes` | ARRAY [0..n] OF STRING | PLC → App | Verfügbare Modi. | Modus-Auswahl per Tippen. |


### Beispiel JSON (Full-Feature)

```json
{
  "Timestamp": "2026-02-19T08:46:23.247",
  "GroupName": "Homeassistant",
  "Values": {
    "stLock": {
      "sDisplayName": "Haustür",
      "bLock": false,
      "bUnlock": false,
      "bOpen": false,
      "bLocked": true,
      "bOpened": false,
      "bJammed": false,
      "sState": "Locked",
      "sMode": "Auto",
      "aModes": [
        "Auto",
        "Manuell",
        "Nacht"
      ]
    }
  },
  "MetaData": {
    "stLock": {
      "iot.DisplayName": "Haustür",
      "iot.ReadOnly": "false",
      "iot.WidgetType": "Lock",
      "iot.LockWidgetIcon": "Lock",
      "iot.LockLockVisible": "true",
      "iot.LockUnlockVisible": "true",
      "iot.LockOpenVisible": "true",
      "iot.LockStateVisible": "true",
      "iot.LockJammedVisible": "true",
      "iot.LockModeVisible": "true",
      "iot.LockModeChangeable": "true",
      "iot.PermittedUsers": "*"
    }
  },
  "ForceUpdate": false
}
```

### MQTT-Kommandos

Kommandos folgen dem bestehenden Rx/Data-Format:

Verriegeln:
```json
{"Values": {"stWidgets.stLock.bLock": true}}
```

Entriegeln:
```json
{"Values": {"stWidgets.stLock.bUnlock": true}}
```

Tür öffnen:
```json
{"Values": {"stWidgets.stLock.bOpen": true}}
```

Modus ändern:
```json
{"Values": {"stWidgets.stLock.sMode": "Nacht"}}
```
