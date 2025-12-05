# ABOUTME: Tests for centralized model configuration system
# ABOUTME: Ensures correct model availability, IDs, regions, and descriptions

"""Tests for the centralized model configuration system."""

import pytest

from claude_code_with_bedrock.models import (
    CLAUDE_MODELS,
    DEFAULT_REGIONS,
    get_all_model_display_names,
    get_available_profiles_for_model,
    get_default_region_for_profile,
    get_destination_regions_for_model_profile,
    get_model_id_for_profile,
    get_profile_description,
    get_source_regions_for_model_profile,
)


class TestModelConfiguration:
    """Test the centralized model configuration system."""

    def test_default_regions_structure(self):
        """Test that DEFAULT_REGIONS has the expected structure."""
        expected_profiles = {"us", "europe", "apac", "us-gov"}
        assert set(DEFAULT_REGIONS.keys()) == expected_profiles

        # Verify regions are valid AWS regions
        assert DEFAULT_REGIONS["us"] == "us-east-1"
        assert DEFAULT_REGIONS["europe"] == "eu-west-3"
        assert DEFAULT_REGIONS["apac"] == "ap-northeast-1"
        assert DEFAULT_REGIONS["us-gov"] == "us-gov-west-1"

    def test_claude_models_structure(self):
        """Test that CLAUDE_MODELS has the expected structure."""
        expected_models = {
            "opus-4-1",
            "opus-4",
            "sonnet-4",
            "sonnet-4-5",
            "sonnet-4-5-govcloud",
            "sonnet-3-7",
            "sonnet-3-7-govcloud",
        }
        assert set(CLAUDE_MODELS.keys()) == expected_models

        # Verify each model has required fields
        for _model_key, model_config in CLAUDE_MODELS.items():
            assert "name" in model_config
            assert "base_model_id" in model_config
            assert "profiles" in model_config
            assert isinstance(model_config["profiles"], dict)
            assert len(model_config["profiles"]) > 0

    def test_model_profiles_structure(self):
        """Test that each model profile has the expected structure."""
        # Valid profile keys that can appear in model configurations
        valid_profile_keys = set(DEFAULT_REGIONS.keys()) | {"eu", "japan", "global"}

        for _model_key, model_config in CLAUDE_MODELS.items():
            for profile_key, profile_config in model_config["profiles"].items():
                # Verify required fields
                assert "model_id" in profile_config
                assert "description" in profile_config
                assert "source_regions" in profile_config
                assert "destination_regions" in profile_config

                # Verify profile_key is valid (either in DEFAULT_REGIONS or special profiles)
                assert profile_key in valid_profile_keys, f"Invalid profile_key: {profile_key}"

                # Verify model_id follows correct pattern
                model_id = profile_config["model_id"]
                if profile_key == "us":
                    assert model_id.startswith("us.anthropic.")
                elif profile_key in ["europe", "eu"]:
                    assert model_id.startswith("eu.anthropic.")
                elif profile_key == "apac":
                    assert model_id.startswith("apac.anthropic.")
                elif profile_key == "us-gov":
                    assert model_id.startswith("us-gov.anthropic.")
                elif profile_key == "japan":
                    assert model_id.startswith("jp.anthropic.")
                elif profile_key == "global":
                    assert model_id.startswith("global.anthropic.")

    def test_get_available_profiles_for_model(self):
        """Test getting available profiles for each model."""
        # Test valid models
        opus_4_1_profiles = get_available_profiles_for_model("opus-4-1")
        assert opus_4_1_profiles == ["us"]  # Opus 4.1 is US-only

        opus_4_profiles = get_available_profiles_for_model("opus-4")
        assert opus_4_profiles == ["us"]  # Opus 4 is US-only

        sonnet_4_profiles = get_available_profiles_for_model("sonnet-4")
        assert set(sonnet_4_profiles) == {"us", "europe", "apac", "global"}  # Sonnet 4 has global profile now

        sonnet_4_5_profiles = get_available_profiles_for_model("sonnet-4-5")
        assert set(sonnet_4_5_profiles) == {"us", "eu", "japan", "global"}  # Sonnet 4.5 regional profiles

        sonnet_4_5_govcloud_profiles = get_available_profiles_for_model("sonnet-4-5-govcloud")
        assert sonnet_4_5_govcloud_profiles == ["us-gov"]  # Sonnet 4.5 GovCloud

        sonnet_3_7_profiles = get_available_profiles_for_model("sonnet-3-7")
        assert set(sonnet_3_7_profiles) == {"us", "europe", "apac"}  # Sonnet 3.7 regional profiles

        sonnet_3_7_govcloud_profiles = get_available_profiles_for_model("sonnet-3-7-govcloud")
        assert sonnet_3_7_govcloud_profiles == ["us-gov"]  # Sonnet 3.7 GovCloud

        # Test invalid model
        assert get_available_profiles_for_model("invalid-model") == []

    def test_get_model_id_for_profile(self):
        """Test getting model IDs for specific profiles."""
        # Test US profiles
        assert get_model_id_for_profile("opus-4-1", "us") == "us.anthropic.claude-opus-4-1-20250805-v1:0"
        assert get_model_id_for_profile("sonnet-4", "us") == "us.anthropic.claude-sonnet-4-20250514-v1:0"

        # Test Europe profiles
        assert get_model_id_for_profile("sonnet-4", "europe") == "eu.anthropic.claude-sonnet-4-20250514-v1:0"
        assert get_model_id_for_profile("sonnet-3-7", "europe") == "eu.anthropic.claude-3-7-sonnet-20250219-v1:0"

        # Test APAC profiles
        assert get_model_id_for_profile("sonnet-4", "apac") == "apac.anthropic.claude-sonnet-4-20250514-v1:0"
        assert get_model_id_for_profile("sonnet-3-7", "apac") == "apac.anthropic.claude-3-7-sonnet-20250219-v1:0"

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_model_id_for_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_model_id_for_profile("opus-4-1", "europe")  # Opus 4.1 not available in Europe

    def test_get_default_region_for_profile(self):
        """Test getting default regions for profiles."""
        assert get_default_region_for_profile("us") == "us-east-1"
        assert get_default_region_for_profile("europe") == "eu-west-3"
        assert get_default_region_for_profile("apac") == "ap-northeast-1"

        # Test invalid profile
        with pytest.raises(ValueError, match="Unknown profile"):
            get_default_region_for_profile("invalid-profile")

    def test_get_source_regions_for_model_profile(self):
        """Test getting source regions for model profiles."""
        # Test valid combinations - these should not raise errors
        # (Currently empty lists since regions are TODO, but structure should work)
        source_regions = get_source_regions_for_model_profile("sonnet-4", "us")
        assert isinstance(source_regions, list)

        source_regions = get_source_regions_for_model_profile("sonnet-4", "europe")
        assert isinstance(source_regions, list)

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_source_regions_for_model_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_source_regions_for_model_profile("opus-4-1", "europe")

    def test_get_destination_regions_for_model_profile(self):
        """Test getting destination regions for model profiles."""
        # Test valid combinations - these should not raise errors
        dest_regions = get_destination_regions_for_model_profile("sonnet-4", "us")
        assert isinstance(dest_regions, list)

        dest_regions = get_destination_regions_for_model_profile("sonnet-4", "europe")
        assert isinstance(dest_regions, list)

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_destination_regions_for_model_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_destination_regions_for_model_profile("opus-4-1", "europe")

    def test_get_all_model_display_names(self):
        """Test getting all model display names."""
        display_names = get_all_model_display_names()

        # Should have entries for all model/profile combinations
        expected_entries = set()
        for _model_key, model_config in CLAUDE_MODELS.items():
            for _profile_key, profile_config in model_config["profiles"].items():
                expected_entries.add(profile_config["model_id"])

        assert set(display_names.keys()) == expected_entries

        # Test specific display names
        assert display_names["us.anthropic.claude-opus-4-1-20250805-v1:0"] == "Claude Opus 4.1"
        assert display_names["eu.anthropic.claude-sonnet-4-20250514-v1:0"] == "Claude Sonnet 4 (EUROPE)"
        assert display_names["apac.anthropic.claude-3-7-sonnet-20250219-v1:0"] == "Claude 3.7 Sonnet (APAC)"

    def test_get_profile_description(self):
        """Test getting profile descriptions."""
        # Test valid combinations
        desc = get_profile_description("opus-4-1", "us")
        assert desc == "US regions only"

        desc = get_profile_description("sonnet-4", "europe")
        assert desc == "European regions"

        desc = get_profile_description("sonnet-3-7", "apac")
        assert desc == "Asia-Pacific regions"

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_profile_description("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_profile_description("opus-4-1", "europe")

    def test_model_availability_consistency(self):
        """Test that model availability is consistent across functions."""
        for model_key in CLAUDE_MODELS.keys():
            available_profiles = get_available_profiles_for_model(model_key)

            for profile_key in available_profiles:
                # These should all work without raising exceptions
                model_id = get_model_id_for_profile(model_key, profile_key)
                description = get_profile_description(model_key, profile_key)
                source_regions = get_source_regions_for_model_profile(model_key, profile_key)
                dest_regions = get_destination_regions_for_model_profile(model_key, profile_key)

                # Verify types
                assert isinstance(model_id, str)
                assert isinstance(description, str)
                assert isinstance(source_regions, list)
                assert isinstance(dest_regions, list)

                # Verify model_id appears in display names
                display_names = get_all_model_display_names()
                assert model_id in display_names

    def test_regional_model_id_patterns(self):
        """Test that model IDs follow correct regional patterns."""
        for _model_key, model_config in CLAUDE_MODELS.items():
            base_model_id = model_config["base_model_id"]

            for profile_key, profile_config in model_config["profiles"].items():
                model_id = profile_config["model_id"]

                if profile_key == "us":
                    # US models should start with us.anthropic
                    assert model_id.startswith("us.anthropic.")
                    # Should match base model pattern but with us. prefix
                    expected = base_model_id.replace("anthropic.", "us.anthropic.")
                    assert model_id == expected

                elif profile_key == "europe":
                    # Europe models should start with eu.anthropic
                    assert model_id.startswith("eu.anthropic.")
                    # Should match base model pattern but with eu. prefix
                    expected = base_model_id.replace("anthropic.", "eu.anthropic.")
                    assert model_id == expected

                elif profile_key == "apac":
                    # APAC models should start with apac.anthropic
                    assert model_id.startswith("apac.anthropic.")
                    # Should match base model pattern but with apac. prefix
                    expected = base_model_id.replace("anthropic.", "apac.anthropic.")
                    assert model_id == expected

    def test_us_only_models_limitation(self):
        """Test that US-only models (Opus 4.1, Opus 4) are correctly limited."""
        us_only_models = ["opus-4-1", "opus-4"]

        for model_key in us_only_models:
            profiles = get_available_profiles_for_model(model_key)
            assert profiles == ["us"], f"{model_key} should only be available in US profile"

            # Should work for US
            model_id = get_model_id_for_profile(model_key, "us")
            assert model_id.startswith("us.anthropic.")

            # Should fail for other regions
            with pytest.raises(ValueError, match="not available in profile"):
                get_model_id_for_profile(model_key, "europe")

            with pytest.raises(ValueError, match="not available in profile"):
                get_model_id_for_profile(model_key, "apac")

    def test_global_models_availability(self):
        """Test that models with global profiles are correctly configured."""
        # Sonnet 4 has global profile
        sonnet_4_profiles = get_available_profiles_for_model("sonnet-4")
        assert "global" in sonnet_4_profiles, "sonnet-4 should have a global profile"
        assert set(sonnet_4_profiles) == {"us", "europe", "apac", "global"}

        # Test global profile works
        global_model_id = get_model_id_for_profile("sonnet-4", "global")
        assert global_model_id.startswith("global.anthropic.")

        # Sonnet 4.5 has global profile
        sonnet_4_5_profiles = get_available_profiles_for_model("sonnet-4-5")
        assert "global" in sonnet_4_5_profiles, "sonnet-4-5 should have a global profile"
        assert set(sonnet_4_5_profiles) == {"us", "eu", "japan", "global"}

        # Test global profile works for sonnet-4-5
        global_model_id = get_model_id_for_profile("sonnet-4-5", "global")
        assert global_model_id.startswith("global.anthropic.")

        # Sonnet 3.7 is regional only (no global profile)
        sonnet_3_7_profiles = get_available_profiles_for_model("sonnet-3-7")
        assert set(sonnet_3_7_profiles) == {"us", "europe", "apac"}

        # Should work for all regions
        for profile in ["us", "europe", "apac"]:
            model_id = get_model_id_for_profile("sonnet-3-7", profile)
            if profile == "us":
                assert model_id.startswith("us.anthropic.")
            elif profile == "europe":
                assert model_id.startswith("eu.anthropic.")
            elif profile == "apac":
                assert model_id.startswith("apac.anthropic.")
