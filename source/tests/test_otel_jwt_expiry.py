"""Tests for OTEL JWT token expiry handling.

Verifies that otel-helper correctly:
1. Serves cached headers when JWT token is still valid
2. Rejects cached headers when JWT token has expired
3. Refreshes JWT via credential-process when cache expires
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_cache_dir(tmp_path):
    """Create a temporary cache directory for testing."""
    cache_dir = tmp_path / ".claude-code-session"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def mock_cache_file(mock_cache_dir, monkeypatch):
    """Mock the cache file path to use temporary directory."""
    monkeypatch.setenv("HOME", str(mock_cache_dir.parent))
    monkeypatch.setenv("AWS_PROFILE", "test-profile")
    cache_path = mock_cache_dir / "test-profile-otel-headers.json"
    return cache_path


def test_read_cached_headers_with_valid_token(mock_cache_file):
    """Test that cached headers are returned when JWT token is still valid."""
    from otel_helper.__main__ import read_cached_headers

    # Create cache with token expiring in 5 minutes
    future_exp = int(time.time()) + 300
    cache_data = {
        "headers": {"x-user-email": "test@example.com", "authorization": "Bearer valid.jwt.token"},
        "token_exp": future_exp,
        "cached_at": int(time.time()),
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Should return cached headers
    result = read_cached_headers()
    assert result is not None
    assert result["x-user-email"] == "test@example.com"


def test_read_cached_headers_with_expired_token(mock_cache_file):
    """Test that cached headers are rejected when JWT token has expired."""
    from otel_helper.__main__ import read_cached_headers

    # Create cache with token that expired 5 minutes ago
    past_exp = int(time.time()) - 300
    cache_data = {
        "headers": {"x-user-email": "test@example.com", "authorization": "Bearer expired.jwt.token"},
        "token_exp": past_exp,
        "cached_at": int(time.time()) - 400,
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Should reject expired cache
    result = read_cached_headers()
    assert result is None


def test_read_cached_headers_with_soon_to_expire_token(mock_cache_file):
    """Test that cached headers are rejected when JWT token expires within 60 seconds."""
    from otel_helper.__main__ import read_cached_headers

    # Create cache with token expiring in 30 seconds (within 60s buffer)
    soon_exp = int(time.time()) + 30
    cache_data = {
        "headers": {"x-user-email": "test@example.com", "authorization": "Bearer expiring.jwt.token"},
        "token_exp": soon_exp,
        "cached_at": int(time.time()),
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Should reject cache (within 60s expiry buffer)
    result = read_cached_headers()
    assert result is None


def test_read_cached_headers_at_exact_boundary(mock_cache_file):
    """Test that token expiring exactly at 60s boundary is rejected (boundary condition)."""
    from otel_helper.__main__ import read_cached_headers

    # Create cache with token expiring in exactly 60 seconds (at the boundary)
    boundary_exp = int(time.time()) + 60
    cache_data = {
        "headers": {"x-user-email": "test@example.com", "authorization": "Bearer boundary.jwt.token"},
        "token_exp": boundary_exp,
        "cached_at": int(time.time()),
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Should reject cache (token_exp - now <= 60 means boundary is rejected)
    result = read_cached_headers()
    assert result is None


def test_read_cached_headers_without_token_exp(mock_cache_file):
    """Test that cached headers without token_exp are rejected (old cache format)."""
    from otel_helper.__main__ import read_cached_headers

    # Create cache without token_exp field
    cache_data = {
        "headers": {"x-user-email": "test@example.com"},
        "cached_at": int(time.time()),
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Should reject cache without token_exp
    result = read_cached_headers()
    assert result is None


def test_read_cached_headers_with_missing_file(mock_cache_file):
    """Test that None is returned when cache file doesn't exist."""
    from otel_helper.__main__ import read_cached_headers

    # Don't create cache file
    result = read_cached_headers()
    assert result is None


def test_read_cached_headers_with_malformed_json(mock_cache_file):
    """Test that malformed cache file is handled gracefully."""
    from otel_helper.__main__ import read_cached_headers

    # Write malformed JSON
    mock_cache_file.write_text("{this is not: valid json")

    # Should return None without crashing
    result = read_cached_headers()
    assert result is None


def test_write_cached_headers_includes_token_exp(mock_cache_file):
    """Test that write_cached_headers saves token_exp field."""
    from otel_helper.__main__ import write_cached_headers

    headers = {"x-user-email": "test@example.com"}
    token_exp = int(time.time()) + 3600

    write_cached_headers(headers, token_exp)

    # Verify cache file was written with token_exp
    assert mock_cache_file.exists()
    cache_data = json.loads(mock_cache_file.read_text())
    assert cache_data["token_exp"] == token_exp
    assert cache_data["headers"] == headers

    # Verify raw file was also written
    raw_file = mock_cache_file.with_suffix(".raw")
    assert raw_file.exists()
    raw_data = json.loads(raw_file.read_text())
    assert raw_data == headers


@patch("otel_helper.__main__.get_token_via_credential_process")
def test_main_refreshes_expired_cache(mock_get_token, mock_cache_file, monkeypatch):
    """Test that main() refreshes JWT when cached token is expired."""
    from otel_helper.__main__ import main

    # Mock sys.argv to avoid argparse errors
    monkeypatch.setattr("sys.argv", ["otel-helper"])

    # Mock environment
    monkeypatch.setenv("AWS_PROFILE", "test-profile")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    # Create expired cache
    past_exp = int(time.time()) - 300
    cache_data = {
        "headers": {"x-user-email": "old@example.com", "authorization": "Bearer expired.jwt.token"},
        "token_exp": past_exp,
        "cached_at": int(time.time()) - 400,
    }
    mock_cache_file.write_text(json.dumps(cache_data))

    # Mock credential-process to return fresh token
    mock_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im5ld0BleGFtcGxlLmNvbSIsImV4cCI6OTk5OTk5OTk5OX0.x"
    mock_get_token.return_value = mock_jwt

    # Mock stdout capture
    import io
    import sys

    captured_output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_output)

    # Run main - should refresh expired cache
    with patch("otel_helper.__main__.get_aws_caller_identity", return_value={"Arn": "test"}):
        exit_code = main()

    assert exit_code == 0
    mock_get_token.assert_called_once()  # Should call credential-process

    # Verify new cache was written
    assert mock_cache_file.exists()
    cache_data = json.loads(mock_cache_file.read_text())
    assert cache_data["token_exp"] == 9999999999  # New expiry from mocked JWT
