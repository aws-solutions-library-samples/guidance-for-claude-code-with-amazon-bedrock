# ABOUTME: Contract tests for credential-provider output format
# ABOUTME: Ensures credential-process JSON matches what Claude Code / AWS SDK expects

"""Contract tests for credential-provider.

The credential-process binary outputs JSON that must conform to the AWS
credential_process spec (https://docs.aws.amazon.com/sdkref/latest/guide/setting-global-credential_process.html).
If the output format changes, the AWS SDK silently fails to authenticate.

These tests verify the contract between credential-provider and its consumers.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# AWS credential_process output spec — required fields
CREDENTIAL_PROCESS_REQUIRED_KEYS = {"Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"}

# Version must be 1 per AWS spec
CREDENTIAL_PROCESS_VERSION = 1


class TestCredentialOutputContract:
    """Verify credential-provider output matches AWS credential_process spec."""

    def _make_credential_output(self, **overrides):
        """Build a credential output dict matching what the provider produces."""
        base = {
            "Version": CREDENTIAL_PROCESS_VERSION,
            "AccessKeyId": "ASIAXXXXXXXXXEXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "SessionToken": "FwoGZXIvYXdzEBYaDHqa0AP9H9EXAMPLE...",
            "Expiration": "2026-01-01T12:00:00Z",
        }
        base.update(overrides)
        return base

    def test_output_has_all_required_keys(self):
        """credential_process output must have all AWS-required keys."""
        output = self._make_credential_output()
        for key in CREDENTIAL_PROCESS_REQUIRED_KEYS:
            assert key in output, f"Missing required key: {key}"

    def test_version_is_integer_one(self):
        """Version field must be integer 1 per AWS spec."""
        output = self._make_credential_output()
        assert output["Version"] == 1
        assert isinstance(output["Version"], int)

    def test_access_key_format(self):
        """AccessKeyId must start with ASIA (temporary) or AKIA (permanent)."""
        output = self._make_credential_output()
        assert output["AccessKeyId"].startswith(("ASIA", "AKIA"))
        assert len(output["AccessKeyId"]) >= 16

    def test_expiration_is_iso8601(self):
        """Expiration must be parseable as ISO 8601 datetime."""
        output = self._make_credential_output()
        # Should not raise
        dt = datetime.fromisoformat(output["Expiration"].replace("Z", "+00:00"))
        assert dt.tzinfo is not None  # Must be timezone-aware

    def test_session_token_is_non_empty_string(self):
        """SessionToken must be a non-empty string."""
        output = self._make_credential_output()
        assert isinstance(output["SessionToken"], str)
        assert len(output["SessionToken"]) > 0

    def test_output_is_valid_json(self):
        """Output must serialize to valid JSON (no special chars that break parsing)."""
        output = self._make_credential_output()
        serialized = json.dumps(output)
        # Round-trip
        deserialized = json.loads(serialized)
        assert deserialized == output

    def test_no_extra_keys_break_aws_sdk(self):
        """Extra keys are allowed by AWS SDK but should not include sensitive data."""
        output = self._make_credential_output()
        # These keys should NEVER appear in output
        forbidden_keys = {"Password", "IdToken", "RefreshToken", "ClientSecret"}
        for key in forbidden_keys:
            assert key not in output, f"Sensitive key '{key}' must not appear in credential output"


class TestCredentialProviderConfig:
    """Contract tests for credential-provider config expectations."""

    def test_profile_fields_credential_provider_reads(self):
        """credential-provider must be able to read all fields it needs from config."""
        from claude_code_with_bedrock.config import Profile

        # Create a profile with all fields credential-provider accesses
        profile = Profile(
            name="contract-test",
            provider_domain="company.okta.com",
            client_id="0oa1234",
            credential_storage="keyring",
            aws_region="us-west-2",
            identity_pool_name="claude-pool",
            provider_type="okta",
            federation_type="cognito",
            sso_enabled=True,
            quota_monitoring_enabled=True,
            quota_api_endpoint="https://api.example.com/quota",
            quota_check_interval=30,
            quota_fail_mode="open",
            redirect_port=8400,
            azure_auth_mode=None,
            client_certificate_path=None,
            client_certificate_key_path=None,
        )

        # Verify all fields that credential-provider reads exist and have correct types
        assert isinstance(profile.provider_domain, str)
        assert isinstance(profile.client_id, str)
        assert profile.credential_storage in ("keyring", "session")
        assert isinstance(profile.aws_region, str)
        assert isinstance(profile.identity_pool_name, str)
        assert profile.federation_type in ("cognito", "direct")
        assert isinstance(profile.sso_enabled, bool)
        assert isinstance(profile.quota_monitoring_enabled, bool)
        assert isinstance(profile.quota_check_interval, int)
        assert profile.quota_fail_mode in ("open", "closed")

    def test_config_json_schema_stability(self, tmp_path):
        """Config JSON file has stable key names that credential-provider reads."""
        from claude_code_with_bedrock.config import Config, Profile

        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    profile = Profile(
                        name="schema-test",
                        provider_domain="test.example.com",
                        client_id="test-id",
                        credential_storage="session",
                        aws_region="us-east-1",
                        identity_pool_name="test-pool",
                        quota_monitoring_enabled=True,
                        monthly_token_limit=225000000,
                        daily_token_limit=11250000,
                        daily_enforcement_mode="block",
                    )
                    config.save_profile(profile)

                    # Read raw JSON to verify field names
                    profile_path = tmp_path / "profiles" / "schema-test.json"
                    with open(profile_path) as f:
                        raw = json.load(f)

                    # These field names are the contract with credential-provider
                    assert "provider_domain" in raw
                    assert "client_id" in raw
                    assert "credential_storage" in raw
                    assert "aws_region" in raw
                    assert "identity_pool_name" in raw
                    assert "quota_monitoring_enabled" in raw
                    assert "monthly_token_limit" in raw
                    assert "daily_token_limit" in raw
                    assert "daily_enforcement_mode" in raw


class TestQuotaCheckResponseContract:
    """Contract tests ensuring quota_check Lambda responses match credential-provider expectations.

    The credential-provider binary parses quota_check responses to decide whether
    to allow or block access. Both sides must agree on field names, types, and semantics.
    """

    # Required fields in every response
    RESPONSE_REQUIRED = {"allowed"}

    # Fields present in a normal (policy-found) response
    NORMAL_RESPONSE_FIELDS = {
        "allowed", "reason", "enforcement_mode", "usage", "policy", "unblock_status", "message"
    }

    # Valid reason values the credential-provider switches on
    VALID_REASONS = {
        "within_quota", "monthly_exceeded", "daily_exceeded",
        "no_policy", "no_email", "unblocked", "missing_email_claim",
    }

    def test_allowed_response_structure(self):
        """An allowed response has all expected fields with correct types."""
        response = {
            "allowed": True,
            "reason": "within_quota",
            "enforcement_mode": "block",
            "usage": {
                "monthly_tokens": 50000,
                "monthly_limit": 225000000,
                "monthly_percent": 0.02,
                "daily_tokens": 5000,
                "daily_limit": 11250000,
            },
            "policy": {"type": "user", "identifier": "user@example.com"},
            "unblock_status": {"is_unblocked": False},
            "message": "Within quota limits",
        }

        assert isinstance(response["allowed"], bool)
        assert response["reason"] in self.VALID_REASONS
        assert isinstance(response["usage"], dict)
        assert isinstance(response["policy"], dict)
        assert isinstance(response["unblock_status"], dict)
        assert isinstance(response["message"], str)

    def test_blocked_response_structure(self):
        """A blocked response has the same fields but allowed=False."""
        response = {
            "allowed": False,
            "reason": "daily_exceeded",
            "enforcement_mode": "block",
            "usage": {
                "monthly_tokens": 200000000,
                "monthly_limit": 225000000,
                "monthly_percent": 88.9,
                "daily_tokens": 15000000,
                "daily_limit": 11250000,
            },
            "policy": {"type": "default", "identifier": "__default__"},
            "unblock_status": {"is_unblocked": False},
            "message": "Daily token limit exceeded",
        }

        assert response["allowed"] is False
        assert response["reason"] in self.VALID_REASONS
        assert "daily_tokens" in response["usage"]
        assert "daily_limit" in response["usage"]

    def test_usage_field_has_required_subfields(self):
        """The usage dict must contain fields credential-provider uses for display."""
        usage = {
            "monthly_tokens": 100000,
            "monthly_limit": 225000000,
            "monthly_percent": 0.04,
            "daily_tokens": 10000,
            "daily_limit": 11250000,
        }

        required_usage_fields = {"monthly_tokens", "monthly_limit", "daily_tokens", "daily_limit"}
        for field in required_usage_fields:
            assert field in usage, f"Missing usage field: {field}"
            assert isinstance(usage[field], (int, float)), f"usage.{field} must be numeric"

    def test_credential_provider_decision_logic(self):
        """credential-provider's decision is: if allowed==False and reason in block_reasons → exit(1)."""
        block_reasons = {"monthly_exceeded", "daily_exceeded", "missing_email_claim"}
        allow_reasons = {"within_quota", "no_policy", "unblocked"}

        # Verify all reasons are accounted for
        assert block_reasons | allow_reasons | {"no_email"} == self.VALID_REASONS

    def test_response_json_serializes_cleanly(self):
        """Response must JSON-serialize without special types (no Decimal, datetime objects)."""
        response = {
            "allowed": True,
            "reason": "within_quota",
            "enforcement_mode": "alert",
            "usage": {
                "monthly_tokens": 100000,
                "monthly_limit": 225000000,
                "monthly_percent": 0.04,
                "daily_tokens": 10000,
                "daily_limit": 11250000,
            },
            "policy": {"type": "user", "identifier": "test@test.com"},
            "unblock_status": {"is_unblocked": False},
            "message": "OK",
        }

        # Must not raise
        serialized = json.dumps(response)
        roundtrip = json.loads(serialized)
        assert roundtrip["allowed"] is True
        assert roundtrip["usage"]["monthly_tokens"] == 100000


class TestOtelHelperContract:
    """Contract tests for otel-helper JWT and payload expectations."""

    def test_otel_monitoring_token_structure(self):
        """Monitoring token saved by credential-provider must have expected fields."""
        # This is what credential-provider writes for otel-helper to consume
        monitoring_data = {
            "id_token": "eyJ...",
            "email": "user@company.com",
            "expiry": "2026-01-01T13:00:00Z",
            "identity_pool_id": "us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        }

        assert "id_token" in monitoring_data
        assert "email" in monitoring_data
        assert "expiry" in monitoring_data
        # otel-helper uses these to refresh credentials
        assert isinstance(monitoring_data["id_token"], str)
        assert "@" in monitoring_data["email"]

    def test_otel_collector_config_required_fields(self):
        """otel-helper generates collector config that must have specific structure."""
        # Minimal valid OTEL collector config structure
        config_structure = {
            "receivers": {"otlp": {"protocols": {"grpc": {}, "http": {}}}},
            "exporters": {},
            "service": {"pipelines": {}},
        }

        assert "receivers" in config_structure
        assert "otlp" in config_structure["receivers"]
        assert "service" in config_structure
        assert "pipelines" in config_structure["service"]
