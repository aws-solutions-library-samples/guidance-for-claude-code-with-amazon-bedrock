# ABOUTME: Unit tests for selected_model field in Profile configuration
# ABOUTME: Tests model selection persistence and backward compatibility

"""Tests for the selected_model field and model configuration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.config import Config, Profile


class TestSelectedModelField:
    """Tests for the selected_model field in Profile."""

    def test_selected_model_field_exists(self):
        """Test that selected_model field is available in Profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            selected_model="us.anthropic.claude-opus-4-1-20250805-v1:0",
        )

        assert profile.selected_model == "us.anthropic.claude-opus-4-1-20250805-v1:0"
        assert "selected_model" in profile.to_dict()

    def test_selected_model_optional(self):
        """Test that selected_model is optional and defaults to None."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

        assert profile.selected_model is None

    def test_from_dict_with_selected_model(self):
        """Test Profile.from_dict handles selected_model field."""
        data = {
            "name": "test",
            "provider_domain": "test.okta.com",
            "client_id": "test-client",
            "credential_storage": "session",
            "aws_region": "us-east-1",
            "identity_pool_name": "test-pool",
            "allowed_bedrock_regions": ["us-east-1", "us-east-2", "us-west-2"],
            "cross_region_profile": "us",
            "selected_model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "monitoring_enabled": True,
        }

        profile = Profile.from_dict(data)

        assert profile.selected_model == "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
        assert profile.cross_region_profile == "us"

    def test_to_dict_includes_selected_model(self):
        """Test that to_dict includes selected_model."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            cross_region_profile="europe",
            selected_model="us.anthropic.claude-sonnet-4-20250514-v1:0",
            allowed_bedrock_regions=["eu-west-1", "eu-west-3", "eu-central-1"],
        )

        result = profile.to_dict()

        assert result["selected_model"] == "us.anthropic.claude-sonnet-4-20250514-v1:0"
        assert result["cross_region_profile"] == "europe"

    def test_all_claude_models(self):
        """Test that all Claude model IDs are valid."""
        model_ids = [
            "us.anthropic.claude-opus-4-1-20250805-v1:0",
            "us.anthropic.claude-opus-4-20250514-v1:0",
            "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
        ]

        for model_id in model_ids:
            profile = Profile(
                name="test",
                provider_domain="test.okta.com",
                client_id="test-client",
                credential_storage="session",
                aws_region="us-east-1",
                identity_pool_name="test-pool",
                selected_model=model_id,
            )

            assert profile.selected_model == model_id

    def test_cognito_user_pool_id_field(self):
        """Test that cognito_user_pool_id field is properly handled."""
        profile = Profile(
            name="test",
            provider_domain="auth.us-east-1.amazoncognito.com",
            client_id="test-client",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            provider_type="cognito",
            cognito_user_pool_id="us-east-1_ABC123def",
            selected_model="us.anthropic.claude-opus-4-1-20250805-v1:0",
        )

        assert profile.provider_type == "cognito"
        assert profile.cognito_user_pool_id == "us-east-1_ABC123def"
        assert profile.selected_model == "us.anthropic.claude-opus-4-1-20250805-v1:0"

        # Test to_dict includes all fields
        result = profile.to_dict()
        assert result["provider_type"] == "cognito"
        assert result["cognito_user_pool_id"] == "us-east-1_ABC123def"
        assert result["selected_model"] == "us.anthropic.claude-opus-4-1-20250805-v1:0"


class TestConfigManagerWithModels:
    """Tests for Config manager with model selection."""

    def test_save_and_load_with_selected_model(self):
        """Test that Config properly saves and loads selected_model."""
        with tempfile.TemporaryDirectory() as tmpdir:
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
                        selected_model="us.anthropic.claude-opus-4-1-20250805-v1:0",
                        allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
                    )
                    config.add_profile(profile)
                    config.save()

                    # Load and verify
                    loaded_config = Config.load()
                    loaded_profile = loaded_config.get_profile("test")

                    assert loaded_profile is not None
                    assert loaded_profile.selected_model == "us.anthropic.claude-opus-4-1-20250805-v1:0"
                    assert loaded_profile.cross_region_profile == "us"

    def test_backward_compatibility_without_model(self):
        """Test loading old config files without selected_model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            profiles_dir = Path(tmpdir) / "profiles"
            profiles_dir.mkdir()

            # Write new-style config
            config_data = {"schema_version": "2.0", "active_profile": "default", "profiles_dir": str(profiles_dir)}

            with open(config_file, "w") as f:
                json.dump(config_data, f)

            # Write profile without selected_model (backward compatibility test)
            profile_data = {
                "name": "default",
                "provider_domain": "test.okta.com",
                "client_id": "test-client",
                "credential_storage": "session",
                "aws_region": "us-east-1",
                "identity_pool_name": "test-pool",
                "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
                "cross_region_profile": "us",
                "monitoring_enabled": True,
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
                        # selected_model should be None for old configs
                        assert profile.selected_model is None
                        # Other fields should be preserved
                        assert profile.cross_region_profile == "us"
                        assert profile.allowed_bedrock_regions == ["us-east-1", "us-west-2"]

    def test_cognito_config_with_model(self):
        """Test Cognito User Pool configuration with model selection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch.object(Config, "CONFIG_FILE", config_file):
                with patch.object(Config, "CONFIG_DIR", Path(tmpdir)):
                    # Create Cognito-based config with model
                    config = Config()
                    profile = Profile(
                        name="cognito-test",
                        provider_domain="auth.us-east-1.amazoncognito.com",
                        client_id="cognito-client-id",
                        credential_storage="session",
                        aws_region="us-east-1",
                        identity_pool_name="cognito-pool",
                        provider_type="cognito",
                        cognito_user_pool_id="us-east-1_TestPool",
                        cross_region_profile="us",
                        selected_model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                        allowed_bedrock_regions=["us-east-1", "us-east-2", "us-west-2"],
                    )
                    config.add_profile(profile)
                    config.save()

                    # Load and verify all fields
                    loaded_config = Config.load()
                    loaded_profile = loaded_config.get_profile("cognito-test")

                    assert loaded_profile is not None
                    assert loaded_profile.provider_type == "cognito"
                    assert loaded_profile.cognito_user_pool_id == "us-east-1_TestPool"
                    assert loaded_profile.selected_model == "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
                    assert loaded_profile.cross_region_profile == "us"
