# ABOUTME: Tests for centralized model configuration system
# ABOUTME: Ensures correct model availability, IDs, regions, and descriptions

"""Tests for the centralized model configuration system."""

import pytest

from claude_code_with_bedrock.models import (
    CLAUDE_MODELS,
    DEFAULT_REGIONS,
    get_all_destination_regions_for_profile,
    get_all_model_display_names,
    get_all_source_regions,
    get_available_profiles_for_model,
    get_default_region_for_profile,
    get_destination_regions_for_model_profile,
    get_model_id_for_profile,
    get_models_for_tier,
    get_profile_description,
    get_profiles_for_region,
    get_source_regions_for_model_profile,
)


class TestModelConfiguration:
    """Test the centralized model configuration system."""

    def test_default_regions_structure(self):
        """Test that DEFAULT_REGIONS has the expected structure."""
        expected_profiles = {"us", "europe", "eu", "apac", "japan", "australia", "global", "us-gov"}
        assert set(DEFAULT_REGIONS.keys()) == expected_profiles

        # Verify regions are valid AWS regions
        assert DEFAULT_REGIONS["us"] == "us-east-1"
        assert DEFAULT_REGIONS["europe"] == "eu-west-3"
        assert DEFAULT_REGIONS["eu"] == "eu-west-3"
        assert DEFAULT_REGIONS["apac"] == "ap-northeast-1"
        assert DEFAULT_REGIONS["japan"] == "ap-northeast-1"
        assert DEFAULT_REGIONS["australia"] == "ap-southeast-2"
        assert DEFAULT_REGIONS["global"] == "us-east-1"
        assert DEFAULT_REGIONS["us-gov"] == "us-gov-west-1"

    def test_claude_models_structure(self):
        """Test that CLAUDE_MODELS has the expected structure."""
        expected_models = {
            "opus-4-6",
            "opus-4-1",
            "opus-4",
            "opus-4-5",
            "opus-4-6",
            "sonnet-4",
            "sonnet-4-5",
            "sonnet-4-5-govcloud",
            "sonnet-4-6",
            "haiku-4-5",
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
        valid_profile_keys = set(DEFAULT_REGIONS.keys()) | {"eu", "japan", "global", "au"}

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
                elif profile_key == "au":
                    assert model_id.startswith("au.anthropic.")

    def test_get_available_profiles_for_model(self):
        """Test getting available profiles for each model."""
        # Test valid models
        opus_4_6_profiles = get_available_profiles_for_model("opus-4-6")
        assert set(opus_4_6_profiles) == {"us", "eu", "au", "global"}  # Opus 4.6 has global and regional profiles

        opus_4_1_profiles = get_available_profiles_for_model("opus-4-1")
        assert opus_4_1_profiles == ["us"]  # Opus 4.1 is US-only

        opus_4_profiles = get_available_profiles_for_model("opus-4")
        assert opus_4_profiles == ["us"]  # Opus 4 is US-only

        sonnet_4_profiles = get_available_profiles_for_model("sonnet-4")
        assert set(sonnet_4_profiles) == {"us", "europe", "apac", "global"}  # Sonnet 4 has global profile now

        sonnet_4_5_profiles = get_available_profiles_for_model("sonnet-4-5")
        assert set(sonnet_4_5_profiles) == {"us", "eu", "japan", "australia", "global"}  # Sonnet 4.5 regional profiles

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
        assert get_model_id_for_profile("opus-4-6", "us") == "us.anthropic.claude-opus-4-6-v1"
        assert get_model_id_for_profile("opus-4-1", "us") == "us.anthropic.claude-opus-4-1-20250805-v1:0"
        assert get_model_id_for_profile("sonnet-4", "us") == "us.anthropic.claude-sonnet-4-20250514-v1:0"

        # Test Global profiles
        assert get_model_id_for_profile("opus-4-6", "global") == "global.anthropic.claude-opus-4-6-v1"

        # Test Europe profiles
        assert get_model_id_for_profile("opus-4-6", "eu") == "eu.anthropic.claude-opus-4-6-v1"
        assert get_model_id_for_profile("sonnet-4", "europe") == "eu.anthropic.claude-sonnet-4-20250514-v1:0"
        assert get_model_id_for_profile("sonnet-3-7", "europe") == "eu.anthropic.claude-3-7-sonnet-20250219-v1:0"

        # Test AU profiles
        assert get_model_id_for_profile("opus-4-6", "au") == "au.anthropic.claude-opus-4-6-v1"

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
        assert display_names["global.anthropic.claude-opus-4-6-v1"] == "Claude Opus 4.6 (GLOBAL)"
        assert display_names["us.anthropic.claude-opus-4-6-v1"] == "Claude Opus 4.6"
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

                elif profile_key == "eu":
                    assert model_id.startswith("eu.anthropic.")
                    expected = base_model_id.replace("anthropic.", "eu.anthropic.")
                    assert model_id == expected

                elif profile_key == "apac":
                    # APAC models should start with apac.anthropic
                    assert model_id.startswith("apac.anthropic.")
                    # Should match base model pattern but with apac. prefix
                    expected = base_model_id.replace("anthropic.", "apac.anthropic.")
                    assert model_id == expected

                elif profile_key == "japan":
                    assert model_id.startswith("jp.anthropic.")

                elif profile_key == "australia":
                    assert model_id.startswith("au.anthropic.")

                elif profile_key == "global":
                    assert model_id.startswith("global.anthropic.")
                    expected = base_model_id.replace("anthropic.", "global.anthropic.")
                    assert model_id == expected

                elif profile_key == "us-gov":
                    assert model_id.startswith("us-gov.anthropic.")
                    expected = base_model_id.replace("anthropic.", "us-gov.anthropic.")
                    assert model_id == expected

    def test_get_all_source_regions(self):
        """Test that get_all_source_regions returns a non-empty sorted list of known regions."""
        regions = get_all_source_regions()

        assert isinstance(regions, list)
        assert len(regions) > 0
        # Verify sorted order
        assert regions == sorted(regions)
        # Verify well-known regions are present
        assert "us-east-1" in regions
        assert "eu-central-1" in regions
        assert "ap-northeast-1" in regions
        # All entries should look like valid AWS region codes
        for r in regions:
            assert "-" in r, f"Expected region code with dash: {r}"

    def test_get_profiles_for_region_eu(self):
        """Test that eu-central-1 returns EU-related profiles including global."""
        profiles = get_profiles_for_region("eu-central-1")

        assert isinstance(profiles, list)
        assert len(profiles) > 0
        # eu-central-1 must appear in eu (or europe) and global profiles
        assert "eu" in profiles or "europe" in profiles
        assert "global" in profiles
        # Should NOT contain us or japan profiles
        assert "us" not in profiles
        assert "japan" not in profiles
        # eu and europe should not both appear (deduplication)
        assert not ("eu" in profiles and "europe" in profiles)

    def test_get_profiles_for_region_us(self):
        """Test that us-east-1 returns US-related profiles including global."""
        profiles = get_profiles_for_region("us-east-1")

        assert isinstance(profiles, list)
        assert len(profiles) > 0
        assert "us" in profiles
        assert "global" in profiles
        # Should NOT contain eu or japan profiles
        assert "eu" not in profiles
        assert "europe" not in profiles
        assert "japan" not in profiles

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

    def test_get_models_for_tier(self):
        """Test that get_models_for_tier returns correct models per tier and profile."""
        # haiku/eu should return haiku-4-5 with the eu model id
        haiku_eu = get_models_for_tier("haiku", "eu")
        assert len(haiku_eu) > 0
        model_keys = [mk for mk, _, _ in haiku_eu]
        assert "haiku-4-5" in model_keys
        model_ids = [mid for _, _, mid in haiku_eu]
        assert "eu.anthropic.claude-haiku-4-5-20251001-v1:0" in model_ids

        # haiku/europe resolves via eu↔europe alias — same result as haiku/eu
        haiku_europe = get_models_for_tier("haiku", "europe")
        assert len(haiku_europe) > 0
        assert [mid for _, _, mid in haiku_europe] == [mid for _, _, mid in haiku_eu]

        # haiku/apac — haiku-4-5 has no apac profile and no alias → empty
        assert get_models_for_tier("haiku", "apac") == []

        # haiku/us-gov — no haiku model for GovCloud → empty
        assert get_models_for_tier("haiku", "us-gov") == []

        # sonnet/eu should return at least one model, all with eu. prefix
        sonnet_eu = get_models_for_tier("sonnet", "eu")
        assert len(sonnet_eu) > 0
        for _mk, _name, mid in sonnet_eu:
            assert mid.startswith("eu.anthropic.")

        # opus/us-gov returns empty (no GovCloud opus model)
        assert get_models_for_tier("opus", "us-gov") == []

        # unknown tier returns empty
        assert get_models_for_tier("unknown", "us") == []

    def test_get_all_destination_regions_for_profile_eu(self):
        """Test that EU profile returns only EU destination regions."""
        regions = get_all_destination_regions_for_profile("eu")
        assert isinstance(regions, list)
        assert len(regions) > 0
        assert regions == sorted(regions)
        # All should be eu-* regions
        for r in regions:
            assert r.startswith("eu-"), f"Non-EU region in EU profile: {r}"
        # Should NOT contain US or APAC regions
        assert "us-east-1" not in regions
        assert "ap-northeast-1" not in regions

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
        assert set(sonnet_4_5_profiles) == {"us", "eu", "japan", "australia", "global"}

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
