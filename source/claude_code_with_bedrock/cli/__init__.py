# ABOUTME: CLI module for Claude Code with Bedrock
# ABOUTME: Provides command-line interface for deployment and management

"""Command-line interface for Claude Code with Bedrock."""

from cleo.application import Application
from cleo.commands.command import Command
from cleo.helpers import argument, option

from .commands.init import InitCommand
from .commands.deploy import DeployCommand
from .commands.status import StatusCommand
from .commands.test import TestCommand
from .commands.package import PackageCommand
from .commands.destroy import DestroyCommand
from .commands.cleanup import CleanupCommand
from .commands.enterprise import EnterpriseCommand
# TokenCommand temporarily disabled - not implemented


def create_application() -> Application:
    """Create the CLI application."""
    application = Application(
        "claude-code-with-bedrock",
        "1.0.0"
    )
    
    # Add commands
    application.add(InitCommand())
    application.add(DeployCommand())
    application.add(StatusCommand())
    application.add(TestCommand())
    application.add(PackageCommand())
    application.add(DestroyCommand())
    application.add(CleanupCommand())
    application.add(EnterpriseCommand())
    # application.add(TokenCommand())  # Temporarily disabled
    
    return application


def main():
    """Main entry point for the CLI."""
    application = create_application()
    application.run()


if __name__ == "__main__":
    main()