# ABOUTME: Configure SAML authentication for the IAM Identity Center landing page
# ABOUTME: Saves the SAML metadata URL to the profile and updates the CloudFormation stack

"""Configure SAML command - Set up SAML authentication for the IDC landing page.

IAM Identity Center has no API to create custom SAML applications, so admins
must create the SAML app manually in the IDC console (using the ACS URL /
Audience printed by `ccwb deploy distribution`). Once that's done and IDC
provides a SAML metadata URL, this command saves it to the profile and
re-deploys the distribution stack so CloudFormation's IdcSamlIdentityProvider
resource (conditional on IdcSamlMetadataUrl being set) gets created and wired
into both the web app client and the bootstrap client.
"""

from cleo.commands.command import Command
from cleo.helpers import argument, option
from rich.console import Console
from rich.panel import Panel

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.cli.utils.cloudformation import CloudFormationManager
from claude_code_with_bedrock.config import Config


class ConfigureSamlCommand(Command):
    """Configure SAML authentication for the IDC landing page."""

    name = "configure-saml"
    description = "Configure SAML authentication for IAM Identity Center landing page"

    arguments = [
        argument(
            "metadata-url",
            description="SAML metadata URL from the IAM Identity Center application",
        ),
    ]

    options = [
        option(
            "profile",
            None,
            description="Configuration profile to use (defaults to active profile)",
            flag=False,
        ),
    ]

    def handle(self) -> int:
        """Execute the configure-saml command."""
        console = Console()
        metadata_url = self.argument("metadata-url")

        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print("[red]No profile found. Run 'ccwb init' first.[/red]")
            return 1

        console.print(f"Using profile: [cyan]{profile.name}[/cyan]\n")

        if profile.distribution_type != "landing-page-idc":
            console.print("[red]This command is only for 'landing-page-idc' distribution type.[/red]")
            console.print(f"[dim]Current distribution type: {profile.distribution_type}[/dim]")
            return 1

        # Verify the distribution stack has already been deployed at least once
        # (the ACS URL / Audience the admin needed to create the SAML app come
        # from this stack's outputs).
        stack_name = profile.stack_names.get("distribution", f"{profile.identity_pool_name}-distribution")
        cf_manager = CloudFormationManager(region=profile.aws_region)

        existing_outputs = get_stack_outputs(stack_name, profile.aws_region)

        if not existing_outputs:
            console.print(f"[red]Distribution stack '{stack_name}' not found.[/red]")
            console.print("[dim]Run 'poetry run ccwb deploy distribution' first.[/dim]")
            return 1

        landing_page_url = existing_outputs.get("DistributionURL", "")

        console.print(
            Panel(
                f"[bold]Stack:[/bold] {stack_name}\n"
                f"[bold]Landing Page:[/bold] {landing_page_url}\n"
                f"[bold]Metadata URL:[/bold] {metadata_url}",
                title="SAML Configuration",
                border_style="cyan",
            )
        )

        # Save the metadata URL to the profile and re-deploy. CloudFormation's
        # conditional IdcSamlIdentityProvider resource (and the callback-updater
        # custom resource that adds IAMIdentityCenter to both app clients) will
        # be created/updated as part of this stack update.
        profile.distribution_idc_saml_metadata_url = metadata_url
        config.save_profile(profile)

        console.print("\n[yellow]Updating distribution stack with SAML configuration...[/yellow]")

        from claude_code_with_bedrock.cli.commands.deploy import DeployCommand

        deploy_command = DeployCommand()
        result = deploy_command._deploy_stack("distribution", profile, console, cf_manager)

        if result != 0:
            console.print("[red]Stack update failed. See errors above.[/red]")
            return result

        updated_outputs = get_stack_outputs(stack_name, profile.aws_region) or {}
        saml_status = updated_outputs.get("IdcSamlConfigurationStatus", "")

        console.print(
            Panel(
                f"[bold green]SAML Configuration Complete![/bold green]\n\n"
                f"[bold]Landing Page:[/bold] {landing_page_url}\n"
                f"{saml_status}\n\n"
                f"Users can now sign in via IAM Identity Center.",
                border_style="green",
            )
        )

        return 0
