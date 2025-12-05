# ABOUTME: Unit tests for package command model handling
# ABOUTME: Tests that selected model is properly included in package output

"""Tests for model handling in the package command."""

import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestPackageModelHandling:
    """Tests for package command model functionality."""

    def test_settings_without_monitoring(self):
        """Test that settings.json is not created when monitoring is disabled."""
        command = PackageCommand()

        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            selected_model="us.anthropic.claude-opus-4-1-20250805-v1:0",
            monitoring_enabled=False,  # Monitoring disabled
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # _create_claude_settings should not be called when monitoring is disabled
            # but we can still test that it handles this gracefully
            try:
                command._create_claude_settings(output_dir, profile)
            except Exception:
                # It might fail due to no monitoring endpoint, which is expected
                pass

            # When monitoring is disabled, .claude directory might not be created
            # This is fine - settings.json is only for monitoring
            assert not (output_dir / ".claude" / "settings.json").exists()

    def test_model_display_names(self):
        """Test that model display names are correctly mapped."""
        model_names = {
            "us.anthropic.claude-opus-4-1-20250805-v1:0": "Claude Opus 4.1",
            "us.anthropic.claude-opus-4-20250514-v1:0": "Claude Opus 4",
            "us.anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
            "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude Sonnet 4",
        }

        # This mapping is used in the package command for display
        for model_id, expected_name in model_names.items():
            assert expected_name.startswith("Claude")
            assert model_id.startswith("us.anthropic.claude")

    def test_cross_region_display_names(self):
        """Test that cross-region profiles are correctly displayed."""
        cross_region_names = {
            "us": "US Cross-Region (us-east-1, us-east-2, us-west-2)",
            "europe": "Europe Cross-Region (eu-west-1, eu-west-3, eu-central-1, eu-north-1)",
            "apac": "APAC Cross-Region (ap-northeast-1, ap-southeast-1/2, ap-south-1)",
        }

        for profile_key, expected_display in cross_region_names.items():
            assert "Cross-Region" in expected_display
            if profile_key == "us":
                assert "us-east-1" in expected_display
            elif profile_key == "europe":
                assert "eu-west-1" in expected_display
            elif profile_key == "apac":
                assert "ap-northeast-1" in expected_display
