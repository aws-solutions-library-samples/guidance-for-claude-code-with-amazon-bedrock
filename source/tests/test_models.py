# ABOUTME: Tests for centralized model configuration system
# ABOUTME: Ensures correct model availability, IDs, regions, and descriptions

"""Tests for the centralized model configuration system."""

import pytest

from claude_code_with_bedrock.models import (
    CLAUDE_MODELS,
    DEFAULT_REGIONS,
    get_all_model_display_names,
    get_available_profiles_for_model,
    get_claude_code_alias,
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
        expected_profiles = {"us", "eu", "europe", "apac", "us-gov"}
        assert set(DEFAULT_REGIONS.keys()) == expected_profiles

        # Verify regions are valid AWS regions
        assert DEFAULT_REGIONS["us"] == "us-east-1"
        assert DEFAULT_REGIONS["eu"] == "eu-west-1"
        assert DEFAULT_REGIONS["apac"] == "ap-northeast-1"
        assert DEFAULT_REGIONS["us-gov"] == "us-gov-west-1"

    def test_claude_models_structure(self):
        """Test that CLAUDE_MODELS has the expected structure."""
        expected_models = {
            "sonnet-4-6",
            "opus-4-7",
            "opus-4-6",
            "opus-4-5",
            "opus-4-1",
            "opus-4",
            "sonnet-4",
            "sonnet-4-5",
            "sonnet-4-5-govcloud",
            "sonnet-3-7",
            "sonnet-3-7-govcloud",
            "haiku-4-5",
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
        valid_profile_keys = set(DEFAULT_REGIONS.keys()) | {"eu", "jp", "global", "au"}

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
                elif profile_key in ["eu", "eu"]:
                    assert model_id.startswith("eu.anthropic.")
                elif profile_key == "apac":
                    assert model_id.startswith("apac.anthropic.")
                elif profile_key == "us-gov":
                    assert model_id.startswith("us-gov.anthropic.")
                elif profile_key == "jp":
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
        assert set(sonnet_4_profiles) == {"us", "eu", "apac", "global"}  # Sonnet 4 has global profile now

        sonnet_4_5_profiles = get_available_profiles_for_model("sonnet-4-5")
        assert set(sonnet_4_5_profiles) == {"us", "eu", "jp", "au", "global"}  # Sonnet 4.5 regional profiles

        sonnet_4_5_govcloud_profiles = get_available_profiles_for_model("sonnet-4-5-govcloud")
        assert sonnet_4_5_govcloud_profiles == ["us-gov"]  # Sonnet 4.5 GovCloud

        sonnet_3_7_profiles = get_available_profiles_for_model("sonnet-3-7")
        assert set(sonnet_3_7_profiles) == {"us", "eu", "apac"}  # Sonnet 3.7 regional profiles

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
        assert get_model_id_for_profile("sonnet-4", "eu") == "eu.anthropic.claude-sonnet-4-20250514-v1:0"
        assert get_model_id_for_profile("sonnet-3-7", "eu") == "eu.anthropic.claude-3-7-sonnet-20250219-v1:0"

        # Test AU profiles
        assert get_model_id_for_profile("opus-4-6", "au") == "au.anthropic.claude-opus-4-6-v1"

        # Test APAC profiles
        assert get_model_id_for_profile("sonnet-4", "apac") == "apac.anthropic.claude-sonnet-4-20250514-v1:0"
        assert get_model_id_for_profile("sonnet-3-7", "apac") == "apac.anthropic.claude-3-7-sonnet-20250219-v1:0"

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_model_id_for_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_model_id_for_profile("opus-4-1", "eu")  # Opus 4.1 not available in Europe

    def test_get_default_region_for_profile(self):
        """Test getting default regions for profiles."""
        assert get_default_region_for_profile("us") == "us-east-1"
        assert get_default_region_for_profile("eu") == "eu-west-1"
        assert get_default_region_for_profile("apac") == "ap-northeast-1"

        # Test invalid profile
        with pytest.raises(ValueError, match="Unknown profile"):
            get_default_region_for_profile("invalid-profile")

    def test_get_source_regions_for_model_profile(self):
        """Test getting source regions for model profiles."""
        # Test valid combinations - these should not raise errors
        # (Currently empty lists since regions are TODO, but structure should work)
        source_regions = get_source_regions_for_model_profile("sonnet-4", "us")
        assert isinstance(source_regions, (list, tuple))

        source_regions = get_source_regions_for_model_profile("sonnet-4", "eu")
        assert isinstance(source_regions, (list, tuple))

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_source_regions_for_model_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_source_regions_for_model_profile("opus-4-1", "eu")

    def test_get_destination_regions_for_model_profile(self):
        """Test getting destination regions for model profiles."""
        # Test valid combinations - these should not raise errors
        dest_regions = get_destination_regions_for_model_profile("sonnet-4", "us")
        assert isinstance(dest_regions, (list, tuple))

        dest_regions = get_destination_regions_for_model_profile("sonnet-4", "eu")
        assert isinstance(dest_regions, (list, tuple))

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_destination_regions_for_model_profile("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_destination_regions_for_model_profile("opus-4-1", "eu")

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
        assert display_names["eu.anthropic.claude-sonnet-4-20250514-v1:0"] == "Claude Sonnet 4 (EU)"
        assert display_names["apac.anthropic.claude-3-7-sonnet-20250219-v1:0"] == "Claude 3.7 Sonnet (APAC)"

    def test_get_profile_description(self):
        """Test getting profile descriptions."""
        # Test valid combinations
        desc = get_profile_description("opus-4-1", "us")
        assert desc == "US regions only"

        desc = get_profile_description("sonnet-4", "eu")
        assert desc == "European regions"

        desc = get_profile_description("sonnet-3-7", "apac")
        assert desc == "Asia-Pacific regions"

        # Test invalid combinations
        with pytest.raises(ValueError, match="Unknown model"):
            get_profile_description("invalid-model", "us")

        with pytest.raises(ValueError, match="not available in profile"):
            get_profile_description("opus-4-1", "eu")

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
                assert isinstance(source_regions, (list, tuple))
                assert isinstance(dest_regions, (list, tuple))

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

                elif profile_key == "eu":
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
                get_model_id_for_profile(model_key, "eu")

            with pytest.raises(ValueError, match="not available in profile"):
                get_model_id_for_profile(model_key, "apac")

    def test_global_models_availability(self):
        """Test that models with global profiles are correctly configured."""
        # Sonnet 4 has global profile
        sonnet_4_profiles = get_available_profiles_for_model("sonnet-4")
        assert "global" in sonnet_4_profiles, "sonnet-4 should have a global profile"
        assert set(sonnet_4_profiles) == {"us", "eu", "apac", "global"}

        # Test global profile works
        global_model_id = get_model_id_for_profile("sonnet-4", "global")
        assert global_model_id.startswith("global.anthropic.")

        # Sonnet 4.5 has global profile
        sonnet_4_5_profiles = get_available_profiles_for_model("sonnet-4-5")
        assert "global" in sonnet_4_5_profiles, "sonnet-4-5 should have a global profile"
        assert set(sonnet_4_5_profiles) == {"us", "eu", "jp", "au", "global"}

        # Test global profile works for sonnet-4-5
        global_model_id = get_model_id_for_profile("sonnet-4-5", "global")
        assert global_model_id.startswith("global.anthropic.")

        # Sonnet 3.7 is regional only (no global profile)
        sonnet_3_7_profiles = get_available_profiles_for_model("sonnet-3-7")
        assert set(sonnet_3_7_profiles) == {"us", "eu", "apac"}

        # Should work for all regions
        for profile in ["us", "eu", "apac"]:
            model_id = get_model_id_for_profile("sonnet-3-7", profile)
            if profile == "us":
                assert model_id.startswith("us.anthropic.")
            elif profile == "eu":
                assert model_id.startswith("eu.anthropic.")
            elif profile == "apac":
                assert model_id.startswith("apac.anthropic.")


class TestGetAllBedrockRegions:
    """Test the get_all_bedrock_regions helper."""

    def test_returns_sorted_list(self):
        from claude_code_with_bedrock.models import get_all_bedrock_regions
        regions = get_all_bedrock_regions()
        assert regions == sorted(regions)

    def test_contains_major_regions(self):
        from claude_code_with_bedrock.models import get_all_bedrock_regions
        regions = get_all_bedrock_regions()
        # Must include key commercial regions
        assert "us-east-1" in regions
        assert "us-west-2" in regions
        assert "eu-west-1" in regions
        assert "ap-southeast-2" in regions
        assert "eu-central-1" in regions

    def test_no_duplicates(self):
        from claude_code_with_bedrock.models import get_all_bedrock_regions
        regions = get_all_bedrock_regions()
        assert len(regions) == len(set(regions))

    def test_all_regions_valid_format(self):
        """All regions should match AWS region format."""
        import re
        from claude_code_with_bedrock.models import get_all_bedrock_regions
        pattern = re.compile(r'^[a-z]{2}(-gov)?-(north|south|east|west|central|northeast|southeast)-\d+$')
        for region in get_all_bedrock_regions():
            assert pattern.match(region), f"Invalid region format: {region}"

    def test_consistent_with_model_data(self):
        """Every destination region in CLAUDE_MODELS should appear (excluding sentinels)."""
        from claude_code_with_bedrock.models import CLAUDE_MODELS, get_all_bedrock_regions
        regions = set(get_all_bedrock_regions())
        for model_config in CLAUDE_MODELS.values():
            for profile_config in model_config.get("profiles", {}).values():
                for r in profile_config.get("destination_regions", []):
                    if not r.startswith("all-"):  # Skip sentinel values
                        assert r in regions, f"Region {r} missing from get_all_bedrock_regions()"


class TestResolveModelForTier:
    """Test resolve_model_for_tier with real admin profile scenarios."""

    def test_us_admin_gets_latest_models(self):
        from claude_code_with_bedrock.models import resolve_model_for_tier

        haiku = resolve_model_for_tier("haiku", "us")
        sonnet = resolve_model_for_tier("sonnet", "us")
        opus = resolve_model_for_tier("opus", "us")

        assert haiku is not None
        assert sonnet is not None
        assert opus is not None
        assert "us." in haiku
        assert "us." in sonnet
        assert "us." in opus

    def test_europe_admin_gets_eu_models(self):
        """Config stores 'europe' but newer models use 'eu' key."""
        from claude_code_with_bedrock.models import resolve_model_for_tier

        haiku = resolve_model_for_tier("haiku", "eu")
        sonnet = resolve_model_for_tier("sonnet", "eu")
        opus = resolve_model_for_tier("opus", "eu")
        assert haiku is not None and "eu." in haiku
        assert sonnet is not None and "eu." in sonnet
        assert opus is not None and "eu." in opus

    def test_eu_admin_gets_eu_models(self):
        from claude_code_with_bedrock.models import resolve_model_for_tier

        haiku = resolve_model_for_tier("haiku", "eu")
        sonnet = resolve_model_for_tier("sonnet", "eu")
        opus = resolve_model_for_tier("opus", "eu")
        assert haiku is not None and "eu." in haiku
        assert sonnet is not None and "eu." in sonnet
        assert opus is not None and "eu." in opus

    def test_au_admin_gets_au_models_no_global_fallback(self):
        """AU is data-residency: must NOT fall back to global."""
        from claude_code_with_bedrock.models import resolve_model_for_tier

        haiku = resolve_model_for_tier("haiku", "au")
        sonnet = resolve_model_for_tier("sonnet", "au")
        opus = resolve_model_for_tier("opus", "au")
        assert haiku is not None and "au." in haiku, f"AU haiku should be au.*, got {haiku}"
        assert sonnet is not None and "au." in sonnet, f"AU sonnet should be au.*, got {sonnet}"
        assert opus is not None and "au." in opus, f"AU opus should be au.*, got {opus}"

    def test_jp_admin_gets_jp_models_no_global_fallback(self):
        """JP is data-residency: must NOT fall back to global."""
        from claude_code_with_bedrock.models import resolve_model_for_tier

        haiku = resolve_model_for_tier("haiku", "jp")
        sonnet = resolve_model_for_tier("sonnet", "jp")
        opus = resolve_model_for_tier("opus", "jp")
        assert haiku is not None and "jp." in haiku, f"JP haiku should be jp.*, got {haiku}"
        assert sonnet is not None and "jp." in sonnet, f"JP sonnet should be jp.*, got {sonnet}"
        # JP has no Opus profile — falls back to best available jp.* model
        assert opus is not None and "jp." in opus, f"JP opus should fall back to jp.*, got {opus}"

    def test_japan_alias_resolves_to_jp(self):
        from claude_code_with_bedrock.models import resolve_model_for_tier

        sonnet = resolve_model_for_tier("sonnet", "jp")
        assert sonnet is not None and "jp." in sonnet

    def test_global_admin_gets_global_prefix(self):
        from claude_code_with_bedrock.models import resolve_model_for_tier

        sonnet = resolve_model_for_tier("sonnet", "global")
        opus = resolve_model_for_tier("opus", "global")
        haiku = resolve_model_for_tier("haiku", "global")
        assert "global." in sonnet
        assert "global." in opus
        assert "global." in haiku

    def test_apac_falls_back_to_global_for_opus(self):
        """APAC is not strict data-residency, can fall back to global."""
        from claude_code_with_bedrock.models import resolve_model_for_tier

        opus = resolve_model_for_tier("opus", "apac")
        assert opus is not None and "global." in opus

    def test_get_claude_code_alias_sonnet(self):
        """Sonnet CRIS model IDs resolve to 'sonnet' alias."""
        assert get_claude_code_alias("us.anthropic.claude-sonnet-4-6") == "sonnet"
        assert get_claude_code_alias("eu.anthropic.claude-sonnet-4-6") == "sonnet"

    def test_get_claude_code_alias_opus(self):
        """Opus CRIS model IDs resolve to 'opus' alias."""
        assert get_claude_code_alias("us.anthropic.claude-opus-4-7") == "opus"
        assert get_claude_code_alias("eu.anthropic.claude-opus-4-6-v1") == "opus"

    def test_get_claude_code_alias_haiku(self):
        """Haiku CRIS model IDs resolve to 'haiku' alias."""
        assert get_claude_code_alias("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "haiku"

    def test_get_claude_code_alias_unknown(self):
        """Unknown model IDs return None."""
        assert get_claude_code_alias("us.anthropic.claude-unknown-99") is None

    def test_data_residency_prefixes_match_api(self):
        """Every prefix from the live API should resolve all available tiers."""
        from claude_code_with_bedrock.models import resolve_model_for_tier

        # These must resolve to their own prefix (not global/us)
        for prefix in ["us", "eu", "au", "global"]:
            for tier in ["haiku", "sonnet", "opus"]:
                result = resolve_model_for_tier(tier, prefix)
                if result is not None:
                    assert f"{prefix}." in result, \
                        f"resolve_model_for_tier('{tier}', '{prefix}') = '{result}' wrong prefix"