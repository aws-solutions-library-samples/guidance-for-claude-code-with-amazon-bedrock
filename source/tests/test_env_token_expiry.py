# ABOUTME: Tests for env-var token expiry validation in otel-helper
# ABOUTME: Ensures expired CLAUDE_CODE_MONITORING_TOKEN is not used blindly

"""Regression tests for monitoring token expiry check (issue #561)."""

import base64
import json
import time
import importlib.util
from pathlib import Path

# Load otel_helper module
_spec = importlib.util.spec_from_file_location(
    "otel_helper_main",
    Path(__file__).resolve().parents[1] / "otel_helper" / "__main__.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
is_token_expired = _module.is_token_expired


def _make_jwt(exp_offset_seconds):
    """Create a minimal JWT with exp claim at now + offset."""
    payload = {"sub": "test", "email": "test@co.com", "exp": int(time.time()) + exp_offset_seconds}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.fake_signature"


class TestIsTokenExpired:
    """Verify is_token_expired correctly identifies stale tokens."""

    def test_valid_token_not_expired(self):
        """Token with exp 1 hour in future is not expired."""
        token = _make_jwt(3600)
        assert is_token_expired(token) is False

    def test_expired_token_detected(self):
        """Token with exp 1 hour in past is expired."""
        token = _make_jwt(-3600)
        assert is_token_expired(token) is True

    def test_token_within_buffer_is_expired(self):
        """Token expiring within 60s buffer is treated as expired."""
        token = _make_jwt(30)  # Expires in 30s, buffer is 60s
        assert is_token_expired(token) is True

    def test_token_beyond_buffer_is_valid(self):
        """Token expiring in 120s (beyond 60s buffer) is valid."""
        token = _make_jwt(120)
        assert is_token_expired(token) is False

    def test_no_exp_claim_treated_as_expired(self):
        """Token without exp claim is treated as expired (fail-safe)."""
        payload = {"sub": "test", "email": "test@co.com"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        token = f"eyJhbGciOiJSUzI1NiJ9.{payload_b64}.fake"
        assert is_token_expired(token) is True

    def test_malformed_token_treated_as_expired(self):
        """Unparseable token is treated as expired (fail-safe)."""
        assert is_token_expired("not.a.valid.jwt") is True
        assert is_token_expired("") is True
        assert is_token_expired("garbage") is True
