"""Lightweight JWT helpers for TwinCAT IoT Communicator.

Only decodes the payload – no signature verification is performed,
matching the behaviour specified for the TcIoT Communicator app.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any


def decode_jwt_unverified(token: str) -> dict[str, Any]:
    """Decode a JWT payload without signature verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload))


def jwt_extract_username(token: str) -> str | None:
    """Extract the MQTT username from a JWT (preferred_username or sub)."""
    claims = decode_jwt_unverified(token)
    return claims.get("preferred_username") or claims.get("sub")


def jwt_is_expired(token: str) -> bool:
    """Return True if the JWT's ``exp`` claim is in the past or missing."""
    claims = decode_jwt_unverified(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return True
    return time.time() > exp


def jwt_validate_claims(token: str, expected_issuer: str | None = None) -> str | None:
    """Validate mandatory JWT claims. Returns error string or None if valid."""
    try:
        claims = decode_jwt_unverified(token)
    except (ValueError, Exception):  # noqa: BLE001
        return "invalid_jwt_format"

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return "missing_exp_claim"
    if time.time() > exp:
        return "token_expired"

    if not (claims.get("preferred_username") or claims.get("sub")):
        return "missing_username_claim"

    if expected_issuer:
        iss = claims.get("iss")
        if iss != expected_issuer:
            return "issuer_mismatch"

    return None


def jwt_remaining_seconds(token: str) -> float | None:
    """Return seconds until the JWT expires, or None if no ``exp`` claim."""
    claims = decode_jwt_unverified(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return exp - time.time()


def jwt_expiry_summary(token: str) -> str:
    """Human-readable summary of token validity for logging."""
    remaining = jwt_remaining_seconds(token)
    if remaining is None:
        return "no exp claim (REJECTED)"
    if remaining <= 0:
        return f"EXPIRED ({abs(remaining):.0f}s ago)"
    minutes, secs = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours >= 1:
        return f"valid for {int(hours)}h {int(minutes)}m"
    if minutes >= 1:
        return f"valid for {int(minutes)}m {int(secs)}s"
    return f"valid for {int(secs)}s"
