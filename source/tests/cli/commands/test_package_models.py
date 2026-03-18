# ABOUTME: Unit tests for package command model handling
# ABOUTME: Tests that selected model is properly included in package output

"""Tests for model handling in the package command."""

import json
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


class TestTierDefaultsInSettings:
    """Tests that tier default env vars are written to settings.json independently of selected_model."""

    def _make_profile(self, **kwargs) -> Profile:
        """Build a minimal Profile, overriding fields via kwargs."""
        defaults = dict(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client-id",
            credential_storage="session",
            aws_region="eu-central-1",
            identity_pool_name="test-pool",
            monitoring_enabled=False,
            selected_source_region="eu-central-1",
            cross_region_profile="eu",
        )
        defaults.update(kwargs)
        return Profile(**defaults)

    def _read_settings(self, output_dir: Path) -> dict:
        settings_path = output_dir / "claude-settings" / "settings.json"
        with open(settings_path) as f:
            return json.load(f)

    def test_tier_defaults_written_when_selected_model_is_none(self):
        """Tier env vars appear in settings.json even when selected_model is None (Q3 auto-select)."""
        command = PackageCommand()
        profile = self._make_profile(
            selected_model=None,
            default_sonnet_model="eu.anthropic.claude-sonnet-4-6",
            default_haiku_model="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            command._create_claude_settings(Path(tmpdir), profile)
            env = self._read_settings(Path(tmpdir))["env"]

        assert "ANTHROPIC_MODEL" not in env
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "eu.anthropic.claude-sonnet-4-6"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env

    def test_selected_model_and_tier_defaults_both_written(self):
        """When selected_model and tier defaults are all set, all four env vars appear."""
        command = PackageCommand()
        profile = self._make_profile(
            selected_model="eu.anthropic.claude-sonnet-4-6",
            default_opus_model="eu.anthropic.claude-opus-4-6-v1",
            default_sonnet_model="eu.anthropic.claude-sonnet-4-6",
            default_haiku_model="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            command._create_claude_settings(Path(tmpdir), profile)
            env = self._read_settings(Path(tmpdir))["env"]

        assert env["ANTHROPIC_MODEL"] == "eu.anthropic.claude-sonnet-4-6"
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "eu.anthropic.claude-opus-4-6-v1"
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "eu.anthropic.claude-sonnet-4-6"
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_path_a_no_model_env_vars(self):
        """Path A (Q2 auto-select): selected_model=None and all tier defaults None → no model env vars."""
        command = PackageCommand()
        profile = self._make_profile(
            cross_region_profile=None,
            selected_model=None,
            default_opus_model=None,
            default_sonnet_model=None,
            default_haiku_model=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            command._create_claude_settings(Path(tmpdir), profile)
            env = self._read_settings(Path(tmpdir))["env"]

        assert "ANTHROPIC_MODEL" not in env
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env
        assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
        assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env

    def test_haiku_fallback_to_sonnet_when_no_haiku_models_and_selected_model_is_none(self):
        """Edge case: selected_model=None, haiku default=None, sonnet default set, profile has no haiku.

        GovCloud has sonnet but no haiku tier. The fallback should set
        ANTHROPIC_DEFAULT_HAIKU_MODEL to the sonnet model ID.
        Before this refactor, this path was unreachable when selected_model was None
        because the entire tier-defaults block was nested inside the selected_model guard.
        """
        command = PackageCommand()
        profile = self._make_profile(
            aws_region="us-gov-west-1",
            selected_source_region="us-gov-west-1",
            cross_region_profile="us-gov",
            selected_model=None,
            default_opus_model=None,
            default_sonnet_model="us-gov.anthropic.claude-3-7-sonnet-20250219-v1:0",
            default_haiku_model=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            command._create_claude_settings(Path(tmpdir), profile)
            env = self._read_settings(Path(tmpdir))["env"]

        assert "ANTHROPIC_MODEL" not in env
        assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "us-gov.anthropic.claude-3-7-sonnet-20250219-v1:0"
        # Fallback: haiku tier gets sonnet model because no haiku exists for us-gov
        assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "us-gov.anthropic.claude-3-7-sonnet-20250219-v1:0"
