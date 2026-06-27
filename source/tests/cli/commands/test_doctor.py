# ABOUTME: Tests for ccwb doctor command — validates health checks work correctly.
# ABOUTME: Covers binary detection, --explain integration, Windows path handling.

"""Tests for doctor command."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.doctor import (
    _find_binary,
    run_doctor,
)


class TestDoctorBinaryDetection:
    """Test binary detection across platforms."""

    def test_find_binary_unix(self, tmp_path):
        """Unix: finds binary without extension."""
        (tmp_path / "credential-process").write_text("#!/bin/sh")
        result = _find_binary(tmp_path, "credential-process")
        assert result is not None
        assert result.name == "credential-process"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_find_binary_windows_exe(self, tmp_path):
        """Windows: prefers .exe over .cmd/.ps1."""
        (tmp_path / "credential-process.exe").write_text("")
        (tmp_path / "credential-process.cmd").write_text("")
        result = _find_binary(tmp_path, "credential-process")
        assert result.suffix == ".exe"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_find_binary_windows_cmd_fallback(self, tmp_path):
        """Windows: falls back to .cmd when .exe missing."""
        (tmp_path / "credential-process.cmd").write_text("")
        result = _find_binary(tmp_path, "credential-process")
        assert result.suffix == ".cmd"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_find_binary_windows_ps1_fallback(self, tmp_path):
        """Windows: falls back to .ps1 when .exe and .cmd missing."""
        (tmp_path / "otel-helper.ps1").write_text("")
        result = _find_binary(tmp_path, "otel-helper")
        assert result.suffix == ".ps1"

    def test_find_binary_missing(self, tmp_path):
        """Returns None when binary not found."""
        result = _find_binary(tmp_path, "nonexistent")
        assert result is None


class TestDoctorHealthChecks:
    """Test the full doctor run with mocked filesystem."""

    def test_all_pass_with_complete_install(self, tmp_path):
        """All static checks pass with correct installation."""
        # Set up mock installation
        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()

        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).write_text("binary")

        otel_name = "otel-helper.exe" if sys.platform == "win32" else "otel-helper"
        (install_dir / otel_name).write_text("binary")

        config = {
            "profiles": {
                "default": {
                    "provider_domain": "company.okta.com",
                    "aws_region": "us-west-2",
                }
            }
        }
        (install_dir / "config.json").write_text(json.dumps(config))

        # AWS config
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        (aws_dir / "config").write_text(
            "[profile ClaudeCode]\ncredential_process = ~/claude-code-with-bedrock/credential-process\n"
        )

        # Claude settings
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"env": {"AWS_PROFILE": "ClaudeCode"}, "hooks": {}}))

        # Mock subprocess calls for --explain and --status
        explain_output = json.dumps(
            {
                "version": "2.5.0",
                "commit": "abc1234",
                "profile": "default",
                "auth": {"mode": "oidc", "reason": "sso_enabled=true"},
                "provider": {"type": "okta", "domain": "company.okta.com"},
                "quota": {"enabled": False},
                "storage": {"mode": "keyring"},
                "paths": {},
                "platform": {"os": "linux", "arch": "amd64"},
            }
        )
        status_output = json.dumps(
            {
                "version": "2.5.0",
                "proxy": {"listening": False, "port": 4318},
                "cache": {"has_headers": False},
            }
        )

        def mock_run(cmd, **kwargs):
            mock_result = MagicMock()
            if "--explain" in cmd:
                mock_result.returncode = 0
                mock_result.stdout = explain_output
            elif "--status" in cmd:
                mock_result.returncode = 0
                mock_result.stdout = status_output
            else:
                mock_result.returncode = 1
                mock_result.stdout = ""
            return mock_result

        with patch("claude_code_with_bedrock.cli.commands.doctor.subprocess.run", side_effect=mock_run):
            checks = run_doctor(home=tmp_path)

        # All static checks should pass (no monitoring configured, so otel is skipped)
        fails = [c for c in checks if c.status == "fail"]
        assert len(fails) == 0, f"Unexpected failures: {[(c.name, c.message) for c in fails]}"

    def test_missing_binary_fails(self, tmp_path):
        """Missing credential-process binary causes failure."""
        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()
        (install_dir / "config.json").write_text('{"profiles":{}}')

        checks = run_doctor(home=tmp_path)
        binary_check = next(c for c in checks if c.name == "credential-process")
        assert binary_check.status == "fail"

    def test_invalid_config_json_fails(self, tmp_path):
        """Invalid JSON in config.json causes failure."""
        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()
        (install_dir / "config.json").write_text("not valid json{{{")

        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).write_text("binary")

        checks = run_doctor(home=tmp_path)
        config_check = next(c for c in checks if c.name == "config.json")
        assert config_check.status == "fail"
        assert "Invalid JSON" in config_check.message

    def test_explain_populates_detail(self, tmp_path):
        """--explain output is captured in check detail field."""
        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()

        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).write_text("binary")
        (install_dir / "config.json").write_text('{"profiles":{"default":{}}}')

        explain_data = {
            "version": "2.5.0",
            "commit": "abc1234",
            "auth": {"mode": "idc", "reason": "auth_type=idc"},
            "profile": "default",
            "platform": {"os": "linux", "arch": "arm64"},
            "quota": {"enabled": True, "auth_method": "sigv4"},
            "storage": {"mode": "file"},
            "paths": {},
        }

        def mock_run(cmd, **kwargs):
            mock_result = MagicMock()
            if "--explain" in cmd:
                mock_result.returncode = 0
                mock_result.stdout = json.dumps(explain_data)
            else:
                mock_result.returncode = 1
                mock_result.stdout = ""
            return mock_result

        with patch("claude_code_with_bedrock.cli.commands.doctor.subprocess.run", side_effect=mock_run):
            checks = run_doctor(home=tmp_path)

        explain_check = next(c for c in checks if c.name == "explain")
        assert explain_check.status == "pass"
        assert explain_check.detail is not None
        assert explain_check.detail["auth"]["mode"] == "idc"
        assert "mode=idc" in explain_check.message

    def test_json_output_format(self, tmp_path):
        """--json output is valid JSON with expected structure."""
        install_dir = tmp_path / "claude-code-with-bedrock"
        install_dir.mkdir()
        (install_dir / "config.json").write_text('{"profiles":{}}')

        checks = run_doctor(home=tmp_path)
        output = {
            "checks": [
                {"name": c.name, "status": c.status, "message": c.message, "fix": c.fix, "detail": c.detail}
                for c in checks
            ],
        }
        # Should be valid JSON
        serialized = json.dumps(output)
        parsed = json.loads(serialized)
        assert "checks" in parsed
        assert all("name" in c for c in parsed["checks"])
