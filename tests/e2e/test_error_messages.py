"""
E2E Tests — Error Message Regression

Validates that stderr messages for common failure scenarios remain
stable and helpful. Prevents confusing UX drift for end users.

These are snapshot-style tests: if the error message changes intentionally,
update the expected substring. Unintentional changes fail the test.
"""

import json
import os
import subprocess
import time

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(15)]


class TestErrorMessages:
    """Validate error messages for common failure scenarios."""

    def test_missing_config_file_message(
        self, credential_process_binary, isolated_config_dir
    ):
        """Missing config file produces a clear, actionable error."""
        env = os.environ.copy()
        env["CCWB_CONFIG_DIR"] = str(isolated_config_dir / "nonexistent")
        result = subprocess.run(
            [str(credential_process_binary)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        assert result.returncode != 0
        stderr_lower = result.stderr.lower()
        # Should mention config file and how to fix
        assert any(
            phrase in stderr_lower
            for phrase in [
                "config",
                "not found",
                "no such file",
                "initialize",
                "ccwb init",
            ]
        ), f"Unhelpful error for missing config: {result.stderr[:200]}"

    def test_invalid_config_format_message(
        self, credential_process_binary, isolated_config_dir
    ):
        """Malformed config produces a parse error, not a crash."""
        config_dir = isolated_config_dir / "bad_config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.yaml").write_text("not: [valid: yaml: {{{}}")

        env = os.environ.copy()
        env["CCWB_CONFIG_DIR"] = str(config_dir)
        result = subprocess.run(
            [str(credential_process_binary)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        assert result.returncode != 0
        stderr_lower = result.stderr.lower()
        assert any(
            phrase in stderr_lower
            for phrase in ["parse", "invalid", "yaml", "syntax", "config"]
        ), f"Unhelpful error for bad config: {result.stderr[:200]}"

    def test_unreachable_oidc_endpoint_message(
        self, credential_process_binary, isolated_config_dir, e2e_profile
    ):
        """Unreachable OIDC provider produces a timeout/connection error, not a crash."""
        if e2e_profile["auth"]["type"] == "passthrough":
            pytest.skip("OIDC error test not applicable to passthrough mode")
        config_dir = isolated_config_dir / "unreachable_oidc"
        config_dir.mkdir(exist_ok=True)
        # Write a config pointing to an unreachable endpoint

        config = {
            "auth_type": "oidc",
            "oidc_issuer": "https://192.0.2.1:9999/unreachable",  # RFC 5737 TEST-NET
            "client_id": "test-client",
            "federation": "direct",
            "region": "us-east-1",
        }
        (config_dir / "config.yaml").write_text(
            "\n".join(f"{k}: {v}" for k, v in config.items())
        )

        env = os.environ.copy()
        env["CCWB_CONFIG_DIR"] = str(config_dir)
        result = subprocess.run(
            [str(credential_process_binary)],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode != 0
        stderr_lower = result.stderr.lower()
        assert any(
            phrase in stderr_lower
            for phrase in ["timeout", "connection", "unreachable", "dial", "connect"]
        ), f"Unhelpful error for unreachable OIDC: {result.stderr[:200]}"

    def test_expired_token_no_refresh_message(
        self, credential_process_binary, isolated_config_dir, e2e_profile
    ):
        """Expired token with no refresh token available produces auth-required message."""
        if e2e_profile["auth"]["type"] == "passthrough":
            pytest.skip("Token refresh test not applicable to passthrough mode")
        config_dir = isolated_config_dir / "expired_no_refresh"
        config_dir.mkdir(exist_ok=True)
        # Create a token cache with an expired token and no refresh token
        cache_dir = config_dir / "cache"
        cache_dir.mkdir(exist_ok=True)

        expired_cache = {
            "access_token": "expired.token.value",
            "expires_at": int(time.time()) - 3600,  # Expired 1 hour ago
            "token_type": "Bearer",
        }
        (cache_dir / "token_cache.json").write_text(json.dumps(expired_cache))

        env = os.environ.copy()
        env["CCWB_CONFIG_DIR"] = str(config_dir)
        env["CCWB_CACHE_DIR"] = str(cache_dir)
        result = subprocess.run(
            [str(credential_process_binary)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        assert result.returncode != 0
        stderr_lower = result.stderr.lower()
        assert any(
            phrase in stderr_lower
            for phrase in ["expired", "re-authenticate", "login", "refresh", "browser"]
        ), f"Unhelpful error for expired token: {result.stderr[:200]}"

    def test_version_flag_output(self, credential_process_binary):
        """--version produces clean version string, not an error."""
        result = subprocess.run(
            [str(credential_process_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"--version failed: {result.stderr}"
        # Should contain a version-like string
        version = result.stdout.strip()
        assert version, "--version produced empty output"
        assert "error" not in version.lower(), (
            f"--version looks like an error: {version}"
        )

    def test_help_flag_output(self, credential_process_binary):
        """--help produces usage info, not an error."""
        result = subprocess.run(
            [str(credential_process_binary), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Some CLIs exit 0 for help, some exit 2 — both are fine
        assert result.returncode in (0, 2), (
            f"--help exited {result.returncode}: {result.stderr}"
        )
        output = result.stdout + result.stderr
        assert any(
            phrase in output.lower()
            for phrase in ["usage", "help", "credential", "options", "flags"]
        ), f"--help doesn't look helpful: {output[:200]}"

    def test_unknown_flag_message(self, credential_process_binary):
        """Unknown flag produces a clear error mentioning the bad flag."""
        result = subprocess.run(
            [str(credential_process_binary), "--nonexistent-flag-xyz"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert (
            "nonexistent-flag-xyz" in output.lower() or "unknown" in output.lower()
        ), f"Unknown flag error doesn't mention the flag: {output[:200]}"
