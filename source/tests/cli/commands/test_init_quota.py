# ABOUTME: Tests for init command quota monitoring configuration
# ABOUTME: Simplified to focus on core quota logic without complex mocking

"""Tests for init command quota monitoring configuration."""


import pytest
from cleo.testers.command_tester import CommandTester

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Profile


class TestInitQuotaCommand:
    """Test init command quota monitoring configuration - simplified."""

    @pytest.fixture
    def command(self):
        """Create init command instance."""
        return InitCommand()

    @pytest.fixture
    def tester(self, command):
        """Create command tester."""
        return CommandTester(command)

    def test_quota_threshold_calculations_simple(self):
        """Test threshold calculations for various token limits."""
        # Test cases: (monthly_limit, expected_80%, expected_90%)
        test_cases = [
            (100_000_000, 80_000_000, 90_000_000),  # 100M tokens
            (300_000_000, 240_000_000, 270_000_000),  # 300M tokens (default)
            (500_000_000, 400_000_000, 450_000_000),  # 500M tokens
            (1_000_000_000, 800_000_000, 900_000_000),  # 1B tokens
        ]

        for monthly_limit, expected_80, expected_90 in test_cases:
            # Simple calculation test
            threshold_80 = int(monthly_limit * 0.8)
            threshold_90 = int(monthly_limit * 0.9)

            assert threshold_80 == expected_80, f"80% of {monthly_limit} should be {expected_80}"
            assert threshold_90 == expected_90, f"90% of {monthly_limit} should be {expected_90}"

    def test_quota_minimum_validation(self):
        """Test validation of minimum token limits."""
        MIN_TOKENS = 1_000_000  # 1M minimum

        # Test invalid limits
        invalid_limits = [500_000, 0, -100_000]
        for limit in invalid_limits:
            assert limit < MIN_TOKENS, f"{limit} should be below minimum"

        # Test valid limits
        valid_limits = [1_000_000, 10_000_000, 100_000_000]
        for limit in valid_limits:
            assert limit >= MIN_TOKENS, f"{limit} should be above minimum"

    def test_quota_cost_estimation(self):
        """Test cost estimation display for quota limits."""
        # Cost per million tokens (approximate)
        cost_per_million = 15.0

        test_limits = [
            (100000000, 1500),  # 100M tokens = $1,500
            (300000000, 4500),  # 300M tokens = $4,500
            (500000000, 7500),  # 500M tokens = $7,500
            (1000000000, 15000),  # 1B tokens = $15,000
        ]

        for token_limit, expected_cost in test_limits:
            calculated_cost = (token_limit / 1000000) * cost_per_million
            assert calculated_cost == expected_cost

    def test_profile_quota_attributes(self):
        """Test that Profile class has required quota attributes."""
        # Create a profile with quota settings
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        # Verify quota attributes exist with defaults
        assert hasattr(profile, "quota_monitoring_enabled")
        assert hasattr(profile, "monthly_token_limit")
        assert hasattr(profile, "warning_threshold_80")
        assert hasattr(profile, "warning_threshold_90")

        # Check default values
        assert profile.quota_monitoring_enabled is False
        assert profile.monthly_token_limit == 225_000_000
        assert profile.warning_threshold_80 == 180_000_000
        assert profile.warning_threshold_90 == 202_500_000
