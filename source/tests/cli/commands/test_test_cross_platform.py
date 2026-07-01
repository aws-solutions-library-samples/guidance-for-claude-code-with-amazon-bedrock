# ABOUTME: Tests that `ccwb test` builds a cross-platform credential_process command
# ABOUTME: Regression guard against the /bin/sh wrapper that broke on Windows

"""Cross-platform regression tests for the `ccwb test` credential command.

The credential_process previously used a `/bin/sh -c '...'` wrapper to set the
CCWB_PROFILE env var. `/bin/sh` does not exist on Windows, so the temporary test
profile could never execute. The fix passes the profile via the binary's
`--profile` flag instead -- the same convention the install scripts use -- and
quotes the binary path so a space in it survives botocore's shell split.
"""

from pathlib import Path

import pytest

# botocore is the parser that actually executes credential_process; test against
# the real splitter (shlex on POSIX, a Windows-rules splitter on win32) rather
# than re-implementing it.
from botocore.compat import compat_shell_split

TEST_SOURCE = Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "test.py"


def _build_command(credential_binary: str, test_profile_name: str) -> str:
    """The exact credential_process string `ccwb test` writes (both call sites).

    Kept in sync with test.py; the source-text test below guards against drift.
    """
    return f'"{credential_binary}" --profile {test_profile_name}'


class TestNoShellWrapper:
    """The Windows-incompatible /bin/sh wrapper must not return."""

    def test_no_bin_sh_in_source(self):
        source = TEST_SOURCE.read_text(encoding="utf-8")
        # Allow the substring in comments/docstrings; forbid the executable wrapper.
        assert "/bin/sh -c" not in source, "test.py must not use a /bin/sh wrapper (breaks on Windows)"
        assert "/bin/bash -c" not in source, "test.py must not use a /bin/bash wrapper (breaks on Windows)"

    def test_both_call_sites_use_helper_format(self):
        # Both credential_command assignments use the quoted --profile form.
        source = TEST_SOURCE.read_text(encoding="utf-8")
        assert source.count("credential_command = f'\"{credential_binary}\" --profile {test_profile_name}'") == 2


class TestCredentialCommandParsing:
    """The command must parse, via botocore's real splitter, back to argv."""

    @pytest.mark.parametrize(
        "binary",
        [
            "/home/user/claude-code-with-bedrock/credential-process",
            "/opt/credential-process",
            r"C:\Users\dev\claude-code-with-bedrock\credential-process.exe",
            # The regression that motivated quoting: a space in the path.
            r"C:\Users\First Last\claude code with bedrock\credential-process.exe",
            "/Users/jane doe/claude-code-with-bedrock/credential-process",
        ],
    )
    @pytest.mark.parametrize("platform", ["linux2", "darwin", "win32"])
    def test_path_survives_shell_split(self, binary, platform):
        # Skip Windows-style backslash paths on POSIX splitters and vice versa;
        # each path form is only ever produced on its own platform.
        is_windows_path = "\\" in binary
        if is_windows_path and platform != "win32":
            pytest.skip("Windows path only occurs on win32")
        if not is_windows_path and platform == "win32":
            pytest.skip("POSIX path only occurs on POSIX")

        cmd = _build_command(binary, "ClaudeCode")
        argv = compat_shell_split(cmd, platform=platform)
        # The binary path must come back as ONE argument, not split on its spaces.
        assert argv[0] == binary, f"path was mis-split on {platform}: {argv}"
        assert argv[-2:] == ["--profile", "ClaudeCode"]

    def test_no_shell_metacharacters(self):
        # No /bin/sh, no env-var wrapper -- just a quoted path plus flag.
        cmd = _build_command("/opt/credential-process", "prod")
        assert "sh -c" not in cmd
        assert "CCWB_PROFILE" not in cmd
