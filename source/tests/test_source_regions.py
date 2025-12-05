# ABOUTME: Tests for source region selection functionality
# ABOUTME: Validates user-selected source regions and fallback logic

"""Tests for source region selection functionality."""

from unittest.mock import Mock

import pytest

from claude_code_with_bedrock.models import (
    CLAUDE_MODELS,
    get_source_region_for_profile,
    get_source_regions_for_model_profile,
)


class TestSourceRegionFunctionality:
    """Test source region selection and configuration."""

    def test_source_regions_available_for_models(self):
        """Test that source regions are available for all model/profile combinations."""
        for model_key, model_config in CLAUDE_MODELS.items():
            for profile_key, profile_config in model_config["profiles"].items():
                source_regions = profile_config["source_regions"]

                # Should have at least one source region available
                assert isinstance(source_regions, list)
                assert len(source_regions) > 0, f"No source regions for {model_key}/{profile_key}"

                # All source regions should be valid AWS region format
                for region in source_regions:
                    assert isinstance(region, str)
                    assert len(region) > 0
                    # Basic AWS region format check (e.g., us-west-2, eu-central-1)
                    assert "-" in region and len(region.split("-")) >= 2

    def test_get_source_regions_for_model_profile(self):
        """Test getting source regions for specific model/profile combinations."""
        # Test US model
        us_regions = get_source_regions_for_model_profile("opus-4-1", "us")
        assert isinstance(us_regions, list)
        assert len(us_regions) > 0
        assert "us-west-2" in us_regions  # Should include us-west-2

        # Test Europe model
        eu_regions = get_source_regions_for_model_profile("sonnet-4", "europe")
        assert isinstance(eu_regions, list)
        assert len(eu_regions) > 0
        assert any(region.startswith("eu-") for region in eu_regions)

        # Test APAC model
        apac_regions = get_source_regions_for_model_profile("sonnet-4", "apac")
        assert isinstance(apac_regions, list)
        assert len(apac_regions) > 0
        assert any(region.startswith("ap-") for region in apac_regions)

    def test_get_source_region_for_profile_with_selected_region(self):
        """Test source region selection when user has selected a specific region."""
        # Create mock profile with selected source region
        profile = Mock()
        profile.selected_source_region = "us-east-2"
        profile.cross_region_profile = "us"
        profile.aws_region = "us-east-1"

        # Should return the user-selected region
        result = get_source_region_for_profile(profile)
        assert result == "us-east-2"

    def test_get_source_region_for_profile_fallback_to_cross_region(self):
        """Test source region fallback to cross-region profile logic."""
        # Create mock profile without selected source region
        profile = Mock()
        profile.selected_source_region = None
        profile.cross_region_profile = "europe"
        profile.aws_region = "us-east-1"

        # Should fallback to cross-region profile default
        result = get_source_region_for_profile(profile)
        assert result == "eu-west-3"  # Default Europe region

    def test_get_source_region_for_profile_fallback_to_aws_region(self):
        """Test source region fallback to infrastructure region for US profiles."""
        # Create mock profile without selected source region, US profile
        profile = Mock()
        profile.selected_source_region = None
        profile.cross_region_profile = "us"
        profile.aws_region = "us-west-2"

        # Should fallback to infrastructure region
        result = get_source_region_for_profile(profile)
        assert result == "us-west-2"

    def test_get_source_region_for_profile_no_attributes(self):
        """Test source region when profile has minimal attributes."""
        # Create mock profile with only basic attributes
        profile = Mock()
        profile.selected_source_region = None
        profile.cross_region_profile = None
        profile.aws_region = "us-east-1"

        # Should fallback to infrastructure region
        result = get_source_region_for_profile(profile)
        assert result == "us-east-1"

    def test_source_region_regional_consistency(self):
        """Test that source regions are consistent with their profile regions."""
        test_cases = [
            ("opus-4-1", "us", "us-"),
            ("sonnet-4", "us", "us-"),
            ("sonnet-4", "europe", "eu-"),
            ("sonnet-4", "apac", "ap-"),
            ("sonnet-3-7", "europe", "eu-"),
            ("sonnet-3-7", "apac", "ap-"),
        ]

        for model_key, profile_key, expected_prefix in test_cases:
            source_regions = get_source_regions_for_model_profile(model_key, profile_key)

            # All source regions should match the expected regional prefix
            for region in source_regions:
                assert region.startswith(
                    expected_prefix
                ), f"Region {region} doesn't match expected prefix {expected_prefix} for {model_key}/{profile_key}"

    def test_source_region_invalid_model_profile_combinations(self):
        """Test that invalid model/profile combinations raise appropriate errors."""
        invalid_combinations = [
            ("opus-4-1", "europe"),  # Opus 4.1 not available in Europe
            ("opus-4-1", "apac"),  # Opus 4.1 not available in APAC
            ("opus-4", "europe"),  # Opus 4 not available in Europe
            ("opus-4", "apac"),  # Opus 4 not available in APAC
            ("invalid-model", "us"),  # Invalid model
            ("sonnet-4", "invalid-profile"),  # Invalid profile
        ]

        for model_key, profile_key in invalid_combinations:
            with pytest.raises(ValueError):
                get_source_regions_for_model_profile(model_key, profile_key)

    def test_source_region_profile_with_getattr_fallback(self):
        """Test source region selection with getattr-style profile access."""
        # Create mock profile that might not have all attributes
        profile = Mock()

        # Test when selected_source_region attribute doesn't exist
        del profile.selected_source_region
        profile.cross_region_profile = "europe"
        profile.aws_region = "us-east-1"

        # Should handle missing attribute gracefully and use fallback
        result = get_source_region_for_profile(profile)
        assert result == "eu-west-3"

    def test_all_models_have_source_regions(self):
        """Test that all models in CLAUDE_MODELS have source regions defined."""
        for model_key, model_config in CLAUDE_MODELS.items():
            for profile_key, profile_config in model_config["profiles"].items():
                assert (
                    "source_regions" in profile_config
                ), f"Model {model_key} profile {profile_key} missing source_regions"

                source_regions = profile_config["source_regions"]
                assert len(source_regions) > 0, f"Model {model_key} profile {profile_key} has empty source_regions"

    def test_source_regions_do_not_overlap_inappropriately(self):
        """Test that source regions are regionally appropriate."""
        regional_tests = {
            "us": ["us-east-1", "us-east-2", "us-west-1", "us-west-2"],
            "europe": ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-3"],
            "apac": [
                "ap-northeast-1",
                "ap-northeast-2",
                "ap-northeast-3",
                "ap-south-1",
                "ap-south-2",
                "ap-southeast-1",
                "ap-southeast-2",
            ],
        }

        for model_key, model_config in CLAUDE_MODELS.items():
            for profile_key, profile_config in model_config["profiles"].items():
                source_regions = profile_config["source_regions"]
                expected_regions = regional_tests.get(profile_key, [])

                if expected_regions:
                    # Check that all source regions are from the expected regional set
                    for region in source_regions:
                        assert region in expected_regions, (
                            f"Unexpected region {region} for {model_key}/{profile_key}. "
                            f"Expected one of {expected_regions}"
                        )
