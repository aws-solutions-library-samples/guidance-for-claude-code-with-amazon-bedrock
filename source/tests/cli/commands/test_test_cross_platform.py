# ABOUTME: Tests that `ccwb test` builds a cross-platform credential_process command
# ABOUTME: Regression guard against the /bin/sh wrapper that broke on Windows

"""Cross-platform regression tests for the `ccwb test` credential command.

The credential_process previously used a `/bin/sh -c '...'` wrapper to set the
CCWB_PROFILE env var. `/bin/sh` does not exist on Windows, so the temporary test
profile could never execute. The fix passes the profile via the binary's
`--profile` flag instead -- the same convention the install scripts use.
"""

import shlex
from pathlib import Path

TEST_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "claude_code_with_bedrock"
    / "cli"
    / "commands"
    / "test.py"
)


class TestNoShellWrapper:
    """The Windows-incompatible /bin/sh wrapper must not return."""

    def test_no_bin_sh_in_source(self):
        source = TEST_SOURCE.read_text(encoding="utf-8")
        assert "/bin/sh" not in source, "test.py must not use /bin/sh (breaks on Windows)"
        assert "/bin/bash" not in source, "test.py must not use /bin/bash (breaks on Windows)"

    def test_credential_command_uses_profile_flag(self):
        source = TEST_SOURCE.read_text(encoding="utf-8")
        # Both call sites build the command via the --profile flag format string.
        assert source.count('f"{credential_binary} --profile {test_profile_name}"') == 2


class TestCredentialCommandFormat:
    """The built command is what botocore expects: a shlex-parseable argv."""

    def _build(self, binary: str, profile: str) -> str:
        # Mirror the exact format string used in test.py (both call sites).
        credential_binary = binary
        test_profile_name = profile
        return f"{credential_binary} --profile {test_profile_name}"

    def test_command_is_shlex_parseable(self):
        # botocore parses credential_process with shlex; the result must be argv.
        cmd = self._build("/home/user/claude-code-with-bedrock/credential-process", "ClaudeCode")
        argv = shlex.split(cmd)
        assert argv == [
            "/home/user/claude-code-with-bedrock/credential-process",
            "--profile",
            "ClaudeCode",
        ]

    def test_windows_exe_path_parses(self):
        cmd = self._build(
            r"C:\Users\dev\claude-code-with-bedrock\credential-process.exe", "ClaudeCode"
        )
        argv = shlex.split(cmd, posix=False)
        assert argv[-2:] == ["--profile", "ClaudeCode"]
        assert argv[0].endswith("credential-process.exe")

    def test_no_shell_metacharacters(self):
        # No /bin/sh, no quoting wrapper -- a plain argv string.
        cmd = self._build("/opt/credential-process", "prod")
        assert "sh -c" not in cmd
        assert "'" not in cmd
