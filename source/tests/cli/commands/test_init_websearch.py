# ABOUTME: Tests for the optional web-search prompt in `ccwb init` (T5, AC7)
# ABOUTME: Flag persists via _save_configuration and round-trips via _check_existing_deployment

"""AC7: `ccwb init` shows an optional, skippable web-search prompt.

The prompt discloses the ~$7/1,000-queries cost and the us-east-1-only
constraint, sets `web_search_enabled`, and **round-trips on re-init**. Unlike
quota, it is offered in all auth modes (the gating to OIDC happens at deploy
time, not in the wizard).

These tests exercise the persistence + round-trip contract (the questionary
prompt itself is interactive and covered by the wizard flow); they assert that
`_save_configuration` maps the wizard's `web_search.enabled` to the profile and
that `_check_existing_deployment` reflects it back into the config dict.
"""

import json
from unittest.mock import patch

import pytest

from claude_code_with_bedrock.config import Config


@pytest.fixture
def cmd():
    from claude_code_with_bedrock.cli.commands.init import InitCommand

    return InitCommand()


@pytest.fixture
def base_aws():
    return {
        "region": "ap-southeast-2",
        "identity_pool_name": "demo-pool",
        "allowed_bedrock_regions": ["us-east-1"],
        "stacks": {},
        "cross_region_profile": "us",
        "selected_model": None,
    }


def _config_dirs(tmp_path, active="ws-test"):
    config_dir = tmp_path / ".ccwb"
    config_dir.mkdir()
    profiles_dir = config_dir / "profiles"
    profiles_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"schema_version": "2.0", "active_profile": active}))
    return config_dir, profiles_dir, config_file


class TestWebSearchPersistence:
    def test_enabled_flag_saved_to_profile(self, cmd, base_aws, tmp_path):
        config_data = {
            "sso_enabled": True,
            "aws": base_aws,
            "monitoring": {"enabled": False},
            "credential_storage": "session",
            "web_search": {"enabled": True},
        }
        config_dir, profiles_dir, config_file = _config_dirs(tmp_path)

        with (
            patch.object(Config, "CONFIG_DIR", config_dir),
            patch.object(Config, "CONFIG_FILE", config_file),
            patch.object(Config, "PROFILES_DIR", profiles_dir),
        ):
            cmd._save_configuration(config_data, "ws-test")
            saved = json.loads((profiles_dir / "ws-test.json").read_text())

        assert saved["web_search_enabled"] is True

    def test_declining_leaves_flag_false(self, cmd, base_aws, tmp_path):
        """No web_search block (user skipped/declined) → flag defaults False."""
        config_data = {
            "sso_enabled": True,
            "aws": base_aws,
            "monitoring": {"enabled": False},
            "credential_storage": "session",
            # no "web_search" key at all
        }
        config_dir, profiles_dir, config_file = _config_dirs(tmp_path)

        with (
            patch.object(Config, "CONFIG_DIR", config_dir),
            patch.object(Config, "CONFIG_FILE", config_file),
            patch.object(Config, "PROFILES_DIR", profiles_dir),
        ):
            cmd._save_configuration(config_data, "ws-test")
            saved = json.loads((profiles_dir / "ws-test.json").read_text())

        assert saved["web_search_enabled"] is False

    def test_explicit_false_leaves_flag_false(self, cmd, base_aws, tmp_path):
        config_data = {
            "sso_enabled": True,
            "aws": base_aws,
            "monitoring": {"enabled": False},
            "credential_storage": "session",
            "web_search": {"enabled": False},
        }
        config_dir, profiles_dir, config_file = _config_dirs(tmp_path)

        with (
            patch.object(Config, "CONFIG_DIR", config_dir),
            patch.object(Config, "CONFIG_FILE", config_file),
            patch.object(Config, "PROFILES_DIR", profiles_dir),
        ):
            cmd._save_configuration(config_data, "ws-test")
            saved = json.loads((profiles_dir / "ws-test.json").read_text())

        assert saved["web_search_enabled"] is False


class TestWebSearchRoundTrip:
    def test_reinit_round_trips_enabled_flag(self, cmd, base_aws, tmp_path):
        """A profile saved with web_search enabled reloads with the prompt defaulting on."""
        config_data = {
            "sso_enabled": True,
            "aws": base_aws,
            "monitoring": {"enabled": False},
            "credential_storage": "session",
            "web_search": {"enabled": True},
        }
        config_dir, profiles_dir, config_file = _config_dirs(tmp_path)

        with (
            patch.object(Config, "CONFIG_DIR", config_dir),
            patch.object(Config, "CONFIG_FILE", config_file),
            patch.object(Config, "PROFILES_DIR", profiles_dir),
        ):
            cmd._save_configuration(config_data, "ws-test")

            # Reload the profile and run the existing-deployment reader.
            existing = cmd._check_existing_deployment("ws-test")

        assert existing is not None
        assert existing.get("web_search", {}).get("enabled") is True

    def test_reinit_round_trips_disabled_flag(self, cmd, base_aws, tmp_path):
        config_data = {
            "sso_enabled": True,
            "aws": base_aws,
            "monitoring": {"enabled": False},
            "credential_storage": "session",
            "web_search": {"enabled": False},
        }
        config_dir, profiles_dir, config_file = _config_dirs(tmp_path)

        with (
            patch.object(Config, "CONFIG_DIR", config_dir),
            patch.object(Config, "CONFIG_FILE", config_file),
            patch.object(Config, "PROFILES_DIR", profiles_dir),
        ):
            cmd._save_configuration(config_data, "ws-test")
            existing = cmd._check_existing_deployment("ws-test")

        assert existing is not None
        assert existing.get("web_search", {}).get("enabled") is False
