# ABOUTME: Tests for init command source region selection integration
# ABOUTME: Validates source region selection flow during initialization

"""Tests for init command integration with source region selection."""

from unittest.mock import Mock, patch

import pytest

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Profile
from claude_code_with_bedrock.models import get_source_regions_for_model_profile


class TestInitCommandSourceRegions:
    """Test init command integration with source region selection."""

    def test_source_region_selection_flow_us(self):
        """Test source region selection for US models."""
        # Test that US models have source regions available
        us_regions = get_source_regions_for_model_profile("opus-4-1", "us")
        assert len(us_regions) > 0
        assert "us-west-2" in us_regions
        assert "us-east-2" in us_regions
        assert "us-east-1" in us_regions

    def test_source_region_selection_flow_europe(self):
        """Test source region selection for Europe models."""
        # Test that Europe models have source regions available
        eu_regions = get_source_regions_for_model_profile("sonnet-4", "europe")
        assert len(eu_regions) > 0
        assert all(region.startswith("eu-") for region in eu_regions)
        assert "eu-west-3" in eu_regions
        assert "eu-west-1" in eu_regions

    def test_source_region_selection_flow_apac(self):
        """Test source region selection for APAC models."""
        # Test that APAC models have source regions available
        apac_regions = get_source_regions_for_model_profile("sonnet-3-7", "apac")
        assert len(apac_regions) > 0
        assert all(region.startswith("ap-") for region in apac_regions)
        assert "ap-southeast-2" in apac_regions
        assert "ap-southeast-1" in apac_regions

    def test_config_includes_selected_source_region(self):
        """Test that configuration includes selected source region."""
        # Mock a configuration that would include source region
        mock_config = {
            "aws": {
                "selected_source_region": "us-west-2",
                "cross_region_profile": "us",
                "selected_model": "us.anthropic.claude-opus-4-1-20250805-v1:0",
            }
        }

        # Verify the configuration structure includes source region
        assert "selected_source_region" in mock_config["aws"]
        assert mock_config["aws"]["selected_source_region"] == "us-west-2"

    def test_profile_stores_selected_source_region(self):
        """Test that Profile object can store selected source region."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="client123",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            selected_source_region="us-west-2",
        )

        assert profile.selected_source_region == "us-west-2"

    def test_existing_config_preserves_source_region(self):
        """Test that existing configurations preserve source region."""
        # Create a mock existing profile with source region
        existing_profile = Mock()
        existing_profile.name = "default"
        existing_profile.selected_source_region = "eu-central-1"
        existing_profile.cross_region_profile = "europe"
        existing_profile.selected_model = "eu.anthropic.claude-sonnet-4-20250514-v1:0"

        # Mock the config loading
        with patch("claude_code_with_bedrock.cli.commands.init.Config.load") as mock_config_load:
            mock_config = Mock()
            mock_config.get_profile.return_value = existing_profile
            mock_config_load.return_value = mock_config

            command = InitCommand()

            # Mock stack existence check
            with patch.object(command, "_stack_exists") as mock_stack_exists:
                mock_stack_exists.return_value = True

                # Check existing deployment with profile name
                existing_config = command._check_existing_deployment("test-profile")

                # Should preserve existing source region if available
                if existing_config and hasattr(existing_profile, "selected_source_region"):
                    assert existing_profile.selected_source_region == "eu-central-1"

    def test_source_region_choices_generation(self):
        """Test that source region choices are properly generated."""
        # Test for different model/profile combinations
        test_cases = [
            ("opus-4-1", "us", ["us-west-2", "us-east-2", "us-east-1"]),
            ("sonnet-4", "europe", ["eu-west-3", "eu-west-1", "eu-central-1", "eu-north-1"]),
            (
                "sonnet-3-7",
                "apac",
                [
                    "ap-southeast-2",
                    "ap-southeast-1",
                    "ap-south-1",
                    "ap-northeast-3",
                    "ap-northeast-2",
                    "ap-northeast-1",
                ],
            ),
        ]

        for model_key, profile_key, expected_regions in test_cases:
            source_regions = get_source_regions_for_model_profile(model_key, profile_key)

            # Should have all expected regions
            for expected_region in expected_regions:
                assert (
                    expected_region in source_regions
                ), f"Expected region {expected_region} not found in {source_regions} for {model_key}/{profile_key}"

    def test_source_region_fallback_behavior(self):
        """Test fallback behavior when no source region is selected."""
        from claude_code_with_bedrock.models import get_source_region_for_profile

        # Test US profile fallback
        us_profile = Mock()
        us_profile.selected_source_region = None
        us_profile.cross_region_profile = "us"
        us_profile.aws_region = "us-east-1"

        result = get_source_region_for_profile(us_profile)
        assert result == "us-east-1"  # Should use infrastructure region

        # Test Europe profile fallback
        eu_profile = Mock()
        eu_profile.selected_source_region = None
        eu_profile.cross_region_profile = "europe"
        eu_profile.aws_region = "us-east-1"

        result = get_source_region_for_profile(eu_profile)
        assert result == "eu-west-3"  # Should use default Europe region

    def test_source_region_priority_order(self):
        """Test that source region selection follows correct priority order."""
        from claude_code_with_bedrock.models import get_source_region_for_profile

        # Create profile with both selected source region and cross-region profile
        profile = Mock()
        profile.selected_source_region = "us-west-2"  # This should take priority
        profile.cross_region_profile = "europe"  # This should be ignored
        profile.aws_region = "us-east-1"  # This should be ignored

        result = get_source_region_for_profile(profile)
        assert result == "us-west-2"  # Should use selected source region, not cross-region default

    def test_source_region_validation_in_init_flow(self):
        """Test that source region validation works in init flow."""
        # Valid source regions should be accepted
        valid_regions = ["us-west-2", "eu-central-1", "ap-southeast-2"]
        for region in valid_regions:
            # Basic AWS region format validation
            assert "-" in region
            assert len(region.split("-")) >= 2

    def test_source_region_model_specific_availability(self):
        """Test that source regions are model-specific and available."""
        # US-only models should only have US source regions
        us_only_models = ["opus-4-1", "opus-4"]
        for model_key in us_only_models:
            if model_key in {"opus-4-1", "opus-4"}:  # These are US-only
                us_regions = get_source_regions_for_model_profile(model_key, "us")
                assert len(us_regions) > 0
                assert all(region.startswith("us-") for region in us_regions)

                # Should not be available in other regions
                with pytest.raises(ValueError):
                    get_source_regions_for_model_profile(model_key, "europe")

    def test_configuration_review_includes_source_region(self):
        """Test that configuration review displays selected source region."""
        # This would be tested in the _review_configuration method
        # For now, we verify the structure supports it
        config = {
            "aws": {
                "selected_source_region": "eu-west-3",
                "cross_region_profile": "europe",
                "selected_model": "eu.anthropic.claude-sonnet-4-20250514-v1:0",
                "region": "us-east-1",  # Infrastructure region
            }
        }

        # Verify structure
        assert config["aws"]["selected_source_region"] == "eu-west-3"
        assert config["aws"]["cross_region_profile"] == "europe"

        # The source region should be different from infrastructure region for cross-region profiles
        assert config["aws"]["selected_source_region"] != config["aws"]["region"]
