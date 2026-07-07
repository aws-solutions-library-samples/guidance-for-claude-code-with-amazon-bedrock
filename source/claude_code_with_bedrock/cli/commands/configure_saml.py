# ABOUTME: Configure SAML authentication for IDC landing page
# ABOUTME: Automates Cognito SAML provider setup after manual IAM Identity Center configuration

"""Configure SAML command - Set up SAML authentication for IDC landing page."""

import json
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import argument, option
from rich.console import Console
from rich.panel import Panel


class ConfigureSamlCommand(Command):
    """Configure SAML authentication for the IDC landing page."""

    name = "configure-saml"
    description = "Configure SAML authentication for IAM Identity Center landing page"

    arguments = [
        argument(
            "metadata-url",
            description="SAML metadata URL from IAM Identity Center application",
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
        import boto3

        console = Console()
        metadata_url = self.argument("metadata-url")

        # Load profile
        from claude_code_with_bedrock.config import Config

        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print("[red]No profile found. Run 'ccwb init' first.[/red]")
            return 1

        console.print(f"Using profile: [cyan]{profile.name}[/cyan]\n")

        # Check if this is an IDC landing page deployment
        if profile.distribution_type != "landing-page-idc":
            console.print("[red]This command is only for 'landing-page-idc' distribution type.[/red]")
            console.print(f"[dim]Current distribution type: {profile.distribution_type}[/dim]")
            return 1

        # Try to load deployment info
        project_root = Path(__file__).parent.parent.parent.parent.parent
        deployment_info_file = project_root / "deployment" / "idc-landing-page" / "deployment-info.json"

        if deployment_info_file.exists():
            deployment_info = json.loads(deployment_info_file.read_text())
            user_pool_id = deployment_info.get("userPoolId")
            client_id = deployment_info.get("clientId")
            landing_page_url = deployment_info.get("landingPageUrl")
            region = deployment_info.get("region", profile.aws_region)
        else:
            # Fall back to getting from CloudFormation
            console.print("[yellow]Loading configuration from CloudFormation...[/yellow]")
            try:
                cf_client = boto3.client("cloudformation", region_name=profile.aws_region)
                cognito_stack = f"{profile.identity_pool_name}-cognito"
                landing_stack = f"{profile.identity_pool_name}-landing-page"

                cognito_outputs = cf_client.describe_stacks(StackName=cognito_stack)["Stacks"][0]["Outputs"]
                user_pool_id = next((o["OutputValue"] for o in cognito_outputs if o["OutputKey"] == "UserPoolId"), None)
                client_id = next(
                    (o["OutputValue"] for o in cognito_outputs if o["OutputKey"] == "UserPoolClientId"), None
                )

                landing_outputs = cf_client.describe_stacks(StackName=landing_stack)["Stacks"][0]["Outputs"]
                landing_page_url = next(
                    (o["OutputValue"] for o in landing_outputs if o["OutputKey"] == "LandingPageUrl"), None
                )
                region = profile.aws_region
            except Exception as e:
                console.print(f"[red]Error loading stack outputs: {e}[/red]")
                console.print("[dim]Make sure you have deployed the distribution stack first.[/dim]")
                return 1

        if not all([user_pool_id, client_id, landing_page_url]):
            console.print("[red]Missing required deployment information.[/red]")
            console.print("[dim]Run 'ccwb deploy distribution' first.[/dim]")
            return 1

        console.print(
            Panel(
                f"[bold]User Pool ID:[/bold] {user_pool_id}\n"
                f"[bold]Client ID:[/bold] {client_id}\n"
                f"[bold]Landing Page:[/bold] {landing_page_url}\n"
                f"[bold]Metadata URL:[/bold] {metadata_url}",
                title="SAML Configuration",
                border_style="cyan",
            )
        )

        cognito_client = boto3.client("cognito-idp", region_name=region)

        # Step 1: Create or update SAML Identity Provider
        console.print("\n[yellow]Creating SAML identity provider in Cognito...[/yellow]")

        try:
            # Check if provider exists
            try:
                cognito_client.describe_identity_provider(
                    UserPoolId=user_pool_id,
                    ProviderName="IAMIdentityCenter",
                )
                # Provider exists, update it
                console.print("[dim]Provider exists, updating...[/dim]")
                cognito_client.update_identity_provider(
                    UserPoolId=user_pool_id,
                    ProviderName="IAMIdentityCenter",
                    ProviderDetails={"MetadataURL": metadata_url},
                    AttributeMapping={"email": "email"},
                )
                console.print("[green]✓ SAML provider updated[/green]")
            except cognito_client.exceptions.ResourceNotFoundException:
                # Provider doesn't exist, create it
                cognito_client.create_identity_provider(
                    UserPoolId=user_pool_id,
                    ProviderName="IAMIdentityCenter",
                    ProviderType="SAML",
                    ProviderDetails={"MetadataURL": metadata_url},
                    AttributeMapping={"email": "email"},
                )
                console.print("[green]✓ SAML provider created[/green]")
        except Exception as e:
            console.print(f"[red]Error creating SAML provider: {e}[/red]")
            return 1

        # Step 2: Enable SAML provider in App Client (web client)
        console.print("[yellow]Enabling SAML provider in web app client...[/yellow]")

        try:
            cognito_client.update_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id,
                CallbackURLs=[f"{landing_page_url}/callback"],
                LogoutURLs=[f"{landing_page_url}/logout", landing_page_url],
                AllowedOAuthFlows=["code"],
                AllowedOAuthScopes=["openid", "email", "profile"],
                AllowedOAuthFlowsUserPoolClient=True,
                SupportedIdentityProviders=["COGNITO", "IAMIdentityCenter"],
            )
            console.print("[green]✓ Web app client updated with IAMIdentityCenter provider[/green]")
        except Exception as e:
            console.print(f"[red]Error updating app client: {e}[/red]")
            return 1

        # Step 3: Enable SAML provider in Bootstrap Client (for Claude Desktop dynamic config)
        console.print("[yellow]Enabling SAML provider in bootstrap client...[/yellow]")

        try:
            # Find the bootstrap client
            existing_clients = cognito_client.list_user_pool_clients(
                UserPoolId=user_pool_id,
                MaxResults=60,
            )
            bootstrap_client = next(
                (c for c in existing_clients.get("UserPoolClients", []) if "bootstrap" in c["ClientName"].lower()), None
            )

            if bootstrap_client:
                cognito_client.update_user_pool_client(
                    UserPoolId=user_pool_id,
                    ClientId=bootstrap_client["ClientId"],
                    CallbackURLs=["http://127.0.0.1:8080/callback"],
                    AllowedOAuthFlows=["code"],
                    AllowedOAuthScopes=["openid", "email", "profile"],
                    AllowedOAuthFlowsUserPoolClient=True,
                    SupportedIdentityProviders=["COGNITO", "IAMIdentityCenter"],
                )
                console.print("[green]✓ Bootstrap client updated with IAMIdentityCenter provider[/green]")
            else:
                console.print("[dim]No bootstrap client found (dynamic config disabled)[/dim]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not update bootstrap client: {e}[/yellow]")

        # Success
        console.print(
            Panel(
                f"[bold green]SAML Configuration Complete![/bold green]\n\n"
                f"[bold]Landing Page:[/bold] {landing_page_url}\n"
                f"[bold]Admin Console:[/bold] {landing_page_url}/admin\n\n"
                f"Users can now sign in via IAM Identity Center.",
                border_style="green",
            )
        )

        return 0
