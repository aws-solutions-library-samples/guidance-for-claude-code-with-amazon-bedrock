# ABOUTME: CoWork 3P command for generating Claude Cowork MDM configurations
# ABOUTME: Standalone command that uses shared utilities from cli/utils/cowork_3p.py

"""CoWork 3P command - Generate Claude Cowork MDM configuration files."""

from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.panel import Panel

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    add_monitoring_config,
    build_mdm_config,
    derive_model_aliases,
    generate_json,
    generate_mobileconfig,
    generate_reg_file,
)
from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.models import get_source_region_for_profile


class CoworkGenerateCommand(Command):
    """
    Generate Claude Cowork 3P MDM configuration files

    cowork generate
    """

    name = "cowork generate"
    description = "Generate Claude Cowork 3P MDM configuration files (JSON, macOS, Windows)"

    options = [
        option(
            "profile",
            description="Configuration profile to use (defaults to active profile)",
            flag=False,
            default=None,
        ),
        option(
            "output",
            "o",
            description="Output directory (defaults to dist/cowork-3p/)",
            flag=False,
            default=None,
        ),
        option(
            "format",
            "f",
            description="Output format: all, json, mobileconfig, reg (default: all)",
            flag=False,
            default="all",
        ),
        option(
            "models",
            "m",
            description="Comma-separated model aliases (default: auto-detect from profile)",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:
        """Execute the cowork generate command."""
        console = Console()

        console.print(
            Panel(
                "[bold]Claude Cowork 3P MDM Configuration Generator[/bold]\n"
                "Generates MDM configuration files for Claude Desktop with Amazon Bedrock",
                border_style="cyan",
            )
        )

        # Load configuration
        config = Config.load()
        profile_name = self.option("profile") or config.active_profile or "ClaudeCode"
        profile = config.get_profile(profile_name)

        if not profile:
            console.print("[red]No deployment found. Run 'poetry run ccwb init' first.[/red]")
            return 1

        # Determine output directory
        output_dir_str = self.option("output")
        if output_dir_str:
            output_dir = Path(output_dir_str)
        else:
            output_dir = Path("dist") / "cowork-3p"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_format = self.option("format")
        valid_formats = ["all", "json", "mobileconfig", "reg"]
        if output_format not in valid_formats:
            console.print(f"[red]Invalid format '{output_format}'. Must be one of: {', '.join(valid_formats)}[/red]")
            return 1

        # Determine Bedrock region
        bedrock_region = get_source_region_for_profile(profile)

        # Derive model aliases
        models_option = self.option("models")
        if models_option:
            model_aliases = [m.strip() for m in models_option.split(",")]
        else:
            model_aliases = derive_model_aliases()

        console.print(f"\n[dim]Profile: {profile_name}[/dim]")
        console.print(f"[dim]Bedrock region: {bedrock_region}[/dim]")
        console.print(f"[dim]Models: {', '.join(model_aliases)}[/dim]")
        console.print(f"[dim]Output: {output_dir}[/dim]")

        # Build the MDM configuration using shared utility
        mdm_config = build_mdm_config(
            bedrock_region=bedrock_region,
            model_aliases=model_aliases,
            profile_name=profile_name,
        )

        # Add monitoring OTLP endpoint if available
        add_monitoring_config(mdm_config, profile, console)

        # Generate requested formats
        generated = []

        if output_format in ("all", "json"):
            generate_json(output_dir, mdm_config)
            generated.append("cowork-3p-config.json")
            console.print("[green]✓[/green] Generated cowork-3p-config.json")

        if output_format in ("all", "mobileconfig"):
            generate_mobileconfig(output_dir, mdm_config)
            generated.append("cowork-3p.mobileconfig")
            console.print("[green]✓[/green] Generated cowork-3p.mobileconfig (macOS)")

        if output_format in ("all", "reg"):
            generate_reg_file(output_dir, mdm_config)
            generated.append("cowork-3p.reg")
            console.print("[green]✓[/green] Generated cowork-3p.reg (Windows)")

        # Summary
        console.print(f"\n[bold green]Generated {len(generated)} file(s) in {output_dir}/[/bold green]")
        for f in generated:
            console.print(f"  • {f}")

        console.print("\n[bold]Next steps:[/bold]")
        console.print("  macOS: Deploy .mobileconfig via Jamf, Kandji, or Mosyle")
        console.print("  Windows: Deploy .reg via Group Policy, Intune, or SCCM")
        console.print("  Manual: Import cowork-3p-config.json via Claude Desktop Setup UI")
        console.print(
            "\n[dim]Docs: https://support.claude.com/en/articles/14680741"
            "-install-and-configure-claude-cowork-with-third-party-platforms[/dim]"
        )

        return 0
