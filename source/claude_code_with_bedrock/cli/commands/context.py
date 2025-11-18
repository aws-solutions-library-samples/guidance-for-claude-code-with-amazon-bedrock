# ABOUTME: Context management commands for profile switching and inspection
# ABOUTME: Implements list, current, use, and show subcommands for deployment profiles

"""Context command - Manage deployment profile contexts."""

from cleo.commands.command import Command
from cleo.helpers import argument
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.validators import ProfileValidator


class ContextListCommand(Command):
    """List all available profiles."""

    name = "context list"
    description = "List all available deployment profiles"

    def handle(self) -> int:
        """Execute the context list command."""
        console = Console()

        try:
            config = Config.load()
            profiles = config.list_profiles()

            if not profiles:
                console.print("\n[yellow]No profiles found.[/yellow]")
                console.print("Run [cyan]ccwb init[/cyan] to create your first profile.\n")
                return 0

            # Create table
            table = Table(title="Available Profiles", box=box.ROUNDED, show_header=True, header_style="bold cyan")
            table.add_column("Profile Name", style="cyan", no_wrap=True)
            table.add_column("Status", justify="center")

            # Add profiles to table
            for profile_name in profiles:
                is_active = profile_name == config.active_profile
                status = "★ active" if is_active else ""
                style = "bold green" if is_active else "white"
                table.add_row(profile_name, status, style=style)

            console.print()
            console.print(table)

            if config.active_profile:
                console.print(f"\n[green]Active profile:[/green] {config.active_profile}")
            else:
                console.print("\n[yellow]No active profile set.[/yellow]")
                console.print("Use [cyan]ccwb context use <profile>[/cyan] to set one.\n")

            return 0

        except Exception as e:
            console.print(f"\n[red]Error listing profiles: {e}[/red]\n")
            return 1


class ContextCurrentCommand(Command):
    """Show the currently active profile."""

    name = "context current"
    description = "Show the currently active deployment profile"

    def handle(self) -> int:
        """Execute the context current command."""
        console = Console()

        try:
            config = Config.load()

            if not config.active_profile:
                console.print("\n[yellow]No active profile set.[/yellow]")
                console.print("Use [cyan]ccwb context use <profile>[/cyan] to set one.\n")
                return 0

            console.print(f"\n[green]Active profile:[/green] {config.active_profile}\n")
            return 0

        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            return 1


class ContextUseCommand(Command):
    """Switch to a different profile."""

    name = "context use"
    description = "Switch to a different deployment profile"
    arguments = [
        argument(
            "profile",
            description="Name of the profile to activate",
            optional=False,
        )
    ]

    def handle(self) -> int:
        """Execute the context use command."""
        console = Console()
        profile_name = self.argument("profile")

        try:
            config = Config.load()

            # Check if profile exists
            if profile_name not in config.list_profiles():
                console.print(f"\n[red]Error: Profile '{profile_name}' not found.[/red]")
                console.print("\nAvailable profiles:")
                for name in config.list_profiles():
                    console.print(f"  • {name}")
                console.print("\nUse [cyan]ccwb context list[/cyan] to see all profiles.\n")
                return 1

            # Switch to profile
            if config.set_active_profile(profile_name):
                console.print(f"\n[green]✓ Switched to profile:[/green] {profile_name}\n")
                return 0
            else:
                console.print(f"\n[red]Error: Could not switch to profile '{profile_name}'[/red]\n")
                return 1

        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            return 1


class ContextShowCommand(Command):
    """Show detailed information about a profile."""

    name = "context show"
    description = "Show detailed information about a deployment profile"
    arguments = [
        argument(
            "profile",
            description="Name of the profile to show (default: active profile)",
            optional=True,
        )
    ]

    def handle(self) -> int:
        """Execute the context show command."""
        console = Console()
        profile_name = self.argument("profile")

        try:
            config = Config.load()

            # Use active profile if none specified
            if not profile_name:
                profile_name = config.active_profile
                if not profile_name:
                    console.print("\n[red]No active profile set and no profile specified.[/red]")
                    console.print("Use [cyan]ccwb context show <profile>[/cyan] or set an active profile.\n")
                    return 1

            # Load profile
            try:
                profile = config.load_profile(profile_name)
            except FileNotFoundError:
                console.print(f"\n[red]Error: Profile '{profile_name}' not found.[/red]")
                console.print("\nUse [cyan]ccwb context list[/cyan] to see all profiles.\n")
                return 1

            # Display profile information
            console.print()
            console.print(
                Panel(
                    f"[cyan]{profile_name}[/cyan]",
                    title="Profile Configuration",
                    subtitle="Active" if profile_name == config.active_profile else "Inactive",
                    box=box.ROUNDED,
                )
            )

            # Authentication
            console.print("\n[bold cyan]Authentication:[/bold cyan]")
            console.print(f"  Provider Type:    {profile.provider_type or 'auto-detect'}")
            console.print(f"  Provider Domain:  {profile.provider_domain}")
            console.print(f"  Client ID:        {profile.client_id}")
            console.print(f"  Credential Store: {profile.credential_storage}")
            if profile.cognito_user_pool_id:
                console.print(f"  User Pool ID:     {profile.cognito_user_pool_id}")

            # AWS Infrastructure
            console.print("\n[bold cyan]AWS Infrastructure:[/bold cyan]")
            console.print(f"  Region:             {profile.aws_region}")
            console.print(f"  Identity Pool Name: {profile.identity_pool_name}")
            console.print(f"  Federation Type:    {profile.federation_type}")
            if profile.federated_role_arn:
                console.print(f"  Federated Role ARN: {profile.federated_role_arn}")

            # Bedrock
            console.print("\n[bold cyan]Bedrock Configuration:[/bold cyan]")
            if profile.selected_model:
                console.print(f"  Selected Model:       {profile.selected_model}")
            if profile.selected_source_region:
                console.print(f"  Source Region:        {profile.selected_source_region}")
            if profile.cross_region_profile:
                console.print(f"  Cross-Region Profile: {profile.cross_region_profile}")
            if profile.allowed_bedrock_regions:
                console.print(f"  Allowed Regions:      {', '.join(profile.allowed_bedrock_regions)}")

            # Features
            console.print("\n[bold cyan]Features:[/bold cyan]")
            console.print(f"  Monitoring:           {'✓ enabled' if profile.monitoring_enabled else '✗ disabled'}")
            console.print(f"  Analytics:            {'✓ enabled' if profile.analytics_enabled else '✗ disabled'}")
            console.print(
                f"  Quota Monitoring:     {'✓ enabled' if profile.quota_monitoring_enabled else '✗ disabled'}"
            )
            console.print(f"  CodeBuild:            {'✓ enabled' if profile.enable_codebuild else '✗ disabled'}")

            # Distribution
            if profile.distribution_type:
                console.print("\n[bold cyan]Distribution:[/bold cyan]")
                console.print(f"  Type:         {profile.distribution_type}")
                if profile.distribution_type == "landing-page":
                    console.print(f"  IdP Provider: {profile.distribution_idp_provider}")
                    console.print(f"  IdP Domain:   {profile.distribution_idp_domain}")
                    if profile.distribution_custom_domain:
                        console.print(f"  Custom Domain: {profile.distribution_custom_domain}")

            # Metadata
            console.print("\n[bold cyan]Metadata:[/bold cyan]")
            console.print(f"  Schema Version: {profile.schema_version}")
            console.print(f"  Created:        {profile.created_at}")
            console.print(f"  Updated:        {profile.updated_at}")

            console.print()
            return 0

        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            return 1


class ConfigValidateCommand(Command):
    """Validate profile configuration."""

    name = "config validate"
    description = "Validate profile configuration for errors"
    arguments = [
        argument(
            "profile",
            description="Name of the profile to validate (default: active profile, or 'all' for all profiles)",
            optional=True,
        )
    ]

    def handle(self) -> int:
        """Execute the config validate command."""
        console = Console()
        profile_arg = self.argument("profile")

        try:
            config = Config.load()

            # Validate all profiles
            if profile_arg == "all":
                profiles_to_validate = config.list_profiles()
                if not profiles_to_validate:
                    console.print("\n[yellow]No profiles found to validate.[/yellow]\n")
                    return 0

                console.print(f"\n[cyan]Validating {len(profiles_to_validate)} profile(s)...[/cyan]\n")

                all_valid = True
                for profile_name in profiles_to_validate:
                    try:
                        profile = config.load_profile(profile_name)
                        result = ProfileValidator.validate_profile(profile.to_dict())

                        if result.valid:
                            console.print(f"[green]✓[/green] {profile_name}: Valid")
                            if result.warnings:
                                for warning in result.warnings:
                                    console.print(f"  [yellow]⚠[/yellow]  {warning}")
                        else:
                            console.print(f"[red]✗[/red] {profile_name}: Invalid")
                            for error in result.errors:
                                console.print(f"  [red]✗[/red]  {error}")
                            for warning in result.warnings:
                                console.print(f"  [yellow]⚠[/yellow]  {warning}")
                            all_valid = False

                    except Exception as e:
                        console.print(f"[red]✗[/red] {profile_name}: Error loading profile - {e}")
                        all_valid = False

                console.print()
                return 0 if all_valid else 1

            # Validate single profile
            else:
                profile_name = profile_arg or config.active_profile

                if not profile_name:
                    console.print("\n[red]No active profile set and no profile specified.[/red]")
                    console.print("Use [cyan]ccwb config validate <profile>[/cyan] or set an active profile.\n")
                    return 1

                # Load profile
                try:
                    profile = config.load_profile(profile_name)
                except FileNotFoundError:
                    console.print(f"\n[red]Error: Profile '{profile_name}' not found.[/red]")
                    console.print("\nUse [cyan]ccwb context list[/cyan] to see all profiles.\n")
                    return 1

                # Validate
                result = ProfileValidator.validate_profile(profile.to_dict())

                console.print(f"\n[bold]Validating profile:[/bold] {profile_name}\n")

                if result.valid:
                    console.print("[green]✓ Validation passed[/green]")
                    if result.warnings:
                        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
                        for warning in result.warnings:
                            console.print(f"  ⚠  {warning}")
                    console.print()
                    return 0
                else:
                    console.print(f"[red]✗ Validation failed ({len(result.errors)} error(s))[/red]")
                    console.print("\n[red]Errors:[/red]")
                    for error in result.errors:
                        console.print(f"  ✗  {error}")

                    if result.warnings:
                        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
                        for warning in result.warnings:
                            console.print(f"  ⚠  {warning}")

                    console.print()
                    return 1

        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            return 1


class ConfigExportCommand(Command):
    """Export profile configuration."""

    name = "config export"
    description = "Export profile configuration (sanitized for sharing)"
    arguments = [
        argument(
            "profile",
            description="Name of the profile to export (default: active profile)",
            optional=True,
        )
    ]

    def handle(self) -> int:
        """Execute the config export command."""
        import sys

        Console()
        console_err = Console(file=sys.stderr)
        profile_name = self.argument("profile")

        try:
            config = Config.load()

            # Use active profile if none specified
            if not profile_name:
                profile_name = config.active_profile
                if not profile_name:
                    console_err.print("\n[red]No active profile set and no profile specified.[/red]")
                    console_err.print("Use [cyan]ccwb config export <profile>[/cyan] or set an active profile.\n")
                    return 1

            # Load profile
            try:
                profile = config.load_profile(profile_name)
            except FileNotFoundError:
                console_err.print(f"\n[red]Error: Profile '{profile_name}' not found.[/red]")
                console_err.print("\nUse [cyan]ccwb context list[/cyan] to see all profiles.\n")
                return 1

            # Sanitize profile (remove secrets)
            profile_dict = profile.to_dict()
            sanitized = self._sanitize_profile(profile_dict)

            # Output JSON to stdout
            import json

            print(json.dumps(sanitized, indent=2))

            # Log to stderr
            console_err.print(f"\n[green]✓ Exported profile:[/green] {profile_name} (sanitized)")
            console_err.print("[dim]Secrets have been removed for safe sharing.[/dim]\n")

            return 0

        except Exception as e:
            console_err.print(f"\n[red]Error: {e}[/red]\n")
            return 1

    @staticmethod
    def _sanitize_profile(profile_data: dict) -> dict:
        """Remove sensitive data from profile for safe sharing.

        Args:
            profile_data: Profile dictionary to sanitize.

        Returns:
            Sanitized profile dictionary.
        """
        import copy

        sanitized = copy.deepcopy(profile_data)

        # Fields to remove (secrets/credentials)
        sensitive_fields = [
            "client_id",  # OIDC client ID
            "cognito_user_pool_id",  # Cognito User Pool ID
            "distribution_idp_client_id",  # Distribution client ID
            "distribution_idp_client_secret_arn",  # Secret ARN
            "federated_role_arn",  # IAM role ARN (may contain account ID)
        ]

        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "[REDACTED]"

        # Redact stack names (may contain account-specific info)
        if "stack_names" in sanitized:
            for key in sanitized["stack_names"]:
                sanitized["stack_names"][key] = "[REDACTED]"

        # Add export metadata
        from datetime import datetime

        sanitized["_exported_at"] = datetime.utcnow().isoformat()
        sanitized["_export_note"] = "Sensitive fields have been redacted. Update before importing."

        return sanitized


class ConfigImportCommand(Command):
    """Import profile configuration."""

    name = "config import"
    description = "Import profile configuration from file"
    arguments = [
        argument(
            "file",
            description="Path to profile JSON file to import",
            optional=False,
        ),
        argument(
            "name",
            description="Name for the imported profile (default: name from file)",
            optional=True,
        ),
    ]

    def handle(self) -> int:
        """Execute the config import command."""
        console = Console()
        file_path = self.argument("file")
        profile_name = self.argument("name")

        try:
            import json
            from pathlib import Path

            # Read file
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                console.print(f"\n[red]Error: File not found: {file_path}[/red]\n")
                return 1

            with open(file_path_obj) as f:
                profile_data = json.load(f)

            # Use provided name or name from file
            if profile_name:
                profile_data["name"] = profile_name
            elif "name" not in profile_data:
                console.print("\n[red]Error: Profile name not specified and not found in file.[/red]")
                console.print(f"Use [cyan]ccwb config import {file_path} <name>[/cyan] to specify a name.\n")
                return 1

            profile_name = profile_data["name"]

            # Remove export metadata if present
            profile_data.pop("_exported_at", None)
            profile_data.pop("_export_note", None)

            # Validate profile
            console.print("\n[cyan]Validating imported profile...[/cyan]\n")
            result = ProfileValidator.validate_profile(profile_data)

            # Check for redacted fields
            redacted_fields = []
            for key, value in profile_data.items():
                if value == "[REDACTED]":
                    redacted_fields.append(key)

            if redacted_fields:
                console.print("[yellow]⚠  Redacted fields detected:[/yellow]")
                for field in redacted_fields:
                    console.print(f"   • {field}")
                console.print("\n[yellow]You must update these fields before the profile can be used.[/yellow]\n")

            # Show validation results
            if not result.valid:
                console.print(f"[red]✗ Validation failed ({len(result.errors)} error(s))[/red]")
                for error in result.errors:
                    console.print(f"  ✗  {error}")
                console.print()
            else:
                console.print("[green]✓ Validation passed[/green]")

            if result.warnings:
                console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
                for warning in result.warnings:
                    console.print(f"  ⚠  {warning}")
                console.print()

            # Ask for confirmation
            if not result.valid or redacted_fields:
                console.print("[yellow]Profile has validation errors or redacted fields.[/yellow]")
                console.print("Import anyway? (You can edit later) [y/N]: ", end="")

                import sys

                response = sys.stdin.readline().strip().lower()
                if response not in ["y", "yes"]:
                    console.print("\n[yellow]Import cancelled.[/yellow]\n")
                    return 1

            # Import profile (save)
            from claude_code_with_bedrock.config import Profile

            config = Config.load()

            profile = Profile.from_dict(profile_data)
            config.save_profile(profile)

            console.print(f"\n[green]✓ Imported profile:[/green] {profile_name}")
            console.print(f"[dim]Profile saved to: ~/.ccwb/profiles/{profile_name}.json[/dim]\n")

            return 0

        except json.JSONDecodeError as e:
            console.print(f"\n[red]Error: Invalid JSON file: {e}[/red]\n")
            return 1
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            return 1
