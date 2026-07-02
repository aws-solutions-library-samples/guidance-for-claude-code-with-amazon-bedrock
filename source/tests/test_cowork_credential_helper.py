# ABOUTME: Tests for CoWork 3P credential helper mode (inferenceCredentialHelper)
# ABOUTME: Verifies MDM config generation for both "helper" and "profile" modes

"""Tests for CoWork 3P credential helper mode."""

import json

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    build_mdm_config,
    generate_json,
    generate_reg_file,
)


class TestBuildMdmConfigCredentialHelper:
    """Test build_mdm_config with credential_mode='helper' (default)."""

    def test_helper_mode_includes_credential_helper_keys(self):
        """Default mode should produce inferenceCredentialHelper keys."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="MyProfile",
        )
        assert "inferenceCredentialHelper" in config
        assert "inferenceCredentialHelperTtlSec" in config
        assert "inferenceCredentialHelperSilentRefreshEnabled" in config
        assert config["inferenceCredentialHelperSilentRefreshEnabled"] == "true"

    def test_helper_mode_path_includes_profile_name(self):
        """Credential helper path should include --profile <name>."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Production",
        )
        assert "--profile Production" in config["inferenceCredentialHelper"]
        assert "credential-process" in config["inferenceCredentialHelper"]

    def test_helper_mode_ttl_default(self):
        """Default TTL should be 3500s (under 1h STS expiry)."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
        )
        assert config["inferenceCredentialHelperTtlSec"] == "3500"

    def test_helper_mode_custom_ttl(self):
        """Custom TTL should override default."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            credential_helper_ttl_sec=1800,
        )
        assert config["inferenceCredentialHelperTtlSec"] == "1800"

    def test_helper_mode_still_includes_bedrock_profile(self):
        """Helper mode should still include inferenceBedrockProfile for SDK fallback."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="ClaudeCode",
        )
        assert config["inferenceBedrockProfile"] == "ClaudeCode"

    def test_helper_mode_uses_unix_path_by_default(self):
        """Default path should use ~/ prefix (Unix convention)."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        assert config["inferenceCredentialHelper"].startswith("~/")


class TestBuildMdmConfigProfileMode:
    """Test build_mdm_config with credential_mode='profile' (legacy)."""

    def test_profile_mode_uses_bedrock_profile_only(self):
        """Legacy mode should use inferenceBedrockProfile without credential helper."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus"],
            profile_name="LegacyProfile",
            credential_mode="profile",
        )
        assert config["inferenceBedrockProfile"] == "LegacyProfile"
        assert "inferenceCredentialHelper" not in config
        assert "inferenceCredentialHelperTtlSec" not in config
        assert "inferenceCredentialHelperSilentRefreshEnabled" not in config

    def test_profile_mode_backward_compatible(self):
        """Legacy mode output should match previous behavior exactly."""
        config = build_mdm_config(
            bedrock_region="eu-west-1",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="ClaudeCode",
            credential_mode="profile",
        )
        assert config == {
            "inferenceProvider": "bedrock",
            "inferenceBedrockRegion": "eu-west-1",
            "inferenceBedrockProfile": "ClaudeCode",
            "inferenceModels": ["opus", "sonnet", "haiku"],
            "isClaudeCodeForDesktopEnabled": True,
            "isDesktopExtensionEnabled": True,
            "isDesktopExtensionDirectoryEnabled": True,
            "isDesktopExtensionSignatureRequired": True,
            "isLocalDevMcpEnabled": True,
        }


class TestGenerateRegFileCredentialHelper:
    """Test Windows .reg generation with credential helper path rewriting."""

    def test_reg_file_rewrites_unix_path_to_windows(self, tmp_path):
        """Unix ~/... path should become %USERPROFILE%\\... with .exe suffix."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        reg_path = generate_reg_file(tmp_path, config)
        content = reg_path.read_text(encoding="utf-8")
        # Should contain Windows-style path
        assert "%USERPROFILE%" in content
        assert "credential-process.exe" in content
        assert "--profile Test" in content

    def test_reg_file_no_rewrite_for_profile_mode(self, tmp_path):
        """Profile mode should not contain credential helper in .reg file."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            credential_mode="profile",
        )
        reg_path = generate_reg_file(tmp_path, config)
        content = reg_path.read_text(encoding="utf-8")
        assert "inferenceCredentialHelper" not in content


class TestGenerateJsonCredentialHelper:
    """Test JSON output includes credential helper keys."""

    def test_json_output_includes_helper_keys(self, tmp_path):
        """JSON output should include all credential helper keys."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus", "sonnet"],
            profile_name="MyProfile",
        )
        json_path = generate_json(tmp_path, config)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert (
            data["inferenceCredentialHelper"]
            == "~/claude-code-with-bedrock/credential-process --desktop --profile MyProfile"
        )
        assert data["inferenceCredentialHelperTtlSec"] == "3500"
        assert data["inferenceCredentialHelperSilentRefreshEnabled"] == "true"
