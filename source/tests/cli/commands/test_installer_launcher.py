# ABOUTME: Tests that installers generate an optional claude-bedrock launcher that signs in before running claude
# ABOUTME: In-session re-auth works via awsAuthRefresh; the launcher is a convenience for a smoother first sign-in

"""Tests for the generated `claude-bedrock` launcher wrapper.

In-session IDC re-auth works: Claude Code runs `credential-process --login` via
the `awsAuthRefresh` hook and surfaces the interactive IAM Identity Center
sign-in prompt live, so plain `claude` handles first sign-in and re-auth. The
installer still generates a `claude-bedrock` launcher as an OPTIONAL convenience
— it runs `credential-process --login` (no-op if already signed in) and then
execs `claude`, front-running the sign-in without the ~165s in-session hook cap.

These tests generate the actual install.sh / install.bat and assert the launcher
logic is present, that the closing message presents `claude` as the usual path
with the launcher as optional, and, for bash, that both the installer and the
launcher it writes are syntactically valid shell.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _idc_profile() -> Profile:
    return Profile(
        name="idc-test",
        provider_domain="",
        client_id="",
        credential_storage="session",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1"],
        cross_region_profile="us",
        auth_type="idc",
        sso_enabled=False,
        idc_start_url="https://d-1234567890.awsapps.com/start",
        idc_account_id="123456789012",
        idc_permission_set_name="ClaudeCodeRole",
    )


class TestBashInstallerLauncher:
    def _generate(self) -> str:
        cmd = PackageCommand()
        out = Path(tempfile.mkdtemp())
        path = cmd._create_installer(out, _idc_profile(), [("linux", Path("/tmp/x"))])
        return path.read_text(encoding="utf-8")

    def test_installer_creates_launcher(self):
        content = self._generate()
        assert 'LAUNCHER="$ACTUAL_HOME/claude-code-with-bedrock/claude-bedrock"' in content
        assert "chmod +x" in content

    def test_launcher_runs_login_before_claude(self):
        content = self._generate()
        # --login must run, and only then exec claude; a failed login aborts.
        assert "--login --profile" in content
        assert "exec claude" in content
        assert "|| exit 1" in content

    @pytest.mark.skipif(sys.platform == "win32", reason="bash heredoc validation not meaningful on Windows")
    def test_installer_is_valid_bash(self):
        if shutil.which("bash") is None:
            pytest.skip("bash not available")
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "install.sh"
            script.write_text(self._generate(), encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            assert result.returncode == 0, f"install.sh has bash syntax errors: {result.stderr}"

    @pytest.mark.skipif(sys.platform == "win32", reason="bash heredoc validation not meaningful on Windows")
    def test_generated_launcher_is_valid_bash(self):
        """Execute just the heredoc that writes the launcher, then syntax-check
        the launcher it produces — this is where escaping bugs would surface."""
        if shutil.which("bash") is None:
            pytest.skip("bash not available")
        with tempfile.TemporaryDirectory() as d:
            launcher = Path(d) / "claude-bedrock"
            harness = f"""
CRED_PROC="/opt/cred/credential-process"
LAUNCHER="{launcher}"
FIRST_PROFILE="idc-test"
cat > "$LAUNCHER" << EOF
#!/bin/bash
PROFILE="\\${{AWS_PROFILE:-$FIRST_PROFILE}}"
"$CRED_PROC" --login --profile "\\$PROFILE" || exit 1
export AWS_PROFILE="\\$PROFILE"
exec claude "\\$@"
EOF
"""
            subprocess.run(["bash", "-c", harness], check=True, capture_output=True, text=True)
            generated = launcher.read_text(encoding="utf-8")
            # Runtime placeholders must remain literal (deferred), install-time vars expanded.
            assert "${AWS_PROFILE:-idc-test}" in generated
            assert "/opt/cred/credential-process" in generated
            assert 'exec claude "$@"' in generated
            check = subprocess.run(["bash", "-n", str(launcher)], capture_output=True, text=True)
            assert check.returncode == 0, f"generated launcher invalid: {check.stderr}"


class TestWindowsInstallerLauncher:
    def _generate(self) -> str:
        cmd = PackageCommand()
        out = Path(tempfile.mkdtemp())
        path = cmd._create_windows_installer(out, _idc_profile())
        return path.read_text(encoding="utf-8")

    def test_installer_creates_cmd_launcher(self):
        content = self._generate()
        assert "claude-bedrock.cmd" in content

    def test_otel_helper_path_points_at_cmd_with_backslashes(self):
        """otelHeadersHelper must reference otel-helper.cmd (the AV-resilient
        wrapper that runs the .exe and falls back to the .ps1), using a
        backslash path.

        Claude Code runs otelHeadersHelper through cmd.exe on Windows, where a
        .cmd is the correct target. The path must use escaped BACKSLASHES, not
        forward slashes: cmd.exe can misparse a forward-slash path to a .cmd
        (treating a segment as a switch). The installer builds the value with
        .Replace('\\\\','\\\\\\\\') so the JSON contains doubled backslashes
        (valid JSON) that un-escape to a native Windows path.
        """
        content = self._generate()
        # otelHeadersHelper targets the .cmd wrapper...
        assert "otel-helper.cmd'" in content, "otelHeadersHelper must point at otel-helper.cmd"
        # ...via backslash-doubling (rendered as .Replace('\','\\')), NOT the old
        # forward-slash conversion. r"..." keeps the backslashes literal.
        assert r".Replace('\','\\')" in content, "otel path must double backslashes for valid JSON"
        assert r"otel-helper.cmd' -replace '\\', '/'" not in content, (
            "otel path must not use forward slashes (cmd.exe may misparse a /-path to a .cmd)"
        )

    def test_otel_helper_missing_is_fatal_when_monitoring(self):
        """With monitoring enabled, a missing otel-helper.cmd/.ps1 must abort the
        install (exit /b 1) rather than silently leaving a broken telemetry
        config — the root cause of metrics never being sent."""
        content = self._generate()  # _idc_profile() has monitoring enabled
        assert "otel-helper.cmd not found in package" in content
        assert "ERROR: otel-helper.cmd not found" in content
        assert "otel-helper.ps1 not found in package" in content

    def test_launcher_runs_login_before_claude(self):
        content = self._generate()
        # The launcher lines: --login then claude, aborting on failure.
        assert "--login --profile" in content
        assert "exit /b 1" in content
        assert "claude %%*" in content  # %%* -> %* in the generated .cmd

    def test_profile_guard_has_balanced_quotes(self):
        """Regression: the AWS_PROFILE-empty guard must be fully quoted.

        The earlier PowerShell-written launcher dropped embedded quotes, producing
        `if %AWS_PROFILE%==" set ...` which cmd.exe rejects with "The syntax of the
        command is incorrect." Assert the balanced form is emitted. In install.bat
        the line uses %% which cmd collapses to % when writing the .cmd, so the
        launcher gets `if "%AWS_PROFILE%"=="" set AWS_PROFILE=...`.
        """
        content = self._generate()
        assert 'echo if "%%AWS_PROFILE%%"=="" set AWS_PROFILE=' in content

    def test_launcher_not_written_via_embedded_quote_powershell(self):
        """The launcher must be written with plain batch echo redirection, not a
        `powershell -Command "...\\"...\\"..."` with embedded quotes — that nesting
        is what corrupted the quotes in the first place."""
        content = self._generate()
        launcher_section = content[content.index("Creating launcher") : content.index("Installation complete")]
        assert '> "%LAUNCHER%" echo @echo off' in launcher_section
        # No PowerShell invocation should be building the launcher lines.
        assert "$lines" not in launcher_section

    def test_closing_message_presents_claude_as_usual_path(self):
        content = self._generate()
        # In-session re-auth now works, so `claude` is the normal way to start and
        # the launcher is presented as an optional convenience (not required).
        assert "Start Claude Code the usual way" in content
        assert "Optional: a 'claude-bedrock' launcher" in content
        assert "claude-bedrock.cmd" in content
        # The old "run the launcher, NOT 'claude' directly" framing must be gone.
        assert "NOT 'claude' directly" not in content
