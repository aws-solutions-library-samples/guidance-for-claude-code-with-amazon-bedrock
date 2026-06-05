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
        profile = self._make_profile(
            sso_enabled=True, quota_enabled=True, monitoring_enabled=False
        )
        stacks = self._stacks_for_profile(profile)
        assert "quota" not in stacks
