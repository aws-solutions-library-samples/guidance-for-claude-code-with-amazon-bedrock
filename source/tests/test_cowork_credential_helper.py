# ABOUTME: Tests for CoWork 3P credential helper mode (inferenceCredentialHelper)
# ABOUTME: Verifies MDM config generation for both "helper" and "profile" modes

"""Tests for CoWork 3P credential helper mode."""

import json

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    build_mdm_config,
    generate_intune_script,
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
        """Default macOS path uses the __CCWB_HOME__ placeholder (install.sh resolves it)."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        assert config["inferenceCredentialHelper"].startswith("__CCWB_HOME__/")


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
        """Unix path becomes __CCWB_HOME__\\...credential-process.exe (placeholder kept).

        The placeholder is NOT %USERPROFILE%: Claude Desktop reads the registry
        value literally and does not expand env vars. install.bat substitutes
        __CCWB_HOME__ with the absolute home before importing the .reg.
        """
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        reg_path = generate_reg_file(tmp_path, config)
        content = reg_path.read_text(encoding="utf-8")
        # Placeholder kept, env var NOT used
        assert "__CCWB_HOME__" in content
        assert "%USERPROFILE%" not in content
        # Windows binary form: backslashes + .exe suffix
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


class TestGenerateIntuneScript:
    """Test Intune .ps1 generation resolves the home placeholder at deploy time."""

    def test_ps1_resolves_home_placeholder_at_runtime(self, tmp_path):
        """The .ps1 resolves __CCWB_HOME__ to $env:USERPROFILE when it runs.

        Claude Desktop does not expand env vars in registry MDM values, so the
        script must write an absolute path. It resolves the placeholder at deploy
        time rather than emitting a literal %USERPROFILE%.
        """
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        ps1_path = generate_intune_script(tmp_path, config)
        content = ps1_path.read_text(encoding="utf-8")
        assert "$ccwbHome = $env:USERPROFILE" in content
        assert ".Replace('__CCWB_HOME__', $ccwbHome)" in content
        # credential helper converted to the Windows .exe form
        assert "credential-process.exe" in content
        assert "--profile Test" in content
        # no emitted registry VALUE carries the unexpanded env var (comments may
        # mention it, so check the Set-ItemProperty lines specifically)
        value_lines = [ln for ln in content.splitlines() if ln.startswith("Set-ItemProperty")]
        assert value_lines  # sanity: we did emit values
        assert all("%USERPROFILE%" not in ln for ln in value_lines)


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
            == "__CCWB_HOME__/claude-code-with-bedrock/credential-process --profile MyProfile"
        )
        assert data["inferenceCredentialHelperTtlSec"] == "3500"
        assert data["inferenceCredentialHelperSilentRefreshEnabled"] == "true"
