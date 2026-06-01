# ABOUTME: Cleanup command to remove installed authentication components
# ABOUTME: Removes files and configuration created by the test or manual installation

"""Cleanup command - Remove installed authentication components."""

import os
import shutil
import subprocess
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm


class CleanupCommand(Command):
    name = "cleanup"
    description = "Remove installed authentication components"

    options = [
        option("force", description="Skip confirmation prompts", flag=True),
        option(
            "profile", description="AWS profile name to remove (default: ClaudeCode)", flag=False, default="ClaudeCode"
        ),
        option(
            "credentials-only", description="Only clear cached credentials without removing other components", flag=True
        ),
    ]

    def handle(self) -> int:
        """Execute the cleanup command."""
        console = Console()

        profile_name = self.option("profile")
        force = self.option("force")
        credentials_only = self.option("credentials-only")

        # Handle credentials-only mode
        if credentials_only:
            return self._clear_credentials_only(console, profile_name, force)

        # Show what will be cleaned
        console.print(
            Panel.fit(
                "[bold yellow]Authentication Cleanup[/bold yellow]\n\n"
                "This will remove components installed by the test command or manual installation",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        # List items to be removed
        items_to_remove = []

        # Check for installed files
        auth_dir = Path.home() / "claude-code-with-bedrock"
        if auth_dir.exists():
            items_to_remove.append(("Directory", str(auth_dir), "Authentication tools and config"))

        # Check for AWS profile
        aws_config = Path.home() / ".aws" / "config"
        has_profile = False
        if aws_config.exists():
            with open(aws_config) as f:
                if f"[profile {profile_name}]" in f.read():
                    has_profile = True
                    items_to_remove.append(("AWS Profile", profile_name, f"In {aws_config}"))

        # Check for Claude settings
        claude_settings = Path.home() / ".claude" / "settings.json"
        if claude_settings.exists():
            items_to_remove.append(("File", str(claude_settings), "Claude Code telemetry settings"))

        # Check for OTEL PATH line in shell rc files (new shim installer uses 'claude-otel-path'
        # marker; old sourced-function installer used 'claude-otel-wrapper' — clean up both).
        # Use anchored patterns that match only the installer-written line shapes, not bare
        # substrings that could accidentally match unrelated user lines.
        _OTEL_PATH_MARKER = "claude-otel-path"
        _OTEL_WRAPPER_MARKER = "claude-otel-wrapper"  # legacy marker from old installs
        # Installer-written line shapes (anchored match for deletion):
        #   new:    export PATH="$HOME/claude-code-with-bedrock/bin:$PATH"  # claude-otel-path
        #   legacy: [ -f "…/claude-otel-wrapper.sh" ] && source …  # claude-otel-wrapper
        _OTEL_PATH_LINE_ANCHOR = "claude-code-with-bedrock/bin"   # present only in the installer PATH line
        _OTEL_WRAPPER_LINE_ANCHOR = "claude-otel-wrapper.sh"      # present only in the legacy source line
        # Installer comment prefix — used to remove the preceding comment during cleanup.
        _OTEL_COMMENT_PREFIX = "# Claude Code OTEL"

        def _is_otel_path_line(line: str) -> bool:
            """Return True iff this line is an installer-written OTEL PATH / wrapper entry."""
            return (
                (_OTEL_PATH_MARKER in line and _OTEL_PATH_LINE_ANCHOR in line)
                or (_OTEL_WRAPPER_MARKER in line and _OTEL_WRAPPER_LINE_ANCHOR in line)
            )

        def _file_has_otel_line(content: str) -> bool:
            return any(_is_otel_path_line(l) for l in content.splitlines(keepends=True))

        rc_files_with_otel = []
        for rc_path in [
            Path.home() / ".zshrc",
            Path.home() / ".bashrc",
            Path.home() / ".bash_profile",
            Path.home() / ".profile",
        ]:
            if rc_path.exists():
                try:
                    with open(rc_path) as f:
                        content = f.read()
                    if _file_has_otel_line(content):
                        rc_files_with_otel.append(rc_path)
                        items_to_remove.append(
                            ("Shell rc", str(rc_path), "Claude Code OTEL PATH / wrapper line")
                        )
                except OSError:
                    pass

        # Check for fish conf.d drop-in
        fish_conf = Path.home() / ".config" / "fish" / "conf.d" / "claude-otel-path.fish"
        if fish_conf.exists():
            items_to_remove.append(("File", str(fish_conf), "Claude Code OTEL fish PATH config"))

        if not items_to_remove:
            console.print("[green]No authentication components found to clean up.[/green]")
            return 0

        # Display what will be removed
        console.print("\n[bold]Items to be removed:[/bold]")
        for item_type, item_path, description in items_to_remove:
            console.print(f"  • {item_type}: [cyan]{item_path}[/cyan]")
            console.print(f"    [dim]{description}[/dim]")

        # Confirm removal
        if not force:
            if not Confirm.ask("\n[bold yellow]Remove these items?[/bold yellow]"):
                console.print("\n[yellow]Cleanup cancelled.[/yellow]")
                return 0

        # Perform cleanup
        console.print("\n[bold]Cleaning up...[/bold]")

        # Remove authentication directory
        if auth_dir.exists():
            try:
                shutil.rmtree(auth_dir)
                console.print(f"✓ Removed {auth_dir}")
            except Exception as e:
                console.print(f"[red]✗ Failed to remove {auth_dir}: {e}[/red]")

        # Remove AWS profile
        if has_profile and aws_config.exists():
            try:
                # Read the config file
                with open(aws_config) as f:
                    lines = f.readlines()

                # Find and remove the profile section
                new_lines = []
                skip = False
                for _i, line in enumerate(lines):
                    if line.strip() == f"[profile {profile_name}]":
                        skip = True
                        # Remove any trailing blank line before the profile
                        if new_lines and new_lines[-1].strip() == "":
                            new_lines.pop()
                        continue
                    elif skip and line.strip() and line[0] == "[":
                        # Found next section, stop skipping
                        skip = False
                    elif skip and line.strip() == "":
                        # End of profile section
                        skip = False
                        continue

                    if not skip:
                        new_lines.append(line)

                # Write back the cleaned config
                with open(aws_config, "w") as f:
                    f.writelines(new_lines)

                console.print(f"✓ Removed AWS profile '{profile_name}'")
            except Exception as e:
                console.print(f"[red]✗ Failed to remove AWS profile: {e}[/red]")

        # Remove Claude settings if empty directory
        if claude_settings.exists():
            try:
                os.remove(claude_settings)
                console.print(f"✓ Removed {claude_settings}")

                # Remove .claude directory if empty
                claude_dir = claude_settings.parent
                if claude_dir.exists() and not any(claude_dir.iterdir()):
                    claude_dir.rmdir()
                    console.print(f"✓ Removed empty directory {claude_dir}")
            except Exception as e:
                console.print(f"[red]✗ Failed to remove Claude settings: {e}[/red]")

        # Remove OTEL PATH / wrapper lines from shell rc files.
        # Handles both the new 'claude-otel-path' marker and the legacy 'claude-otel-wrapper' marker.
        # Only remove lines that match the anchored installer-line shapes (not bare substring).
        # Also remove the preceding installer comment (starts with _OTEL_COMMENT_PREFIX)
        # and any blank line before it, so uninstall leaves the rc file byte-identical.
        for rc_path in rc_files_with_otel:
            try:
                with open(rc_path) as f:
                    lines = f.readlines()
                new_lines = []
                for line in lines:
                    if _is_otel_path_line(line):
                        # Remove the installer comment line immediately before this one.
                        # The comment may or may not contain a marker — match by prefix text.
                        while (
                            new_lines
                            and new_lines[-1].strip().startswith("#")
                            and (
                                _OTEL_PATH_MARKER in new_lines[-1]
                                or _OTEL_WRAPPER_MARKER in new_lines[-1]
                                or new_lines[-1].strip().startswith(_OTEL_COMMENT_PREFIX)
                            )
                        ):
                            new_lines.pop()
                        # Remove an orphaned blank line left before the comment block.
                        if new_lines and new_lines[-1].strip() == "":
                            new_lines.pop()
                    else:
                        new_lines.append(line)
                with open(rc_path, "w") as f:
                    f.writelines(new_lines)
                console.print(f"✓ Removed OTEL PATH line from {rc_path}")
            except Exception as e:
                console.print(f"[red]✗ Failed to update {rc_path}: {e}[/red]")

        # Remove fish conf.d drop-in
        if fish_conf.exists():
            try:
                fish_conf.unlink()
                console.print(f"✓ Removed {fish_conf}")
            except Exception as e:
                console.print(f"[red]✗ Failed to remove {fish_conf}: {e}[/red]")

        console.print("\n[green]Cleanup completed![/green]")

        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")
        console.print("• Run 'ccwb package' to create a new distribution")
        console.print("• Run 'ccwb test' to reinstall and test")

        return 0

    def _clear_credentials_only(self, console, profile_name, force):
        """Clear only cached credentials without removing other components."""
        console.print(
            Panel.fit(
                "[bold cyan]Clear Cached Credentials[/bold cyan]\n\n"
                f"This will clear cached credentials for profile: {profile_name}",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Check if credential-process exists
        credential_process = Path.home() / "claude-code-with-bedrock" / "credential-process"

        if not credential_process.exists():
            console.print("[yellow]Credential process not found. Nothing to clear.[/yellow]")
            return 0

        # Confirm clearing
        if not force:
            if not Confirm.ask("\n[bold yellow]Clear cached credentials?[/bold yellow]"):
                console.print("\n[yellow]Operation cancelled.[/yellow]")
                return 0

        # Run the credential process with --clear-cache flag
        console.print("\n[bold]Clearing cached credentials...[/bold]")

        try:
            result = subprocess.run(
                [str(credential_process), "--profile", profile_name, "--clear-cache"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                if result.stderr:
                    # Parse the output to show what was cleared
                    for line in result.stderr.split("\n"):
                        if line.strip():
                            console.print(f"  {line}")
                console.print("\n[green]✓ Cached credentials cleared successfully![/green]")
            else:
                console.print(f"[red]Failed to clear credentials: {result.stderr}[/red]")
                return 1

        except subprocess.TimeoutExpired:
            console.print("[red]Operation timed out[/red]")
            return 1
        except Exception as e:
            console.print(f"[red]Error clearing credentials: {e}[/red]")
            return 1

        console.print("\n[bold]Next steps:[/bold]")
        console.print("• The next AWS command will trigger re-authentication")
        console.print("• Use 'export AWS_PROFILE=ClaudeCode' to set the profile")

        return 0
