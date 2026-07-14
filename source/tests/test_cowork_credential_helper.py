# ABOUTME: Tests for CoWork 3P credential helper mode (inferenceCredentialHelper)
# ABOUTME: Verifies MDM config generation for both "helper" and "profile" modes

"""Tests for CoWork 3P credential helper mode."""

import json

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    _to_windows_credential_helper,
    build_mdm_config,
    generate_all,
    generate_intune_script,
    generate_json,
    generate_reg_file,
)


class TestToWindowsCredentialHelper:
    """Direct regression tests for the unix->windows helper-path conversion.

    Pins the PR #733 bug class: the value is a bare wrapper path, so the
    converter must swap .sh->.cmd and rewrite slashes WITHOUT appending .exe or
    splitting on spaces, and must be a no-op for non-placeholder values.
    """

    def test_sh_wrapper_becomes_cmd_no_exe(self):
        out = _to_windows_credential_helper("__CCWB_HOME__/claude-code-with-bedrock/cowork-credential-helper.sh")
        assert out == "__CCWB_HOME__\\claude-code-with-bedrock\\cowork-credential-helper.cmd"
        assert ".exe" not in out
        assert " " not in out  # bare path, no inline args

    def test_noop_for_non_placeholder_value(self):
        for val in ("C:\\some\\abs\\path.cmd", "/usr/local/bin/helper", ""):
            assert _to_windows_credential_helper(val) == val


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

    def test_helper_path_is_bare_wrapper_no_args(self):
        """Claude Desktop runs the helper 'with no arguments', so the MDM value
        must be a bare path to the wrapper script — the --desktop/--profile flags
        live inside the wrapper, not in this value."""
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Production",
        )
        helper = config["inferenceCredentialHelper"]
        assert helper.endswith("cowork-credential-helper.sh")
        assert "--profile" not in helper
        assert "--desktop" not in helper

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
        """Unix wrapper path becomes __CCWB_HOME__\\...cowork-credential-helper.cmd.

        The placeholder is NOT %USERPROFILE%: Claude Desktop reads the registry
        value literally and does not expand env vars. install.bat substitutes
        __CCWB_HOME__ with the absolute home before importing the .reg. The value
        is a bare path (no arguments) — Claude Desktop runs it with none.
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
        # Windows wrapper form: backslashes + .cmd, no inline args
        assert "cowork-credential-helper.cmd" in content
        assert "--profile" not in content
        assert "--desktop" not in content

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
        # credential helper converted to the Windows wrapper (.cmd), no inline args
        assert "cowork-credential-helper.cmd" in content
        assert "--profile" not in content
        assert "--desktop" not in content
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
        assert data["inferenceCredentialHelper"] == "__CCWB_HOME__/claude-code-with-bedrock/cowork-credential-helper.sh"
        assert data["inferenceCredentialHelperTtlSec"] == "3500"
        assert data["inferenceCredentialHelperSilentRefreshEnabled"] == "true"


class TestGenerateHelperWrappers:
    """The wrapper scripts bake --desktop/--profile so the MDM value stays bare."""

    def test_wrappers_written_with_profile_and_desktop(self, tmp_path):
        from claude_code_with_bedrock.cli.utils.cowork_3p import generate_helper_wrappers

        names = generate_helper_wrappers(tmp_path, "MyProfile")
        assert set(names) == {"cowork-credential-helper.sh", "cowork-credential-helper.cmd"}

        sh = (tmp_path / "cowork-credential-helper.sh").read_text(encoding="utf-8")
        assert "--desktop --profile MyProfile" in sh
        assert 'exec "$SCRIPT_DIR/credential-process"' in sh

        # .cmd must be CRLF-terminated and call the co-located .exe via %~dp0
        cmd_bytes = (tmp_path / "cowork-credential-helper.cmd").read_bytes()
        assert b"\r\n" in cmd_bytes
        cmd = cmd_bytes.decode("utf-8")
        assert '"%~dp0credential-process.exe" --desktop --profile MyProfile' in cmd

    def test_generate_all_emits_wrappers_in_helper_mode(self, tmp_path):
        from rich.console import Console

        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="P",
        )
        generated = generate_all(tmp_path, config, Console())
        assert "cowork-credential-helper.sh" in generated
        assert "cowork-credential-helper.cmd" in generated
        assert (tmp_path / "cowork-credential-helper.sh").exists()

    def test_generate_all_skips_wrappers_in_profile_mode(self, tmp_path):
        from rich.console import Console

        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="P",
            credential_mode="profile",
        )
        generated = generate_all(tmp_path, config, Console())
        assert "cowork-credential-helper.sh" not in generated
        assert not (tmp_path / "cowork-credential-helper.sh").exists()
