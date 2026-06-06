"""Tests for the JWT helper module."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest

from homeassistant.components.twincat_iot_communicator.jwt_helper import (
    decode_jwt_unverified,
    jwt_expiry_summary,
    jwt_extract_username,
    jwt_is_expired,
    jwt_remaining_seconds,
    jwt_validate_claims,
)


def _make_jwt(payload: dict) -> str:
    """Build a fake JWT with the given payload (no real signature)."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.fakesig"


class TestDecodeJwtUnverified:
    """Tests for decode_jwt_unverified."""

    def test_valid_jwt(self) -> None:
        """Decode a valid JWT payload."""
        payload = {"sub": "testuser", "exp": 1234567890}
        token = _make_jwt(payload)
        result = decode_jwt_unverified(token)
        assert result == payload

    def test_invalid_format_no_dots(self) -> None:
        """Raise ValueError for a token without three parts."""
        with pytest.raises(ValueError, match="Invalid JWT format"):
            decode_jwt_unverified("not-a-jwt")

    def test_invalid_format_two_parts(self) -> None:
        """Raise ValueError for a token with only two parts."""
        with pytest.raises(ValueError, match="Invalid JWT format"):
            decode_jwt_unverified("part1.part2")


class TestJwtExtractUsername:
    """Tests for jwt_extract_username."""

    def test_preferred_username(self) -> None:
        """Return preferred_username when present."""
        token = _make_jwt({"preferred_username": "alice", "sub": "fallback"})
        assert jwt_extract_username(token) == "alice"

    def test_sub_fallback(self) -> None:
        """Fall back to sub when preferred_username is absent."""
        token = _make_jwt({"sub": "bob"})
        assert jwt_extract_username(token) == "bob"

    def test_missing_both(self) -> None:
        """Return None when neither claim is present."""
        token = _make_jwt({"aud": "something"})
        assert jwt_extract_username(token) is None


class TestJwtIsExpired:
    """Tests for jwt_is_expired."""

    def test_expired(self) -> None:
        """Return True for an expired token."""
        token = _make_jwt({"exp": 1000000000})
        assert jwt_is_expired(token) is True

    def test_not_expired(self) -> None:
        """Return False for a token valid far in the future."""
        token = _make_jwt({"exp": 9999999999})
        assert jwt_is_expired(token) is False

    def test_no_exp_claim(self) -> None:
        """Return True when there is no exp claim (missing exp = expired)."""
        token = _make_jwt({"sub": "user"})
        assert jwt_is_expired(token) is True

    def test_string_exp_expired(self) -> None:
        """Return True when exp claim is a string (non-numeric = expired)."""
        token = _make_jwt({"exp": "not-a-number"})
        assert jwt_is_expired(token) is True

    def test_none_exp_expired(self) -> None:
        """Return True when exp claim is explicitly None (= expired)."""
        token = _make_jwt({"exp": None})
        assert jwt_is_expired(token) is True


class TestJwtRemainingSeconds:
    """Tests for jwt_remaining_seconds."""

    def test_remaining_positive(self) -> None:
        """Return positive seconds for a future expiry."""
        future = time.time() + 3600
        token = _make_jwt({"exp": future})
        remaining = jwt_remaining_seconds(token)
        assert remaining is not None
        assert 3590 < remaining < 3610

    def test_remaining_negative(self) -> None:
        """Return negative seconds for an expired token."""
        past = time.time() - 60
        token = _make_jwt({"exp": past})
        remaining = jwt_remaining_seconds(token)
        assert remaining is not None
        assert remaining < 0

    def test_no_exp(self) -> None:
        """Return None when there is no exp claim."""
        token = _make_jwt({"sub": "user"})
        assert jwt_remaining_seconds(token) is None

    def test_string_exp_returns_none(self) -> None:
        """Return None when exp claim is a string (non-numeric)."""
        token = _make_jwt({"exp": "not-a-number"})
        assert jwt_remaining_seconds(token) is None


class TestJwtExpirySummary:
    """Tests for jwt_expiry_summary."""

    def test_no_exp_claim(self) -> None:
        """Return 'no exp claim (REJECTED)' message."""
        token = _make_jwt({"sub": "user"})
        assert jwt_expiry_summary(token) == "no exp claim (REJECTED)"

    def test_expired_summary(self) -> None:
        """Return 'EXPIRED' message for past expiry."""
        with patch("homeassistant.components.twincat_iot_communicator.jwt_helper.time") as mock_time:
            mock_time.time.return_value = 1000100.0
            token = _make_jwt({"exp": 1000000})
            result = jwt_expiry_summary(token)
            assert "EXPIRED" in result
            assert "100s ago" in result

    def test_valid_hours(self) -> None:
        """Return 'valid for Xh Ym' for long validity."""
        with patch("homeassistant.components.twincat_iot_communicator.jwt_helper.time") as mock_time:
            mock_time.time.return_value = 1000000.0
            token = _make_jwt({"exp": 1000000 + 7200 + 300})
            result = jwt_expiry_summary(token)
            assert result == "valid for 2h 5m"

    def test_valid_minutes(self) -> None:
        """Return 'valid for Xm Ys' for moderate validity."""
        with patch("homeassistant.components.twincat_iot_communicator.jwt_helper.time") as mock_time:
            mock_time.time.return_value = 1000000.0
            token = _make_jwt({"exp": 1000000 + 125})
            result = jwt_expiry_summary(token)
            assert result == "valid for 2m 5s"

    def test_valid_seconds(self) -> None:
        """Return 'valid for Xs' for short validity."""
        with patch("homeassistant.components.twincat_iot_communicator.jwt_helper.time") as mock_time:
            mock_time.time.return_value = 1000000.0
            token = _make_jwt({"exp": 1000045})
            result = jwt_expiry_summary(token)
            assert result == "valid for 45s"


class TestJwtValidateClaims:
    """Tests for jwt_validate_claims."""

    def test_valid_token(self) -> None:
        """Return None for a fully valid token."""
        token = _make_jwt({"sub": "user", "exp": 9999999999, "iss": "https://auth.example.com"})
        assert jwt_validate_claims(token, expected_issuer="https://auth.example.com") is None

    def test_missing_exp(self) -> None:
        """Return error when exp claim is missing."""
        token = _make_jwt({"sub": "user"})
        assert jwt_validate_claims(token) == "missing_exp_claim"

    def test_expired_token(self) -> None:
        """Return error when token is expired."""
        token = _make_jwt({"sub": "user", "exp": 1000000000})
        assert jwt_validate_claims(token) == "token_expired"

    def test_missing_username(self) -> None:
        """Return error when no username claim is present."""
        token = _make_jwt({"exp": 9999999999, "aud": "something"})
        assert jwt_validate_claims(token) == "missing_username_claim"

    def test_issuer_mismatch(self) -> None:
        """Return error when issuer does not match."""
        token = _make_jwt({"sub": "user", "exp": 9999999999, "iss": "https://wrong.com"})
        assert jwt_validate_claims(token, expected_issuer="https://auth.example.com") == "issuer_mismatch"

    def test_issuer_not_checked_when_none(self) -> None:
        """Return None when expected_issuer is not provided."""
        token = _make_jwt({"sub": "user", "exp": 9999999999, "iss": "https://any.com"})
        assert jwt_validate_claims(token) is None

    def test_invalid_jwt_format(self) -> None:
        """Return error for malformed JWT."""
        assert jwt_validate_claims("not-a-jwt") == "invalid_jwt_format"

    def test_preferred_username_accepted(self) -> None:
        """Return None when preferred_username is present (no sub needed)."""
        token = _make_jwt({"preferred_username": "alice", "exp": 9999999999})
        assert jwt_validate_claims(token) is None
