# ABOUTME: Tests for OTEL helper Authorization header behavior.
# ABOUTME: Verifies Bearer token emission across all output paths (normal, Layer 1 cache hit, proxy).

"""Tests for OTEL helper Authorization header behavior.

The OTEL collector ALB performs OIDC JWT validation when HTTPS is enabled.
The otel-helper must include `Authorization: Bearer <jwt>` in its emitted headers
whenever a token is available, so the ALB accepts the OTLP request.

Also covers the direct cache-file fallback in get_token_via_credential_process
(avoids the 30s subprocess timeout when the credential-provider has already
written a valid token to disk).
"""

import base64
import io
import json
import sys
import time
from unittest.mock import patch

import pytest


def _build_fake_jwt(payload):
    """Build an unsigned JWT-shaped string for tests (avoids secret-scanner flags on static tokens)."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.fakesig"


@pytest.fixture
def mock_cache_dir(tmp_path, monkeypatch):
    """Redirect HOME so cache reads/writes hit a temp directory."""
    cache_dir = tmp_path / ".claude-code-session"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AWS_PROFILE", "test-profile")
    return cache_dir


@pytest.fixture
def monitoring_cache_file(mock_cache_dir):
    """Path of the credential-provider's monitoring token cache."""
    return mock_cache_dir / "test-profile-monitoring.json"


@pytest.fixture
def otel_headers_cache_file(mock_cache_dir):
    """Path of the otel-helper's headers cache (written after main() runs)."""
    return mock_cache_dir / "test-profile-otel-headers.json"


# ---------------------------------------------------------------------------
# Normal path: main() must include Authorization header when token is available
# ---------------------------------------------------------------------------


@patch("otel_helper.__main__.get_token_via_credential_process")
def test_authorization_header_present_with_token(mock_get_token, mock_cache_dir, otel_headers_cache_file, monkeypatch):
    """main() emits 'authorization: Bearer <token>' when a JWT is available."""
    from otel_helper.__main__ import main

    monkeypatch.setattr("sys.argv", ["otel-helper"])
    monkeypatch.delenv("CLAUDE_CODE_MONITORING_TOKEN", raising=False)

    fake_token = _build_fake_jwt({"email": "user@example.com", "exp": int(time.time()) + 3600})
    mock_get_token.return_value = fake_token

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    with patch("otel_helper.__main__.get_aws_caller_identity", return_value={"Arn": "test"}):
        exit_code = main()

    assert exit_code == 0
    output = json.loads(captured.getvalue().strip())
    assert output.get("authorization") == f"Bearer {fake_token}"


@patch("otel_helper.__main__.get_token_via_credential_process", return_value=None)
def test_no_authorization_in_anonymous_mode(mock_get_token, mock_cache_dir, otel_headers_cache_file, monkeypatch):
    """No Authorization header is emitted when there is no token (anonymous fallback)."""
    from otel_helper.__main__ import main

    monkeypatch.setattr("sys.argv", ["otel-helper"])
    monkeypatch.delenv("CLAUDE_CODE_MONITORING_TOKEN", raising=False)

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    with patch(
        "otel_helper.__main__.get_aws_caller_identity",
        return_value={"Arn": "arn:aws:iam::111122223333:user/alice", "Account": "111122223333"},
    ):
        exit_code = main()

    assert exit_code == 0
    output = json.loads(captured.getvalue().strip())
    assert "authorization" not in output


def test_bearer_token_not_in_cache_file(mock_cache_dir, otel_headers_cache_file, monkeypatch):
    """Bearer token must not be written to the otel-headers cache file on disk."""
    from otel_helper.__main__ import main

    monkeypatch.setattr("sys.argv", ["otel-helper"])
    monkeypatch.delenv("CLAUDE_CODE_MONITORING_TOKEN", raising=False)

    fake_token = _build_fake_jwt({"email": "user@example.com", "exp": int(time.time()) + 3600})

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    with (
        patch("otel_helper.__main__.get_token_via_credential_process", return_value=fake_token),
        patch("otel_helper.__main__.get_aws_caller_identity", return_value={"Arn": "test"}),
    ):
        main()

    assert otel_headers_cache_file.exists(), "Cache file should have been written"
    cache_data = json.loads(otel_headers_cache_file.read_text())
    cached_headers = cache_data.get("headers", {})
    assert "authorization" not in cached_headers, "Bearer token must never be persisted to the cache file"


# ---------------------------------------------------------------------------
# Layer 1 cache-hit path: cached attribution + fresh Bearer from env
# ---------------------------------------------------------------------------


def test_layer1_cache_hit_includes_bearer(mock_cache_dir, otel_headers_cache_file, monkeypatch):
    """When Layer 1 cache is warm, output still includes a Bearer token from env."""
    from otel_helper.__main__ import main

    monkeypatch.setattr("sys.argv", ["otel-helper"])

    # Seed warm cache with attribution headers only (no authorization)
    future_exp = int(time.time()) + 3600
    cache_entry = {
        "schema_version": 2,
        "headers": {"x-user-email": "cached@example.com"},
        "token_exp": future_exp,
        "cached_at": int(time.time()),
    }
    otel_headers_cache_file.write_text(json.dumps(cache_entry))

    env_token = _build_fake_jwt({"email": "cached@example.com", "exp": future_exp})
    monkeypatch.setenv("CLAUDE_CODE_MONITORING_TOKEN", env_token)

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    exit_code = main()

    assert exit_code == 0
    output = json.loads(captured.getvalue().strip())

    # Attribution from cache
    assert output.get("x-user-email") == "cached@example.com"
    # Bearer from env — must be present even on cache hit
    assert output.get("authorization") == f"Bearer {env_token}"

    # Cache file must NOT have been updated to include the Bearer token
    cache_data = json.loads(otel_headers_cache_file.read_text())
    assert "authorization" not in cache_data.get(
        "headers", {}
    ), "Bearer token must not be persisted to the cache file on a Layer 1 hit"


def test_layer1_cache_hit_no_bearer_logs_info(mock_cache_dir, otel_headers_cache_file, monkeypatch, caplog):
    """Layer 1 cache hit with no resolvable token emits attribution + logs (Finding 2)."""
    from otel_helper.__main__ import main

    monkeypatch.setattr("sys.argv", ["otel-helper"])
    monkeypatch.delenv("CLAUDE_CODE_MONITORING_TOKEN", raising=False)

    future_exp = int(time.time()) + 3600
    cache_entry = {
        "schema_version": 2,
        "headers": {"x-user-email": "cached@example.com"},
        "token_exp": future_exp,
        "cached_at": int(time.time()),
    }
    otel_headers_cache_file.write_text(json.dumps(cache_entry))

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    # No env token and credential-process unavailable → no Bearer resolvable.
    with patch("otel_helper.__main__.get_token_via_credential_process", return_value=None):
        with caplog.at_level("INFO", logger="claude-otel-headers"):
            exit_code = main()

    assert exit_code == 0
    output = json.loads(captured.getvalue().strip())
    # Attribution still emitted (contract), but no authorization key.
    assert output.get("x-user-email") == "cached@example.com"
    assert "authorization" not in output
    # The omission must be logged so an ALB 401 is diagnosable, not silent.
    assert any(
        "no Bearer token available" in rec.message for rec in caplog.records
    ), "Layer 1 no-token cache hit must log a diagnostic breadcrumb"

    # Cache file untouched — no Bearer leaked to disk.
    cache_data = json.loads(otel_headers_cache_file.read_text())
    assert "authorization" not in cache_data.get("headers", {})


# ---------------------------------------------------------------------------
# get_token_via_credential_process: direct cache fallback
# ---------------------------------------------------------------------------


@patch("otel_helper.__main__.subprocess.run")
def test_subprocess_called_when_no_env_token(mock_run, mock_cache_dir, monkeypatch):
    """get_token_via_credential_process() invokes the credential-process subprocess."""
    from otel_helper.__main__ import get_token_via_credential_process

    monkeypatch.setattr("os.path.exists", lambda _: True)

    fallback_token = _build_fake_jwt({"email": "x@y.z", "exp": int(time.time()) + 3600})
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = fallback_token

    result = get_token_via_credential_process()

    assert result == fallback_token
    mock_run.assert_called_once()


@patch("otel_helper.__main__.subprocess.run")
def test_subprocess_fallback_on_expired_cache(mock_run, mock_cache_dir, monitoring_cache_file, monkeypatch):
    """Cached token within the 60s expiry buffer triggers the subprocess fallback."""
    from otel_helper.__main__ import get_token_via_credential_process

    monkeypatch.setattr("os.path.exists", lambda _: True)

    stale_token = _build_fake_jwt({"email": "stale@example.com", "exp": int(time.time()) + 30})
    monitoring_cache_file.write_text(json.dumps({"token": stale_token, "expires": int(time.time()) + 30}))

    fresh_token = _build_fake_jwt({"email": "fresh@example.com", "exp": int(time.time()) + 3600})
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = fresh_token

    result = get_token_via_credential_process()

    assert result == fresh_token
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Proxy mode: build_proxy_user_headers() must include Authorization
# ---------------------------------------------------------------------------


def test_proxy_mode_includes_authorization(monkeypatch):
    """build_proxy_user_headers attaches a Bearer token when one is available."""
    import otel_helper.__main__ as helper

    fake_token = _build_fake_jwt({"email": "proxy@example.com", "exp": int(time.time()) + 3600})

    monkeypatch.setattr(helper, "ANONYMOUS_MODE", False)
    monkeypatch.setenv("CLAUDE_CODE_MONITORING_TOKEN", fake_token)

    headers = helper.build_proxy_user_headers()

    assert headers["authorization"] == f"Bearer {fake_token}"
    assert headers.get("x-user-email") == "proxy@example.com"


def test_proxy_mode_omits_authorization_when_anonymous(monkeypatch):
    """build_proxy_user_headers does not attach Bearer in anonymous mode."""
    import otel_helper.__main__ as helper

    monkeypatch.setattr(helper, "ANONYMOUS_MODE", True)
    monkeypatch.delenv("CLAUDE_CODE_MONITORING_TOKEN", raising=False)

    with patch(
        "otel_helper.__main__.get_aws_caller_identity",
        return_value={"Arn": "arn:aws:iam::111122223333:user/alice", "Account": "111122223333"},
    ):
        headers = helper.build_proxy_user_headers()

    assert "authorization" not in headers
