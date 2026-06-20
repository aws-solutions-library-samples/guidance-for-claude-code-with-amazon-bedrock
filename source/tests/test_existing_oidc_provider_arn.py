# ABOUTME: Regression tests for existing_oidc_provider_arn field (issue #528)
# ABOUTME: Tests field defaults, round-trip serialization, and backward compatibility

"""Tests for the existing_oidc_provider_arn field in Profile dataclass.

Issue #528: Allow reusing a pre-existing IAM OIDC provider ARN instead of
creating a new one, for multi-profile same-account deployments.
"""

from claude_code_with_bedrock.config import Profile


class TestExistingOidcProviderArn:
    """Tests for the existing_oidc_provider_arn federation field."""

    def test_field_defaults_to_none(self):
        """existing_oidc_provider_arn is optional and defaults to None."""
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.existing_oidc_provider_arn is None

    def test_field_round_trips_through_to_dict_from_dict(self):
        """existing_oidc_provider_arn survives to_dict() → from_dict() round-trip."""
        arn = "arn:aws:iam::123456789012:oidc-provider/company.okta.com"
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            existing_oidc_provider_arn=arn,
        )

        serialized = profile.to_dict()
        restored = Profile.from_dict(serialized)

        assert restored.existing_oidc_provider_arn == arn

    def test_old_config_without_field_still_loads(self):
        """OLD saved config without existing_oidc_provider_arn must load (backward compat).

        This is a Tier 1 requirement per .claude/rules/review-tiers.md:
        changes to config.py must not break old configs.
        """
        # Realistic minimal profile dict representing an OLD saved config
        # (pre-issue-528) with NO existing_oidc_provider_arn key
        data = {
            "name": "legacy",
            "provider_domain": "dev-12345.okta.com",
            "client_id": "0oa123abc456",
            "credential_storage": "session",
            "aws_region": "us-west-2",
            "identity_pool_name": "ccwb-identity-pool",
            "federation_type": "direct",
            "federated_role_arn": "arn:aws:iam::123456789012:role/ClaudeCodeRole",
            # existing_oidc_provider_arn intentionally absent (old config)
        }

        profile = Profile.from_dict(data)

        assert profile.existing_oidc_provider_arn is None

    def test_to_dict_includes_field(self):
        """to_dict() must include existing_oidc_provider_arn in output."""
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            existing_oidc_provider_arn="arn:aws:iam::123456789012:oidc-provider/company.okta.com",
        )

        result = profile.to_dict()

        assert "existing_oidc_provider_arn" in result
        assert result["existing_oidc_provider_arn"] == "arn:aws:iam::123456789012:oidc-provider/company.okta.com"

    def test_to_dict_includes_field_when_none(self):
        """to_dict() must include existing_oidc_provider_arn even when None (for schema completeness)."""
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        result = profile.to_dict()

        assert "existing_oidc_provider_arn" in result
        assert result["existing_oidc_provider_arn"] is None


class TestFederatedRoleName:
    """Tests for the federated_role_name field (issue #528 follow-up).

    A per-profile IAM role name so multiple profiles in one account don't collide
    on the federation role. None -> template default (backward compatible).
    """

    def test_field_defaults_to_none(self):
        """federated_role_name is optional and defaults to None (template default)."""
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.federated_role_name is None

    def test_field_round_trips(self):
        """federated_role_name survives to_dict() → from_dict() round-trip."""
        profile = Profile(
            name="test",
            provider_domain="company.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            federated_role_name="BedrockOktaFederatedRole-test-pool",
        )

        restored = Profile.from_dict(profile.to_dict())

        assert restored.federated_role_name == "BedrockOktaFederatedRole-test-pool"

    def test_old_config_without_field_still_loads(self):
        """OLD saved config without federated_role_name must load (backward compat)."""
        data = {
            "name": "legacy",
            "provider_domain": "dev-12345.okta.com",
            "client_id": "0oa123abc456",
            "credential_storage": "session",
            "aws_region": "us-west-2",
            "identity_pool_name": "ccwb-identity-pool",
            "federation_type": "direct",
            # federated_role_name intentionally absent (old config)
        }

        profile = Profile.from_dict(data)

        assert profile.federated_role_name is None
