# ABOUTME: Cleanup command to remove installed authentication components
# ABOUTME: Removes files and configuration created by the test or manual installation

"""Cleanup command - Remove installed authentication components."""

import os
import shutil
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
        option(
            "force",
            description="Skip confirmation prompts",
            flag=True
        ),
        option(
            "profile",
            description="AWS profile name to remove (default: ClaudeCode)",
            flag=False,
            default="ClaudeCode"
        )
    ]
    
    def handle(self) -> int:
        """Execute the cleanup command."""
        console = Console()
        
        # Show what will be cleaned
        console.print(Panel.fit(
            "[bold yellow]Authentication Cleanup[/bold yellow]\n\n"
            "This will remove components installed by the test command or manual installation",
            border_style="yellow",
            padding=(1, 2)
        ))
        
        profile_name = self.option("profile")
        force = self.option("force")
        
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
            with open(aws_config, 'r') as f:
                if f"[profile {profile_name}]" in f.read():
                    has_profile = True
                    items_to_remove.append(("AWS Profile", profile_name, f"In {aws_config}"))
        
        # Check for Claude settings
        claude_settings = Path.home() / ".claude" / "settings.json"
        if claude_settings.exists():
            items_to_remove.append(("File", str(claude_settings), "Claude Code telemetry settings"))
        
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
                with open(aws_config, 'r') as f:
                    lines = f.readlines()
                
                # Find and remove the profile section
                new_lines = []
                skip = False
                for i, line in enumerate(lines):
                    if line.strip() == f"[profile {profile_name}]":
                        skip = True
                        # Remove any trailing blank line before the profile
                        if new_lines and new_lines[-1].strip() == "":
                            new_lines.pop()
                        continue
                    elif skip and line.strip() and line[0] == '[':
                        # Found next section, stop skipping
                        skip = False
                    elif skip and line.strip() == "":
                        # End of profile section
                        skip = False
                        continue
                    
                    if not skip:
                        new_lines.append(line)
                
                # Write back the cleaned config
                with open(aws_config, 'w') as f:
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
        
        console.print("\n[green]Cleanup completed![/green]")
        
        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")
        console.print("• Run 'ccwb package' to create a new distribution")
        console.print("• Run 'ccwb test' to reinstall and test")
        
        return 0