"""Config flow for TwinCAT IoT Communicator."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
import hashlib
import logging
import secrets
import ssl
from typing import Any
import uuid
from urllib.parse import urlencode

import aiomqtt
from aiohttp import web_response
import voluptuous as vol

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.helpers import device_registry as dr, http
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    AUTH_CALLBACK_NAME,
    AUTH_CALLBACK_PATH,
    AUTH_MODE_CREDENTIALS,
    AUTH_MODE_ONLINE,
    CONF_ASSIGN_DEVICES_TO_AREAS,
    CONF_AUTH_MODE,
    CONF_AUTH_URL,
    CONF_JWT_TOKEN,
    CONF_CREATE_AREAS,
    CONF_MAIN_TOPIC,
    CONF_SELECTED_DEVICES,
    CONF_USE_TLS,
    DEFAULT_CLIENT_ID,
    DEFAULT_MAIN_TOPIC,
    DEFAULT_PORT,
    DOMAIN,
    TOPIC_SUB_DESC,
    TOPIC_SUB_TX,
)
from .jwt_helper import jwt_expiry_summary, jwt_extract_username, jwt_is_expired

_LOGGER = logging.getLogger(__name__)

HEADER_FRONTEND_BASE = "HA-Frontend-Base"

DATA_JWT_TOKENS = f"{DOMAIN}_jwt_tokens"
DATA_AUTH_CODES = f"{DOMAIN}_auth_codes"
DATA_PKCE_VERIFIERS = f"{DOMAIN}_pkce_verifiers"
DATA_REDIRECT_URIS = f"{DOMAIN}_redirect_uris"
DATA_OIDC_ENDPOINTS = f"{DOMAIN}_oidc_endpoints"

STEP_BROKER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USE_TLS, default=False): bool,
    }
)

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)

STEP_TOPIC_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAIN_TOPIC, default=DEFAULT_MAIN_TOPIC): str,
    }
)

SCAN_TIMEOUT = 5


# ── PKCE helpers ─────────────────────────────────────────────────


def _generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── OAuth callback view ─────────────────────────────────────────


class TcIotOAuthCallbackView(HomeAssistantView):
    """Handle the OAuth redirect callback from the external auth server.

    Supports two modes:
    - Authorization Code flow: receives ``code`` query param
    - Direct token delivery: receives ``access_token`` query param or fragment
    """

    url = AUTH_CALLBACK_PATH
    name = AUTH_CALLBACK_NAME
    requires_auth = False

    async def get(self, request: Any) -> web_response.Response:
        """Receive the code or token after external OAuth login."""
        hass = request.app[KEY_HASS]
        flow_id = request.query.get("flow_id", "")

        token = request.query.get("access_token")
        code = request.query.get("code")

        if token:
            _LOGGER.info("OAuth callback: received access_token (flow %s)", flow_id)
            hass.data.setdefault(DATA_JWT_TOKENS, {})[flow_id] = token
            await hass.config_entries.flow.async_configure(
                flow_id=flow_id, user_input=None
            )
            return _success_response()

        if code:
            _LOGGER.info("OAuth callback: received authorization code (flow %s)", flow_id)
            hass.data.setdefault(DATA_AUTH_CODES, {})[flow_id] = code
            await hass.config_entries.flow.async_configure(
                flow_id=flow_id, user_input=None
            )
            return _success_response()

        _LOGGER.debug(
            "OAuth callback: no code/token in query params, "
            "serving fragment extraction page (flow %s)", flow_id,
        )
        # No code and no token in query — try URL fragment (implicit grant).
        return web_response.Response(
            headers={"content-type": "text/html"},
            text=(
                "<!doctype html><html><body>"
                "<p>Completing authentication&hellip;</p>"
                "<script>"
                "const q=new URLSearchParams(window.location.search);"
                "const h=window.location.hash.substring(1);"
                "const p=new URLSearchParams(h);"
                "const t=p.get('access_token');"
                "if(t){"
                "window.location=window.location.pathname+'?'"
                "+new URLSearchParams({flow_id:q.get('flow_id'),access_token:t});"
                "}else{"
                "document.body.textContent="
                "'Error: No access token or authorization code received.';"
                "}"
                "</script>"
                "</body></html>"
            ),
        )


def _success_response() -> web_response.Response:
    return web_response.Response(
        headers={"content-type": "text/html"},
        text=(
            "<script>window.close()</script>"
            "Authentication successful. You can close this window."
        ),
    )


# ── Config flow ──────────────────────────────────────────────────


class TcIotCommunicatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TwinCAT IoT Communicator."""

    VERSION = 2
    MINOR_VERSION = 4

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._broker_data: dict[str, Any] = {}
        self._main_topic: str = ""
        self._discovered_devices: list[str] = []
        self._auth_url: str = ""
        self._client_id: str = DEFAULT_CLIENT_ID
        self._jwt_token: str = ""
        self._reauth_entry: ConfigEntry | None = None

        self._authorize_endpoint: str = ""
        self._token_endpoint: str = ""

    # ── Step 1: broker connection + OAuth toggle ───────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 -- broker connection details."""
        if user_input is not None:
            self._broker_data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_USE_TLS: user_input[CONF_USE_TLS],
            }
            _LOGGER.debug(
                "Broker config: %s:%s (TLS=%s)",
                user_input[CONF_HOST], user_input[CONF_PORT],
                user_input[CONF_USE_TLS],
            )
            return await self.async_step_auth_method()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_BROKER_SCHEMA,
        )

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 -- choose authentication method."""
        return self.async_show_menu(
            step_id="auth_method",
            menu_options=["no_auth", "credentials", "auth_url"],
        )

    async def async_step_no_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No authentication -- test broker and proceed to topic."""
        self._broker_data[CONF_AUTH_MODE] = AUTH_MODE_CREDENTIALS
        self._broker_data[CONF_USERNAME] = ""
        self._broker_data[CONF_PASSWORD] = ""

        _LOGGER.debug("Testing broker without authentication")
        error = await self._test_broker(
            host=self._broker_data[CONF_HOST],
            port=self._broker_data[CONF_PORT],
            username=None,
            password=None,
            use_tls=self._broker_data[CONF_USE_TLS],
        )
        if error:
            return self.async_abort(reason=error)
        return await self.async_step_topic()

    # ── Step 2a: credentials (username / password) ───────────────

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect username + password and test the broker."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input.get(CONF_USERNAME) or None
            password = user_input.get(CONF_PASSWORD) or None
            error = await self._test_broker(
                host=self._broker_data[CONF_HOST],
                port=self._broker_data[CONF_PORT],
                username=username,
                password=password,
                use_tls=self._broker_data[CONF_USE_TLS],
            )
            if error:
                errors["base"] = error
            else:
                self._broker_data[CONF_AUTH_MODE] = AUTH_MODE_CREDENTIALS
                self._broker_data[CONF_USERNAME] = user_input.get(CONF_USERNAME, "")
                self._broker_data[CONF_PASSWORD] = user_input.get(CONF_PASSWORD, "")
                return await self.async_step_topic()

        return self.async_show_form(
            step_id="credentials",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    # ── Step 2b: auth URL + client_id input ──────────────────────

    async def async_step_auth_url(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the OAuth issuer URL and client ID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._auth_url = user_input[CONF_AUTH_URL].rstrip("/")
            self._client_id = user_input.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID)
            _LOGGER.info(
                "OAuth: issuer=%s, client_id=%s – starting OIDC discovery",
                self._auth_url, self._client_id,
            )

            ok = await self._discover_oidc(self._auth_url)
            if not ok:
                self._authorize_endpoint = self._auth_url
                self._token_endpoint = ""

            return await self._async_start_oauth()

        defaults: dict[str, Any] = {}
        if self._reauth_entry:
            defaults[CONF_AUTH_URL] = self._reauth_entry.data.get(CONF_AUTH_URL, "")
            defaults[CONF_CLIENT_ID] = self._reauth_entry.data.get(
                CONF_CLIENT_ID, DEFAULT_CLIENT_ID
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AUTH_URL, default=defaults.get(CONF_AUTH_URL, "")
                ): str,
                vol.Optional(
                    CONF_CLIENT_ID,
                    default=defaults.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="auth_url",
            data_schema=schema,
            errors=errors,
        )

    # ── OIDC discovery ───────────────────────────────────────────

    async def _discover_oidc(self, issuer_url: str) -> bool:
        """Try to fetch OIDC well-known configuration.

        Returns True if discovery succeeded and endpoints were set.
        """
        session = async_get_clientsession(self.hass)
        for suffix in (
            "/.well-known/openid-configuration",
            "/.well-known/oauth-authorization-server",
        ):
            url = issuer_url + suffix
            _LOGGER.debug("OIDC discovery: trying %s", url)
            try:
                async with asyncio.timeout(10):
                    resp = await session.get(url)
                    if resp.status != 200:
                        _LOGGER.debug(
                            "OIDC discovery: %s returned HTTP %s", url, resp.status,
                        )
                        continue
                    data = await resp.json()
                    auth_ep = data.get("authorization_endpoint")
                    token_ep = data.get("token_endpoint")
                    if auth_ep and token_ep:
                        self._authorize_endpoint = auth_ep
                        self._token_endpoint = token_ep
                        _LOGGER.info(
                            "OIDC discovery: success – authorize=%s, token=%s",
                            auth_ep, token_ep,
                        )
                        return True
                    _LOGGER.debug(
                        "OIDC discovery: %s responded but missing endpoints "
                        "(authorization_endpoint=%s, token_endpoint=%s)",
                        url, auth_ep, token_ep,
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "OIDC discovery: request to %s failed", url, exc_info=True,
                )

        _LOGGER.warning(
            "OIDC discovery: could not find endpoints for %s – "
            "falling back to direct token mode",
            issuer_url,
        )
        return False

    # ── Step 2c: external OAuth step ─────────────────────────────

    async def _async_start_oauth(self) -> ConfigFlowResult:
        """Register the callback view and open the auth URL in the browser."""
        self.hass.http.register_view(TcIotOAuthCallbackView)

        if (req := http.current_request.get()) is None:
            return self.async_abort(reason="cannot_connect")
        if (hass_url := req.headers.get(HEADER_FRONTEND_BASE)) is None:
            return self.async_abort(reason="cannot_connect")

        callback_url = f"{hass_url}{AUTH_CALLBACK_PATH}"
        redirect_uri = f"{callback_url}?{urlencode({'flow_id': self.flow_id})}"

        if self._token_endpoint:
            # Authorization Code + PKCE flow
            verifier, challenge = _generate_pkce()
            self.hass.data.setdefault(DATA_PKCE_VERIFIERS, {})[self.flow_id] = verifier
            self.hass.data.setdefault(DATA_REDIRECT_URIS, {})[self.flow_id] = redirect_uri
            self.hass.data.setdefault(DATA_OIDC_ENDPOINTS, {})[self.flow_id] = {
                "token_endpoint": self._token_endpoint,
                "client_id": self._client_id,
            }

            params = urlencode({
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": self.flow_id,
            })
            auth_url = f"{self._authorize_endpoint}?{params}"
            _LOGGER.info(
                "OAuth: opening authorize endpoint (PKCE flow), "
                "redirect_uri=%s", redirect_uri,
            )
        else:
            # Direct token mode (simple auth servers)
            auth_url = f"{self._authorize_endpoint}?redirect_uri={redirect_uri}"
            _LOGGER.info(
                "OAuth: opening auth URL (direct token mode), "
                "redirect_uri=%s", redirect_uri,
            )

        _LOGGER.debug("OAuth: full authorize URL = %s", auth_url)
        return self.async_external_step(step_id="obtain_token", url=auth_url)

    async def async_step_obtain_token(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Wait for the OAuth callback, then validate the JWT."""
        _LOGGER.debug("OAuth: obtain_token step triggered, checking for token/code")

        # Check for direct access_token first
        tokens: dict[str, str] = self.hass.data.get(DATA_JWT_TOKENS, {})
        token = tokens.pop(self.flow_id, None)

        if not token:
            # Check for authorization code
            codes: dict[str, str] = self.hass.data.get(DATA_AUTH_CODES, {})
            code = codes.pop(self.flow_id, None)

            if code:
                _LOGGER.info("OAuth: exchanging authorization code for token")
                token = await self._exchange_code_for_token(code)
            else:
                _LOGGER.warning("OAuth: no token and no authorization code received")

        if not token:
            _LOGGER.error("OAuth: failed to obtain access token – aborting")
            return self.async_external_step_done(next_step_id="token_timeout")

        username = jwt_extract_username(token)
        if not username:
            _LOGGER.error(
                "OAuth: JWT has no 'preferred_username' or 'sub' claim – aborting"
            )
            return self.async_external_step_done(next_step_id="token_invalid")

        if jwt_is_expired(token):
            _LOGGER.error("OAuth: received JWT is already expired – aborting")
            return self.async_external_step_done(next_step_id="token_expired")

        validity = jwt_expiry_summary(token)
        _LOGGER.info(
            "OAuth: login successful, MQTT username=%s (token length=%d, %s)",
            username, len(token), validity,
        )

        self._jwt_token = token
        self._broker_data[CONF_AUTH_MODE] = AUTH_MODE_ONLINE
        self._broker_data[CONF_USERNAME] = username
        self._broker_data[CONF_PASSWORD] = ""
        self._broker_data[CONF_AUTH_URL] = self._auth_url
        self._broker_data[CONF_CLIENT_ID] = self._client_id
        self._broker_data[CONF_JWT_TOKEN] = token
        return self.async_external_step_done(next_step_id="oauth_complete")

    async def _exchange_code_for_token(self, code: str) -> str | None:
        """Exchange an authorization code for an access token (PKCE flow)."""
        verifiers: dict[str, str] = self.hass.data.get(DATA_PKCE_VERIFIERS, {})
        redirect_uris: dict[str, str] = self.hass.data.get(DATA_REDIRECT_URIS, {})
        endpoints: dict[str, dict] = self.hass.data.get(DATA_OIDC_ENDPOINTS, {})

        verifier = verifiers.pop(self.flow_id, None)
        redirect_uri = redirect_uris.pop(self.flow_id, None)
        ep = endpoints.pop(self.flow_id, None)

        if not verifier or not ep:
            _LOGGER.error(
                "OAuth token exchange: missing PKCE verifier or endpoint data"
            )
            return None

        token_endpoint = ep["token_endpoint"]
        client_id = ep["client_id"]

        _LOGGER.debug(
            "OAuth token exchange: POST %s (client_id=%s)",
            token_endpoint, client_id,
        )

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }

        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(15):
                resp = await session.post(
                    token_endpoint, data=payload,
                )
                if resp.status != 200:
                    body = await resp.text()
                    _LOGGER.error(
                        "OAuth token exchange failed (HTTP %s): %s",
                        resp.status, body,
                    )
                    return None
                data = await resp.json()
                token = data.get("access_token")
                if token:
                    _LOGGER.info(
                        "OAuth token exchange: success (token length=%d)",
                        len(token),
                    )
                else:
                    _LOGGER.error(
                        "OAuth token exchange: response has no 'access_token' key. "
                        "Keys present: %s", list(data.keys()),
                    )
                return token
        except Exception:  # noqa: BLE001
            _LOGGER.exception("OAuth token exchange request failed")
            return None

    async def async_step_token_timeout(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handle timeout when no token was received."""
        return self.async_abort(reason="token_request_timeout")

    async def async_step_token_invalid(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handle an invalid / undecodable JWT."""
        return self.async_abort(reason="invalid_token")

    async def async_step_token_expired(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handle an already-expired JWT."""
        return self.async_abort(reason="token_expired")

    # ── Step 2d: test broker with OAuth credentials ──────────────

    async def async_step_oauth_complete(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Test the broker connection using JWT credentials."""
        _LOGGER.info(
            "OAuth: testing MQTT broker with JWT credentials (user=%s)",
            self._broker_data.get(CONF_USERNAME),
        )
        error = await self._test_broker(
            host=self._broker_data[CONF_HOST],
            port=self._broker_data[CONF_PORT],
            username=self._broker_data.get(CONF_USERNAME),
            password=self._jwt_token,
            use_tls=self._broker_data[CONF_USE_TLS],
        )
        if error:
            _LOGGER.error(
                "OAuth: MQTT broker rejected JWT credentials: %s", error,
            )
            return self.async_abort(reason=error)

        _LOGGER.info("OAuth: MQTT broker connection successful")

        if self._reauth_entry:
            _LOGGER.info("OAuth: re-authentication completed, updating config entry")
            return await self._async_finish_reauth()

        return await self.async_step_topic()

    # ── Step 3: topic ────────────────────────────────────────────

    async def async_step_topic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """MQTT main topic, then scan for devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._main_topic = user_input[CONF_MAIN_TOPIC]

            mqtt_password = (
                self._jwt_token
                if self._broker_data.get(CONF_AUTH_MODE) == AUTH_MODE_ONLINE
                else self._broker_data.get(CONF_PASSWORD) or None
            )

            devices = await self._scan_devices(
                host=self._broker_data[CONF_HOST],
                port=self._broker_data[CONF_PORT],
                username=self._broker_data.get(CONF_USERNAME) or None,
                password=mqtt_password,
                use_tls=self._broker_data[CONF_USE_TLS],
                main_topic=self._main_topic,
            )

            if not devices:
                errors["base"] = "no_devices_found"
                return self.async_show_form(
                    step_id="topic",
                    data_schema=STEP_TOPIC_SCHEMA,
                    errors=errors,
                )

            self._discovered_devices = devices
            return await self.async_step_select_devices()

        return self.async_show_form(
            step_id="topic",
            data_schema=STEP_TOPIC_SCHEMA,
            errors=errors,
        )

    # ── Step 4: select devices ───────────────────────────────────

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Multi-select discovered devices."""
        errors: dict[str, str] = {}

        already_configured = self._get_already_configured_devices()
        available = [d for d in self._discovered_devices if d not in already_configured]

        if not available:
            return self.async_abort(reason="all_devices_configured")

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_SELECTED_DEVICES, [])
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                host = self._broker_data[CONF_HOST]
                port = self._broker_data[CONF_PORT]
                unique_id = f"{host}:{port}_{self._main_topic}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                data = {
                    **self._broker_data,
                    CONF_MAIN_TOPIC: self._main_topic,
                    CONF_SELECTED_DEVICES: selected,
                    CONF_CREATE_AREAS: user_input.get(CONF_CREATE_AREAS, True),
                    CONF_ASSIGN_DEVICES_TO_AREAS: user_input.get(
                        CONF_ASSIGN_DEVICES_TO_AREAS, True,
                    ),
                }
                return self.async_create_entry(
                    title=f"TcIoT {self._main_topic} ({host})",
                    data=data,
                )

        options = [SelectOptionDict(value=d, label=d) for d in available]

        schema = vol.Schema(
            {
                vol.Required(CONF_SELECTED_DEVICES): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True)
                ),
                vol.Required(
                    CONF_CREATE_AREAS, default=True
                ): BooleanSelector(BooleanSelectorConfig()),
                vol.Required(
                    CONF_ASSIGN_DEVICES_TO_AREAS, default=True
                ): BooleanSelector(BooleanSelectorConfig()),
            }
        )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            errors=errors,
            description_placeholders={"devices_found": str(len(available))},
        )

    # ── Reconfigure flow ──────────────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration to add or remove PLC devices."""
        entry = self._get_reconfigure_entry()
        self._broker_data = dict(entry.data)
        self._main_topic = entry.data[CONF_MAIN_TOPIC]

        errors: dict[str, str] = {}
        try:
            devices = await self._scan_devices(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                username=entry.data.get(CONF_USERNAME) or None,
                password=self._resolve_password(entry.data),
                use_tls=entry.data.get(CONF_USE_TLS, False),
                main_topic=self._main_topic,
            )
        except Exception:
            _LOGGER.debug("Device scan failed during reconfigure", exc_info=True)
            devices = []

        current: list[str] = list(entry.data.get(CONF_SELECTED_DEVICES) or [])
        all_devices = sorted(set(devices) | set(current))

        if not all_devices:
            errors["base"] = "no_devices_found"
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if user_input is not None:
            selected: list[str] = user_input.get(CONF_SELECTED_DEVICES, [])
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                removed = set(current) - set(selected)
                if removed:
                    self._remove_stale_devices(entry, removed)

                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_SELECTED_DEVICES: selected,
                        CONF_CREATE_AREAS: user_input.get(
                            CONF_CREATE_AREAS, True
                        ),
                        CONF_ASSIGN_DEVICES_TO_AREAS: user_input.get(
                            CONF_ASSIGN_DEVICES_TO_AREAS, True,
                        ),
                    },
                )

        current_create_areas = entry.data.get(CONF_CREATE_AREAS, True)
        current_assign = entry.data.get(CONF_ASSIGN_DEVICES_TO_AREAS, True)
        options = [SelectOptionDict(value=d, label=d) for d in all_devices]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_DEVICES, default=current,
                ): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True)
                ),
                vol.Required(
                    CONF_CREATE_AREAS, default=current_create_areas,
                ): BooleanSelector(BooleanSelectorConfig()),
                vol.Required(
                    CONF_ASSIGN_DEVICES_TO_AREAS, default=current_assign,
                ): BooleanSelector(BooleanSelectorConfig()),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={"devices_found": str(len(all_devices))},
        )

    def _remove_stale_devices(
        self,
        entry: ConfigEntry,
        removed_names: set[str],
    ) -> None:
        """Remove device registry entries for deselected devices and their widgets."""
        dev_reg = dr.async_get(self.hass)
        for device_name in removed_names:
            sub_prefix = f"{entry.entry_id}_{device_name}_"
            for dev in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                for domain, ident in dev.identifiers:
                    if domain == DOMAIN and ident.startswith(sub_prefix):
                        dev_reg.async_remove_device(dev.id)
                        break
            identifier = (DOMAIN, f"{entry.entry_id}_{device_name}")
            if device_entry := dev_reg.async_get_device(identifiers={identifier}):
                dev_reg.async_remove_device(device_entry.id)

    @staticmethod
    def _resolve_password(data: Mapping[str, Any]) -> str | None:
        """Resolve the MQTT password from config entry data."""
        if data.get(CONF_AUTH_MODE) == AUTH_MODE_ONLINE:
            return data.get(CONF_JWT_TOKEN)
        return data.get(CONF_PASSWORD) or None

    # ── Reauth flow ──────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the JWT has expired."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._broker_data = dict(entry_data)
        self._auth_url = entry_data.get(CONF_AUTH_URL, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a confirmation dialog explaining why re-auth is needed."""
        if user_input is not None:
            if self._auth_url:
                return await self.async_step_auth_url()
            return await self.async_step_credentials()

        return self.async_show_form(step_id="reauth_confirm")

    async def _async_finish_reauth(self) -> ConfigFlowResult:
        """Update the config entry with fresh JWT credentials after reauth."""
        assert self._reauth_entry is not None
        new_data = {**self._reauth_entry.data, **self._broker_data}
        self.hass.config_entries.async_update_entry(
            self._reauth_entry, data=new_data
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    # ── Helpers ───────────────────────────────────────────────────

    def _get_already_configured_devices(self) -> set[str]:
        """Return device names already configured across all entries for this topic."""
        configured: set[str] = set()
        for entry in self._async_current_entries():
            if entry.data.get(CONF_MAIN_TOPIC) == self._main_topic:
                for dev in entry.data.get(CONF_SELECTED_DEVICES, []):
                    configured.add(dev)
        return configured

    async def _test_broker(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
    ) -> str | None:
        """Test the MQTT broker connection and return an error key or None."""
        pwd_log = f"(JWT, len={len(password)})" if password and len(password) > 50 else "(password)" if password else "(none)"
        _LOGGER.debug(
            "Broker test: connecting to %s:%s (user=%s, password=%s, TLS=%s)",
            host, port, username, pwd_log, use_tls,
        )
        tls_ctx = (
            await self.hass.async_add_executor_job(ssl.create_default_context)
            if use_tls
            else None
        )
        try:
            async with asyncio.timeout(10):
                async with aiomqtt.Client(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    identifier=f"twincat_iot_test_{uuid.uuid4().hex[:8]}",
                    tls_context=tls_ctx,
                ):
                    pass
            _LOGGER.debug("Broker test: connection successful")
            return None
        except aiomqtt.MqttCodeError as err:
            _LOGGER.debug(
                "Broker test: MQTT error rc=%s connecting to %s:%s – %s",
                err.rc, host, port, err,
            )
            if err.rc == 5:
                return "invalid_auth"
            return "cannot_connect"
        except aiomqtt.MqttError as err:
            # MqttError wraps paho errors; "timed out" means paho-level timeout.
            err_str = str(err).lower()
            if "timed out" in err_str:
                _LOGGER.debug(
                    "Broker test: connection timed out to %s:%s – %s",
                    host, port, err,
                )
                return "connection_timeout"
            _LOGGER.debug(
                "Broker test: cannot connect to %s:%s – %s", host, port, err,
            )
            return "cannot_connect"
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "Broker test: connection timed out after 10s to %s:%s",
                host, port,
            )
            return "connection_timeout"
        except ssl.SSLError as err:
            _LOGGER.debug(
                "Broker test: TLS/SSL error connecting to %s:%s – %s",
                host, port, err,
            )
            return "tls_error"
        except OSError as err:
            # errno -2 / ENOENT = DNS resolution failed.
            if getattr(err, "errno", None) in (-2, 11001, 11004):
                _LOGGER.debug(
                    "Broker test: hostname not found %s – %s", host, err,
                )
                return "hostname_not_found"
            _LOGGER.debug(
                "Broker test: network error connecting to %s:%s – %s (%s)",
                host, port, type(err).__name__, err,
            )
            return "cannot_connect"
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Broker test: unexpected error connecting to %s:%s – %s: %s",
                host, port, type(err).__name__, err, exc_info=True,
            )
            return "cannot_connect"

    async def _scan_devices(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        main_topic: str,
    ) -> list[str]:
        """Subscribe to Desc and Tx/Data wildcards to collect device names."""
        tls_ctx = (
            await self.hass.async_add_executor_job(ssl.create_default_context)
            if use_tls
            else None
        )
        devices: set[str] = set()

        try:
            async with asyncio.timeout(SCAN_TIMEOUT + 5):
                async with aiomqtt.Client(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    identifier=f"twincat_iot_scan_{uuid.uuid4().hex[:8]}",
                    tls_context=tls_ctx,
                ) as client:
                    sub_desc = TOPIC_SUB_DESC.format(main_topic=main_topic)
                    sub_tx = TOPIC_SUB_TX.format(main_topic=main_topic)
                    await client.subscribe(sub_desc, qos=1)
                    await client.subscribe(sub_tx, qos=1)

                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + SCAN_TIMEOUT
                    while True:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            break
                        try:
                            message = await asyncio.wait_for(
                                anext(client.messages), timeout=remaining,
                            )
                            topic = str(message.topic)
                            parts = topic.split("/")
                            try:
                                tc_idx = parts.index("TcIotCommunicator")
                                if tc_idx >= 1:
                                    devices.add(parts[tc_idx - 1])
                            except ValueError:
                                pass
                        except (asyncio.TimeoutError, StopAsyncIteration):
                            break

        except Exception:
            _LOGGER.debug("Device scan failed", exc_info=True)

        return sorted(devices)
