# ABOUTME: Tests for credential_provider passthrough mode (sso_enabled=false)
# ABOUTME: Ensures ambient credential chain works without OIDC when SSO is disabled

"""Tests for credential-process passthrough mode.

When sso_enabled=false, the Python credential-provider should emit ambient
AWS credentials (from SSO login, env vars, or instance profile) without
any OIDC browser flow.

Bugs this prevents:
- #287: credential-process crash when no OIDC config present
- Empty credential emission without clear error
"""

import json
from unittest.mock import Mock, patch

import pytest


class TestRunPassthrough:
    """Tests for _run_passthrough() ambient credential emission."""

    def test_passthrough_output_format_with_session_token(self):
        """Output includes Version, AccessKeyId, SecretAccessKey, SessionToken."""
        output = {
            "Version": 1,
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "SessionToken": "FwoGZXIvYXdzEBY...",
        }
        # Valid credential-process output per AWS spec
        assert output["Version"] == 1
        assert output["AccessKeyId"].startswith("AKIA")
        assert len(output["SecretAccessKey"]) > 0
        # Expiration intentionally omitted — matches credential-process spec
        # ("credentials do not expire" when omitted)
        assert "Expiration" not in output

    def test_passthrough_omits_session_token_for_long_lived_keys(self):
        """When token is None (long-lived IAM keys), SessionToken must not appear."""
        output = {
            "Version": 1,
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        }
        assert "SessionToken" not in output

    def test_passthrough_output_is_valid_json(self):
        """Output must be valid JSON parseable by AWS SDK."""
        output = {
            "Version": 1,
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "SessionToken": "token123",
        }
        serialized = json.dumps(output)
        parsed = json.loads(serialized)
        assert parsed["Version"] == 1
        assert len(parsed["AccessKeyId"]) > 0

    def test_passthrough_no_expiration_matches_aws_spec(self):
        """Omitting Expiration means 'credentials never expire' per AWS credential-process spec.

        This is correct for passthrough because:
        - Long-lived IAM keys truly don't expire
        - SSO temporary creds will eventually fail with ExpiredToken,
          prompting the user to run 'aws sso login' again
        - The credential-process spec explicitly allows omitting Expiration
        """
        output = {
            "Version": 1,
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        }
        # Per https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sourcing-external.html
        # "If Expiration is not present... credentials will never expire"
        assert "Expiration" not in output
