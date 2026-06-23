# ABOUTME: Unit tests for managed-settings.json deployment feature (#538)
# ABOUTME: Tests Profile backward compat, filename selection, and installer script logic

"""Tests for managed-settings deployment in the package command."""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


class TestProfileSettingsTarget:
    """Tests for Profile settings_target field and backward compatibility."""

    def test_profile_defaults_to_user_target(self):
        """New profiles default to settings_target='user'."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        assert profile.settings_target == "user"

    def test_profile_accepts_managed_target(self):
        """Profiles can be created with settings_target='managed'."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            settings_target="managed",
        )
        assert profile.settings_target == "managed"

    def test_profile_without_settings_target_field_is_backward_compatible(self):
        """Profiles loaded from old configs without settings_target work correctly."""
        # Simulate loading an old profile dict that lacks the field
        old_profile_data = {
            "name": "legacy",
            "provider_domain": "legacy.okta.com",
            "client_id": "old-client",
            "credential_storage": "keyring",
            "aws_region": "eu-west-1",
            "identity_pool_name": "legacy-pool",
        }
        profile = Profile(**old_profile_data)
        # Should default to "user" — no KeyError or crash
        assert profile.settings_target == "user"

    def test_getattr_settings_target_fallback(self):
        """getattr with default works for settings_target on any profile."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )
        # This is how the package command reads it
        target = getattr(profile, "settings_target", "user")
        assert target == "user"


class TestGenerateClaudeSettings:
    """Tests for _create_claude_settings filename selection."""

    def _make_profile(self, settings_target="user", monitoring_enabled=False):
        """Helper to create a test profile."""
        return Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            monitoring_enabled=monitoring_enabled,
            settings_target=settings_target,
        )

    def test_user_target_creates_settings_json(self):
        """settings_target='user' writes to claude-settings/settings.json."""
        command = PackageCommand()
        profile = self._make_profile(settings_target="user")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            assert (output_dir / "claude-settings" / "settings.json").exists()
            assert not (output_dir / "claude-settings" / "managed-settings.json").exists()

    def test_managed_target_creates_managed_settings_json(self):
        """settings_target='managed' writes to claude-settings/managed-settings.json."""
        command = PackageCommand()
        profile = self._make_profile(settings_target="managed")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            assert (output_dir / "claude-settings" / "managed-settings.json").exists()
            assert not (output_dir / "claude-settings" / "settings.json").exists()

    def test_managed_settings_contains_correct_content(self):
        """managed-settings.json has the same Bedrock config as settings.json would."""
        command = PackageCommand()
        profile = self._make_profile(settings_target="managed")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            settings_path = output_dir / "claude-settings" / "managed-settings.json"
            with open(settings_path) as f:
                settings = json.load(f)

            # Must contain Bedrock env vars
            assert settings["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
            assert settings["env"]["AWS_REGION"] == "us-east-1"
            assert "__CREDENTIAL_PROCESS_PATH__" in settings["env"]["AWS_CREDENTIAL_PROCESS"]

    def test_user_target_settings_content_unchanged(self):
        """Default user target still produces correct settings.json content."""
        command = PackageCommand()
        profile = self._make_profile(settings_target="user")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path) as f:
                settings = json.load(f)

            assert settings["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
            assert settings["env"]["AWS_REGION"] == "us-east-1"


class TestInstallerScriptManagedSettings:
    """Tests for install.sh template handling of managed-settings.json."""

    def _get_installer_content(self, profile):
        """Generate installer and return its content."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Create minimal required structure
            (output_dir / "claude-settings").mkdir()
            (output_dir / "config.json").write_text("{}")

            # Generate settings based on profile target
            command._create_claude_settings(output_dir, profile)

            # Build a mock executables list
            built_executables = [("darwin-arm64", output_dir / "credential-process")]
            (output_dir / "credential-process").touch()

            # Generate installer
            installer_path = command._create_installer(output_dir, profile, built_executables, built_otel_helpers=[])

            return installer_path.read_text(encoding="utf-8")

    def test_managed_installer_contains_elevation_check(self):
        """Installer checks for root when managed-settings.json is present."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            settings_target="managed",
            monitoring_enabled=False,
        )

        content = self._get_installer_content(profile)

        # Should contain managed-settings handling
        assert "managed-settings.json" in content
        assert "id -u" in content or "sudo" in content

    def test_user_installer_has_merge_logic(self):
        """User-mode installer merges into existing settings rather than overwriting."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            settings_target="user",
            monitoring_enabled=False,
        )

        content = self._get_installer_content(profile)

        # Should contain merge logic
        assert "deep_merge" in content or "Merge" in content.lower()

    def test_user_installer_creates_backup(self):
        """User-mode installer backs up existing settings before merge."""
        profile = Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            settings_target="user",
            monitoring_enabled=False,
        )

        content = self._get_installer_content(profile)

        assert "backup" in content.lower()


class TestInstallerMergeLogic:
    """Tests for the deep merge logic in the installer."""

    def test_deep_merge_preserves_user_keys(self):
        """The merge function preserves keys that only exist in the user's config."""

        def deep_merge(base, override):
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        existing = {
            "env": {"MY_CUSTOM_VAR": "keep_me", "AWS_REGION": "old-region"},
            "myCustomSetting": True,
        }
        incoming = {
            "env": {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"},
        }

        merged = deep_merge(existing, incoming)

        # User's custom key preserved
        assert merged["myCustomSetting"] is True
        # User's env var preserved
        assert merged["env"]["MY_CUSTOM_VAR"] == "keep_me"
        # Incoming values applied
        assert merged["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
        # Conflicting key overridden by incoming
        assert merged["env"]["AWS_REGION"] == "us-east-1"

    def test_deep_merge_handles_nested_dicts(self):
        """Deep merge recurses into nested dictionaries."""

        def deep_merge(base, override):
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        existing = {"env": {"A": "1", "B": "2"}, "permissions": {"deny": ["rm"]}}
        incoming = {"env": {"C": "3"}, "permissions": {"deny": ["rm", "sudo"]}}

        merged = deep_merge(existing, incoming)

        assert merged["env"] == {"A": "1", "B": "2", "C": "3"}
        # Non-dict values are overwritten (not merged)
        assert merged["permissions"]["deny"] == ["rm", "sudo"]


class TestInstallerSudoOwnership:
    """Regression tests: running install.sh with sudo must not create root-owned user files."""

    def _get_installer_script(self, profile, settings_target="user"):
        """Generate an install.sh string for the given profile."""
        profile.settings_target = settings_target
        cmd = PackageCommand()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            # create dummy files so the method doesn't fail on missing artefacts
            (output_dir / "claude-settings").mkdir()
            if settings_target == "managed":
                (output_dir / "claude-settings" / "managed-settings.json").write_text("{}")
            else:
                (output_dir / "claude-settings" / "settings.json").write_text("{}")
            installer = cmd._create_installer(output_dir, profile, [], [])
            return installer.read_text(encoding="utf-8")

    def _make_profile(self):
        return Profile(
            name="Test",
            provider_domain="test.okta.com",
            client_id="client-id",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
        )

    def test_installer_defines_actual_home_from_sudo_user(self):
        """install.sh must resolve ACTUAL_HOME from SUDO_USER when present."""
        script = self._get_installer_script(self._make_profile())
        assert 'ACTUAL_HOME=$(eval echo "~$SUDO_USER")' in script
        assert "ACTUAL_USER=$SUDO_USER" in script or 'ACTUAL_USER="$SUDO_USER"' in script

    def test_installer_falls_back_to_home_when_no_sudo(self):
        """install.sh must fall back to $HOME/$USER when SUDO_USER is not set."""
        script = self._get_installer_script(self._make_profile())
        assert 'ACTUAL_HOME="$HOME"' in script
        assert 'ACTUAL_USER="$USER"' in script

    def test_installer_user_files_use_actual_home(self):
        """User-space paths (~/claude-code-with-bedrock, ~/.claude, ~/.aws) must use ACTUAL_HOME."""
        script = self._get_installer_script(self._make_profile())
        # Must not hard-code ~ for user-space directories
        assert "mkdir -p ~/claude-code-with-bedrock" not in script
        assert "mkdir -p ~/.claude" not in script
        assert "mkdir -p ~/.aws" not in script
        # Must use ACTUAL_HOME variable instead
        assert "$ACTUAL_HOME/claude-code-with-bedrock" in script
        assert "$ACTUAL_HOME/.claude" in script
        assert "$ACTUAL_HOME/.aws" in script

    def test_installer_managed_settings_does_not_exit_if_not_root(self):
        """Managed settings must not exit 1 when script runs as non-root; use inline sudo instead."""
        profile = self._make_profile()
        script = self._get_installer_script(profile, settings_target="managed")
        # Old bad pattern must be gone
        assert "Re-run the installer with: sudo ./install.sh" not in script
        # New inline-sudo pattern must be present
        assert "sudo mkdir" in script or "sudo tee" in script

    def test_installer_chowns_files_when_sudo_user_set(self):
        """install.sh must chown user-space files back to ACTUAL_USER after sudo writes."""
        script = self._get_installer_script(self._make_profile())
        assert 'chown "$ACTUAL_USER"' in script or 'chown -R "$ACTUAL_USER"' in script
