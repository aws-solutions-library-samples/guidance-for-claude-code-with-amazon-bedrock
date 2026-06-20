# ABOUTME: Tests that install.bat template handles AWS CLI presence/absence correctly
# ABOUTME: Regression test for issue #592 (false success when aws not found)

"""Tests for install.bat AWS CLI handling logic."""

from pathlib import Path

import pytest


class TestInstallBatAwsCliHandling:
    """Verify install.bat correctly handles AWS CLI presence/absence."""

    @pytest.fixture(autouse=True)
    def load_package_py(self):
        self.package_path = (
            Path(__file__).parent.parent.parent.parent / "claude_code_with_bedrock" / "cli" / "commands" / "package.py"
        )
        self.content = self.package_path.read_text(encoding="utf-8")

    def test_has_aws_cli_detection_variable(self):
        """install.bat must set HAS_AWS_CLI variable based on 'where aws' check."""
        assert "set HAS_AWS_CLI=0" in self.content
        assert "set HAS_AWS_CLI=1" in self.content

    def test_profile_config_checks_has_aws_cli(self):
        """Profile configuration must be conditional on HAS_AWS_CLI."""
        assert 'if "!HAS_AWS_CLI!"=="1"' in self.content

    def test_fallback_writes_config_directly(self):
        """When AWS CLI is absent, must write ~/.aws/config directly via PowerShell."""
        assert ".aws" in self.content
        assert "config" in self.content
        assert "[profile" in self.content
        assert "credential_process" in self.content

    def test_no_unconditional_aws_calls_in_profile_setup(self):
        """aws configure must NOT be called unconditionally in the profile section."""
        # Find the profile configuration section
        profile_section_start = self.content.find("REM Configure AWS profiles")
        profile_section_end = self.content.find("Installation complete!", profile_section_start)
        profile_section = self.content[profile_section_start:profile_section_end]

        # Every 'aws configure' must be inside the HAS_AWS_CLI=1 branch
        lines = profile_section.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("aws configure"):
                # Look backwards for the HAS_AWS_CLI check (within 15 lines)
                context = "\n".join(lines[max(0, i - 15) : i])
                assert "HAS_AWS_CLI" in context, (
                    f"Line {i}: 'aws configure' called without HAS_AWS_CLI guard: {stripped}"
                )

    def test_success_message_only_on_actual_success(self):
        """'OK Created AWS profile' must not be printed unconditionally after aws calls."""
        profile_section_start = self.content.find("REM Configure AWS profiles")
        profile_section_end = self.content.find("Installation complete!", profile_section_start)
        profile_section = self.content[profile_section_start:profile_section_end]

        # The old bug: 'echo OK Created' appeared outside any error check
        lines = profile_section.splitlines()
        for i, line in enumerate(lines):
            if "OK Created AWS profile" in line:
                # Must be inside a conditional (errorlevel check or PowerShell Write-Host)
                context = "\n".join(lines[max(0, i - 3) : i + 1])
                is_conditional = "errorlevel" in context.lower() or "else" in context or "Write-Host" in line
                assert is_conditional, f"'OK Created AWS profile' at line {i} must be inside an error-check branch"
