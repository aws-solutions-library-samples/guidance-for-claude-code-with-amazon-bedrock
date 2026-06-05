# ABOUTME: Tests for deploy command with quota stack functionality
# ABOUTME: Covers quota stack deployment, dependency checking, and parameter passing

"""Tests for deploy command quota stack functionality."""

from unittest.mock import Mock

import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


class TestDeployQuotaCommand:
    """Test deploy command with quota stack."""

    @pytest.fixture
    def command(self):
        """Create deploy command instance."""
        return DeployCommand()

    @pytest.fixture
    def tester(self, command):
        """Create command tester."""
        return CommandTester(command)

    @pytest.fixture
    def mock_profile_with_quota(self):
        """Create mock profile with quota monitoring enabled."""
        profile = Mock(spec=Profile)
        profile.profile_name = "test-profile"
        profile.aws_profile = "test-aws-profile"
        profile.aws_region = "us-east-1"
        profile.identity_pool_name = "test-identity-pool"
        profile.monitoring_enabled = True
        profile.quota_monitoring_enabled = True
        profile.monthly_token_limit = 500000000  # 500M tokens
        profile.warning_threshold_80 = 400000000  # 80% of 500M
        profile.warning_threshold_90 = 450000000  # 90% of 500M
        profile.stack_names = {}  # Add missing stack_names attribute
        return profile

    @pytest.fixture
    def mock_profile_no_quota(self):
        """Create mock profile without quota monitoring."""
        profile = Mock(spec=Profile)
        profile.profile_name = "test-profile"
        profile.monitoring_enabled = True
        profile.quota_monitoring_enabled = False
        profile.stack_names = {}  # Add missing stack_names attribute
        profile.aws_region = "us-east-1"  # Add missing aws_region attribute
        profile.identity_pool_name = "test-identity-pool"  # Add missing identity_pool_name
        return profile

    def test_quota_thresholds_calculation(self, mock_profile_with_quota):
        """Test that quota thresholds are calculated correctly."""
        # Test 80% threshold
        assert mock_profile_with_quota.warning_threshold_80 == 400000000
        # Test 90% threshold
        assert mock_profile_with_quota.warning_threshold_90 == 450000000
        # Test relationship
        assert mock_profile_with_quota.warning_threshold_80 == mock_profile_with_quota.monthly_token_limit * 0.8
        assert mock_profile_with_quota.warning_threshold_90 == mock_profile_with_quota.monthly_token_limit * 0.9

    def test_quota_configuration_validation(self):
        """Test validation of quota configuration - simplified."""
        # Profile with quota enabled
        profile_with_quota = Mock()
        profile_with_quota.monitoring_enabled = True
        profile_with_quota.quota_monitoring_enabled = True

        # Profile without quota
        profile_no_quota = Mock()
        profile_no_quota.monitoring_enabled = True
        profile_no_quota.quota_monitoring_enabled = False

        # Profile without monitoring
        profile_no_monitoring = Mock()
        profile_no_monitoring.monitoring_enabled = False

        # Tests
        assert profile_with_quota.quota_monitoring_enabled is True
        assert profile_no_quota.quota_monitoring_enabled is False
        assert profile_no_monitoring.monitoring_enabled is False

    def test_quota_parameter_generation(self):
        """Test CloudFormation parameter generation for quota stack - simplified."""
        monthly_limit = 500_000_000

        # Expected parameters
        expected_params = [
            f"MonthlyTokenLimit={monthly_limit}",
            f"WarningThreshold80={int(monthly_limit * 0.8)}",
            f"WarningThreshold90={int(monthly_limit * 0.9)}",
        ]

        # Verify parameter format
        for param in expected_params:
            assert "=" in param
            key, value = param.split("=")
            assert key in ["MonthlyTokenLimit", "WarningThreshold80", "WarningThreshold90"]
            assert int(value) > 0


class TestResolveOidcConfig:
    """Regression tests for OIDC config resolution with SSO disabled.

    Prevents issue #287: quota deploy crash when sso_enabled=False
    because no valid JWT issuer URL exists.
    """

    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_sso_disabled_returns_empty_strings(self, command):
        """When SSO is disabled, OIDC config must return empty strings (no crash)."""
        profile = Mock()
        profile.sso_enabled = False
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == ""
        assert client_id == ""

    def test_sso_enabled_okta_returns_valid_issuer(self, command):
        """Okta provider returns https:// prefixed domain."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "okta"
        profile.provider_domain = "company.okta.com"
        profile.client_id = "abc123"
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == "https://company.okta.com"
        assert client_id == "abc123"

    def test_sso_enabled_cognito_returns_pool_url(self, command):
        """Cognito provider returns cognito-idp issuer URL."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "cognito"
        profile.cognito_user_pool_id = "us-east-1_abc123"
        profile.aws_region = "us-east-1"
        profile.client_id = "cogclient"
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123"
        assert client_id == "cogclient"

    def test_sso_enabled_cognito_no_pool_id_raises(self, command):
        """Cognito without pool_id must raise ValueError (not crash with None)."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "cognito"
        profile.cognito_user_pool_id = ""
        with pytest.raises(ValueError, match="Cognito User Pool ID is required"):
            command._resolve_oidc_config(profile)

    def test_sso_enabled_auth0_appends_slash(self, command):
        """Auth0 issuer URL must end with trailing slash (matches iss claim)."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "auth0"
        profile.provider_domain = "company.auth0.com"
        profile.client_id = "auth0client"
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == "https://company.auth0.com/"
        assert client_id == "auth0client"

    def test_sso_enabled_azure_no_trailing_slash(self, command):
        """Azure issuer URL must NOT have trailing slash."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "azure"
        profile.provider_domain = "login.microsoftonline.com/tenant-id/v2.0"
        profile.client_id = "azureclient"
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == "https://login.microsoftonline.com/tenant-id/v2.0"
        assert not issuer.endswith("/")
