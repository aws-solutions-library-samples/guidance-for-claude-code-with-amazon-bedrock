"""
E2E Tests — Authentication Flow

Verifies that the credential-process binary authenticates correctly
across all auth types (OIDC, IDC, passthrough) and federation modes.
"""

import json
import time

import pytest

pytestmark = [pytest.mark.e2e]


class TestAuthFlow:
    """Authentication flow tests — run for all profiles with 'auth_flow' in tests list."""

    def test_initial_auth_produces_valid_creds(self, run_credential_process):
        """Binary exits 0, produces JSON on stdout, AccessKeyId starts with ASIA."""
        result = run_credential_process(context="initial")

        assert result.returncode == 0, (
            f"credential-process exited {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

        creds = json.loads(result.stdout)
        assert "AccessKeyId" in creds, "Missing AccessKeyId in output"
        assert creds["AccessKeyId"].startswith("ASIA"), (
            f"AccessKeyId should start with ASIA (temporary creds), got: {creds['AccessKeyId'][:8]}"
        )

    def test_credential_cache_hit_fast(self, run_credential_process):
        """Second invocation completes in <200ms with same credentials (cache hit)."""
        # First call to warm cache
        first = run_credential_process(context="initial")
        assert first.returncode == 0

        first_creds = json.loads(first.stdout)

        # Second call should be fast (cached)
        start = time.time()
        second = run_credential_process(context="initial")
        elapsed_ms = (time.time() - start) * 1000

        assert second.returncode == 0
        second_creds = json.loads(second.stdout)

        assert elapsed_ms < 200, (
            f"Cache hit took {elapsed_ms:.0f}ms (expected <200ms)"
        )
        assert first_creds["AccessKeyId"] == second_creds["AccessKeyId"], (
            "Cache miss: different AccessKeyId on second call"
        )

    def test_expired_token_silent_refresh(self, run_credential_process, e2e_profile):
        """When token is expired, mid-session refresh gets new creds without browser."""
        if e2e_profile["auth"]["type"] == "passthrough":
            pytest.skip("Passthrough auth does not use token refresh")

        # Simulate expired token via env override
        result = run_credential_process(
            context="mid-session-refresh",
            extra_env={"CCWB_TOKEN_EXPIRY_OVERRIDE": "2020-01-01T00:00:00Z"},
        )

        assert result.returncode == 0, (
            f"Silent refresh failed (exit {result.returncode})\nstderr: {result.stderr}"
        )

        creds = json.loads(result.stdout)
        assert creds["AccessKeyId"].startswith("ASIA")

        # Should NOT contain browser-launch indicators
        assert "opening browser" not in result.stderr.lower(), (
            "Silent refresh should not open browser"
        )

    def test_revoked_refresh_exits_nonzero(self, run_credential_process, e2e_profile):
        """When refresh token is revoked, mid-session refresh fails gracefully."""
        if e2e_profile["auth"]["type"] == "passthrough":
            pytest.skip("Passthrough auth does not use refresh tokens")

        result = run_credential_process(
            context="mid-session-refresh",
            extra_env={
                "CCWB_TOKEN_EXPIRY_OVERRIDE": "2020-01-01T00:00:00Z",
                "CCWB_REFRESH_TOKEN_OVERRIDE": "revoked-invalid-token",
            },
        )

        assert result.returncode != 0, (
            "Expected non-zero exit when refresh token is revoked"
        )

    def test_explain_matches_profile(self, run_credential_process, e2e_profile):
        """--explain output auth.mode matches profile.auth.type."""
        result = run_credential_process(extra_args=["--explain"])

        assert result.returncode == 0, (
            f"--explain failed (exit {result.returncode})\nstderr: {result.stderr}"
        )

        explain = json.loads(result.stdout)
        expected_mode = e2e_profile["auth"]["type"]

        assert explain.get("auth", {}).get("mode") == expected_mode, (
            f"Explain auth.mode={explain.get('auth', {}).get('mode')} "
            f"doesn't match profile auth.type={expected_mode}"
        )
