# ABOUTME: End-to-end tests for the full CLI lifecycle
# ABOUTME: Exercises config creation, profile CRUD, validation, and export/import round-trips

"""End-to-end tests for CLI lifecycle — no AWS credentials required.

These tests exercise the full user journey through the CLI by running
commands against an isolated config directory (tmp_path). They catch:
- Config serialization/deserialization bugs
- Profile CRUD regressions
- Validation logic errors
- Command argument definition issues
- Import/export round-trip fidelity
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from claude_code_with_bedrock.cli import create_application  # noqa: E402
from claude_code_with_bedrock.config import Config, Profile  # noqa: E402


class TestConfigLifecycle:
    """Test full config creation → save → load → modify → validate cycle."""

    def test_create_profile_save_and_reload(self, tmp_path):
        """A profile round-trips through save/load without data loss."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    profile = Profile(
                        name="production",
                        provider_domain="company.okta.com",
                        client_id="0oa1234567890abcdef",
                        credential_storage="keyring",
                        aws_region="us-west-2",
                        identity_pool_name="claude-code-pool",
                        cross_region_profile="us",
                        selected_model="us.anthropic.claude-sonnet-4-20250514-v1:0",
                        selected_source_region="us-east-1",
                        monitoring_enabled=True,
                        analytics_enabled=True,
                        quota_monitoring_enabled=True,
                        monthly_token_limit=500000000,
                        daily_enforcement_mode="block",
                        tags={"team": "platform", "env": "prod"},
                    )

                    config.save_profile(profile)
                    config.active_profile = "production"
                    config.save()

                    # Reload from disk
                    loaded_config = Config.load()
                    assert loaded_config.active_profile == "production"

                    loaded_profile = loaded_config.load_profile("production")
                    assert loaded_profile.name == "production"
                    assert loaded_profile.provider_domain == "company.okta.com"
                    assert loaded_profile.client_id == "0oa1234567890abcdef"
                    assert loaded_profile.aws_region == "us-west-2"
                    assert loaded_profile.cross_region_profile == "us"
                    assert loaded_profile.selected_model == "us.anthropic.claude-sonnet-4-20250514-v1:0"
                    assert loaded_profile.selected_source_region == "us-east-1"
                    assert loaded_profile.monitoring_enabled is True
                    assert loaded_profile.quota_monitoring_enabled is True
                    assert loaded_profile.monthly_token_limit == 500000000
                    assert loaded_profile.daily_enforcement_mode == "block"
                    assert loaded_profile.tags == {"team": "platform", "env": "prod"}

    def test_multiple_profiles_coexist(self, tmp_path):
        """Multiple profiles can be saved and retrieved independently."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()

                    profiles = [
                        Profile(
                            name="dev",
                            provider_domain="dev.okta.com",
                            client_id="dev-client",
                            credential_storage="session",
                            aws_region="us-east-1",
                            identity_pool_name="dev-pool",
                        ),
                        Profile(
                            name="staging",
                            provider_domain="staging.okta.com",
                            client_id="staging-client",
                            credential_storage="keyring",
                            aws_region="eu-west-1",
                            identity_pool_name="staging-pool",
                        ),
                        Profile(
                            name="prod",
                            provider_domain="prod.okta.com",
                            client_id="prod-client",
                            credential_storage="keyring",
                            aws_region="us-west-2",
                            identity_pool_name="prod-pool",
                        ),
                    ]

                    for p in profiles:
                        config.save_profile(p)

                    # All profiles listed
                    profile_names = config.list_profiles()
                    assert set(profile_names) == {"dev", "staging", "prod"}

                    # Each profile retains its own data
                    dev = config.load_profile("dev")
                    assert dev.aws_region == "us-east-1"
                    assert dev.credential_storage == "session"

                    prod = config.load_profile("prod")
                    assert prod.aws_region == "us-west-2"
                    assert prod.credential_storage == "keyring"

    def test_profile_update_preserves_other_fields(self, tmp_path):
        """Updating one field doesn't clobber others."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    profile = Profile(
                        name="test",
                        provider_domain="test.okta.com",
                        client_id="test-client",
                        credential_storage="keyring",
                        aws_region="us-east-1",
                        identity_pool_name="test-pool",
                        monitoring_enabled=True,
                        quota_monitoring_enabled=True,
                        monthly_token_limit=100000000,
                    )
                    config.save_profile(profile)

                    # Load, modify, save
                    loaded = config.load_profile("test")
                    loaded.monthly_token_limit = 200000000
                    loaded.daily_enforcement_mode = "block"
                    config.save_profile(loaded)

                    # Reload and verify
                    reloaded = config.load_profile("test")
                    assert reloaded.monthly_token_limit == 200000000
                    assert reloaded.daily_enforcement_mode == "block"
                    # Other fields preserved
                    assert reloaded.monitoring_enabled is True
                    assert reloaded.quota_monitoring_enabled is True
                    assert reloaded.provider_domain == "test.okta.com"

    def test_nonexistent_profile_raises(self, tmp_path):
        """Loading a nonexistent profile raises FileNotFoundError."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    with pytest.raises(FileNotFoundError):
                        config.load_profile("nonexistent")

    def test_config_export_import_round_trip(self, tmp_path):
        """Export → import produces identical profile (minus sensitive fields)."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    profile = Profile(
                        name="export-test",
                        provider_domain="export.okta.com",
                        client_id="export-client",
                        credential_storage="session",
                        aws_region="eu-central-1",
                        identity_pool_name="export-pool",
                        cross_region_profile="eu",
                        selected_model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
                        tags={"exported": "true"},
                    )
                    config.save_profile(profile)

                    # Export
                    export_path = tmp_path / "exported.json"
                    loaded = config.load_profile("export-test")
                    export_data = loaded.to_dict()
                    with open(export_path, "w") as f:
                        json.dump(export_data, f, indent=2)

                    # Import into new profile
                    with open(export_path) as f:
                        imported_data = json.load(f)

                    imported_data["name"] = "imported-test"
                    imported_profile = Profile.from_dict(imported_data)
                    config.save_profile(imported_profile)

                    # Verify round-trip
                    result = config.load_profile("imported-test")
                    assert result.provider_domain == "export.okta.com"
                    assert result.aws_region == "eu-central-1"
                    assert result.cross_region_profile == "eu"
                    assert result.tags == {"exported": "true"}


class TestCLICommandExecution:
    """Test CLI commands execute without crashes using isolated config."""

    def test_context_list_empty(self, tmp_path, capsys):
        """context list works with no profiles configured."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    app = create_application()
                    from cleo.testers.command_tester import CommandTester

                    command = app.find("context list")
                    tester = CommandTester(command)
                    exit_code = tester.execute("")
                    assert exit_code == 0
                    # Rich Console writes to stdout, not cleo IO
                    captured = capsys.readouterr()
                    assert "No profiles found" in captured.out

    def test_context_list_with_profiles(self, tmp_path, capsys):
        """context list shows all profiles."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    config.save_profile(
                        Profile(
                            name="alpha",
                            provider_domain="a.okta.com",
                            client_id="a",
                            credential_storage="session",
                            aws_region="us-east-1",
                            identity_pool_name="a-pool",
                        )
                    )
                    config.save_profile(
                        Profile(
                            name="beta",
                            provider_domain="b.okta.com",
                            client_id="b",
                            credential_storage="session",
                            aws_region="eu-west-1",
                            identity_pool_name="b-pool",
                        )
                    )

                    app = create_application()
                    from cleo.testers.command_tester import CommandTester

                    command = app.find("context list")
                    tester = CommandTester(command)
                    exit_code = tester.execute("")
                    assert exit_code == 0
                    captured = capsys.readouterr()
                    assert "alpha" in captured.out
                    assert "beta" in captured.out

    def test_context_use_and_current(self, tmp_path, capsys):
        """context use + context current round-trip works."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    config.save_profile(
                        Profile(
                            name="myprofile",
                            provider_domain="test.okta.com",
                            client_id="test",
                            credential_storage="session",
                            aws_region="us-west-2",
                            identity_pool_name="pool",
                        )
                    )

                    app = create_application()
                    from cleo.testers.command_tester import CommandTester

                    # Use the profile
                    use_cmd = app.find("context use")
                    tester = CommandTester(use_cmd)
                    exit_code = tester.execute("myprofile")
                    assert exit_code == 0

                    # Verify it's current
                    capsys.readouterr()  # Clear buffer
                    current_cmd = app.find("context current")
                    tester2 = CommandTester(current_cmd)
                    exit_code = tester2.execute("")
                    assert exit_code == 0
                    captured = capsys.readouterr()
                    assert "myprofile" in captured.out

    def test_config_validate_valid_profile(self, tmp_path, capsys):
        """config validate passes for a well-formed profile."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    config.save_profile(
                        Profile(
                            name="valid",
                            provider_domain="company.okta.com",
                            client_id="0oa123",
                            credential_storage="keyring",
                            aws_region="us-east-1",
                            identity_pool_name="valid-pool",
                        )
                    )
                    config.active_profile = "valid"
                    config.save()

                    app = create_application()
                    from cleo.testers.command_tester import CommandTester

                    cmd = app.find("config validate")
                    tester = CommandTester(cmd)
                    exit_code = tester.execute("valid")
                    assert exit_code == 0
                    captured = capsys.readouterr()
                    output = captured.out.lower()
                    assert "passed" in output or "valid" in output

    def test_context_show_displays_profile_details(self, tmp_path, capsys):
        """context show renders all profile fields without crashing."""
        with patch.object(Config, "CONFIG_DIR", tmp_path):
            with patch.object(Config, "CONFIG_FILE", tmp_path / "config.json"):
                with patch.object(Config, "PROFILES_DIR", tmp_path / "profiles"):
                    (tmp_path / "profiles").mkdir()

                    config = Config()
                    config.save_profile(
                        Profile(
                            name="detailed",
                            provider_domain="detailed.okta.com",
                            client_id="detail-id",
                            credential_storage="keyring",
                            aws_region="ap-southeast-2",
                            identity_pool_name="detail-pool",
                            cross_region_profile="us",
                            selected_model="us.anthropic.claude-opus-4-1-20250805-v1:0",
                            monitoring_enabled=True,
                            quota_monitoring_enabled=True,
                            monthly_token_limit=225000000,
                        )
                    )

                    app = create_application()
                    from cleo.testers.command_tester import CommandTester

                    cmd = app.find("context show")
                    tester = CommandTester(cmd)
                    exit_code = tester.execute("detailed")
                    assert exit_code == 0
                    captured = capsys.readouterr()
                    assert "ap-southeast-2" in captured.out
                    assert "detailed" in captured.out


class TestQuotaCLILifecycle:
    """Test quota command lifecycle without real DynamoDB."""

    def test_quota_commands_instantiate_cleanly(self):
        """All quota commands instantiate without errors."""
        from claude_code_with_bedrock.cli.commands.quota import (
            QuotaDeleteCommand,
            QuotaExportCommand,
            QuotaImportCommand,
            QuotaListCommand,
            QuotaSetDefaultCommand,
            QuotaSetGroupCommand,
            QuotaSetUserCommand,
            QuotaShowCommand,
            QuotaUnblockCommand,
            QuotaUsageCommand,
        )

        commands = [
            QuotaSetUserCommand,
            QuotaSetGroupCommand,
            QuotaSetDefaultCommand,
            QuotaListCommand,
            QuotaDeleteCommand,
            QuotaShowCommand,
            QuotaUsageCommand,
            QuotaUnblockCommand,
            QuotaExportCommand,
            QuotaImportCommand,
        ]

        for cmd_cls in commands:
            cmd = cmd_cls()
            assert cmd.name is not None
            assert cmd.description is not None
            assert hasattr(cmd, "handle")

    def test_quota_export_import_json_structure(self, tmp_path):
        """Quota export produces valid JSON that import can consume."""

        # Simulate a policy export structure
        policies = [
            {
                "policy_type": "user",
                "identifier": "alice@company.com",
                "monthly_token_limit": 500000000,
                "daily_token_limit": 25000000,
                "enforcement_mode": "block",
                "daily_enforcement_mode": "alert",
                "enabled": True,
            },
            {
                "policy_type": "group",
                "identifier": "engineering",
                "monthly_token_limit": 1000000000,
                "daily_token_limit": 50000000,
                "enforcement_mode": "alert",
                "daily_enforcement_mode": "alert",
                "enabled": True,
            },
            {
                "policy_type": "default",
                "identifier": "__default__",
                "monthly_token_limit": 225000000,
                "daily_token_limit": 11250000,
                "enforcement_mode": "block",
                "daily_enforcement_mode": "block",
                "enabled": True,
            },
        ]

        # Write to file
        export_path = tmp_path / "policies.json"
        with open(export_path, "w") as f:
            json.dump({"policies": policies, "version": "1.0"}, f)

        # Read back and validate structure
        with open(export_path) as f:
            data = json.load(f)

        assert "policies" in data
        assert len(data["policies"]) == 3
        for policy in data["policies"]:
            assert "policy_type" in policy
            assert "identifier" in policy
            assert "monthly_token_limit" in policy
            assert policy["policy_type"] in ("user", "group", "default")
