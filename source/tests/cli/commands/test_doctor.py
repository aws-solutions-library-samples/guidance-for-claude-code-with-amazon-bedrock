# ABOUTME: Unit tests for the doctor command
# ABOUTME: Tests health check logic with mocked install directories

"""Tests for the doctor command."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.cli.commands.doctor import run_doctor


class TestDoctorAllPass:
    """Test that all checks pass with a fully mocked install directory."""

    def test_all_checks_pass(self, tmp_path):
        """All checks pass when all files and binaries are present."""
        home = tmp_path

        # Create install directory with binary and config
        install_dir = home / "claude-code-with-bedrock"
        install_dir.mkdir()

        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        binary_path = install_dir / binary_name
        binary_path.touch()
        binary_path.chmod(0o755)

        # Config with a profile
        config = {"profiles": {"default": {"provider_domain": "example.okta.com", "client_id": "abc123"}}}
        (install_dir / "config.json").write_text(json.dumps(config))

        # AWS config
        aws_dir = home / ".aws"
        aws_dir.mkdir()
        (aws_dir / "config").write_text(
            "[profile ClaudeCode]\n"
            "credential_process = /home/user/claude-code-with-bedrock/credential-process --profile default\n"
        )

        # Claude settings
        claude_dir = home / ".claude"
        claude_dir.mkdir()
        settings = {"env": {"AWS_PROFILE": "ClaudeCode"}, "hooks": {"preToolUse": []}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        # Mock subprocess for credential-test
        with patch("claude_code_with_bedrock.cli.commands.doctor.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            checks = run_doctor(home=home)

        statuses = {c.name: c.status for c in checks}
        assert statuses["credential-process"] == "pass"
        assert statuses["config.json"] == "pass"
        assert statuses["aws-profile"] == "pass"
        assert statuses["settings.json"] == "pass"
        assert statuses["credential-test"] == "pass"
        assert statuses["otel-helper"] == "skipped"  # Monitoring not configured


class TestDoctorMissingBinary:
    """Test that missing binary results in FAIL."""

    def test_missing_binary_fails(self, tmp_path):
        """Missing credential-process binary → FAIL."""
        home = tmp_path

        # Create install dir without the binary
        install_dir = home / "claude-code-with-bedrock"
        install_dir.mkdir()

        checks = run_doctor(home=home)

        statuses = {c.name: c.status for c in checks}
        assert statuses["credential-process"] == "fail"
        assert "Not found" in next(c.message for c in checks if c.name == "credential-process")


class TestDoctorInvalidConfig:
    """Test that invalid config.json results in FAIL."""

    def test_invalid_config_json_fails(self, tmp_path):
        """Malformed config.json → FAIL."""
        home = tmp_path

        install_dir = home / "claude-code-with-bedrock"
        install_dir.mkdir()

        # Create binary so that check passes
        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).touch()

        # Write invalid JSON
        (install_dir / "config.json").write_text("{ invalid json !!!")

        checks = run_doctor(home=home)

        statuses = {c.name: c.status for c in checks}
        assert statuses["config.json"] == "fail"
        assert "Invalid JSON" in next(c.message for c in checks if c.name == "config.json")


class TestDoctorOtelSkip:
    """Test that otel-helper is SKIP when monitoring is not configured."""

    def test_no_monitoring_no_otel_skips(self, tmp_path):
        """No monitoring configured + no otel-helper → SKIP (not FAIL)."""
        home = tmp_path

        install_dir = home / "claude-code-with-bedrock"
        install_dir.mkdir()

        # Config without otel_collector_endpoint
        config = {"profiles": {"default": {"provider_domain": "example.okta.com"}}}
        (install_dir / "config.json").write_text(json.dumps(config))

        # Binary present so config loads
        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).touch()

        checks = run_doctor(home=home)

        statuses = {c.name: c.status for c in checks}
        assert statuses["otel-helper"] == "skipped"
        assert "Monitoring not configured" in next(c.message for c in checks if c.name == "otel-helper")

    def test_monitoring_configured_but_otel_missing_fails(self, tmp_path):
        """Monitoring configured but otel-helper missing → FAIL."""
        home = tmp_path

        install_dir = home / "claude-code-with-bedrock"
        install_dir.mkdir()

        # Config WITH otel_collector_endpoint
        config = {
            "profiles": {
                "default": {
                    "provider_domain": "example.okta.com",
                    "otel_collector_endpoint": "http://localhost:4318",
                }
            }
        }
        (install_dir / "config.json").write_text(json.dumps(config))

        binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
        (install_dir / binary_name).touch()

        checks = run_doctor(home=home)

        statuses = {c.name: c.status for c in checks}
        assert statuses["otel-helper"] == "fail"
        assert "Monitoring configured" in next(c.message for c in checks if c.name == "otel-helper")
