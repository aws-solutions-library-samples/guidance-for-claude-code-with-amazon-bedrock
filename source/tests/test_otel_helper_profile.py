# ABOUTME: Tests for otel-helper profile resolution (--profile flag) and the
# ABOUTME: collector sidecar's separate stdout/stderr log files.

"""Profile resolution and collector-launch regression tests.

The otel-helper previously resolved its profile ONLY from AWS_PROFILE, so a
Claude Code config pointing the helper at a non-default profile was ignored.
Resolution order (kept in sync with the Go binary's resolveProfile and the
.sh/.ps1 wrappers):

    --profile flag > CCWB_PROFILE env > AWS_PROFILE env > "ClaudeCode"

The winner is exported to AWS_PROFILE so every downstream consumer (cache
path, credential-process subprocess, collector sidecar) resolves the same
profile.

The collector sidecar must also write stdout and stderr to SEPARATE files:
Windows does not support redirecting both streams into one file, which made
the PowerShell fallback silently never start the collector.
"""

import os
import signal
import sys
import time

import pytest


@pytest.fixture(autouse=True)
def _clean_profile_env(monkeypatch):
    """Isolate each test from ambient profile overrides."""
    monkeypatch.delenv("CCWB_PROFILE", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _parse(monkeypatch, argv):
    from otel_helper.__main__ import parse_args

    monkeypatch.setattr(sys, "argv", ["otel-helper"] + argv)
    return parse_args()


class TestProfileResolution:
    def test_profile_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CCWB_PROFILE", "CcwbProfile")
        monkeypatch.setenv("AWS_PROFILE", "EnvProfile")
        _parse(monkeypatch, ["--profile", "FlagProfile"])
        # The flag must be exported so cache path, credential-process, and the
        # collector sidecar all resolve the SAME profile.
        assert os.environ["AWS_PROFILE"] == "FlagProfile"

    def test_ccwb_profile_beats_aws_profile(self, monkeypatch):
        # CCWB_PROFILE is the ccwb-specific override (same convention as
        # credential-process) and must win over the ambient AWS_PROFILE.
        monkeypatch.setenv("CCWB_PROFILE", "CcwbProfile")
        monkeypatch.setenv("AWS_PROFILE", "EnvProfile")
        _parse(monkeypatch, [])
        assert os.environ["AWS_PROFILE"] == "CcwbProfile"

    def test_no_flag_leaves_env_untouched(self, monkeypatch):
        monkeypatch.setenv("AWS_PROFILE", "EnvProfile")
        _parse(monkeypatch, [])
        assert os.environ["AWS_PROFILE"] == "EnvProfile"

    def test_cache_path_follows_profile_flag(self, monkeypatch, tmp_path):
        from otel_helper.__main__ import get_cache_path

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("AWS_PROFILE", "EnvProfile")
        _parse(monkeypatch, ["--profile", "FlagProfile"])
        assert get_cache_path().name == "FlagProfile-otel-headers.json"


class TestCollectorSeparateLogFiles:
    @pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in for otelcol")
    def test_collector_stdout_stderr_go_to_separate_files(self, monkeypatch, tmp_path):
        from otel_helper.__main__ import ensure_collector_running

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("AWS_PROFILE", "TestProfile")

        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()
        otelcol = install_dir / "otelcol"
        otelcol.write_text("#!/bin/sh\necho stdout-marker\necho stderr-marker >&2\nsleep 10\n", encoding="utf-8")
        otelcol.chmod(0o755)
        (install_dir / "collector-config.yaml").write_text("receivers:\n", encoding="utf-8")

        ensure_collector_running()

        pid_file = install_dir / "collector.pid"
        assert pid_file.exists(), "collector.pid must be written"
        pid = int(pid_file.read_text().strip())
        try:
            cache_dir = tmp_path / ".claude-code-session"
            log_file = cache_dir / "collector.log"
            err_file = cache_dir / "collector.err"
            deadline = time.time() + 3
            while time.time() < deadline:
                if (
                    log_file.exists()
                    and "stdout-marker" in log_file.read_text()
                    and err_file.exists()
                    and "stderr-marker" in err_file.read_text()
                ):
                    break
                time.sleep(0.02)
            assert log_file.exists() and "stdout-marker" in log_file.read_text()
            assert err_file.exists() and "stderr-marker" in err_file.read_text(), (
                "collector stderr must go to its own file — Windows cannot redirect both streams into one"
            )
            assert "stderr-marker" not in log_file.read_text()
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
