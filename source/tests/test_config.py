# ABOUTME: Unit tests for Profile model and configuration management
# ABOUTME: Tests cross-region profile field handling and migration logic

"""Tests for the Profile model and Config manager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.config import Config, Profile


class TestProfileModel:
    """Tests for the Profile dataclass."""

    def test_cross_region_profile_field_exists(self):
        """Test that cross_region_profile field is available in Profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            cross_region_profile="us",
        )

        assert profile.cross_region_profile == "us"
        assert "cross_region_profile" in profile.to_dict()

    def test_cross_region_profile_optional(self):
        """Test that cross_region_profile is optional and defaults to None."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.cross_region_profile is None

    def test_from_dict_with_cross_region(self):
        """Test Profile.from_dict handles cross_region_profile field."""
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-east-1", "us-east-2", "us-west-2"],
            "cross_region_profile": "us",
            "monitoring_enabled": True,
            "analytics_enabled": True,
        }

        profile = Profile.from_dict(data)

        assert profile.cross_region_profile == "us"
        assert profile.allowed_bedrock_regions == ["us-east-1", "us-east-2", "us-west-2"]

    def test_migration_us_regions_to_cross_region_profile(self):
        """Test that existing US regions configs get 'us' cross-region profile."""
        # Legacy config without cross_region_profile but with US regions
        data = {
            "name": "legacy",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-west-2", "us-east-1"],
            "monitoring_enabled": False,
        }

        profile = Profile.from_dict(data)

        # Should auto-detect US profile
        assert profile.cross_region_profile == "us"

    def test_migration_non_us_regions_no_profile(self):
        """Test that non-US regions don't get auto-assigned a profile."""
        data = {
            "name": "eu-config",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "eu-west-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["eu-west-1", "eu-central-1"],
            "monitoring_enabled": False,
        }

        profile = Profile.from_dict(data)

        # Should not auto-assign profile for non-US regions
        assert profile.cross_region_profile is None

    def test_to_dict_includes_cross_region_profile(self):
        """Test that to_dict includes cross_region_profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            cross_region_profile="us",
            allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
        )

        result = profile.to_dict()

        assert result["cross_region_profile"] == "us"
        assert result["allowed_bedrock_regions"] == ["us-east-1", "us-east-2", "us-west-2"]


class TestConfigManager:
    """Tests for the Config manager."""

    def test_save_and_load_with_cross_region_profile(self):
        """Test that Config properly saves and loads cross_region_profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock the config directory
            config_file = Path(tmpdir) / "config.json"

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    # Create and save config
                    config = Config()
                    profile = Profile(
                        name="test",
                        provider_domain="test.okta.com",
                        client_id="test-client",
                        credential_storage="keyring",
                        aws_region="us-west-2",
                        identity_pool_name="test-pool",
                        cross_region_profile="us",
                        allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
                    )
                    config.add_profile(profile)
                    config.save()

                    # Load and verify
                    loaded_config = Config.load()
                    loaded_profile = loaded_config.get_profile("test")

                    assert loaded_profile is not None
                    assert loaded_profile.cross_region_profile == "us"
                    assert loaded_profile.allowed_bedrock_regions == ["us-east-1", "us-east-2", "us-west-2"]

    def test_backward_compatibility_load(self):
        """Test loading old config files without cross_region_profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            profiles_dir = Path(tmpdir) / "profiles"
            profiles_dir.mkdir()

            # Write new-style config
            config_data = {"schema_version": "2.0", "active_profile": "default", "profiles_dir": str(profiles_dir)}

            with open(config_file, "w") as f:
                json.dump(config_data, f)

            # Write profile without cross_region_profile (backward compatibility test)
            profile_data = {
                "name": "default",
                "provider_domain": "test.okta.com",
                "client_id": "test-client",
                "credential_storage": "session",
                "aws_region": "us-east-1",
                "identity_pool_name": "test-pool",
                "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
                "monitoring_enabled": True,
                "analytics_enabled": False,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }

            with open(profiles_dir / "default.json", "w") as f:
                json.dump(profile_data, f)

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    with patch.object(Config, "PROFILES_DIR", profiles_dir):
                        loaded_config = Config.load()
                        profile = loaded_config.get_profile()

                        assert profile is not None
                        # Should auto-detect US profile from regions
                        assert profile.cross_region_profile == "us"
