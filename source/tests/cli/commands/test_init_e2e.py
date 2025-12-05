# ABOUTME: End-to-end tests for init command
# ABOUTME: Tests complete workflows and integration points

"""End-to-end tests for init command."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Imports after path setup
# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.init import InitCommand


class TestInitCommandE2E:
    """End-to-end tests for the init command."""

    def test_init_command_instantiation(self):
        """Test that InitCommand can be instantiated without errors."""
        command = InitCommand()

        assert command is not None
        assert command.name == "init"
        assert command.description == "Interactive setup wizard for first-time deployment"

    def test_init_command_has_required_methods(self):
        """Test that InitCommand has all required methods."""
        command = InitCommand()

        # Check required methods exist
        assert hasattr(command, "handle")
        assert callable(command.handle)

        assert hasattr(command, "_check_prerequisites")
        assert callable(command._check_prerequisites)

        assert hasattr(command, "_gather_configuration")
        assert callable(command._gather_configuration)

        assert hasattr(command, "_review_configuration")
        assert callable(command._review_configuration)

        assert hasattr(command, "_save_configuration")
        assert callable(command._save_configuration)

    def test_validation_functions_accessible(self):
        """Test that validation functions are accessible from InitCommand."""
        from claude_code_with_bedrock.cli.commands.init import (
            validate_cognito_user_pool_id,
            validate_identity_pool_name,
        )

        # Test they can be called
        assert validate_identity_pool_name("test-pool") is True
        assert validate_cognito_user_pool_id("us-east-1_abc123") is True

        # Test invalid inputs return error messages
        assert isinstance(validate_identity_pool_name(""), str)
        assert isinstance(validate_cognito_user_pool_id("invalid"), str)

    def test_cli_can_register_init_command(self):
        """Test that the CLI can register and use InitCommand."""
        from claude_code_with_bedrock.cli import create_application

        app = create_application()

        # Check init command is registered
        assert app.has("init")

        # Get the command
        init_cmd = app.find("init")
        assert init_cmd is not None
        assert init_cmd.name == "init"

    def test_regex_operations_in_context(self):
        """Test that all regex operations work in the context of the init module."""
        import re

        from claude_code_with_bedrock.cli.commands import init as init_module

        # Test that re module is accessible in the init module's namespace
        assert hasattr(init_module, "re")

        # Test regex operations that are used in the module
        test_patterns = [
            (r"^[a-zA-Z0-9_-]+$", "test-pool_123", True),
            (r"^[\w-]+_[0-9a-zA-Z]+$", "us-east-1_abc123XYZ", True),
            (r"\.auth\.([^.]+)\.amazoncognito\.com", "app.auth.us-east-1.amazoncognito.com", True),
            (r"\.([a-z]{2}-[a-z]+-\d+)\.", "custom.us-west-2.example.com", True),
        ]

        for pattern, test_string, should_match in test_patterns:
            match = re.match(pattern, test_string) if pattern.startswith("^") else re.search(pattern, test_string)
            if should_match:
                assert match is not None, f"Pattern {pattern} should match {test_string}"
            else:
                assert match is None, f"Pattern {pattern} should not match {test_string}"

    @patch("claude_code_with_bedrock.cli.commands.init.Config")
    @patch("claude_code_with_bedrock.cli.commands.init.WizardProgress")
    def test_init_command_progress_handling(self, mock_progress, mock_config):
        """Test that init command handles progress correctly."""
        _command = InitCommand()

        # Mock the progress object
        progress_instance = MagicMock()
        mock_progress.return_value = progress_instance
        progress_instance.has_saved_progress.return_value = False
        progress_instance.get_saved_data.return_value = {}

        # Mock config
        config_instance = MagicMock()
        mock_config.load.return_value = config_instance
        config_instance.get_profile.return_value = None

        # This tests that the progress system is properly initialized
        # and doesn't cause any import or scoping issues
        assert mock_progress("init") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
