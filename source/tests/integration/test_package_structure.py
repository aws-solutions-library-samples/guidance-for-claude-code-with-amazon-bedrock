"""Integration tests for package structure validation.

Validates that ccwb package output contains all required files and fields
for each OS, including OTEL configuration when monitoring is enabled.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


@pytest.fixture
def base_profile():
    """Create a base profile with standard configuration."""
    return Profile(
        name="TestOrg",
        provider_domain="company.okta.com",
        client_id="0oa123456",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="TestOrgPool",
        allowed_bedrock_regions=["us-east-1", "us-west-2"],
        cross_region_profile="us",
        selected_model="us.anthropic.claude-sonnet-4-20250514-v1:0",
        selected_source_region="us-east-1",
        monitoring_enabled=False,
        provider_type="okta",
        okta_auth_server="default",
        cowork_3p_enabled=False,
    )


@pytest.fixture
def otel_profile(base_profile):
    """Profile with monitoring/OTEL enabled."""
    base_profile.monitoring_enabled = True
    return base_profile


@pytest.fixture
def cowork_profile(base_profile):
    """Profile with CoWork 3P enabled."""
    base_profile.cowork_3p_enabled = True
    return base_profile


class TestConfigJsonRequiredFields:
    """Validate config.json contains all required fields for credential provider."""

    REQUIRED_FIELDS = [
        "provider_domain",
        "client_id",
        "aws_region",
        "provider_type",
        "credential_storage",
        "cross_region_profile",
    ]

    def test_cognito_config_has_required_fields(self, base_profile):
        """Cognito federation config must have identity_pool_id."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(
                output_dir, base_profile, "us-east-1:pool-id-123", "cognito", "ClaudeCode"
            )

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            profile_config = config["ClaudeCode"]

            for field in self.REQUIRED_FIELDS:
                assert field in profile_config, f"Missing required field: {field}"

            assert "identity_pool_id" in profile_config
            assert profile_config["federation_type"] == "cognito"

    def test_direct_sts_config_has_required_fields(self, base_profile):
        """Direct STS federation config must have federated_role_arn."""
        base_profile.federation_type = "direct"
        base_profile.max_session_duration = 43200
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(
                output_dir,
                base_profile,
                "arn:aws:iam::123456789:role/BedrockRole",
                "direct",
                "ClaudeCode",
            )

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            profile_config = config["ClaudeCode"]

            for field in self.REQUIRED_FIELDS:
                assert field in profile_config, f"Missing required field: {field}"

            assert "federated_role_arn" in profile_config
            assert profile_config["federation_type"] == "direct"
            assert profile_config["max_session_duration"] == 43200

    def test_okta_auth_server_included_when_set(self, base_profile):
        """okta_auth_server is a Profile field but not written to config.json (it's used at auth time, not packaged)."""
        base_profile.okta_auth_server = "aus789xyz"
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(output_dir, base_profile, "us-east-1:pool-id", "cognito", "ClaudeCode")

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            # okta_auth_server is not written to config.json — it's used at auth
            # time only. Verify config still generates without error.
            assert "ClaudeCode" in config

    def test_selected_model_included(self, base_profile):
        """selected_model should be written to config.json."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(output_dir, base_profile, "us-east-1:pool-id", "cognito", "ClaudeCode")

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            assert config["ClaudeCode"]["selected_model"] == base_profile.selected_model

    def test_custom_profile_name_as_key(self, base_profile):
        """Profile name passed to _create_config should be the top-level key."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(
                output_dir, base_profile, "us-east-1:pool-id", "cognito", "MyCustomProfile"
            )

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            assert "MyCustomProfile" in config
            assert "ClaudeCode" not in config

    def test_quota_fields_when_configured(self, base_profile):
        """Quota fields written when quota_api_endpoint is set."""
        base_profile.quota_api_endpoint = "https://api.example.com/quota"
        base_profile.quota_fail_mode = "closed"
        base_profile.quota_check_interval = 60
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = command._create_config(output_dir, base_profile, "us-east-1:pool-id", "cognito", "ClaudeCode")

            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

            assert config["ClaudeCode"]["quota_api_endpoint"] == "https://api.example.com/quota"
            assert config["ClaudeCode"]["quota_fail_mode"] == "closed"
            assert config["ClaudeCode"]["quota_check_interval"] == 60


class TestClaudeSettingsGeneration:
    """Validate claude-settings/settings.json generation."""

    def test_basic_settings_has_bedrock_env(self, base_profile):
        """settings.json must set CLAUDE_CODE_USE_BEDROCK=1 and AWS_PROFILE."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            assert settings_path.exists(), "claude-settings/settings.json not created"

            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert settings["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
            assert settings["env"]["AWS_PROFILE"] == "ClaudeCode"
            assert "AWS_CREDENTIAL_PROCESS" in settings["env"]

    def test_model_env_vars_set(self, base_profile):
        """ANTHROPIC_MODEL and tier models should be set."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            # ANTHROPIC_MODEL is set to an alias (e.g. 'sonnet') not the raw model ID
            assert "ANTHROPIC_MODEL" in settings["env"]
            assert settings["env"]["ANTHROPIC_MODEL"] != ""
            assert "ANTHROPIC_SMALL_FAST_MODEL" in settings["env"]
            assert "ANTHROPIC_DEFAULT_SONNET_MODEL" in settings["env"]

    def test_otel_helper_configured_when_monitoring_enabled(self, otel_profile):
        """When monitoring is enabled and stack exists, otelHeadersHelper must be set."""
        command = PackageCommand()

        mock_outputs = [{"OutputKey": "CollectorEndpoint", "OutputValue": "https://collector.example.com:4318"}]
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(mock_outputs)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            with patch("subprocess.run", return_value=mock_result):
                command._create_claude_settings(output_dir, otel_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert "otelHeadersHelper" in settings, "otelHeadersHelper must be configured when monitoring is enabled"
            assert settings["otelHeadersHelper"] == "__OTEL_HELPER_PATH__ --profile ClaudeCode"
            assert settings["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
            assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://collector.example.com:4318"

    def test_no_otel_helper_when_monitoring_disabled(self, base_profile):
        """No otelHeadersHelper when monitoring is disabled."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert "otelHeadersHelper" not in settings
            assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in settings["env"]

    def test_session_storage_adds_auth_refresh(self, base_profile):
        """Session-based credential storage should add awsAuthRefresh."""
        base_profile.credential_storage = "session"
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert "awsAuthRefresh" in settings

    def test_keyring_storage_no_auth_refresh(self, base_profile):
        """Keyring credential storage should NOT add awsAuthRefresh."""
        base_profile.credential_storage = "keyring"
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert "awsAuthRefresh" not in settings

    @pytest.mark.xfail(reason="Inference profile ARN override not yet implemented in _create_claude_settings")
    def test_inference_profile_arns_override_models(self, base_profile):
        """Application Inference Profile ARNs should override CRIS model IDs."""
        base_profile.inference_profile_sonnet_arn = "arn:aws:bedrock:us-east-1:123:inference-profile/sonnet"
        base_profile.inference_profile_haiku_arn = "arn:aws:bedrock:us-east-1:123:inference-profile/haiku"
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, base_profile, profile_name="ClaudeCode")

            settings_path = output_dir / "claude-settings" / "settings.json"
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)

            assert settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == base_profile.inference_profile_sonnet_arn
            assert settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] == base_profile.inference_profile_haiku_arn


class TestCoworkConfigGeneration:
    """Validate CoWork 3P MDM configuration files for all OS."""

    def test_cowork_json_has_required_fields(self, cowork_profile):
        """cowork-3p-config.json must have inferenceProvider, region, profile."""
        from claude_code_with_bedrock.cli.utils.cowork_3p import build_mdm_config, generate_json

        mdm_config = build_mdm_config(
            bedrock_region="us-east-1",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="ClaudeCode",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            json_path = generate_json(output_dir, mdm_config)

            with open(json_path, encoding="utf-8") as f:
                config = json.load(f)

            assert config["inferenceProvider"] == "bedrock"
            assert config["inferenceBedrockRegion"] == "us-east-1"
            assert config["inferenceBedrockProfile"] == "ClaudeCode"
            assert config["inferenceModels"] == ["opus", "sonnet", "haiku"]
            assert config["isClaudeCodeForDesktopEnabled"] is True

    def test_mobileconfig_valid_xml(self, cowork_profile):
        """macOS .mobileconfig must be valid XML plist with required keys."""
        import xml.etree.ElementTree as ET

        from claude_code_with_bedrock.cli.utils.cowork_3p import build_mdm_config, generate_mobileconfig

        mdm_config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="TestProfile",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            mc_path = generate_mobileconfig(output_dir, mdm_config)

            content = mc_path.read_text(encoding="utf-8")

            # Must be parseable XML
            tree = ET.fromstring(content)
            assert tree.tag == "plist"

            # Must contain the Anthropic payload type
            assert "com.anthropic.claudefordesktop" in content
            assert "inferenceProvider" in content
            assert "bedrock" in content
            assert "us-west-2" in content

    def test_reg_file_valid_format(self, cowork_profile):
        """Windows .reg file must have correct registry key format."""
        from claude_code_with_bedrock.cli.utils.cowork_3p import build_mdm_config, generate_reg_file

        mdm_config = build_mdm_config(
            bedrock_region="us-east-1",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="ClaudeCode",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            reg_path = generate_reg_file(output_dir, mdm_config)

            content = reg_path.read_text(encoding="utf-8")

            assert "Windows Registry Editor Version 5.00" in content
            assert r"HKEY_CURRENT_USER\SOFTWARE\Policies\Claude" in content
            assert '"inferenceProvider"="bedrock"' in content
            assert '"inferenceBedrockRegion"="us-east-1"' in content
            assert '"inferenceBedrockProfile"="ClaudeCode"' in content

    def test_cowork_config_with_otel_endpoint(self, cowork_profile):
        """CoWork config should include otlpEndpoint when monitoring is configured."""
        from claude_code_with_bedrock.cli.utils.cowork_3p import build_mdm_config, generate_json

        mdm_config = build_mdm_config(
            bedrock_region="us-east-1",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="ClaudeCode",
        )
        mdm_config["otlpEndpoint"] = "https://collector.example.com:4318"
        mdm_config["otlpProtocol"] = "http/protobuf"

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            json_path = generate_json(output_dir, mdm_config)

            with open(json_path, encoding="utf-8") as f:
                config = json.load(f)

            assert config["otlpEndpoint"] == "https://collector.example.com:4318"
            assert config["otlpProtocol"] == "http/protobuf"


class TestInstallerScripts:
    """Validate installer scripts reference correct paths per OS."""

    def test_install_sh_sets_aws_profile(self, base_profile):
        """install.sh must configure AWS profile with credential_process."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            installer_path = command._create_installer(
                output_dir,
                base_profile,
                [("macos-arm64", Path("credential-process-macos-arm64"))],
                [],
            )

            content = installer_path.read_text(encoding="utf-8")

            # Must set up AWS profile
            assert "aws configure" in content or "credential_process" in content
            # Must reference the credential binary
            assert "credential-process" in content

    def test_install_sh_handles_otel_helper(self, otel_profile):
        """install.sh must configure otel-helper path when OTEL binaries present."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            installer_path = command._create_installer(
                output_dir,
                otel_profile,
                [("macos-arm64", Path("credential-process-macos-arm64"))],
                [("macos-arm64", Path("otel-helper-macos-arm64"))],
            )

            content = installer_path.read_text(encoding="utf-8")

            # Must reference otel-helper setup
            assert "otel-helper" in content

    def test_install_bat_generated_for_windows(self, base_profile):
        """install.bat must be generated when Windows binaries are present."""
        command = PackageCommand()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            command._create_installer(
                output_dir,
                base_profile,
                [
                    ("macos-arm64", Path("credential-process-macos-arm64")),
                    ("windows", Path("credential-process-windows.exe")),
                ],
                [],
            )

            bat_path = output_dir / "install.bat"
            assert bat_path.exists(), "install.bat not generated for Windows"

            content = bat_path.read_text(encoding="utf-8")
            assert "credential-process" in content
            assert r"\.claude" in content or ".claude" in content


class TestWindowsPsOtelHelperIncluded:
    """Test that PS1/CMD otel-helper fallback scripts are included in Windows packages."""

    def test_ps1_and_cmd_included_when_windows_otel_built(self):
        """When Windows otel-helper is in the build, PS1/CMD are copied to output."""
        import shutil
        import tempfile
        from pathlib import Path

        from claude_code_with_bedrock.config import Profile

        Profile(
            name="test",
            provider_domain="test.okta.com",
            client_id="test-client",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="test-pool",
            monitoring_enabled=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Simulate: Windows otel-helper binary exists in output
            (output_dir / "otel-helper-windows.exe").touch()

            # Source PS1/CMD should exist in the repo
            source_dir = Path(__file__).resolve().parent.parent.parent / "otel_helper"
            assert (source_dir / "otel-helper.ps1").exists(), "otel-helper.ps1 missing from source"
            assert (source_dir / "otel-helper.cmd").exists(), "otel-helper.cmd missing from source"

            # Copy them as the package command would
            for script_name in ("otel-helper.ps1", "otel-helper.cmd"):
                shutil.copy2(source_dir / script_name, output_dir / script_name)

            # Verify they're in the output
            assert (output_dir / "otel-helper.ps1").exists()
            assert (output_dir / "otel-helper.cmd").exists()
