# OAuth Authentication – Technical Guide

This document describes the complete OAuth authentication flow of the TwinCAT IoT Communicator integration for Home Assistant. It is intended for system integrators who want to understand how the authentication is technically implemented and which values are hardcoded.

---

## Overview

The integration supports three authentication methods:

| Method | Description |
|--------|-------------|
| **No authentication** | Anonymous MQTT connection |
| **Username / Password** | Classic MQTT credentials in the CONNECT packet |
| **External Login (OAuth / JWT)** | OAuth 2.0 Authorization Code Flow with PKCE |

With the OAuth method, no password is stored in Home Assistant. Instead, the user logs in via an external Identity Provider (e.g. Keycloak) and receives a JWT access token that is used as the MQTT password.

---

## Step-by-Step Flow

### 1. User Input

The user enters two values in the config flow:

| Field | Description | Default |
|-------|-------------|---------|
| **Issuer URL** | OIDC Issuer URL of the Identity Provider | – (required) |
| **Client ID** | Client ID registered at the Identity Provider | `tc_iot_communicator` |

**Example Issuer URL for Keycloak:**
```
https://auth.example.com/realms/myrealm
```

### 2. OIDC Discovery

The integration automatically attempts to determine the OAuth endpoints. Two URLs are fetched sequentially (HTTP GET, 10-second timeout):

1. `{issuer_url}/.well-known/openid-configuration`
2. `{issuer_url}/.well-known/oauth-authorization-server` (fallback)

Two fields are extracted from the JSON response:

| Field | Meaning |
|-------|---------|
| `authorization_endpoint` | URL of the Identity Provider's login page |
| `token_endpoint` | URL for exchanging an authorization code for a token |

**Both endpoints found:** → Authorization Code + PKCE Flow
**Endpoints not found:** → Error (`oidc_discovery_failed`), the config flow shows an error message

### 3. Browser Login (Authorization Code + PKCE)

The integration locally generates a PKCE key pair:

- **code_verifier**: 64 random bytes, Base64url-encoded
- **code_challenge**: SHA-256 of the verifier, Base64url-encoded (without padding)

The browser is then opened with the following URL:

```
GET {authorization_endpoint}
    ?response_type=code
    &client_id={client_id}
    &redirect_uri={ha_url}/auth/tc_iot/callback
    &scope=openid
    &code_challenge={challenge}
    &code_challenge_method=S256
    &state={flow_id}
```

#### Hardcoded Values in the Authorization Request

| Parameter | Value | Hardcoded |
|-----------|-------|:---------:|
| `response_type` | `code` | Yes |
| `scope` | `openid` | Yes |
| `code_challenge_method` | `S256` | Yes |
| `state` | Home Assistant config flow ID | Yes |
| `client_id` | User input (default: `tc_iot_communicator`) | No |
| `redirect_uri` | `{ha_url}/auth/tc_iot/callback` | Path yes |

The callback path `/auth/tc_iot/callback` is hardcoded. The `flow_id` is transmitted exclusively via the `state` parameter, not as a query parameter of the redirect URI. This eliminates the need for wildcard redirect URIs (RFC 9700: exact string matching).

### 4. OAuth Callback

The Identity Provider redirects the browser back to the callback endpoint. The integration only accepts the Authorization Code flow:

| Parameter | Description |
|-----------|-------------|
| `code` | Authorization code from the Identity Provider |
| `state` | Config flow ID to associate the callback with the config flow |

Other token delivery methods (direct token as query parameter or URL fragment) are not supported.

### 5. Token Exchange (Authorization Code only)

Upon receiving an authorization code, the integration sends an HTTP POST to the `token_endpoint`:

```
POST {token_endpoint}
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={authorization_code}
&redirect_uri={redirect_uri}
&client_id={client_id}
&code_verifier={verifier}
```

#### Hardcoded Values in the Token Exchange

| Parameter | Value | Hardcoded |
|-----------|-------|:---------:|
| `grant_type` | `authorization_code` | Yes |
| `code` | Received from callback | No |
| `redirect_uri` | Same URI as in step 3 | No |
| `client_id` | User input | No |
| `code_verifier` | Locally generated PKCE verifier | No |

The field **`access_token`** is read from the JSON response.

### 6. JWT Evaluation

The received JWT is **decoded locally** (Base64 decode of the payload segment). **No signature verification** is performed — signature validation is the responsibility of the MQTT broker.

#### Extracted JWT Claims

| Claim | Usage | Required |
|-------|-------|:--------:|
| `preferred_username` | Used as MQTT username | Yes* |
| `sub` | Fallback username if `preferred_username` is missing | Yes* |
| `exp` | Expiration time (Unix timestamp in seconds) | Yes |
| `iss` | Issuer — validated against the configured Issuer URL | Yes |

*At least one of the two claims `preferred_username` or `sub` must be present.

#### Client-Side Validations

- `preferred_username` or `sub` must be present and non-empty → otherwise abort
- `exp` must be present and must not be in the past → otherwise abort
- `iss` (issuer) is validated against the configured Issuer URL → abort on mismatch

### 7. Broker Test

After JWT evaluation, the integration tests the MQTT connection with the new credentials:

| MQTT Field | Value |
|------------|-------|
| `username` | Claim `preferred_username` (fallback: `sub`) |
| `password` | Full JWT (the complete `header.payload.signature` string) |

On success, the setup flow continues. On error (`rc=5` = auth rejected), the flow is aborted.

### 8. MQTT Connection in Operation

During normal operation, the integration connects using the standard MQTT CONNECT packet:

```
MQTT CONNECT
  username = {preferred_username from JWT}
  password = {full JWT}
  client_id = {UUID based on config entry ID}
```

**No HTTP header is set.** The JWT is transmitted exclusively in the MQTT password field. This is the standard convention for JWT-based MQTT authentication.

### 9. Token Expiry and Re-Authentication

The integration checks the `exp` claim at three points:

| Point in Time | Action on Expired Token |
|---------------|------------------------|
| Integration startup | Trigger reauth flow, `ConfigEntryNotReady` |
| Before each MQTT reconnect | Trigger reauth flow, stop reconnect loop |
| Broker responds with `rc=5` | Trigger reauth flow |

During the reauth flow, the user is redirected to the Identity Provider again and logs in. The new JWT is stored in the config entry and the integration is reloaded.

> **TODO — Refresh Token support:** Currently, every token renewal requires a full browser re-login. A future version should request and store a Refresh Token during the initial OAuth flow and use it to silently renew the access token before expiry (RFC 6749 Section 6). This will allow short access token lifetimes (5–15 min) without impacting usability.

---

## Summary of All Hardcoded Values

### OIDC Discovery
| Value | Description |
|-------|-------------|
| `/.well-known/openid-configuration` | Primary discovery path |
| `/.well-known/oauth-authorization-server` | Fallback discovery path |

### Authorization Request
| Parameter | Hardcoded Value |
|-----------|----------------|
| `response_type` | `code` |
| `scope` | `openid` |
| `code_challenge_method` | `S256` |

### Token Exchange
| Parameter | Hardcoded Value |
|-----------|----------------|
| `grant_type` | `authorization_code` |

### JWT Claims
| Claim | Usage |
|-------|-------|
| `preferred_username` | MQTT username (primary) |
| `sub` | MQTT username (fallback) |
| `exp` | Token expiration time |

### Token Exchange Response
| Field | Usage |
|-------|-------|
| `access_token` | JWT for the MQTT connection |

### Callback
| Value | Description |
|-------|-------------|
| `/auth/tc_iot/callback` | OAuth callback path |

### Defaults
| Value | Description |
|-------|-------------|
| `tc_iot_communicator` | Default client ID |

---

## Identity Provider Requirements

| Requirement | Description |
|-------------|-------------|
| OIDC Discovery | `/.well-known/openid-configuration` must be reachable |
| Authorization Code Flow | Standard OAuth 2.0 flow must be enabled |
| PKCE (S256) | Proof Key for Code Exchange must be supported |
| Public Client | No client secret — the client runs on end-user devices |
| Redirect URI | Must allow the respective redirect URIs of the clients (see below) |

## Configuring Redirect URIs

Redirect URIs are configured per client in the Identity Provider (e.g. Keycloak). Each client that authenticates via OAuth needs its own redirect URI. All URIs are registered under the **same** client — not as separate clients.

### Home Assistant

```
https://<ha-host>:8123/auth/tc_iot/callback
```

The path `/auth/tc_iot/callback` is hardcoded. The `flow_id` is transmitted via the OAuth `state` parameter, not as a query parameter appended to the redirect URI. Therefore, no wildcards are needed — the URI must match exactly (RFC 9700).

If Home Assistant is reachable via multiple addresses (e.g. LAN IP and external DNS), **each address** must be registered as a separate redirect URI:

```
https://192.168.1.100:8123/auth/tc_iot/callback
https://ha.local:8123/auth/tc_iot/callback
https://ha.example.com/auth/tc_iot/callback
```

### Native App (iOS / Android)

For native apps (e.g. the TwinCAT IoT Communicator App), a **custom URI scheme** is used as the redirect URI since no web server exists for the callback. The app registers the URI scheme with the operating system and intercepts the redirect after login.

```
tciot://auth/callback
```

The app opens the login via the **system browser** (not an embedded WebView) — this is the recommendation from RFC 8252 (OAuth 2.0 for Native Apps) and is supported by Keycloak.

### Example: Both Clients in a Single Keycloak Client

All redirect URIs are entered under *Valid redirect URIs* in the same Keycloak client:

```
https://192.168.1.100:8123/auth/tc_iot/callback
https://ha.local:8123/auth/tc_iot/callback
tciot://auth/callback
```

Existing URIs are preserved — new ones are simply added via *Add*.

> **Note:** Redirect URIs must match exactly (RFC 9700). Wildcards are not needed and are not recommended for security reasons.

## MQTT Broker Requirements

| Requirement | Description |
|-------------|-------------|
| JWT as password | The full JWT must be accepted as MQTT password |
| Signature validation | The broker must validate the JWT signature against the Identity Provider's public key (JWKS) |
| Expiration check | The broker must check the `exp` claim and reject expired tokens |
