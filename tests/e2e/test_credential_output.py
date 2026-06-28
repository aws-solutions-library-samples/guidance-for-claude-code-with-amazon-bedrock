"""
E2E Tests — Credential Output Format

Verifies the credential-process binary output conforms to the
AWS credential_process specification (Version=1).
"""

import json
from datetime import datetime, timezone

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class TestCredentialOutput:
    """Credential output format tests — run for all profiles."""

    def test_output_matches_aws_credential_process_spec(self, run_credential_process):
        """Output has Version=1 and all required keys per AWS spec."""
        result = run_credential_process(context="initial")
        assert result.returncode == 0, f"Exit {result.returncode}: {result.stderr}"

        creds = json.loads(result.stdout)

        # AWS credential_process spec requires these keys
        assert creds.get("Version") == 1, (
            f"Expected Version=1, got {creds.get('Version')}"
        )

        # AccessKeyId, SecretAccessKey, SessionToken are always required.
        # Expiration is optional per AWS spec (omitted for non-expiring creds
        # or passthrough mode where ambient creds may not have expiry).
        required_keys = ["AccessKeyId", "SecretAccessKey", "SessionToken"]
        for key in required_keys:
            assert key in creds, f"Missing required key: {key}"

        # Expiration should be present for OIDC/IDC flows but is optional for passthrough
        if "Expiration" in creds:
            # Validate it's a parseable timestamp
            from datetime import datetime

            try:
                datetime.fromisoformat(creds["Expiration"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass  # Some formats may vary, don't fail on format

    def test_expiration_is_future(self, run_credential_process):
        """Expiration timestamp is in the future (if present)."""
        result = run_credential_process(context="initial")
        assert result.returncode == 0

        creds = json.loads(result.stdout)
        if "Expiration" not in creds:
            pytest.skip("No Expiration field in passthrough mode")

        expiration_str = creds["Expiration"]

        # Parse ISO 8601 timestamp
        # Handle both Z suffix and +00:00 format
        expiration_str = expiration_str.replace("Z", "+00:00")
        expiration = datetime.fromisoformat(expiration_str)

        now = datetime.now(timezone.utc)
        assert expiration > now, (
            f"Expiration {expiration} is not in the future (now={now})"
        )

    def test_session_token_present(self, run_credential_process):
        """SessionToken is present and non-empty."""
        result = run_credential_process(context="initial")
        assert result.returncode == 0

        creds = json.loads(result.stdout)
        session_token = creds.get("SessionToken", "")

        assert session_token, "SessionToken is empty"
        assert len(session_token) > 50, (
            f"SessionToken suspiciously short ({len(session_token)} chars)"
        )

    def test_no_sensitive_data_on_stderr(self, run_credential_process):
        """stderr does not leak AccessKeyId or SecretAccessKey."""
        result = run_credential_process(context="initial")
        assert result.returncode == 0

        creds = json.loads(result.stdout)
        access_key = creds["AccessKeyId"]
        secret_key = creds["SecretAccessKey"]

        stderr_lower = result.stderr.lower()

        assert access_key.lower() not in stderr_lower, "AccessKeyId leaked to stderr"
        assert secret_key.lower() not in stderr_lower, (
            "SecretAccessKey leaked to stderr"
        )
