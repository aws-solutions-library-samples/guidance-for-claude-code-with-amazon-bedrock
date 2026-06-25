"""Tests for managed-settings model lock opt-out behavior (issue #665).

Ensures that ANTHROPIC_MODEL and ANTHROPIC_DEFAULT_*_MODEL env vars are only
written to managed-settings.json when lock_default_model is True.
"""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestModelLockManagedSettings:
    """Verify model env vars are gated on lock_default_model."""

    def _make_profile(self, lock_default_model=False, selected_model="us.anthropic.claude-sonnet-4-6:0"):
        return Profile(
            name="Test",
            provider_domain="test.okta.com",
            client_id="client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            selected_model=selected_model,
            model_alias="sonnet",
            cross_region_profile="us",
            lock_default_model=lock_default_model,
            settings_target="managed",
        )

    def _generate_and_read_settings(self, profile):
        """Call _create_claude_settings and return the generated JSON dict."""
        cmd = PackageCommand()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            cmd._create_claude_settings(output_dir, profile)
            settings_path = output_dir / "claude-settings" / "managed-settings.json"
            assert settings_path.exists(), f"Expected {settings_path} to be created"
            return json.loads(settings_path.read_text(encoding="utf-8"))

    def test_model_env_vars_absent_when_lock_false(self):
        """When lock_default_model=False, managed-settings must NOT contain ANTHROPIC_MODEL."""
        profile = self._make_profile(lock_default_model=False)
        settings = self._generate_and_read_settings(profile)
        env = settings.get("env", {})
        assert "ANTHROPIC_MODEL" not in env, (
            "ANTHROPIC_MODEL should not be in managed-settings when lock_default_model=False"
        )
        assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env
        assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env
        assert "ANTHROPIC_SMALL_FAST_MODEL" not in env

    def test_model_env_vars_present_when_lock_true(self):
        """When lock_default_model=True, managed-settings MUST contain model env vars."""
        profile = self._make_profile(lock_default_model=True)
        settings = self._generate_and_read_settings(profile)
        env = settings.get("env", {})
        assert "ANTHROPIC_MODEL" in env, "ANTHROPIC_MODEL should be in managed-settings when lock_default_model=True"
        assert env["ANTHROPIC_MODEL"] == "sonnet"
        # At least some tier models should be set
        assert "ANTHROPIC_DEFAULT_SONNET_MODEL" in env or "ANTHROPIC_SMALL_FAST_MODEL" in env

    def test_lock_default_model_defaults_to_false(self):
        """Profile with no explicit lock_default_model should default to False."""
        profile = Profile(
            name="Test",
            provider_domain="test.okta.com",
            client_id="client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            selected_model="us.anthropic.claude-sonnet-4-6:0",
            model_alias="sonnet",
            cross_region_profile="us",
            settings_target="managed",
        )
        assert profile.lock_default_model is False, "lock_default_model should default to False"

    def test_backward_compat_old_profiles_default_unlocked(self):
        """Profiles saved before lock_default_model field existed should behave as unlocked."""
        profile = self._make_profile(lock_default_model=False)
        settings = self._generate_and_read_settings(profile)
        env = settings.get("env", {})
        # The critical assertion: old behavior (no lock field = False) means NO model lock
        assert "ANTHROPIC_MODEL" not in env

    def test_no_model_env_when_no_selected_model(self):
        """When no model is selected, no model env vars regardless of lock setting."""
        profile = self._make_profile(lock_default_model=True, selected_model=None)
        settings = self._generate_and_read_settings(profile)
        env = settings.get("env", {})
        assert "ANTHROPIC_MODEL" not in env
