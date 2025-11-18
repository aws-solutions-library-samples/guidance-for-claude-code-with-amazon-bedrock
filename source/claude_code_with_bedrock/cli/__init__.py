# ABOUTME: CLI module for Claude Code with Bedrock
# ABOUTME: Provides command-line interface for deployment and management

"""Command-line interface for Claude Code with Bedrock."""

from cleo.application import Application

from .commands.builds import BuildsCommand
from .commands.cleanup import CleanupCommand
from .commands.context import (
    ConfigExportCommand,
    ConfigImportCommand,
    ConfigValidateCommand,
    ContextCurrentCommand,
    ContextListCommand,
    ContextShowCommand,
    ContextUseCommand,
)
from .commands.deploy import DeployCommand
from .commands.destroy import DestroyCommand
from .commands.distribute import DistributeCommand
from .commands.init import InitCommand
from .commands.package import PackageCommand
from .commands.status import StatusCommand
from .commands.test import TestCommand

# TokenCommand temporarily disabled - not implemented


def create_application() -> Application:
    """Create the CLI application."""
    application = Application("claude-code-with-bedrock", "1.0.0")

    # Add commands
    application.add(InitCommand())
    application.add(DeployCommand())
    application.add(StatusCommand())
    application.add(TestCommand())
    application.add(PackageCommand())
    application.add(BuildsCommand())
    application.add(DistributeCommand())
    application.add(DestroyCommand())
    application.add(CleanupCommand())
    # application.add(TokenCommand())  # Temporarily disabled

    # Context management commands
    application.add(ContextListCommand())
    application.add(ContextCurrentCommand())
    application.add(ContextUseCommand())
    application.add(ContextShowCommand())

    # Config management commands
    application.add(ConfigValidateCommand())
    application.add(ConfigExportCommand())
    application.add(ConfigImportCommand())

    return application


def main():
    """Main entry point for the CLI."""
    application = create_application()
    application.run()


if __name__ == "__main__":
    main()
