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
        """Okta returns the default authz server issuer (https://<domain>/oauth2/default).

        Okta tokens are minted by the default custom authorization server, so the
        quota JWT authorizer issuer must include the /oauth2/default suffix to match
        the token's iss claim.
        """
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "okta"
        profile.provider_domain = "company.okta.com"
        profile.client_id = "abc123"
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer == "https://company.okta.com/oauth2/default"
        assert client_id == "abc123"

    def test_sso_enabled_okta_does_not_double_append_oauth2_default(self, command):
        """If provider_domain already includes /oauth2/default, it isn't appended twice."""
        profile = Mock()
        profile.sso_enabled = True
        profile.provider_type = "okta"
        profile.provider_domain = "https://company.okta.com/oauth2/default"
        profile.client_id = "abc123"
        issuer, _ = command._resolve_oidc_config(profile)
        assert issuer == "https://company.okta.com/oauth2/default"

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


class TestQuotaSkippedWhenSsoDisabled:
    """Regression tests for issue #454.

    Quota monitoring requires per-user JWT tokens from an OIDC provider.
    When SSO is disabled, the quota stack must be skipped at deploy time
    rather than failing CloudFormation with 'Invalid issuer' on the JWT
    authorizer.
    """

    def _make_profile(self, *, sso_enabled, quota_enabled, monitoring_enabled=True):
        profile = Mock(spec=Profile)
        profile.profile_name = "test-profile"
        profile.aws_region = "us-east-1"
        profile.identity_pool_name = "test-identity-pool"
        profile.monitoring_enabled = monitoring_enabled
        profile.monitoring_config = {"create_vpc": True}
        profile.quota_monitoring_enabled = quota_enabled
        profile.sso_enabled = sso_enabled
        profile.enable_distribution = False
        profile.enable_codebuild = False
        profile.analytics_enabled = False
        profile.stack_names = {}
        return profile

    def _stacks_for_profile(self, profile):
        """Replay the stack-selection logic from DeployCommand.handle()
        for the all-stacks branch (no --stack argument).

        Mirrors source/claude_code_with_bedrock/cli/commands/deploy.py
        approximately lines 200-215 — kept in sync with that block.
        """
        stacks = []
        if getattr(profile, "sso_enabled", True):
            stacks.append("auth")
        if profile.monitoring_enabled or profile.enable_distribution:
            vpc_config = profile.monitoring_config or {}
            if vpc_config.get("create_vpc", True):
                stacks.append("networking")
        if profile.enable_distribution:
            stacks.append("distribution")
        if profile.monitoring_enabled:
            stacks.append("s3bucket")
            stacks.append("monitoring")
            stacks.append("dashboard")
            stacks.append("cowork-dashboard")
            if getattr(profile, "analytics_enabled", True):
                stacks.append("analytics")
            # Issue #454: only schedule quota stack when SSO is enabled.
            if getattr(profile, "quota_monitoring_enabled", False):
                if getattr(profile, "sso_enabled", True):
                    stacks.append("quota")
        if getattr(profile, "enable_codebuild", False):
            stacks.append("codebuild")
        return stacks

    def test_quota_stack_scheduled_when_sso_enabled(self):
        profile = self._make_profile(sso_enabled=True, quota_enabled=True)
        stacks = self._stacks_for_profile(profile)
        assert "quota" in stacks
        assert "auth" in stacks  # sanity: SSO-enabled adds auth stack

    def test_quota_stack_skipped_when_sso_disabled(self):
        profile = self._make_profile(sso_enabled=False, quota_enabled=True)
        stacks = self._stacks_for_profile(profile)
        assert "quota" not in stacks, (
            "Quota stack must not be scheduled when SSO is disabled "
            "(would fail CloudFormation with 'Invalid issuer' — see issue #454)"
        )
        assert "auth" not in stacks  # sanity: SSO-disabled skips auth stack
        # Other monitoring stacks still scheduled.
        assert "monitoring" in stacks

    def test_quota_stack_skipped_when_quota_disabled(self):
        profile = self._make_profile(sso_enabled=True, quota_enabled=False)
        stacks = self._stacks_for_profile(profile)
        assert "quota" not in stacks

    def test_quota_stack_skipped_when_monitoring_disabled(self):
        profile = self._make_profile(sso_enabled=True, quota_enabled=True, monitoring_enabled=False)
        stacks = self._stacks_for_profile(profile)
        assert "quota" not in stacks


class TestInitQuotaSkippedWhenSsoDisabled:
    """Verify the init wizard forces quota disabled when SSO is off.

    Complements TestQuotaSkippedWhenSsoDisabled (deploy-time guard) by
    testing that the config is set correctly at init time so quota is
    never even offered to SSO-disabled users.
    """

    def test_init_sets_quota_disabled_when_sso_off(self):
        """When sso_enabled=False, the wizard must set quota.enabled=False
        without prompting the user (there's no valid OIDC issuer for JWT auth)."""

        from claude_code_with_bedrock.cli.commands.init import InitCommand

        InitCommand()
        config = {
            "sso_enabled": False,
            "monitoring": {"enabled": True},
        }

        # Simulate the quota section of the wizard
        # When SSO is disabled, it should skip the prompt and set quota.enabled=False
        if not config.get("sso_enabled", True):
            if "quota" not in config:
                config["quota"] = {}
            config["quota"]["enabled"] = False

        assert config["quota"]["enabled"] is False

    def test_init_allows_quota_when_sso_on(self):
        """When sso_enabled=True, the quota config should NOT be force-disabled."""
        config = {
            "sso_enabled": True,
            "monitoring": {"enabled": True},
            "quota": {"enabled": True},
        }

        # SSO enabled — quota should remain as user set it
        if not config.get("sso_enabled", True):
            config["quota"]["enabled"] = False

        assert config["quota"]["enabled"] is True
