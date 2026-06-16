# ABOUTME: Tests for shared CLI utility helpers
# ABOUTME: Verifies clear_cached_credentials and get_codebuild_region

"""Tests for cli/utils/helpers.py."""

import configparser
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_code_with_bedrock.cli.utils.helpers import (
    CODEBUILD_WINDOWS_REGIONS,
    clear_cached_credentials,
    find_nearest_codebuild_region,
    get_codebuild_region,
)


class TestClearCachedCredentials:
    """Tests for clear_cached_credentials utility."""

    def test_clears_ccwb_credential_section(self, tmp_path):
        """Removes credential section created by ccwb."""
        cred_file = tmp_path / ".aws" / "credentials"
        cred_file.parent.mkdir(parents=True)
        cred_file.write_text(
            "[my-profile]\n"
            "credential_process = /usr/local/bin/claude-code-with-bedrock credential-process --profile my-profile\n"
        )
        with patch("claude_code_with_bedrock.cli.utils.helpers.Path.home", return_value=tmp_path):
            result = clear_cached_credentials("my-profile")
        assert result is True
        # Verify section is gone
        config = configparser.ConfigParser()
        config.read(cred_file)
        assert "my-profile" not in config

    def test_does_not_clear_unrelated_credentials(self, tmp_path):
        """Does not touch credential sections not created by ccwb."""
        cred_file = tmp_path / ".aws" / "credentials"
        cred_file.parent.mkdir(parents=True)
        cred_file.write_text(
            "[my-profile]\n"
            "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"  # pragma: allowlist secret
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"  # pragma: allowlist secret
        )
        with patch("claude_code_with_bedrock.cli.utils.helpers.Path.home", return_value=tmp_path):
            result = clear_cached_credentials("my-profile")
        assert result is False

    def test_returns_false_when_no_credentials_file(self, tmp_path):
        """Returns False when ~/.aws/credentials doesn't exist."""
        with patch("claude_code_with_bedrock.cli.utils.helpers.Path.home", return_value=tmp_path):
            result = clear_cached_credentials("any-profile")
        assert result is False

    def test_returns_false_when_profile_not_in_credentials(self, tmp_path):
        """Returns False when profile section doesn't exist."""
        cred_file = tmp_path / ".aws" / "credentials"
        cred_file.parent.mkdir(parents=True)
        cred_file.write_text("[other-profile]\naws_access_key_id = test\n")
        with patch("claude_code_with_bedrock.cli.utils.helpers.Path.home", return_value=tmp_path):
            result = clear_cached_credentials("my-profile")
        assert result is False


class TestGetCodebuildRegion:
    """Tests for get_codebuild_region utility."""

    def test_returns_aws_region_by_default(self):
        """Returns profile.aws_region when no codebuild_region set."""
        profile = MagicMock()
        profile.aws_region = "us-west-2"
        profile.codebuild_region = None
        assert get_codebuild_region(profile) == "us-west-2"

    def test_returns_codebuild_region_when_set(self):
        """Returns codebuild_region override when explicitly set."""
        profile = MagicMock()
        profile.aws_region = "us-west-2"
        profile.codebuild_region = "us-east-1"
        assert get_codebuild_region(profile) == "us-east-1"

    def test_falls_back_when_codebuild_region_missing(self):
        """Falls back to aws_region when attr doesn't exist."""
        profile = MagicMock(spec=[])
        profile.aws_region = "eu-west-1"
        assert get_codebuild_region(profile) == "eu-west-1"

    def test_real_profile_override(self):
        """A real Profile with codebuild_region set resolves to the override.

        Uses the actual dataclass (not a mock) so the test fails if the
        codebuild_region field is ever removed from Profile or dropped by
        from_dict's field-filter.
        """
        from claude_code_with_bedrock.config import Profile

        profile = Profile.from_dict(
            {
                "name": "t",
                "provider_domain": "none",
                "client_id": "x",
                "identity_pool_name": "tp",
                "aws_region": "ap-southeast-1",
                "codebuild_region": "ap-southeast-2",
                "enable_codebuild": True,
            }
        )
        assert get_codebuild_region(profile) == "ap-southeast-2"

    def test_real_profile_fallback(self):
        """A real Profile without codebuild_region falls back to aws_region."""
        from claude_code_with_bedrock.config import Profile

        profile = Profile.from_dict(
            {
                "name": "t",
                "provider_domain": "none",
                "client_id": "x",
                "identity_pool_name": "tp",
                "aws_region": "us-west-2",
            }
        )
        assert get_codebuild_region(profile) == "us-west-2"


class TestFindNearestCodebuildRegion:
    """Tests for find_nearest_codebuild_region (cross-region CodeBuild fallback)."""

    def test_supported_region_returns_itself(self):
        """A supported region is returned unchanged."""
        for region in CODEBUILD_WINDOWS_REGIONS:
            assert find_nearest_codebuild_region(region) == region

    def test_ap_southeast_1_maps_to_ap_southeast_2(self):
        """Singapore (unsupported) maps to Sydney (supported, same sub-geo)."""
        assert find_nearest_codebuild_region("ap-southeast-1") == "ap-southeast-2"

    def test_eu_unsupported_stays_in_eu(self):
        """An unsupported EU region maps to a supported EU region."""
        assert find_nearest_codebuild_region("eu-south-1").startswith("eu-")
        assert find_nearest_codebuild_region("eu-west-3").startswith("eu-")

    def test_ap_unsupported_stays_in_ap(self):
        """An unsupported AP region maps to a supported AP region (not a false 'a*' match)."""
        assert find_nearest_codebuild_region("ap-south-1").startswith("ap-")

    def test_no_continent_match_falls_back_to_us_east_1(self):
        """Regions with no supported same-continent peer fall back to us-east-1."""
        # af-* and me-* have no supported region sharing their continent token.
        assert find_nearest_codebuild_region("af-south-1") == "us-east-1"
        assert find_nearest_codebuild_region("me-central-1") == "us-east-1"
        # "af" must NOT false-match "ap-*" on the shared leading 'a'.
        assert not find_nearest_codebuild_region("af-south-1").startswith("ap-")

    def test_result_is_always_supported(self):
        """Whatever region is returned must itself be deployable."""
        for region in ["ap-southeast-1", "eu-south-1", "ca-central-1", "af-south-1", "me-central-1"]:
            assert find_nearest_codebuild_region(region) in CODEBUILD_WINDOWS_REGIONS
