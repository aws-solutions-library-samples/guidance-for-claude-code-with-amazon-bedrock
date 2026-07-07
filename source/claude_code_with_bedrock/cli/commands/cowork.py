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
    add_websearch_mcp_config,
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
        option(
            "auth-type",
            "a",
            description="Authentication type: profile (credential_process) or idc (native IAM Identity Center SSO)",
            flag=False,
            default="profile",
        ),
        option(
            "idc-start-url",
            description="IAM Identity Center start URL (required for --auth-type=idc)",
            flag=False,
            default=None,
        ),
        option(
            "idc-region",
            description="IAM Identity Center region (defaults to Bedrock region)",
            flag=False,
            default=None,
        ),
        option(
            "idc-account-id",
            description="AWS account ID for IAM Identity Center",
            flag=False,
            default=None,
        ),
        option(
            "idc-role-name",
            description="IAM Identity Center permission set/role name",
            flag=False,
            default=None,
        ),
        option(
            "model-id",
            description="Full Bedrock model ID with label (format: model-id|Label Name, use | as separator)",
            flag=False,
            default=None,
        ),
        option(
            "deployment-uuid",
            description="Deployment organization UUID",
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
        valid_formats = ["all", "json", "mobileconfig", "reg", "admx", "ps1"]
        if output_format not in valid_formats:
            console.print(f"[red]Invalid format '{output_format}'. Must be one of: {', '.join(valid_formats)}[/red]")
            return 1

        # Determine Bedrock region
        bedrock_region = get_source_region_for_profile(profile)

        # Get auth type and IDC options
        auth_type = self.option("auth-type")
        if auth_type not in ("profile", "idc"):
            console.print(f"[red]Invalid auth-type '{auth_type}'. Must be 'profile' or 'idc'.[/red]")
            return 1

        idc_start_url = self.option("idc-start-url")
        idc_region = self.option("idc-region") or bedrock_region
        idc_account_id = self.option("idc-account-id")
        idc_role_name = self.option("idc-role-name")
        deployment_uuid = self.option("deployment-uuid")

        # Validate IDC options if using IDC auth
        if auth_type == "idc":
            if not idc_start_url:
                console.print("[red]--idc-start-url is required when using --auth-type=idc[/red]")
                return 1
            if not idc_account_id:
                console.print("[red]--idc-account-id is required when using --auth-type=idc[/red]")
                return 1
            if not idc_role_name:
                console.print("[red]--idc-role-name is required when using --auth-type=idc[/red]")
                return 1

        # Derive model aliases or use model-id with label
        model_id_option = self.option("model-id")
        models_option = self.option("models")
        models_with_labels = None
        model_aliases = []

        if model_id_option:
            # Parse model-id|Label format (use | as separator since model IDs contain :)
            models_with_labels = []
            for model_spec in model_id_option.split(","):
                if "|" in model_spec:
                    model_id, label = model_spec.split("|", 1)
                    models_with_labels.append({"name": model_id.strip(), "labelOverride": label.strip()})
                else:
                    models_with_labels.append({"name": model_spec.strip()})
        elif models_option:
            model_aliases = [m.strip() for m in models_option.split(",")]
        else:
            model_aliases = derive_model_aliases()

        console.print(f"\n[dim]Profile: {profile_name}[/dim]")
        console.print(f"[dim]Auth type: {auth_type}[/dim]")
        console.print(f"[dim]Bedrock region: {bedrock_region}[/dim]")
        if models_with_labels:
            console.print(
                f"[dim]Models: {', '.join(m.get('labelOverride', m['name']) for m in models_with_labels)}[/dim]"
            )
        else:
            console.print(f"[dim]Models: {', '.join(model_aliases)}[/dim]")
        console.print(f"[dim]Output: {output_dir}[/dim]")
        if auth_type == "idc":
            console.print(f"[dim]IDC Start URL: {idc_start_url}[/dim]")
            console.print(f"[dim]IDC Role: {idc_role_name}[/dim]")

        # Build the MDM configuration using shared utility
        mdm_config = build_mdm_config(
            bedrock_region=bedrock_region,
            model_aliases=model_aliases,
            profile_name=profile_name,
            auth_type=auth_type,
            idc_start_url=idc_start_url,
            idc_region=idc_region,
            idc_account_id=idc_account_id,
            idc_role_name=idc_role_name,
            models_with_labels=models_with_labels,
            deployment_org_uuid=deployment_uuid,
            extra_keys=profile.cowork_3p_extra_keys or None,
            credential_mode=getattr(profile, "cowork_credential_mode", "helper"),
            credential_helper_ttl_sec=getattr(profile, "cowork_credential_helper_ttl_sec", 3500),
        )

        # Add monitoring OTLP endpoint if available
        add_monitoring_config(mdm_config, profile, console)

        # Add the AgentCore web search gateway as a managed MCP server (if enabled)
        add_websearch_mcp_config(mdm_config, profile, console)

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

        if output_format in ("all", "admx"):
            from claude_code_with_bedrock.cli.utils.cowork_3p import generate_admx

            generate_admx(output_dir, mdm_config)
            generated.append("ClaudeCowork3P.admx")
            generated.append("en-US/ClaudeCowork3P.adml")
            console.print("[green]✓[/green] Generated ClaudeCowork3P.admx + .adml (Group Policy / Intune)")

        if output_format in ("all", "ps1"):
            from claude_code_with_bedrock.cli.utils.cowork_3p import generate_intune_script

            generate_intune_script(output_dir, mdm_config)
            generated.append("Set-CoworkPolicy.ps1")
            console.print("[green]✓[/green] Generated Set-CoworkPolicy.ps1 (Intune platform script)")

        # Summary
        console.print(f"\n[bold green]Generated {len(generated)} file(s) in {output_dir}/[/bold green]")
        for f in generated:
            console.print(f"  • {f}")

        console.print("\n[bold]Next steps:[/bold]")
        console.print("  macOS: Deploy .mobileconfig via Jamf, Kandji, or Mosyle")
        console.print("  Windows (GPO/Intune): Import .admx template or run Set-CoworkPolicy.ps1")
        console.print("  Windows (manual): Deploy .reg via Group Policy or SCCM")
        console.print("  Manual: Import cowork-3p-config.json via Claude Desktop Setup UI")
        console.print(
            "\n[dim]Docs: https://support.claude.com/en/articles/14680741"
            "-install-and-configure-claude-cowork-with-third-party-platforms[/dim]"
        )

        return 0
