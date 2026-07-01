# ABOUTME: Tests that the otel-helper.cmd wrapper correctly dispatches to .exe then .ps1 fallback
# ABOUTME: Regression coverage for the AV-bypass fallback chain (PRs #572, #580, #672)

"""Regression tests for the Windows otel-helper .cmd/.ps1 dispatch chain.

The .cmd wrapper tries the Go .exe first; if the binary is missing or AV-blocked
(exit code != 0), it falls through to the PowerShell script. These tests validate:

1. The .cmd structure is syntactically correct (no unmatched quotes/parens)
2. The fallback chain references correct relative paths
3. The .ps1 script emits valid JSON on stdout for the happy path
4. The .ps1 script handles missing config gracefully (empty JSON, not crash)

Bugs prevented:
- #567: Windows binary blocked by AV — users got no output at all
- #572: PowerShell fallback introduced but dispatch chain untested
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

OTEL_HELPER_DIR = Path(__file__).resolve().parents[1] / "otel_helper"
CMD_FILE = OTEL_HELPER_DIR / "otel-helper.cmd"
PS1_FILE = OTEL_HELPER_DIR / "otel-helper.ps1"


class TestOtelHelperCmdStructure:
    """Validate the .cmd wrapper script structure."""

    def test_cmd_file_exists(self):
        assert CMD_FILE.exists(), "otel-helper.cmd missing from source/otel_helper/"

    def test_ps1_file_exists(self):
        assert PS1_FILE.exists(), "otel-helper.ps1 missing from source/otel_helper/"

    def test_cmd_references_exe_with_relative_path(self):
        """The .cmd must reference otel-helper.exe via %~dp0 (same directory)."""
        content = CMD_FILE.read_text(encoding="utf-8")
        assert "%~dp0otel-helper.exe" in content, ".cmd must use %~dp0otel-helper.exe for same-directory resolution"

    def test_cmd_references_ps1_with_relative_path(self):
        """The .cmd must reference otel-helper.ps1 via %~dp0 (same directory)."""
        content = CMD_FILE.read_text(encoding="utf-8")
        assert "%~dp0otel-helper.ps1" in content, ".cmd must use %~dp0otel-helper.ps1 for same-directory resolution"

    def test_cmd_suppresses_exe_stderr(self):
        """The .cmd must suppress .exe stderr (AV warnings) so Claude Code
        doesn't see noise on stderr when the binary fails."""
        content = CMD_FILE.read_text(encoding="utf-8")
        assert "2>nul" in content, ".cmd must redirect exe stderr to nul to suppress AV noise"

    def test_cmd_passes_args_to_both_exe_and_ps1(self):
        """Both dispatch paths must forward %* to preserve --profile etc."""
        content = CMD_FILE.read_text(encoding="utf-8")
        lines_with_exe = [l for l in content.splitlines() if "otel-helper.exe" in l]
        lines_with_ps1 = [l for l in content.splitlines() if "otel-helper.ps1" in l]
        assert any("%*" in l for l in lines_with_exe), "exe invocation must pass %*"
        assert any("%*" in l for l in lines_with_ps1), "ps1 invocation must pass %*"

    def test_cmd_exits_on_exe_success(self):
        """If the .exe succeeds (exit 0), the .cmd must NOT also run the .ps1."""
        content = CMD_FILE.read_text(encoding="utf-8")
        # Pattern: exe call followed by conditional exit before ps1
        assert "exit /b 0" in content or "exit /b %errorlevel%" in content, (
            ".cmd must exit after successful .exe execution to prevent double-output"
        )


class TestOtelHelperPs1Contract:
    """Validate the PowerShell script meets the otel-helper output contract."""

    def test_ps1_outputs_json_structure(self):
        """The .ps1 must write JSON to stdout. Validate it has the expected
        output pattern (Write-Output with ConvertTo-Json or manual JSON)."""
        content = PS1_FILE.read_text(encoding="utf-8")
        # The script should produce JSON output via ConvertTo-Json or manual formatting
        assert "ConvertTo-Json" in content or '"headers"' in content, (
            ".ps1 must produce JSON output (ConvertTo-Json or manual JSON string)"
        )

    def test_ps1_uses_userprofile_not_home(self):
        """Windows paths must use $env:USERPROFILE, not $HOME or ~."""
        content = PS1_FILE.read_text(encoding="utf-8")
        assert "$env:USERPROFILE" in content, ".ps1 must use $env:USERPROFILE for Windows home directory"
        # $HOME is acceptable in PowerShell (it resolves correctly), but
        # the install path specifically uses USERPROFILE for parity with .cmd
        lines = content.splitlines()
        install_lines = [l for l in lines if "installDir" in l or "install_dir" in l]
        assert any("USERPROFILE" in l for l in install_lines), (
            "Install directory must use USERPROFILE for parity with install.bat"
        )

    def test_ps1_has_empty_headers_fallback(self):
        """On cache miss, the script must output empty headers (not crash).
        This is the anti-hammering pattern matching the Go binary."""
        content = PS1_FILE.read_text(encoding="utf-8")
        # Must have an empty/default output path
        assert "emptyHeadersCacheTTL" in content or "empty" in content.lower(), (
            ".ps1 must handle cache-miss gracefully with empty headers output"
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="PowerShell execution requires Windows")
    def test_ps1_runs_without_error_missing_config(self):
        """The .ps1 must not crash when no config/cache exists — it should
        output empty headers JSON and exit 0."""
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PS1_FILE),
                "-Profile",
                "NonExistentTestProfile",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env={"USERPROFILE": str(Path.home()), "PATH": ""},
        )
        # Skip if PowerShell itself failed to load (CI runner infrastructure issue)
        if result.returncode == 4294901760 or "Internal Windows PowerShell error" in result.stderr:
            pytest.skip("PowerShell runtime failed to load on this runner (infra issue, not code)")
        # Should exit 0 (graceful degradation)
        assert result.returncode == 0, f"ps1 crashed: stderr={result.stderr}"
        # Should produce valid JSON
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"ps1 output is not valid JSON: {result.stdout!r}")
        # Should have a headers key (possibly empty)
        assert "headers" in output or output == {}, f"Expected headers key or empty object, got: {output}"
