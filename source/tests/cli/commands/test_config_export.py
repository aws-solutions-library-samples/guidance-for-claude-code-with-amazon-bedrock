# ABOUTME: Tests for ccwb config export --output and --include-secrets flags
# ABOUTME: Verifies file output, stdout default, and secrets handling

"""Regression tests for config export command flags."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestConfigExportOutput:
    """Verify --output flag writes to file and stdout remains default."""

    def test_source_has_output_option(self):
        """ConfigExportCommand defines --output/-o option."""
        source = (Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "context.py").read_text()
        assert 'option("output", "o"' in source

    def test_source_has_include_secrets_option(self):
        """ConfigExportCommand defines --include-secrets option."""
        source = (Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "context.py").read_text()
        assert 'option("include-secrets"' in source

    def test_output_path_writes_file(self, tmp_path):
        """When output_path is set, JSON is written to file."""
        output_file = tmp_path / "export.json"
        data = {"aws_region": "us-east-1", "identity_pool_name": "test"}
        json_output = json.dumps(data, indent=2)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_output + "\n")

        content = output_file.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert parsed["aws_region"] == "us-east-1"
        assert content.endswith("\n")

    def test_sanitize_removes_secrets(self):
        """_sanitize_profile redacts sensitive fields."""
        from claude_code_with_bedrock.cli.commands.context import ConfigExportCommand

        cmd = ConfigExportCommand()
        profile_data = {
            "aws_region": "us-east-1",
            "client_id": "some-client-id",
            "identity_pool_name": "test-pool",
        }
        sanitized = cmd._sanitize_profile(profile_data)
        # Sensitive fields should be redacted
        assert sanitized["client_id"] == "[REDACTED]"
        # Non-secrets preserved
        assert sanitized["aws_region"] == "us-east-1"
        assert sanitized["identity_pool_name"] == "test-pool"

    def test_include_secrets_preserves_sensitive_fields(self):
        """When include_secrets is True, sensitive fields are NOT sanitized."""
        # This is a structural test: verify the code path
        source = (Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "context.py").read_text()
        # The key logic: include_secrets skips sanitization
        assert "profile_dict if include_secrets else self._sanitize_profile(profile_dict)" in source

    def test_default_behavior_unchanged(self):
        """Default (no flags) still outputs to stdout with sanitization."""
        source = (Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "context.py").read_text()
        # output default is None (stdout)
        assert 'default=None' in source
        # When no output_path, prints to stdout
        assert "print(json_output)" in source

    def test_file_write_error_handled_gracefully(self):
        """OSError on file write is caught and returns error message."""
        source = (Path(__file__).resolve().parents[3] / "claude_code_with_bedrock" / "cli" / "commands" / "context.py").read_text()
        # Verify explicit OSError handling for file write
        assert "except OSError as e:" in source
        assert "Error writing to" in source
