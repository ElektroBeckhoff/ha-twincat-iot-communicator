# OAuth-Authentifizierung – Technische Anleitung

Dieses Dokument beschreibt den vollständigen OAuth-Authentifizierungsablauf der TwinCAT IoT Communicator Integration für Home Assistant. Es richtet sich an Systemintegratoren, die verstehen möchten, wie die Authentifizierung technisch umgesetzt ist und welche Werte dabei fest codiert sind.

---

## Übersicht

Die Integration unterstützt drei Authentifizierungsmethoden:

| Methode | Beschreibung |
|---------|-------------|
| **Ohne Authentifizierung** | Anonyme MQTT-Verbindung |
| **Benutzername / Passwort** | Klassische MQTT-Credentials im CONNECT-Paket |
| **Externes Login (OAuth / JWT)** | OAuth 2.0 Authorization Code Flow mit PKCE |

Bei der OAuth-Methode wird kein Passwort in Home Assistant gespeichert. Stattdessen meldet sich der Benutzer über einen externen Identity Provider (z.B. Keycloak) an und erhält ein JWT Access Token, das als MQTT-Passwort verwendet wird.

---

## Ablauf Schritt für Schritt

### 1. Benutzereingabe

Der Benutzer gibt im Config Flow zwei Werte ein:

| Feld | Beschreibung | Default |
|------|-------------|---------|
| **Issuer URL** | OIDC-Issuer-URL des Identity Providers | – (Pflichtfeld) |
| **Client ID** | Am Identity Provider registrierte Client-ID | `tc_iot_communicator` |

**Beispiel Issuer URL für Keycloak:**
```
https://auth.example.com/realms/myrealm
```

### 2. OIDC Discovery

Die Integration versucht automatisch, die OAuth-Endpoints zu ermitteln. Dazu werden nacheinander zwei URLs abgerufen (HTTP GET, Timeout 10 Sekunden):

1. `{issuer_url}/.well-known/openid-configuration`
2. `{issuer_url}/.well-known/oauth-authorization-server` (Fallback)

Aus der JSON-Antwort werden zwei Felder ausgelesen:

| Feld | Bedeutung |
|------|-----------|
| `authorization_endpoint` | URL der Login-Seite des Identity Providers |
| `token_endpoint` | URL zum Tauschen eines Authorization Codes gegen ein Token |

**Beide Endpoints gefunden:** → Authorization Code + PKCE Flow (Normalfall)
**Endpoints nicht gefunden:** → Fallback auf Direct Token Mode

### 3. Browser-Login (Authorization Code + PKCE)

Die Integration erzeugt lokal ein PKCE-Schlüsselpaar:

- **code_verifier**: 64 Byte zufällig, Base64url-kodiert
- **code_challenge**: SHA-256 des Verifiers, Base64url-kodiert (ohne Padding)

Anschließend wird der Browser mit folgender URL geöffnet:

```
GET {authorization_endpoint}
    ?response_type=code
    &client_id={client_id}
    &redirect_uri={ha_url}/auth/tc_iot/callback?flow_id={flow_id}
    &scope=openid
    &code_challenge={challenge}
    &code_challenge_method=S256
    &state={flow_id}
```

#### Fest codierte Werte im Authorization Request

| Parameter | Wert | Fest codiert |
|-----------|------|:------------:|
| `response_type` | `code` | Ja |
| `scope` | `openid` | Ja |
| `code_challenge_method` | `S256` | Ja |
| `state` | Config-Flow-ID von Home Assistant | Ja |
| `client_id` | Benutzereingabe (Default: `tc_iot_communicator`) | Nein |
| `redirect_uri` | `{ha_url}/auth/tc_iot/callback?flow_id={flow_id}` | Pfad ja |

Der Callback-Pfad `/auth/tc_iot/callback` ist fest codiert.

### 3b. Fallback: Direct Token Mode

Wenn die OIDC Discovery keine Endpoints findet, wird der Browser mit einer vereinfachten URL geöffnet:

```
GET {issuer_url}?redirect_uri={ha_url}/auth/tc_iot/callback?flow_id={flow_id}
```

Keine PKCE-Parameter. Der Auth-Server muss das JWT direkt in der Redirect-URL zurückliefern.

### 4. OAuth Callback

Der Identity Provider leitet den Browser zurück auf den Callback-Endpunkt. Die Integration akzeptiert drei Varianten:

| Variante | URL | Verarbeitung |
|----------|-----|-------------|
| **Authorization Code** | `?code={code}` | Code wird in Schritt 5 gegen Token getauscht |
| **Direktes Token** (Query) | `?access_token={jwt}` | JWT wird direkt übernommen |
| **Direktes Token** (Fragment) | `#access_token={jwt}` | JavaScript extrahiert Token aus dem URL-Fragment |

Bei der Fragment-Variante liefert der Callback eine HTML-Seite mit JavaScript aus, die das Token aus `window.location.hash` liest und als Query-Parameter weiterleitet.

### 5. Token Exchange (nur bei Authorization Code)

Bei Empfang eines Authorization Codes sendet die Integration einen HTTP POST an den `token_endpoint`:

```
POST {token_endpoint}
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={authorization_code}
&redirect_uri={redirect_uri}
&client_id={client_id}
&code_verifier={verifier}
```

#### Fest codierte Werte im Token Exchange

| Parameter | Wert | Fest codiert |
|-----------|------|:------------:|
| `grant_type` | `authorization_code` | Ja |
| `code` | Vom Callback empfangen | Nein |
| `redirect_uri` | Gleiche URI wie in Schritt 3 | Nein |
| `client_id` | Benutzereingabe | Nein |
| `code_verifier` | Lokal generierter PKCE-Verifier | Nein |

Aus der JSON-Antwort wird das Feld **`access_token`** gelesen.

### 6. JWT-Auswertung

Das empfangene JWT wird **lokal dekodiert** (Base64-Decode des Payload-Segments). Es findet **keine Signaturprüfung** statt – die Signaturvalidierung ist Aufgabe des MQTT-Brokers.

#### Ausgelesene JWT-Claims

| Claim | Verwendung | Pflicht |
|-------|-----------|:-------:|
| `preferred_username` | Wird als MQTT-Username verwendet | Ja* |
| `sub` | Fallback-Username, wenn `preferred_username` fehlt | Ja* |
| `exp` | Ablaufzeitpunkt (Unix-Timestamp in Sekunden) | Ja |

*Mindestens einer der beiden Claims `preferred_username` oder `sub` muss vorhanden sein.

#### Validierungen auf Client-Seite

- `preferred_username` oder `sub` muss vorhanden und nicht leer sein → sonst Abbruch
- `exp` darf nicht in der Vergangenheit liegen → sonst Abbruch
- Wenn `exp` fehlt, wird das Token als unbegrenzt gültig behandelt

### 7. Broker-Test

Nach der JWT-Auswertung testet die Integration die MQTT-Verbindung mit den neuen Credentials:

| MQTT-Feld | Wert |
|-----------|------|
| `username` | Claim `preferred_username` (Fallback: `sub`) |
| `password` | Vollständiges JWT (der gesamte `header.payload.signature`-String) |

Bei Erfolg wird der Setup-Flow fortgesetzt. Bei Fehler (`rc=5` = Auth rejected) wird abgebrochen.

### 8. MQTT-Verbindung im Betrieb

Im laufenden Betrieb verbindet sich die Integration mit dem Standard-MQTT-CONNECT-Paket:

```
MQTT CONNECT
  username = {preferred_username aus JWT}
  password = {vollständiges JWT}
  client_id = {UUID basierend auf Config-Entry-ID}
```

**Es wird kein HTTP-Header gesetzt.** Das JWT wird ausschließlich im MQTT-Passwort-Feld transportiert. Das ist die Standardkonvention für JWT-basierte MQTT-Authentifizierung.

### 9. Token-Ablauf und Re-Authentifizierung

Die Integration prüft den `exp`-Claim an drei Stellen:

| Zeitpunkt | Aktion bei abgelaufenem Token |
|-----------|-------------------------------|
| Start der Integration | Reauth-Flow auslösen, `ConfigEntryNotReady` |
| Vor jedem MQTT-Reconnect | Reauth-Flow auslösen, Reconnect-Loop stoppen |
| Broker antwortet mit `rc=5` | Reauth-Flow auslösen |

Beim Reauth-Flow wird der Benutzer erneut zum Identity Provider weitergeleitet und meldet sich dort an. Das neue JWT wird im Config Entry gespeichert und die Integration neu geladen.

---

## Zusammenfassung aller fest codierten Werte

### OIDC Discovery
| Wert | Beschreibung |
|------|-------------|
| `/.well-known/openid-configuration` | Primärer Discovery-Pfad |
| `/.well-known/oauth-authorization-server` | Fallback Discovery-Pfad |

### Authorization Request
| Parameter | Fest codierter Wert |
|-----------|-------------------|
| `response_type` | `code` |
| `scope` | `openid` |
| `code_challenge_method` | `S256` |

### Token Exchange
| Parameter | Fest codierter Wert |
|-----------|-------------------|
| `grant_type` | `authorization_code` |

### JWT-Claims
| Claim | Verwendung |
|-------|-----------|
| `preferred_username` | MQTT-Username (primär) |
| `sub` | MQTT-Username (Fallback) |
| `exp` | Token-Ablaufzeit |

### Token Exchange Response
| Feld | Verwendung |
|------|-----------|
| `access_token` | JWT für die MQTT-Verbindung |

### Callback
| Wert | Beschreibung |
|------|-------------|
| `/auth/tc_iot/callback` | OAuth-Callback-Pfad |

### Defaults
| Wert | Beschreibung |
|------|-------------|
| `tc_iot_communicator` | Standard Client-ID |

---

## Anforderungen an den Identity Provider

| Anforderung | Beschreibung |
|-------------|-------------|
| OIDC Discovery | `/.well-known/openid-configuration` muss erreichbar sein |
| Authorization Code Flow | Standard OAuth 2.0 Flow muss aktiviert sein |
| PKCE (S256) | Proof Key for Code Exchange muss unterstützt werden |
| Public Client | Kein Client Secret – der Client läuft auf Endgeräten |
| Redirect URI | Muss die jeweiligen Redirect URIs der Clients erlauben (siehe unten) |

## Redirect URIs konfigurieren

Im Identity Provider (z.B. Keycloak) werden Redirect URIs pro Client konfiguriert. Jeder Client, der sich über OAuth anmelden soll, benötigt eine eigene Redirect URI. Alle URIs werden beim **selben** Client hinterlegt — nicht als separate Clients.

### Home Assistant

```
https://<ha-host>:8123/auth/tc_iot/callback*
```

Der Pfad `/auth/tc_iot/callback` ist fest codiert. Der Wildcard `*` am Ende ist nötig, damit Keycloak den angehängten `?flow_id=...` Query-Parameter akzeptiert.

Wird Home Assistant über verschiedene Adressen erreicht (z.B. LAN-IP und externer DNS), muss **jede Adresse** als eigene Redirect URI eingetragen werden:

```
https://192.168.1.100:8123/auth/tc_iot/callback*
https://ha.local:8123/auth/tc_iot/callback*
https://ha.example.com/auth/tc_iot/callback*
```

### Native App (iOS / Android)

Für native Apps (z.B. die TwinCAT IoT Communicator App) wird ein **Custom URI Scheme** als Redirect URI verwendet, da kein Webserver für den Callback existiert. Die App registriert das URI Scheme im Betriebssystem und fängt den Redirect nach dem Login ab.

```
tciot://auth/callback
```

Die App öffnet den Login über den **Systembrowser** (nicht einen eingebetteten WebView) — das ist die Empfehlung aus RFC 8252 (OAuth 2.0 for Native Apps) und wird von Keycloak unterstützt.

### Beispiel: Beide Clients in einem Keycloak-Client

Alle Redirect URIs werden im selben Keycloak-Client unter *Valid redirect URIs* eingetragen:

```
https://192.168.1.100:8123/auth/tc_iot/callback*
https://ha.local:8123/auth/tc_iot/callback*
tciot://auth/callback
```

Bestehende URIs bleiben erhalten — neue werden einfach über *Add* hinzugefügt.

> **Hinweis:** Keycloak erlaubt Wildcards (`*`) nur am **Ende** einer URI. Wildcards im Host- oder Port-Teil (z.B. `https://*/auth/...`) sind nicht möglich. Das ist eine OIDC-Sicherheitsvorgabe zum Schutz vor Open-Redirect-Angriffen.

## Anforderungen an den MQTT-Broker

| Anforderung | Beschreibung |
|-------------|-------------|
| JWT als Passwort | Das vollständige JWT muss als MQTT-Passwort akzeptiert werden |
| Signaturprüfung | Der Broker muss die JWT-Signatur gegen den Public Key des Identity Providers validieren (JWKS) |
| Ablaufprüfung | Der Broker muss den `exp`-Claim prüfen und abgelaufene Tokens ablehnen |
