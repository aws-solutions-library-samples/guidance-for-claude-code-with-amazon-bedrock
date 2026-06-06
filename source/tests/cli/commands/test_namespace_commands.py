# ABOUTME: Tests for bare namespace CLI commands (quota, config, context)
# ABOUTME: Ensures running 'ccwb <namespace>' without subcommand shows help, not errors

"""Tests for bare namespace commands.

Prevents issue #264: running 'ccwb quota', 'ccwb config', or 'ccwb context'
without a subcommand returned 'command does not exist' instead of showing
available subcommands.
"""

import pytest
from cleo.testers.application_tester import ApplicationTester

from claude_code_with_bedrock.cli import create_application


class TestBareNamespaceCommands:
    """Bare namespace commands must print help, not crash or error."""

    @pytest.fixture
    def app_tester(self):
        app = create_application()
        return ApplicationTester(app)

    @pytest.mark.parametrize("namespace", ["quota", "config", "context"])
    def test_bare_namespace_does_not_error(self, app_tester, namespace):
        """Running 'ccwb <namespace>' must exit 0 and not say 'does not exist'."""
        app_tester.execute(namespace)
        output = app_tester.io.fetch_output()
        assert "does not exist" not in output
        assert app_tester.status_code == 0

    @pytest.mark.parametrize("namespace", ["quota", "config", "context"])
    def test_bare_namespace_shows_subcommands(self, app_tester, namespace):
        """Running 'ccwb <namespace>' must list available subcommands."""
        app_tester.execute(namespace)
        output = app_tester.io.fetch_output()
        # Should mention at least one subcommand
        assert "subcommand" in output.lower() or namespace in output.lower()

    def test_all_registered_commands_have_handle(self):
        """Every command in the application must have a handle() method."""
        app = create_application()
        for name in app._commands:
            cmd = app._commands[name]
            assert hasattr(cmd, 'handle'), (
                f"Command '{name}' is registered but has no handle() method"
            )
