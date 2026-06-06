# OAuth Backend Configuration for MQTT JWT Authentication

## Overview

The TwinCAT IoT Communicator ecosystem (TF6730 – TF6735) supports username/password authentication as defined in the MQTT 3.1.1 specification. This existing mechanism remains fully operational for all current clients — in particular, the **TwinCAT PLC** continues to authenticate with a static username and password.

The OAuth 2.0 / JWT extension described in this document adds a **second, parallel authentication path** exclusively for the **IoT Communicator App**. An external Identity Provider (IdP) issues short-lived JWTs that the MQTT broker validates instead of a static password. Both authentication methods coexist on the same broker; the broker tries JWT validation first and falls back to the classic password check if the credential is not a valid JWT.

### Authentication Scope

| Client | Authentication Method | Change Required |
|---|---|---|
| **TwinCAT PLC** (`FB_IotCommunicator` / `FB_IotMqttClient`) | Static username + password (unchanged) | None |
| **IoT Communicator App** (iOS / Android / HA Integration) | OAuth 2.0 Authorization Code + PKCE → JWT | New — described in this document |
| **Other MQTT clients** (scripts, 3rd-party tools) | Static username + password (unchanged) | None |

This document describes how to configure the authentication backend so that:

1. The **Identity Provider** issues JWT access tokens via OAuth 2.0 Authorization Code + PKCE.
2. The **MQTT broker** validates JWT-based connections from the App **and** continues to accept static credentials from the PLC and other clients.
3. The **IoT Communicator App** authenticates via the browser, obtains a JWT, and connects with `username` = claim from JWT and `password` = full JWT string.

The reference implementation uses **Keycloak**, but any OIDC-compliant Identity Provider that supports the Authorization Code flow with PKCE and issues signed JWTs (RS256 or ES256) will work — e.g. Auth0, Azure AD / Entra ID, Authentik, or Zitadel.

---

## Architecture

The MQTT broker supports **two parallel authentication paths**. The PLC and other existing clients continue to use static credentials. Only the App authenticates via OAuth/JWT.

```
                       ┌────────────────────────────┐
                       │      MQTT Broker            │
                       │  (Mosquitto / EMQX / HiveMQ)│
                       │                            │
┌─────────────┐        │  Auth Chain:               │        ┌──────────────┐
│  TwinCAT PLC│  MQTT  │  1. JWT validation          │        │  Identity    │
│  (Tc3_IoT-  │───────►│     - Signature (JWKS)     │◄───────│  Provider    │
│  Communicator│ user+  │     - exp / iss / aud      │  JWKS  │  (Keycloak)  │
│  Library)   │ pass   │  2. Static user/password    │        │              │
└─────────────┘        │     (fallback)              │        │  Issues JWT  │
                       │                            │        │  via OIDC    │
┌─────────────┐  MQTT  │                            │        │              │
│  IoT Comm.  │───────►│                            │        └──────────────┘
│  App / HA   │ user+  └────────────────────────────┘               ▲
│  Integration│ JWT                                                 │
└─────────────┘                                                     │
       │                                                            │
       └──────────── OAuth 2.0 AuthCode + PKCE ────────────────────┘
```

| Path | Client | Password Field | Broker Behavior |
|---|---|---|---|
| JWT (primary) | IoT Communicator App | Full JWT string | Validates signature, `exp`, `iss` via JWKS |
| Static (fallback) | TwinCAT PLC, scripts, tools | Plain password | Classic username/password check |

---

## 1. Identity Provider Configuration

### 1.1 General Requirements

| Requirement | Description |
|---|---|
| OIDC Discovery | `/.well-known/openid-configuration` must be reachable and return `authorization_endpoint` + `token_endpoint` |
| Authorization Code Flow | Standard OAuth 2.0 Authorization Code flow must be enabled |
| PKCE (S256) | Proof Key for Code Exchange with SHA-256 challenge method |
| Public Client | No client secret — the client runs on end-user devices |
| JWT Signing | RS256 (RSA) or ES256 (ECDSA) — the broker must support the chosen algorithm |
| JWKS Endpoint | `jwks_uri` must be published so the broker can fetch the public keys |

### 1.2 Keycloak Configuration

#### Create a Realm

1. Open the Keycloak Admin Console (`https://<keycloak-host>/admin`).
2. Create a new Realm (e.g. `my-iot-portal`) or use an existing one.
3. The **Issuer URL** will be: `https://<keycloak-host>/realms/<realm-name>`

#### Create a Client

1. Navigate to **Clients → Create client**.
2. Configure the following settings:

| Setting | Value |
|---|---|
| Client ID | `tc_iot_communicator` (or any name you choose) |
| Client type | **OpenID Connect** |
| Client authentication | **Off** (= public client, no client secret) |
| Authentication flow | Enable **Standard flow** (Authorization Code) |
| Root URL | *(leave empty)* |
| Valid redirect URIs | See section 1.3 |
| Web origins | `+` (allows all origins from redirect URIs) |

3. Under **Advanced → Proof Key for Code Exchange Code Challenge Method**, select **S256**.

#### Token Settings

Under **Clients → \<your-client\> → Settings → Advanced**:

| Setting | Recommended Value | Description |
|---|---|---|
| Access Token Lifespan | 5–60 minutes | Short-lived tokens reduce risk if compromised |
| Client Session Idle | 0 | Disable session idle timeout for headless flows |

#### Required JWT Claims

The following claims must be present in the issued access token:

| Claim | Source in Keycloak | Used as |
|---|---|---|
| `preferred_username` | User attribute (default mapper) | MQTT username |
| `sub` | Auto-generated | Fallback MQTT username |
| `exp` | Auto-generated | Token expiration (Unix timestamp) |

**Verify** that `preferred_username` is included in the access token:
1. Go to **Clients → \<your-client\> → Client scopes → \<client-id\>-dedicated**.
2. Check that a mapper for `preferred_username` exists and is configured for **Add to access token = On**.
3. If missing, add a mapper: **Type** = User Attribute, **User Attribute** = `username`, **Token Claim Name** = `preferred_username`.

### 1.3 Redirect URIs

All redirect URIs are configured in the **same** client under **Valid redirect URIs**. Each client application that authenticates via OAuth needs its own entry.

#### Home Assistant Integration

```
https://<ha-host>:8123/auth/tc_iot/callback
```

The path `/auth/tc_iot/callback` is hardcoded in the integration. The `flow_id` is transmitted via the OAuth `state` parameter, not as a query parameter appended to the redirect URI. No wildcards are needed — the URI must match exactly (RFC 9700).

If Home Assistant is reachable via multiple addresses, each one must be registered:

```
https://192.168.1.100:8123/auth/tc_iot/callback
https://ha.local:8123/auth/tc_iot/callback
https://ha.example.com/auth/tc_iot/callback
```

#### Test Script (Test-OAuthMqttFlow.ps1)

```
http://localhost:8123/auth/tc_iot/callback
```

Adjust the port if you use `-CallbackPort` with a different value.

#### Native App (iOS / Android)

```
tciot://auth/callback
```

The app uses a custom URI scheme as recommended by RFC 8252 (OAuth 2.0 for Native Apps).

> **Note:** Redirect URIs must match exactly (RFC 9700). Wildcards are not needed and are not recommended for security reasons.

### 1.4 User Management

1. Navigate to **Users → Add user**.
2. Set a username and email.
3. Under **Credentials**, set a password (temporary or permanent).
4. The `preferred_username` from the JWT will match the Keycloak username.

### 1.5 Using a Different Identity Provider

The configuration steps above are Keycloak-specific, but the **requirements** are universal:

| Provider | Notes |
|---|---|
| **Auth0** | Create a "Regular Web Application" with PKCE enabled. Add redirect URIs under "Allowed Callback URLs". Ensure `preferred_username` or `sub` is in the access token. |
| **Azure AD / Entra ID** | Register an App Registration as a public client. Configure redirect URIs under "Authentication". The `preferred_username` claim is included by default. |
| **Authentik** | Create an OAuth2/OIDC Provider with "Authorization Code + PKCE" flow. Add redirect URIs in the provider settings. |
| **Zitadel** | Create a project and application with PKCE support. Configure redirect URIs. Map username to `preferred_username`. |

**Checklist for any provider:**
- [ ] OIDC Discovery endpoint reachable
- [ ] Authorization Code + PKCE (S256) enabled
- [ ] Public client (no client secret)
- [ ] `preferred_username` or `sub` claim in access token
- [ ] `exp` claim in access token
- [ ] JWKS endpoint published
- [ ] Redirect URIs registered

---

## 2. MQTT Broker Configuration

The MQTT broker must support **two authentication methods simultaneously**:

1. **JWT validation** — for the IoT Communicator App (password field contains a JWT).
2. **Static username/password** — for the TwinCAT PLC and other existing clients.

The broker tries JWT validation first. If the password is not a valid JWT (i.e. not a three-part `header.payload.signature` string), it falls back to classic credential checking. This way, existing PLC connections remain unaffected.

### 2.1 General Requirements

| Requirement | Description |
|---|---|
| Dual auth support | The broker must chain JWT validation with a static password backend (see broker-specific sections below) |
| JWT as password | Accept the full JWT string in the MQTT password field (App connections) |
| Static credentials | Continue accepting classic username/password pairs (PLC connections) |
| Signature validation | Validate the JWT signature against the IdP's public keys (JWKS) |
| Expiration check | Reject tokens where `exp` is in the past |
| Issuer check (recommended) | Verify the `iss` claim matches the expected Issuer URL |
| Audience check (optional) | Verify the `aud` claim if the IdP sets it |

### 2.2 Mosquitto with mosquitto-jwt-auth

[mosquitto-jwt-auth](https://github.com/wiomoc/mosquitto-jwt-auth) is a plugin that validates JWTs for Mosquitto.

Mosquitto 2.x supports **chaining multiple auth plugins**. The JWT plugin handles App connections; the built-in password file handles PLC and other static-credential connections. If the JWT plugin returns `MOSQ_ERR_PLUGIN_DEFER` (credential is not a JWT), Mosquitto proceeds to the next auth backend.

**mosquitto.conf:**

```
listener 8884
protocol mqtt
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key

# Auth chain: JWT first, then static passwords
auth_plugin /usr/lib/mosquitto-jwt-auth.so
auth_opt_jwt_jwks_url https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs
auth_opt_jwt_validate_exp true
auth_opt_jwt_validate_iss https://<keycloak-host>/realms/<realm>

# Static password fallback for PLC and other clients
password_file /etc/mosquitto/passwd
```

| Parameter | Description |
|---|---|
| `auth_opt_jwt_jwks_url` | JWKS endpoint of the Identity Provider (found in OIDC Discovery under `jwks_uri`) |
| `auth_opt_jwt_validate_exp` | Enable expiration validation |
| `auth_opt_jwt_validate_iss` | Expected issuer — must match the `iss` claim in the JWT |
| `password_file` | Static credentials for PLC and other non-OAuth clients (created with `mosquitto_passwd`) |

> **Note:** The PLC connects with its existing username/password pair via the `password_file`. No changes to the PLC configuration are required when adding JWT support for the App.

### 2.3 EMQX with JWT Authentication

EMQX has built-in JWT authentication support. EMQX evaluates the `authentication` array **in order** — the first backend that returns a definitive accept/reject wins. If the JWT backend returns `ignore` (password is not a JWT), the next backend handles the request.

**emqx.conf (or via Dashboard → Authentication):**

```hocon
authentication = [
  # 1. JWT backend for App connections
  {
    mechanism = jwt
    from = password
    use_jwks = true
    endpoint = "https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs"
    verify_claims = {
      iss = "https://<keycloak-host>/realms/<realm>"
    }
    ssl {
      enable = true
      verify = verify_peer
    }
  },
  # 2. Static password backend for PLC and other clients
  {
    mechanism = password_based
    backend = built_in_database
  }
]
```

| Parameter | Description |
|---|---|
| `from` | Where to read the JWT from — `password` means the MQTT password field |
| `use_jwks` | Fetch public keys from the JWKS endpoint |
| `endpoint` | JWKS URI |
| `verify_claims.iss` | Expected issuer claim |
| `built_in_database` | EMQX internal user store for static PLC credentials |

### 2.4 HiveMQ with Enterprise Security Extension

HiveMQ Enterprise supports JWT validation via the Security Extension (ESE). The ESE evaluates JWT first; if the credential is not a JWT, it falls back to the configured file-based or database-backed credential store.

**ese-config.xml:**

```xml
<ese>
  <!-- JWT authentication for App connections -->
  <jwt-auth>
    <jwks-endpoint>https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs</jwks-endpoint>
    <jwt-source>mqtt-password</jwt-source>
    <required-claims>
      <claim name="iss" value="https://<keycloak-host>/realms/<realm>"/>
    </required-claims>
    <validate-expiry>true</validate-expiry>
  </jwt-auth>

  <!-- Static credentials for PLC and other clients -->
  <file-auth>
    <file-path>/opt/hivemq/conf/credentials.xml</file-path>
  </file-auth>
</ese>
```

---

## 3. TwinCAT PLC Configuration (Unchanged)

> **The PLC does not use OAuth.** It continues to authenticate with a static username and password via the broker's classic credential store. No changes to the PLC program are required when adding OAuth support for the App.

### 3.1 FB_IotCommunicator (Tc3_IotCommunicator)

The `FB_IotCommunicator` function block connects to the MQTT broker using static credentials:

```
fbCommunicator.sHostName := 'mqtt.example.com';
fbCommunicator.nPort     := 8884;
fbCommunicator.sUser     := 'plc_user';
fbCommunicator.sPassword := 'static_password';
fbCommunicator.stTls.sCA := 'C:\TwinCAT\3.1\Config\Certificates\ca.pem';
```

| Input | Type | Description |
|---|---|---|
| `sUser` | `STRING` | Static MQTT username (configured in broker `password_file` or built-in database) |
| `sPassword` | `STRING` | Static MQTT password |
| `stTls` | `ST_IotCommunicatorTls` | TLS configuration — **required** to protect credentials in transit |

> **Important:** The MQTT specification transmits username and password in **plain text** unless TLS is enabled. Always use TLS (port 8883/8884).

### 3.2 FB_IotMqttClient (Tc3_IotBase)

If using `FB_IotMqttClient` directly instead of the Communicator wrapper:

```
fbMqttClient.sHostName     := 'mqtt.example.com';
fbMqttClient.nHostPort     := 8884;
fbMqttClient.sUserName     := 'plc_user';
fbMqttClient.sUserPassword := 'static_password';
fbMqttClient.stTLS.sCA     := 'C:\TwinCAT\3.1\Config\Certificates\ca.pem';
fbMqttClient.stTLS.sVersion := 'tlsv1.2';
```

| Input | Type | Description |
|---|---|---|
| `sUserName` | `STRING(255)` | Static MQTT username |
| `sUserPassword` | `STRING(255)` | Static MQTT password |
| `stTLS` | `ST_IotMqttTls` | TLS settings including CA certificate path |

### 3.3 ST_IotCommunicatorTls

```
TYPE ST_IotCommunicatorTls :
STRUCT
    eVersion           : E_IotCommunicatorTlsVersion := tlsv1_2;
    sCA                : STRING(255);  // CA certificate (PEM/DER file or PEM string)
    sCert              : STRING(255);  // Client certificate (optional)
    sKeyFile           : STRING(255);  // Client private key (optional)
    sKeyPwd            : STRING(255);  // Private key password
    bNoServerCertCheck : BOOL;         // FALSE = validate server cert (default)
END_STRUCT
END_TYPE
```

| Parameter | Description |
|---|---|
| `sCA` | Path to the CA certificate that signed the broker's server certificate |
| `bNoServerCertCheck` | Set to `TRUE` only for testing — **never in production** |

### 3.4 Future Considerations

The PLC currently uses static credentials and is **not affected** by the OAuth extension.

**TODO — Future features:**

- [ ] **Refresh Token support:** The current implementation requires a full browser re-login when the access token expires. A future version should use OAuth 2.0 Refresh Tokens (RFC 6749 Section 6) to silently renew access tokens without user interaction. This requires changes in the App, HA integration (`config_flow.py`), and IdP configuration (Keycloak: enable Refresh Token Rotation).
- [ ] **JWT on the PLC:** In a future iteration, the PLC could authenticate via JWT using `FB_JwtEncode` from `Tc3_JsonXml` to create and sign tokens directly.

---

## 4. IoT Communicator App Configuration (OAuth)

The IoT Communicator App is the **only client** that authenticates via OAuth 2.0 / JWT. After a successful browser login, the App receives a JWT and uses it as the MQTT password.

### 4.1 Connection Settings

In the IoT Communicator App, configure the following under **Settings → Connection**:

| Setting | Value |
|---|---|
| Broker Address | Hostname or IP of the MQTT broker |
| Port | TLS port (e.g. `8884`) |
| Topic | Main topic matching the PLC `sMainTopic` |
| Authentication | **OAuth / JWT** (the App handles login and token exchange automatically) |
| Encryption | TLS v1.2 |
| CA certificate | CA certificate file (PEM format) |
| Skip Server Certificate Validation | **Off** (in production) |

The username and password fields are populated automatically by the OAuth flow — the user does not enter static credentials.

### 4.2 QR Code for Connection

Connection parameters can be distributed via QR code. When using OAuth, the QR code contains the **broker** and **OAuth settings** but **not** the JWT itself (the token is obtained at runtime via the browser login):

```
https://iotdemo.beckhoff.com/app?&broker=mqtt.example.com&port=8884&topic=TOPICNAME&auth=oauth&issuer=https://auth.example.com/realms/my-realm&client_id=tc_iot_communicator&tls=TLSv1_2
```

> **Security note:** Do not embed JWTs in QR codes. The QR code should only contain the connection and OAuth parameters; the actual token is obtained through the browser-based login flow on the device.

---

## 5. Verification

### 5.1 Test Script

Use the included `Test-OAuthMqttFlow.ps1` to verify the full OAuth + MQTT flow:

```powershell
.\Test-OAuthMqttFlow.ps1 `
    -IssuerUrl "https://auth.example.com/realms/my-realm" `
    -ClientId "tc_iot_communicator" `
    -MqttHost "mqtt.example.com" `
    -MqttPort 8884
```

The script performs:
1. OIDC Discovery
2. PKCE key pair generation
3. Browser-based login
4. Token exchange (Authorization Code → JWT)
5. JWT validation (structure, claims, expiration)
6. MQTT CONNECT with JWT as password
7. MQTT SUBSCRIBE + PUBLISH roundtrip test

Use `-SkipMqtt` to test only the OAuth flow without MQTT.

### 5.2 Manual Verification

1. **OIDC Discovery:** `curl https://<issuer-url>/.well-known/openid-configuration` — verify `authorization_endpoint`, `token_endpoint`, `jwks_uri` are present.
2. **JWKS Endpoint:** `curl <jwks_uri>` — verify public keys are returned.
3. **JWT Decode:** Paste the access token at [jwt.io](https://jwt.io) — verify `preferred_username`, `sub`, `exp`, `iss` claims.
4. **MQTT Test:** Use `mosquitto_pub` with `-u <username> -P <jwt>` to test broker authentication.

---

## 6. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| OIDC Discovery fails | Issuer URL wrong or not reachable | Verify URL, check DNS, firewall, and HTTPS certificate |
| PKCE S256 not supported | IdP does not support PKCE | Enable PKCE in IdP settings or use a different provider |
| `preferred_username` missing in JWT | Mapper not configured | Add a protocol mapper in Keycloak (see section 1.2) |
| MQTT `rc=4` (Bad credentials) | JWT format invalid or broker cannot parse it | Check broker JWT plugin configuration, verify JWKS URL |
| MQTT `rc=5` (Not authorized) | JWT expired, signature invalid, or issuer mismatch | Check `exp` claim, verify JWKS URL and `iss` configuration |
| Token expired during operation | Access Token Lifespan too short | Increase lifespan in IdP or implement token refresh |
| TLS handshake failure | CA certificate missing or wrong | Verify `sCA` path in PLC and CA certificate chain |
| Redirect URI mismatch | URI not registered in IdP | Add exact URI (including port and path) to Valid redirect URIs |
| PLC cannot connect after adding JWT plugin | Auth chain misconfigured — static fallback missing | Ensure `password_file` (Mosquitto) or secondary auth backend (EMQX/HiveMQ) is configured |
| PLC works but App gets `rc=5` | JWT plugin not loaded or JWKS URL unreachable | Verify plugin is loaded, check broker logs, test JWKS URL connectivity |

---

## References

- [TF6730 – TF6735 | TwinCAT 3 IoT Communicator — Security](https://infosys.beckhoff.com/content/1033/tf6730_tc3_iot_communicator/3915357963.html)
- [TF6730 – TF6735 | TwinCAT 3 IoT Communicator — Authentication](https://infosys.beckhoff.com/content/1033/tf6730_tc3_iot_communicator/3915394443.html)
- [TF6730 – TF6735 | TwinCAT 3 IoT Communicator — Connection Settings](https://infosys.beckhoff.com/content/1033/tf6730_tc3_iot_communicator/10664340875.html)
- [TF6701 | TwinCAT 3 IoT Communication MQTT — Application Level (JWT)](https://infosys.beckhoff.com/content/1033/tf6701_tc3_iot_communication_mqtt/10188104587.html)
- [TF6701 | FB_IotMqttClient](https://infosys.beckhoff.com/content/1033/tf6701_tc3_iot_communication_mqtt/3391835403.html)
- [Tc3_JsonXml | FB_JwtEncode](https://infosys.beckhoff.com/content/1033/tcplclib_tc3_jsonxml/7310448907.html)
- [RFC 7519 — JSON Web Token (JWT)](https://datatracker.ietf.org/doc/html/rfc7519)
- [RFC 7636 — PKCE](https://datatracker.ietf.org/doc/html/rfc7636)
- [RFC 8252 — OAuth 2.0 for Native Apps](https://datatracker.ietf.org/doc/html/rfc8252)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
