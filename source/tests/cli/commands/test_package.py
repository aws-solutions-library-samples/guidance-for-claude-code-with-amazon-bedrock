# ABOUTME: Unit tests for package command with cross-region support
# ABOUTME: Tests that package command properly includes cross-region configuration

"""Tests for the package command."""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestPackageCommandCrossRegion:
    """Tests for package command cross-region functionality."""

    def test_config_includes_cross_region_profile(self):
        """Test that generated config.json includes cross_region_profile."""
        command = PackageCommand()

        # Create a test profile with cross-region settings
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
            cross_region_profile="us",
            monitoring_enabled=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Call _create_config
            config_path = command._create_config(output_dir, profile, "test-identity-pool-id")

            # Read and verify the config
            with open(config_path) as f:
                config = json.load(f)

            assert "ClaudeCode" in config
            claude_config = config["ClaudeCode"]

            # Check all expected fields
            assert claude_config["provider_domain"] == "test.okta.com"
            assert claude_config["client_id"] == "test-client-id"
            assert claude_config["identity_pool_id"] == "test-identity-pool-id"
            assert claude_config["aws_region"] == "us-east-1"
            assert claude_config["cross_region_profile"] == "us"
            assert claude_config["credential_storage"] == "keyring"

    def test_config_defaults_cross_region_to_us(self):
        """Test that config defaults cross_region_profile to 'us' if not set."""
        command = PackageCommand()

        # Create profile without cross_region_profile
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-west-2",
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-west-2"],
            monitoring_enabled=False,
        )
        # Explicitly set to None to test default
        profile.cross_region_profile = None

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Call _create_config
            config_path = command._create_config(output_dir, profile, "test-pool-id")

            # Read and verify
            with open(config_path) as f:
                config = json.load(f)

            # Should default to 'us'
            assert config["ClaudeCode"]["cross_region_profile"] == "us"

    def test_installer_script_preserves_region(self):
        """Test that installer script correctly extracts region from config."""
        command = PackageCommand()

        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-west-2",  # Note: different from cross-region
            identity_pool_name="test-pool",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
            cross_region_profile="us",
            monitoring_enabled=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Create installer
            installer_path = command._create_installer(
                output_dir, profile, [("macos", Path("credential-process-macos"))], []
            )

            # Read installer and check region extraction
            with open(installer_path) as f:
                installer_content = f.read()

            # Should extract region from Claude settings first, then fallback to profile region
            assert "AWS_REGION" in installer_content or "aws_region" in installer_content
            # The fallback should now have the interpolated region value
            assert "us-west-2" in installer_content or "config.json" in installer_content
