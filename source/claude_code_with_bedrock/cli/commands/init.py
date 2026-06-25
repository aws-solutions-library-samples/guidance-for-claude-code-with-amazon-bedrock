# ABOUTME: Interactive setup wizard for first-time users
# ABOUTME: Guides through complete Claude Code with Bedrock deployment

"""Init command - Interactive setup wizard."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import boto3
import questionary
from cleo.commands.command import Command
from cleo.helpers import option
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from claude_code_with_bedrock.cli.utils.aws import (
    check_bedrock_access,
    get_account_id,
    get_current_region,
    get_subnets,
    get_vpcs,
)
from claude_code_with_bedrock.cli.utils.progress import WizardProgress
from claude_code_with_bedrock.cli.utils.validators import (
    validate_oidc_provider_domain,
)
from claude_code_with_bedrock.config import Config, Profile


def validate_identity_pool_name(value: str) -> bool | str:
    """Validate identity pool name format.

    Args:
        value: The identity pool name to validate

    Returns:
        True if valid, error message if invalid
    """
    if not value or not re.match(r"^[a-zA-Z0-9_-]+$", value):
        return "Invalid name (alphanumeric, underscore, hyphen only)"
    # Stack names use identity_pool_name as prefix: e.g. {name}-otel-collector (16 chars suffix)
    # Various AWS resources append further suffixes. Removing explicit Names in CF
    # templates avoids hard limits, but shorter names prevent other edge cases.
    if len(value) > 20:
        return "Name too long (max 20 characters). This is used as the base for all CloudFormation stack names and AWS resources."
    return True


def validate_cognito_user_pool_id(value: str) -> bool | str:
    """Validate Cognito User Pool ID format.

    Args:
        value: The User Pool ID to validate

    Returns:
        True if valid, error message if invalid
    """
    if re.match(r"^[\w-]+_[0-9a-zA-Z]+$", value):
        return True
    return "Invalid User Pool ID format"


def _remember_prior_codebuild_region(config: dict, prior_region: str) -> None:
    """Record a CodeBuild region being abandoned, so destroy can clean its orphan.

    When the user changes the CodeBuild region during re-init, a stack may still
    exist in the old region. ``ccwb destroy`` reads the *current* region, so it
    can't reach the old one — we persist abandoned regions in
    ``config["codebuild"]["prior_regions"]`` and have destroy iterate them.
    Deduped, and never includes the region that is now current.
    """
    cb = config.setdefault("codebuild", {})
    priors = cb.setdefault("prior_regions", [])
    if prior_region and prior_region not in priors:
        priors.append(prior_region)


class InitCommand(Command):
    name = "init"
    description = "Interactive setup wizard for first-time deployment"

    options = [
        option(
            "profile",
            "p",
            description="Configuration profile name (optional, will prompt if not specified)",
            flag=False,
            default=None,
        ),
        option(
            "managed",
            None,
            description="Deploy settings to OS-level managed-settings.json (highest precedence, non-overridable)",
            flag=True,
        ),
    ]

    def handle(self) -> int:
        """Execute the init command."""
        console = Console()
        progress = WizardProgress("init")

        try:
            return self._handle_with_progress(console, progress)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Setup interrupted. Your progress has been saved.[/yellow]")
            console.print("Run [bold cyan]poetry run ccwb init[/bold cyan] to resume where you left off.")
            return 1
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            return 1

    def _handle_with_progress(self, console: Console, progress: WizardProgress) -> int:
        """Handle the command with progress tracking."""

        # Step 1: Select or create profile
        profile_name, is_new_profile, user_action = self._select_or_create_profile(console)

        if not profile_name:
            # User cancelled or switched profiles (no init needed)
            return 0

        # Check for existing deployment for this profile
        existing_config = self._check_existing_deployment(profile_name)

        # If user explicitly chose "Update existing profile", skip the second prompt
        if existing_config and user_action == "update":
            config = self._gather_configuration(progress, existing_config, profile_name)
            if not config:
                return 1
            if not self._review_configuration(config):
                return 1
            self._save_configuration(config, profile_name)
            console.print(f"\n[green]✓ Profile '{profile_name}' updated successfully![/green]")
            console.print("\nNext steps:")
            console.print("• Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]")
            console.print("• Create package: [cyan]poetry run ccwb package[/cyan]")
            console.print("• Test authentication: [cyan]poetry run ccwb test[/cyan]")
            return 0

        # Otherwise, show the configuration summary and ask what to do
        if existing_config:
            # Check if we found stacks or just configuration
            stacks_exist = existing_config.get("_stacks_found", True)

            console.print(f"\n[green]Found existing configuration for profile '{profile_name}'![/green]")
            self._show_existing_deployment(existing_config)

            if not stacks_exist:
                console.print(
                    f"\n[yellow]Note: Stacks for profile '{profile_name}' are not deployed in the "
                    f"current AWS account[/yellow]"
                )
                console.print("[dim]This profile may be configured for a different AWS account.[/dim]")

            action = questionary.select(
                "\nWhat would you like to do?",
                choices=["View current configuration", "Update configuration", "Start fresh"],
            ).ask()

            if action is None:  # User cancelled (Ctrl+C)
                console.print("\n[yellow]Setup cancelled.[/yellow]")
                return 1

            if action == "View current configuration":
                self._review_configuration(existing_config)
                return 0
            elif action == "Update configuration":
                config = self._gather_configuration(progress, existing_config, profile_name)
                if not config:
                    return 1
                if not self._review_configuration(config):
                    return 1
                self._save_configuration(config, profile_name)
                console.print(f"\n[green]✓ Profile '{profile_name}' updated successfully![/green]")
                console.print("\nNext steps:")
                console.print("• Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]")
                console.print("• Create package: [cyan]poetry run ccwb package[/cyan]")
                console.print("• Test authentication: [cyan]poetry run ccwb test[/cyan]")
                return 0
            elif action == "Start fresh":
                confirm = questionary.confirm(
                    "This will replace your existing configuration. Continue?", default=False
                ).ask()
                if confirm is None:  # User cancelled
                    console.print("\n[yellow]Setup cancelled.[/yellow]")
                    return 1
                if not confirm:
                    return 0
                # Clear saved progress to start fresh
                progress.clear()
                # Continue to normal flow

        # Check for saved progress
        elif progress.has_saved_progress():
            console.print("\n[yellow]Found saved progress from previous session:[/yellow]")
            console.print(progress.get_summary())

            resume = questionary.confirm("\nWould you like to resume where you left off?", default=True).ask()

            if not resume:
                progress.clear()

        # Welcome message
        welcome = Panel.fit(
            "[bold cyan]Welcome to Claude Code with Bedrock Setup![/bold cyan]\n\n"
            "This wizard will help you deploy Claude Code using Amazon Bedrock with:\n"
            "  • Secure authentication via your identity provider\n"
            "  • Usage monitoring and dashboards",
            border_style="cyan",
            padding=(1, 2),
        )
        console.print(welcome)

        # Prerequisites check
        if not self._check_prerequisites():
            return 1

        # Gather configuration
        config = self._gather_configuration(progress, profile_name=profile_name)
        if not config:
            return 1
        # Review and confirm
        if not self._review_configuration(config):
            return 1

        # Save configuration
        self._save_configuration(config, profile_name)
        progress.clear()  # Clear progress since we're done

        # Success message
        success_panel = Panel.fit(
            f"[bold green]✓ Profile '{profile_name}' created successfully![/bold green]\n\n"
            "Your configuration has been saved.\n\n"
            "Next steps:\n"
            "1. Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]\n"
            "2. Create package: [cyan]poetry run ccwb package[/cyan]\n"
            "3. Test authentication: [cyan]poetry run ccwb test[/cyan]\n"
            f"4. View profile: [cyan]poetry run ccwb context show {profile_name}[/cyan]",
            border_style="green",
            padding=(1, 2),
        )
        console.print("\n", success_panel)

        return 0

    def _check_prerequisites(self) -> bool:
        """Check system prerequisites."""
        console = Console()

        console.print("[bold cyan]Prerequisites Check:[/bold cyan]")

        # Required checks
        checks = {
            "AWS credentials configured": self._check_aws_credentials(),
            "Python 3.10+ available": self._check_python_version(),
        }

        # Check current region
        region = get_current_region()
        if region:
            checks[f"Current region: {region}"] = True

        # Display required check results
        all_passed = True
        for check, passed in checks.items():
            if passed:
                console.print(f"  [green]✓[/green] {check}")
            else:
                console.print(f"  [red]✗[/red] {check}")
                all_passed = False

        # AWS CLI is optional: Claude Code itself uses credential-process via
        # AWS_CREDENTIAL_PROCESS in ~/.claude/settings.json.  The CLI is only
        # needed here to deploy CloudFormation infrastructure and can be omitted
        # by teams that use an alternative deployment mechanism.
        aws_cli_present = self._check_aws_cli()
        if aws_cli_present:
            console.print("  [green]✓[/green] AWS CLI installed [dim](used for infrastructure deployment)[/dim]")
        else:
            console.print(
                "  [yellow]⚠[/yellow] AWS CLI not found [dim](optional — only needed for CloudFormation "
                "deployment; developer packages work without it)[/dim]"
            )

        go_present = self._check_go_version()
        if go_present:
            console.print("  [green]✓[/green] Go 1.23+ installed [dim](used for OTEL collector sidecar build)[/dim]")
        else:
            console.print(
                "  [yellow]⚠[/yellow] Go 1.23+ not found [dim](optional — only needed for building "
                "the OpenTelemetry collector sidecar)[/dim]"
            )

        # Bedrock access is optional (deployment user may not have direct Bedrock permissions)
        if region:
            bedrock_access = check_bedrock_access(region)
            if bedrock_access:
                console.print(f"  [green]✓[/green] Bedrock access enabled in {region}")
            else:
                console.print(
                    f"  [yellow]⚠[/yellow] Bedrock access not verified in {region} [dim](optional for deployment)[/dim]"
                )

        if not all_passed:
            console.print("\n[red]Prerequisites not met. Please fix the issues above.[/red]")
            return False

        console.print("")
        return True

    def _gather_configuration(
        self, progress: WizardProgress, existing_config: dict[str, Any] = None, profile_name: str | None = None
    ) -> dict[str, Any]:
        """Gather configuration from user."""
        console = Console()
        # Use existing config as base if provided, otherwise use saved progress
        if existing_config:
            config = existing_config.copy()
        else:
            config = progress.get_saved_data() or {}
        last_step = progress.get_last_step()

        # Skip completed steps only if we're not updating existing config
        if existing_config:
            # When updating existing config, don't skip any steps
            skip_okta = False
            skip_aws = False
            skip_monitoring = False
            skip_bedrock = False
        else:
            # Normal progress-based skipping for new installations
            skip_okta = last_step in ["okta_complete", "aws_complete", "monitoring_complete", "bedrock_complete"]
            skip_aws = last_step in ["aws_complete", "monitoring_complete", "bedrock_complete"]
            skip_monitoring = last_step in ["monitoring_complete", "bedrock_complete"]
            skip_bedrock = last_step in ["bedrock_complete"]

        # SSO Authentication Configuration
        if not skip_okta:
            console.print("\n[bold blue]Step 1: Authentication Configuration[/bold blue]")
            console.print("─" * 40)

            console.print("\n[bold]Authentication Method[/bold]")
            console.print("Choose how developers will authenticate to use Claude Code:\n")

            # Determine default based on existing config
            _existing_sso = config.get("sso_enabled", True)
            _existing_auth_type = config.get("auth_type", "oidc" if _existing_sso else "none")
            _default_auth = _existing_auth_type if _existing_auth_type in ("oidc", "idc", "none") else "oidc"

            auth_method = questionary.select(
                "Select authentication method:",
                choices=[
                    questionary.Choice(
                        "OIDC (Okta, Azure AD, Auth0, Cognito)",
                        value="oidc",
                    ),
                    questionary.Choice(
                        "IAM Identity Center",
                        value="idc",
                    ),
                    questionary.Choice(
                        "None",
                        value="none",
                    ),
                ],
                default=_default_auth,
            ).ask()

            if auth_method is None:
                return None

            # Map selection to stored config fields (backward compatible)
            config["auth_type"] = auth_method
            config["sso_enabled"] = auth_method == "oidc"

        # IAM Identity Center Configuration
        if not skip_okta and config.get("auth_type") == "idc":
            console.print("\n[bold blue]IAM Identity Center Configuration[/bold blue]")
            console.print("─" * 30)
            console.print()
            console.print("Configure your IAM Identity Center (SSO) connection.")
            console.print("Users will authenticate via their SSO portal and receive")
            console.print("temporary credentials for Bedrock access.\n")

            # IDC start URL
            idc_start_url = questionary.text(
                "Enter your IAM Identity Center start URL:",
                instruction="(e.g., https://company.awsapps.com/start)",
                default=config.get("idc_start_url", ""),
                validate=lambda x: bool(x.strip()) or "Start URL cannot be empty",
            ).ask()
            if idc_start_url is None:
                return None
            config["idc_start_url"] = idc_start_url.strip().rstrip("/")

            # SSO region (auto-suggest from start URL if possible)
            suggested_region = "us-east-1"
            _region_match = re.search(r"\.(us|eu|ap|sa|ca|me|af|il)-[a-z]+-\d+\.", idc_start_url)
            if _region_match:
                suggested_region = _region_match.group(0).strip(".")

            sso_region = questionary.text(
                "Enter your SSO region (where Identity Center is configured):",
                default=config.get("sso_region", suggested_region),
                validate=lambda x: bool(x.strip()) or "SSO region cannot be empty",
            ).ask()
            if sso_region is None:
                return None
            config["sso_region"] = sso_region.strip()

            # AWS account ID
            account_id = questionary.text(
                "Enter the AWS account ID for Bedrock access:",
                default=config.get("idc_account_id", ""),
                validate=lambda x: (
                    (len(x.strip()) == 12 and x.strip().isdigit()) or "Must be a 12-digit AWS account ID"
                ),
            ).ask()
            if account_id is None:
                return None
            config["idc_account_id"] = account_id.strip()

            # Permission set name
            permission_set = questionary.text(
                "Enter the permission set name (IAM role users will assume):",
                instruction="(e.g., BedrockDeveloperAccess)",
                default=config.get("idc_permission_set_name", "BedrockDeveloperAccess"),
                validate=lambda x: bool(x.strip()) or "Permission set name cannot be empty",
            ).ask()
            if permission_set is None:
                return None
            config["idc_permission_set_name"] = permission_set.strip()

            console.print("\n[green]✓[/green] IAM Identity Center configured")
            console.print(f"  Start URL: {config['idc_start_url']}")
            console.print(f"  Region: {config['sso_region']}")
            console.print(f"  Account: {config['idc_account_id']}")
            console.print(f"  Permission Set: {config['idc_permission_set_name']}")

        # OIDC Provider Configuration
        if not skip_okta and config.get("sso_enabled", True):
            console.print("\n[bold blue]OIDC Provider Configuration[/bold blue]")
            console.print("─" * 30)

            provider_domain = questionary.text(
                "Enter your OIDC provider domain:",
                validate=lambda x: (
                    validate_oidc_provider_domain(x) or "Invalid provider domain format (e.g., company.okta.com)"
                ),
                instruction=(
                    "(e.g., company.okta.com, company.auth0.com, "
                    "login.microsoftonline.com/{tenant-id}/v2.0, "
                    "my-app.auth.us-east-1.amazoncognito.com, or "
                    "my-app.auth-fips.us-gov-west-1.amazoncognito.com for GovCloud)"
                ),
                default=config.get("okta", {}).get("domain", ""),
            ).ask()

            if not provider_domain:
                return None

            # Strip https:// or http:// if provided
            provider_domain = provider_domain.replace("https://", "").replace("http://", "").strip("/")

            # Auto-detect provider type
            provider_type = None
            cognito_user_pool_id = None

            # Secure provider detection using proper URL parsing
            from urllib.parse import urlparse

            # Handle both full URLs and domain-only inputs
            url_to_parse = (
                provider_domain if provider_domain.startswith(("http://", "https://")) else f"https://{provider_domain}"
            )

            try:
                parsed = urlparse(url_to_parse)
                hostname = parsed.hostname

                if hostname:
                    hostname_lower = hostname.lower()

                    # Check for exact domain match or subdomain match
                    # Using endswith with leading dot prevents bypass attacks
                    if hostname_lower.endswith(".okta.com") or hostname_lower == "okta.com":
                        provider_type = "okta"
                    elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                        provider_type = "auth0"
                    elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                        provider_type = "azure"
                    elif hostname_lower.endswith(".windows.net") or hostname_lower == "windows.net":
                        provider_type = "azure"
                    elif hostname_lower.endswith(".amazoncognito.com") or hostname_lower == "amazoncognito.com":
                        provider_type = "cognito"
                    elif hostname_lower.startswith("cognito-idp.") and ".amazonaws.com" in hostname_lower:
                        # Handle cognito-idp.{region}.amazonaws.com format (commercial and GovCloud)
                        provider_type = "cognito"
                    elif hostname_lower == "accounts.google.com":
                        provider_type = "google"
                    elif questionary.confirm("Is this a custom domain for AWS Cognito User Pool?", default=False).ask():
                        provider_type = "cognito"
            except Exception:
                pass  # Continue to manual selection if parsing fails

            # If auto-detection failed (custom domain, Keycloak, PingFederate, etc.)
            # ask the user to select the provider type manually so deploy never gets None
            if provider_type is None:
                console.print("\n[yellow]Could not auto-detect provider type from domain.[/yellow]")
                provider_type = questionary.select(
                    "Select your identity provider type:",
                    choices=[
                        questionary.Choice("Okta", value="okta"),
                        questionary.Choice("Microsoft Entra ID / Azure AD", value="azure"),
                        questionary.Choice("Auth0", value="auth0"),
                        questionary.Choice("AWS Cognito User Pool", value="cognito"),
                        questionary.Choice("Google", value="google"),
                        questionary.Choice("Generic OIDC (PingFederate, Keycloak, ForgeRock, etc.)", value="generic"),
                    ],
                    instruction="(Used to select the correct CloudFormation template)",
                ).ask()
                if not provider_type:
                    return None

            # For Cognito, we must ask for the User Pool ID
            # Cannot reliably extract from domain due to case sensitivity
            if provider_type == "cognito":
                # Try to detect region from domain (handles both .auth. and .auth-fips.)
                region_match = re.search(r"\.auth(?:-fips)?\.([^.]+)\.amazoncognito\.com", provider_domain)
                if not region_match:
                    region_match = re.search(r"\.([a-z]{2}-(?:gov-)?[a-z]+-\d+)\.", provider_domain)

                # Auto-correct domain for GovCloud regions (must use auth-fips instead of auth)
                if region_match:
                    detected_region = region_match.group(1)
                    if (
                        detected_region.startswith("us-gov-")
                        and ".auth." in provider_domain
                        and ".auth-fips." not in provider_domain
                    ):
                        corrected_domain = provider_domain.replace(".auth.", ".auth-fips.")
                        console.print("\n[yellow]GovCloud detected: Correcting domain to use FIPS endpoint[/yellow]")
                        console.print(f"[dim]  {provider_domain} → {corrected_domain}[/dim]")
                        provider_domain = corrected_domain

                region_hint = f" for {region_match.group(1)}" if region_match else ""

                # Always ask for User Pool ID to ensure correct case
                cognito_user_pool_id = questionary.text(
                    f"Enter your Cognito User Pool ID{region_hint}:",
                    validate=validate_cognito_user_pool_id,
                    instruction="(case-sensitive)",
                    default=config.get("cognito_user_pool_id", ""),
                ).ask()

                if not cognito_user_pool_id:
                    return None

            # Generic OIDC providers (PingFederate, Keycloak, ForgeRock, custom IdP):
            # we cannot infer endpoint paths or the JWKS thumbprint from the domain,
            # so we try OIDC discovery first and fall through to manual entry on failure.
            oidc_issuer_url = None
            oidc_authorization_endpoint = None
            oidc_token_endpoint = None
            oidc_jwks_uri = None
            oidc_thumbprint = None
            if provider_type == "generic":
                from claude_code_with_bedrock.cli.utils.oidc_discovery import (
                    OidcDiscoveryError,
                    compute_jwks_thumbprint,
                    discover_oidc_endpoints,
                )

                console.print("\n[bold]Generic OIDC Configuration[/bold]")
                console.print(
                    "[dim]We'll try to auto-discover endpoints via the standard well-known URL,[/dim]\n"
                    "[dim]and fall back to manual entry if your IdP doesn't expose one.[/dim]\n"
                )

                # Construct issuer URL from the domain entered earlier; let the user override.
                default_issuer = (
                    provider_domain
                    if provider_domain.startswith(("http://", "https://"))
                    else f"https://{provider_domain}"
                ).rstrip("/")

                oidc_issuer_url = questionary.text(
                    "OIDC issuer URL:",
                    validate=lambda x: x.startswith("https://") or "Issuer must start with https://",
                    default=config.get("oidc_issuer_url", default_issuer),
                    instruction="(must match the 'iss' claim in tokens)",
                ).ask()
                if not oidc_issuer_url:
                    return None
                oidc_issuer_url = oidc_issuer_url.rstrip("/")

                # Attempt discovery — pre-fill defaults but always let the user confirm/override.
                discovered: dict[str, str] = {}
                console.print(f"[dim]Querying {oidc_issuer_url}/.well-known/openid-configuration ...[/dim]")
                try:
                    discovered = discover_oidc_endpoints(oidc_issuer_url)
                    console.print("[green]✓ Discovery succeeded.[/green]")
                    if discovered.get("issuer") and discovered["issuer"].rstrip("/") != oidc_issuer_url:
                        console.print(
                            f"[yellow]Note: discovery reports issuer={discovered['issuer']}, "
                            f"which differs from {oidc_issuer_url}. Tokens must match the "
                            f"discovered value.[/yellow]"
                        )
                except OidcDiscoveryError as e:
                    console.print(f"[yellow]Discovery failed: {e}[/yellow]")
                    console.print("[dim]Falling back to manual entry.[/dim]")

                oidc_authorization_endpoint = questionary.text(
                    "Authorization endpoint:",
                    validate=lambda x: bool(x) or "Authorization endpoint cannot be empty",
                    default=(
                        discovered.get("authorization_endpoint")
                        or config.get("oidc_authorization_endpoint")
                        or f"{oidc_issuer_url}/as/authorization.oauth2"
                    ),
                    instruction="(full URL)",
                ).ask()
                if not oidc_authorization_endpoint:
                    return None

                oidc_token_endpoint = questionary.text(
                    "Token endpoint:",
                    validate=lambda x: bool(x) or "Token endpoint cannot be empty",
                    default=(
                        discovered.get("token_endpoint")
                        or config.get("oidc_token_endpoint")
                        or f"{oidc_issuer_url}/as/token.oauth2"
                    ),
                    instruction="(full URL)",
                ).ask()
                if not oidc_token_endpoint:
                    return None

                oidc_jwks_uri = questionary.text(
                    "JWKS URI:",
                    validate=lambda x: bool(x) or "JWKS URI cannot be empty",
                    default=(discovered.get("jwks_uri") or config.get("oidc_jwks_uri") or f"{oidc_issuer_url}/pf/JWKS"),
                    instruction="(full URL)",
                ).ask()
                if not oidc_jwks_uri:
                    return None

                # Try to auto-compute the JWKS leaf-cert thumbprint via TLS handshake.
                # Falls back to manual entry on any failure (firewall, hostname mismatch, etc.).
                computed_thumbprint = ""
                console.print(f"[dim]Fetching TLS certificate from {oidc_jwks_uri} ...[/dim]")
                try:
                    computed_thumbprint = compute_jwks_thumbprint(oidc_jwks_uri)
                    console.print(f"[green]✓ Computed thumbprint: {computed_thumbprint}[/green]")
                except OidcDiscoveryError as e:
                    console.print(f"[yellow]Could not compute thumbprint automatically: {e}[/yellow]")
                    console.print(
                        "[dim]Compute manually with: echo | openssl s_client -servername <host> "
                        "-connect <host>:443 2>/dev/null | openssl x509 -fingerprint -sha1 -noout[/dim]"
                    )

                oidc_thumbprint = questionary.text(
                    "JWKS TLS cert SHA-1 thumbprint:",
                    validate=lambda x: (
                        bool(
                            x
                            and len(x.replace(":", "")) == 40
                            and all(c in "0123456789abcdefABCDEF" for c in x.replace(":", ""))
                        )
                        or "Thumbprint must be 40 hex characters (colons optional)"
                    ),
                    default=computed_thumbprint or config.get("oidc_thumbprint", ""),
                    instruction="(40 hex chars, colons optional — confirm or replace)",
                ).ask()
                if not oidc_thumbprint:
                    return None
                # Normalize: strip colons, lowercase
                oidc_thumbprint = oidc_thumbprint.replace(":", "").lower()

            client_id = questionary.text(
                "Enter your OIDC Client ID:",
                validate=lambda x: bool(x and len(x) >= 10) or "Client ID must be at least 10 characters",
                default=config.get("okta", {}).get("client_id", ""),
            ).ask()

            if not client_id:
                return None

            # Confidential client configuration (Azure AD / Entra ID only)
            client_secret = None
            client_certificate_path = None
            client_certificate_key_path = None

            if provider_type == "azure":
                console.print("\n[bold]Azure AD Authentication Mode[/bold]")
                console.print(
                    "Some enterprise Entra ID tenants disable public client flows.\n"
                    "If yours does, configure a confidential client here.\n"
                )

                auth_mode = questionary.select(
                    "Select authentication mode:",
                    choices=[
                        questionary.Choice("Public client (default, no secret required)", value="public"),
                        questionary.Choice("Confidential client — client secret", value="secret"),
                        questionary.Choice(
                            "Confidential client — certificate (recommended for enterprise)", value="certificate"
                        ),
                    ],
                    default=config.get("azure_auth_mode", "public"),
                ).ask()

                if not auth_mode:
                    return None

                if auth_mode == "secret":
                    client_secret = questionary.password(
                        "Enter your client secret:",
                        validate=lambda x: bool(x) or "Client secret cannot be empty",
                    ).ask()
                    if not client_secret:
                        return None
                    if not profile_name:
                        raise ValueError("profile_name is required to store client secret in keyring")
                    import keyring as _keyring

                    _keyring.set_password("claude-code-with-bedrock", f"{profile_name}-client-secret", client_secret)
                    console.print("[dim]  ✓ Client secret stored in OS secure storage (not written to config)[/dim]")
                    console.print(
                        "[dim]  Distribute to end users: they must run[/dim]\n"
                        "[dim]    credential-process --set-client-secret --profile <profile>[/dim]\n"
                        "[dim]  to store the secret on their machine.[/dim]"
                    )

                elif auth_mode == "certificate":
                    console.print(
                        "\n[dim]Generate a self-signed cert with:[/dim]\n"
                        "[dim]  openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes[/dim]\n"
                        "[dim]Then upload cert.pem to your app registration → Certificates & secrets.[/dim]\n"
                    )
                    client_certificate_path = questionary.text(
                        "Path to certificate PEM file:",
                        validate=lambda x: bool(x) or "Certificate path cannot be empty",
                        default=config.get("client_certificate_path", ""),
                    ).ask()
                    if not client_certificate_path:
                        return None

                    client_certificate_key_path = questionary.text(
                        "Path to private key PEM file:",
                        validate=lambda x: bool(x) or "Key path cannot be empty",
                        default=config.get("client_certificate_key_path", ""),
                    ).ask()
                    if not client_certificate_key_path:
                        return None

                config["azure_auth_mode"] = auth_mode
                # client_secret is never written to config — it lives in the OS keyring
                config["client_certificate_path"] = client_certificate_path
                config["client_certificate_key_path"] = client_certificate_key_path

            # Credential Storage Method
            from claude_code_with_bedrock.cli.utils.helpers import is_keyring_available, is_wsl

            wsl_detected = is_wsl()
            keyring_available = is_keyring_available()

            console.print("\n[bold]Credential Storage Method[/bold]")
            console.print("Choose how to store AWS credentials locally:")
            if wsl_detected:
                console.print("  • [dim]Keyring[/dim]: [yellow]Unavailable under WSL (no keyring backend)[/yellow]")
            elif not keyring_available:
                console.print("  • [dim]Keyring[/dim]: [yellow]No keyring backend detected[/yellow]")
            else:
                console.print("  • [cyan]Keyring[/cyan]: Uses OS secure storage (may prompt for password)")
            console.print("  • [cyan]Session Files[/cyan]: Temporary files (deleted on logout)\n")

            if keyring_available and not wsl_detected:
                credential_storage = questionary.select(
                    "Select credential storage method:",
                    choices=[
                        questionary.Choice("Keyring (Secure OS storage)", value="keyring"),
                        questionary.Choice("Session Files (Temporary storage)", value="session"),
                    ],
                    default=config.get("credential_storage", "session"),
                ).ask()
            else:
                reason = "WSL" if wsl_detected else "no backend"
                console.print(f"[yellow]Keyring unavailable ({reason}) — using session files.[/yellow]")
                credential_storage = "session"

            if not credential_storage:
                return None

            # OAuth callback port configuration
            console.print("\n[bold]OAuth Callback Port[/bold]")
            console.print(
                "The credential provider listens on a local port to receive the OAuth callback "
                "from your identity provider. This port must match the redirect URI registered "
                "in your IdP application (e.g., http://localhost:8400/callback)."
            )
            console.print(
                "  • If port 8400 is already used by another application on your users' machines "
                "(e.g., Commvault, HashiCorp Vault), choose a different port."
            )
            console.print(
                "  • The port you choose here must also be registered as a valid redirect URI "
                "in your IdP application configuration.\n"
            )

            use_custom_port = questionary.confirm(
                "Use a custom OAuth callback port? (default: 8400)",
                default=False,
            ).ask()

            if use_custom_port:
                redirect_port_str = questionary.text(
                    "Enter OAuth callback port:",
                    validate=lambda x: (
                        (x.isdigit() and 1024 <= int(x) <= 65535) or "Must be a number between 1024 and 65535"
                    ),
                    default=str(config.get("redirect_port", 8400)),
                    instruction="(must match the port in your IdP's registered redirect URI)",
                ).ask()
                if redirect_port_str:
                    config["redirect_port"] = int(redirect_port_str)
                    console.print(
                        f"[dim]  Remember to register http://localhost:{redirect_port_str}/callback "
                        f"as a redirect URI in your IdP application.[/dim]"
                    )

            # Preserve existing okta settings, only update domain/client_id
            if "okta" not in config:
                config["okta"] = {}
            config["okta"]["domain"] = provider_domain
            config["okta"]["client_id"] = client_id
            config["credential_storage"] = credential_storage
            config["provider_type"] = provider_type
            if cognito_user_pool_id:
                config["cognito_user_pool_id"] = cognito_user_pool_id
            if provider_type == "generic":
                config["oidc_issuer_url"] = oidc_issuer_url
                config["oidc_authorization_endpoint"] = oidc_authorization_endpoint
                config["oidc_token_endpoint"] = oidc_token_endpoint
                config["oidc_jwks_uri"] = oidc_jwks_uri
                config["oidc_thumbprint"] = oidc_thumbprint

            # Ask about federation type
            console.print("\n[cyan]Federation Type Selection[/cyan]")
            console.print("Direct STS.")
            console.print("Cognito Identity Pool.\n")

            # Use existing federation type as default if available
            existing_federation_type = config.get("federation_type", "direct")

            federation_type = questionary.select(
                "Choose federation type:",
                choices=[
                    questionary.Choice("Direct STS", value="direct"),
                    questionary.Choice("Cognito Identity Pool", value="cognito"),
                ],
                default=existing_federation_type,
            ).ask()

            if not federation_type:
                return None

            config["federation_type"] = federation_type
            config["max_session_duration"] = 43200 if federation_type == "direct" else 28800

            # Save progress
            progress.save_step("oidc_complete", config)

        # AWS Configuration
        if not skip_aws:
            console.print("\n[bold blue]Step 2: AWS Infrastructure Configuration[/bold blue]")
            console.print("─" * 40)

            current_region = get_current_region()

            # Get list of common AWS regions
            common_regions = [
                "us-east-1",
                "us-east-2",
                "us-west-1",
                "us-west-2",
                "us-gov-west-1",
                "us-gov-east-1",
                "eu-west-1",
                "eu-west-2",
                "eu-west-3",
                "eu-central-1",
                "ap-northeast-1",
                "ap-northeast-2",
                "ap-southeast-1",
                "ap-southeast-2",
                "ap-south-1",
                "ca-central-1",
                "sa-east-1",
            ]

            # Check for saved region
            saved_region = config.get("aws", {}).get("region", current_region)

            region = questionary.select(
                "Select AWS Region for infrastructure deployment (Cognito, IAM, monitoring):",
                choices=common_regions,
                default=saved_region if saved_region in common_regions else "us-east-1",
                instruction="(This is where your authentication and monitoring resources will be created)",
            ).ask()

            if not region:
                return None

            # For Direct STS, we use a stack name instead of Identity Pool Name
            # But we keep the same field for backward compatibility
            federation_type = config.get("federation_type", "cognito")
            if federation_type == "direct":
                stack_base_name = questionary.text(
                    "Stack base name (for CloudFormation):",
                    default=config.get("aws", {}).get("identity_pool_name", "claude-code-auth"),
                    validate=validate_identity_pool_name,
                ).ask()
            else:
                stack_base_name = questionary.text(
                    "Identity Pool Name:",
                    default=config.get("aws", {}).get("identity_pool_name", "claude-code-auth"),
                    validate=validate_identity_pool_name,
                ).ask()

            if not stack_base_name:
                return None

            # Preserve existing AWS settings, only update region/identity_pool_name/stacks
            if "aws" not in config:
                config["aws"] = {}
            config["aws"]["region"] = region
            config["aws"]["identity_pool_name"] = stack_base_name  # Keep same field name for compatibility
            config["aws"]["stacks"] = {
                "auth": f"{stack_base_name}-stack",
                "monitoring": f"{stack_base_name}-monitoring",
                "dashboard": f"{stack_base_name}-dashboard",
                "analytics": f"{stack_base_name}-analytics",
            }

            # Save progress
            progress.save_step("aws_complete", config)

        # Optional Features Configuration
        if not skip_monitoring:
            console.print("\n[bold cyan]Optional Features Configuration[/bold cyan]")
            console.print("─" * 40)

            # Monitoring
            console.print("\n[bold]Monitoring and Usage Dashboards[/bold]")
            console.print("Track Claude Code usage and performance metrics in CloudWatch")
            enable_monitoring = questionary.confirm(
                "Enable monitoring?", default=config.get("monitoring", {}).get("enabled", True)
            ).ask()

            # Preserve existing monitoring settings, only update enabled flag
            if "monitoring" not in config:
                config["monitoring"] = {}
            config["monitoring"]["enabled"] = enable_monitoring

            # If monitoring is enabled, choose mode and configure
            if enable_monitoring:
                console.print("\n[bold]Monitoring Collector Mode[/bold]")
                console.print(
                    "\n[cyan]Sidecar (Recommended):[/cyan]\n"
                    "  [green]+[/green] No server infrastructure needed\n"
                    "  [green]+[/green] Simpler setup, lower cost\n"
                    "  [green]+[/green] Works offline — each dev machine runs its own collector\n"
                    "  [yellow]-[/yellow] No Athena SQL query pipeline (PromQL dashboards still included)\n"
                    "  [yellow]-[/yellow] Each machine manages its own collector process\n"
                    "  [yellow]-[/yellow] Claude Cowork (desktop) telemetry not supported (cannot reach localhost collector)\n"
                )
                console.print(
                    "[cyan]Central:[/cyan]\n"
                    "  [green]+[/green] Optional Athena SQL pipeline (EMF → Firehose → S3 → Athena)\n"
                    "  [green]+[/green] Single collector for all users — centralized management\n"
                    "  [green]+[/green] Supports Claude Cowork (desktop) telemetry\n"
                    "  [green]+[/green] Recommended if IT policies prevent users running a local OTel collector on localhost\n"
                    "  [yellow]-[/yellow] Requires VPC/ECS Fargate infrastructure\n"
                    "  [yellow]-[/yellow] Higher cost (ECS tasks, NAT gateways, load balancer)\n"
                    "  [yellow]-[/yellow] Requires network connectivity to collector endpoint\n"
                )
                monitoring_mode = questionary.select(
                    "Monitoring mode:",
                    choices=[
                        questionary.Choice(
                            "Sidecar collector (Recommended — runs locally, no server infra)",
                            value="sidecar",
                        ),
                        questionary.Choice(
                            "Central collector (ECS Fargate — server-side, optional Athena SQL pipeline)",
                            value="central",
                        ),
                    ],
                    default=config.get("monitoring", {}).get("mode", "sidecar"),
                ).ask()
                config["monitoring"]["mode"] = monitoring_mode

                if monitoring_mode == "central":
                    # Central mode: VPC, HTTPS, analytics configuration
                    existing_vpc_config = config.get("monitoring", {}).get("vpc_config")
                    vpc_config = self._configure_vpc(
                        config.get("aws", {}).get("region", get_current_region()), existing_vpc_config
                    )
                    if not vpc_config:
                        return None
                    config["monitoring"]["vpc_config"] = vpc_config

                    # Optional: Configure HTTPS with custom domain
                    console.print("\n[yellow]Optional: Configure HTTPS for secure telemetry[/yellow]")

                    existing_custom_domain = config["monitoring"].get("custom_domain")
                    existing_zone_id = config["monitoring"].get("hosted_zone_id")
                    already_configured = bool(existing_custom_domain and existing_zone_id)

                    if already_configured:
                        console.print(f"[dim]Current configuration: {existing_custom_domain}[/dim]")

                    enable_https = questionary.confirm(
                        "Enable HTTPS with custom domain?", default=already_configured
                    ).ask()

                    if enable_https:
                        custom_domain = questionary.text(
                            "Enter custom domain name (e.g., telemetry.company.com):",
                            validate=lambda x: len(x) > 0 and "." in x,
                            default=existing_custom_domain if existing_custom_domain else "",
                        ).ask()

                        config["monitoring"]["custom_domain"] = custom_domain

                        hosted_zones, zones_error = self._get_hosted_zones()
                        if hosted_zones:
                            zone_choices = [
                                f"{zone['Name'].rstrip('.')} ({zone['Id'].split('/')[-1]})" for zone in hosted_zones
                            ]

                            default_zone = None
                            if existing_zone_id:
                                for choice in zone_choices:
                                    if existing_zone_id in choice:
                                        default_zone = choice
                                        break

                            selected_zone = questionary.select(
                                "Select Route53 hosted zone for the domain:",
                                choices=zone_choices,
                                default=default_zone if default_zone else zone_choices[0],
                            ).ask()

                            zone_id = selected_zone.split("(")[-1].rstrip(")")
                            config["monitoring"]["hosted_zone_id"] = zone_id
                            console.print(f"[green]✓[/green] HTTPS will be enabled with domain: {custom_domain}")
                        else:
                            if zones_error:
                                console.print(f"[yellow]Could not list Route53 hosted zones: {zones_error}[/yellow]")
                            else:
                                console.print("[yellow]No Route53 hosted zones found in this account.[/yellow]")
                            console.print("[dim]Domain saved. Enter the Route53 hosted zone ID manually:[/dim]")
                            manual_zone_id = questionary.text(
                                "Hosted Zone ID (e.g., Z1234ABCDEFGH, leave blank to set later):",
                                default=existing_zone_id if existing_zone_id else "",
                            ).ask()
                            if manual_zone_id and manual_zone_id.strip():
                                config["monitoring"]["hosted_zone_id"] = manual_zone_id.strip()
                                console.print(
                                    f"[green]✓[/green] HTTPS configured: {custom_domain} (zone: {manual_zone_id.strip()})"
                                )
                            else:
                                console.print(
                                    "[yellow]⚠[/yellow] Domain saved but no zone ID set. Update before deploying."
                                )
                    else:
                        config["monitoring"]["custom_domain"] = None
                        config["monitoring"]["hosted_zone_id"] = None

                    # Analytics configuration (central mode only)
                    console.print("\n[bold]Analytics Pipeline[/bold]")
                    console.print("Advanced user metrics and reporting through AWS Athena (~$5/month)")
                    enable_analytics = questionary.confirm(
                        "Enable analytics?",
                        default=config.get("analytics", {}).get("enabled", True),
                    ).ask()

                    if "analytics" not in config:
                        config["analytics"] = {}
                    config["analytics"]["enabled"] = enable_analytics

                    if enable_analytics:
                        console.print("[green]✓[/green] Analytics pipeline will be deployed with your monitoring stack")

                else:
                    # Sidecar mode: no VPC, no HTTPS, no Athena pipeline (PromQL dashboards still deployed)
                    console.print("[green]✓[/green] Metrics will be sent directly to CloudWatch via local OTEL sidecar")
                    config["monitoring"]["vpc_config"] = None
                    config["monitoring"]["custom_domain"] = None
                    config["monitoring"]["hosted_zone_id"] = None
                    if "analytics" not in config:
                        config["analytics"] = {}
                    config["analytics"]["enabled"] = False

                # Quota monitoring configuration (both modes)
                # IDC path: quota enforcement works via credential-process binary
                # (SigV4-signed requests to quota API). Show the option with clear tradeoff.
                # None path: no per-user identity → cannot enforce quotas.
                if config.get("auth_type") == "none":
                    if "quota" not in config:
                        config["quota"] = {}
                    config["quota"]["enabled"] = False
                    console.print("\n[bold]Quota Monitoring[/bold]")
                    console.print(
                        "[dim]Skipped — quota enforcement requires per-user identity "
                        "(OIDC or IAM Identity Center) and is not available with anonymous auth.[/dim]"
                    )
                elif config.get("auth_type") == "idc":
                    console.print("\n[bold]Quota Monitoring[/bold]")
                    console.print("Track per-user token consumption, set limits, and receive alerts")
                    console.print("when users approach or exceed their quotas.")
                    console.print()
                    console.print(
                        "⚠️  Quota enforcement on AWS IAM Identity Center requires the credential-process binary."
                    )
                    console.print("    Without it: monitoring only (usage visible, no blocking)")
                    console.print("    With it: full enforcement (blocks when over limit)")
                    console.print()
                    enable_quota_monitoring = questionary.confirm(
                        "Enable quota enforcement?",
                        default=config.get("quota", {}).get("enabled", False),
                    ).ask()

                    if "quota" not in config:
                        config["quota"] = {}
                    config["quota"]["enabled"] = enable_quota_monitoring

                    if enable_quota_monitoring:
                        console.print("\n[yellow]Configure quota limits and thresholds[/yellow]")
                else:
                    console.print("\n[bold]Quota Monitoring[/bold]")
                    console.print("Track per-user token consumption, set limits, and receive alerts")
                    console.print("when users approach or exceed their quotas.")
                    console.print("[dim]Features: per-user/group limits, SNS alerts, access blocking[/dim]")
                    console.print("[dim]Note: Quota monitoring requires the monitoring stack (enabled above)[/dim]")
                    enable_quota_monitoring = questionary.confirm(
                        "Enable quota monitoring?",
                        default=config.get("quota", {}).get("enabled", True),
                    ).ask()

                    # Preserve existing quota settings, only update enabled flag
                    if "quota" not in config:
                        config["quota"] = {}
                    config["quota"]["enabled"] = enable_quota_monitoring

                    if enable_quota_monitoring:
                        console.print("\n[yellow]Configure quota limits and thresholds[/yellow]")

                    # Limit type selection
                    limit_type = questionary.select(
                        "How do you want to limit usage?",
                        choices=[
                            questionary.Choice("Cost-based ($ budget per user) [recommended]", value="cost"),
                            questionary.Choice("Token-based (raw token count per user)", value="token"),
                        ],
                        default=config.get("quota", {}).get("limit_type", "cost"),
                    ).ask()
                    config["quota"]["limit_type"] = limit_type

                    if limit_type == "cost":
                        # Cost-based limits
                        console.print("\n[bold]Monthly Budget[/bold]")
                        console.print("[dim]Cost is calculated server-side from per-model Bedrock pricing rates.[/dim]")

                        monthly_cost_limit_str = questionary.text(
                            "Monthly budget per user (USD):",
                            default=str(config.get("quota", {}).get("monthly_cost_limit", 50)),
                            validate=lambda x: (
                                (x.replace(".", "", 1).isdigit() and float(x) > 0) or "Must be a positive number"
                            ),
                        ).ask()
                        config["quota"]["monthly_cost_limit"] = (
                            float(monthly_cost_limit_str) if monthly_cost_limit_str else 50
                        )

                        daily_cost_limit_str = questionary.text(
                            "Daily budget per user (USD, 0 for no daily cap):",
                            default=str(config.get("quota", {}).get("daily_cost_limit", 0)),
                            validate=lambda x: (
                                (x.replace(".", "", 1).isdigit() and float(x) >= 0) or "Must be a non-negative number"
                            ),
                        ).ask()
                        config["quota"]["daily_cost_limit"] = float(daily_cost_limit_str) if daily_cost_limit_str else 0

                        console.print(f"  \u2192 Monthly budget: ${config['quota']['monthly_cost_limit']:.2f}/user")
                        if config["quota"]["daily_cost_limit"] > 0:
                            console.print(f"  \u2192 Daily cap: ${config['quota']['daily_cost_limit']:.2f}/user")
                        console.print(
                            "[dim]  \u26a0 Estimates use published on-demand Bedrock rates. Use AWS Cost Explorer for billing truth.[/dim]"
                        )

                        # Set token limits to 0 (disabled) when using cost mode
                        config["quota"]["monthly_limit"] = 0
                        config["quota"]["daily_limit"] = 0
                        monthly_limit = 0

                    else:
                        # Token-based limits (existing behavior)
                        config["quota"]["monthly_cost_limit"] = 0
                        config["quota"]["daily_cost_limit"] = 0

                    # Monthly token limit (only prompted for token mode)
                    if limit_type == "token":
                        console.print("\n[bold]Monthly Limit[/bold]")
                    monthly_limit_millions = questionary.text(
                        "Monthly token limit per user (in millions):",
                        default=str(config.get("quota", {}).get("monthly_limit_millions", 225)),
                        validate=lambda x: x.isdigit() and int(x) > 0,
                    ).ask()

                    monthly_limit = int(monthly_limit_millions) * 1000000
                    warning_80 = int(monthly_limit * 0.8)
                    warning_90 = int(monthly_limit * 0.9)

                    config["quota"]["monthly_limit"] = monthly_limit
                    config["quota"]["warning_threshold_80"] = warning_80
                    config["quota"]["warning_threshold_90"] = warning_90

                    console.print(f"  → Monthly limit: {monthly_limit:,} tokens")
                    console.print(f"  → Warning at 80%: {warning_80:,} tokens")
                    console.print(f"  → Critical at 90%: {warning_90:,} tokens")

                    # Daily limit configuration (Bill Shock Protection)
                    console.print("\n[bold]Daily Limit (Bill Shock Protection)[/bold]")
                    console.print("Prevent runaway usage by setting a daily limit with a burst buffer.")

                    base_daily = monthly_limit / 30

                    # Show burst buffer options
                    console.print(f"\nBase daily limit (monthly ÷ 30): {int(base_daily):,} tokens")
                    console.print("\nBurst buffer allows daily variation above the average:")
                    console.print(f"  • [dim]5%  (strict)[/dim]   → {int(base_daily * 1.05):,}/day")
                    console.print(f"  • [cyan]10% (default)[/cyan]  → {int(base_daily * 1.10):,}/day")
                    console.print(f"  • [dim]25% (flexible)[/dim] → {int(base_daily * 1.25):,}/day")

                    burst_buffer = questionary.text(
                        "Burst buffer percentage (5-25%):",
                        default=str(config.get("quota", {}).get("burst_buffer_percent", 10)),
                        validate=lambda x: x.isdigit() and 5 <= int(x) <= 25,
                    ).ask()

                    burst_percent = int(burst_buffer)
                    calculated_daily = int(base_daily * (1 + burst_percent / 100))

                    console.print(f"  → Calculated daily limit: {calculated_daily:,} tokens")

                    # Allow custom override
                    custom_daily = questionary.text(
                        f"Custom daily limit (Enter to accept {calculated_daily:,}):",
                        default="",
                        validate=lambda x: x == "" or (x.isdigit() and int(x) > 0),
                    ).ask()

                    daily_limit = int(custom_daily) if custom_daily else calculated_daily

                    config["quota"]["daily_limit"] = daily_limit
                    config["quota"]["burst_buffer_percent"] = burst_percent

                    if custom_daily:
                        console.print(f"  → Using custom daily limit: {daily_limit:,} tokens")

                    # Enforcement mode configuration
                    console.print("\n[bold]Enforcement Modes[/bold]")
                    console.print("Choose how limits are enforced:")
                    console.print("  • [cyan]alert[/cyan]: Send notifications but allow continued use")
                    console.print("  • [yellow]block[/yellow]: Deny credential issuance when exceeded")

                    daily_enforcement = questionary.select(
                        "Daily limit enforcement:",
                        choices=[
                            questionary.Choice("alert (warn only)", value="alert"),
                            questionary.Choice("block (deny access)", value="block"),
                        ],
                        default=config.get("quota", {}).get("daily_enforcement_mode", "alert"),
                    ).ask()

                    monthly_enforcement = questionary.select(
                        "Monthly limit enforcement:",
                        choices=[
                            questionary.Choice("alert (warn only)", value="alert"),
                            questionary.Choice("block (deny access)", value="block"),
                        ],
                        default=config.get("quota", {}).get("monthly_enforcement_mode", "block"),
                    ).ask()

                    config["quota"]["daily_enforcement_mode"] = daily_enforcement

                    # Quota re-check interval
                    console.print("\n[bold]Quota Re-Check Interval[/bold]")
                    console.print("How often to re-check quota with cached credentials:")
                    console.print("  • 0 = check every request (strictest, ~200ms latency)")
                    console.print("  • 30 = every 30 minutes (default, recommended)")
                    console.print("  • 60 = every hour (minimal impact)")

                    check_interval = questionary.text(
                        "Quota check interval (minutes):",
                        default=str(config.get("quota", {}).get("check_interval", 30)),
                        validate=lambda x: x.isdigit() and int(x) >= 0,
                    ).ask()
                    config["quota"]["check_interval"] = int(check_interval)

                    # Sidecar bypass detection (opt-in compliance/audit control)
                    monitoring_mode = config.get("monitoring", {}).get("mode", "sidecar")
                    if monitoring_mode == "sidecar":
                        console.print("\n[bold]Sidecar Bypass Detection[/bold]")
                        console.print("Quota usage is measured from telemetry sent by the local OTEL sidecar.")
                        console.print("If a user stops the sidecar, their usage is not counted toward quotas.")
                        console.print(
                            "[dim]This opt-in detective control joins CloudTrail Bedrock activity against[/dim]"
                        )
                        console.print(
                            "[dim]reported telemetry to flag users invoking Bedrock without a running sidecar.[/dim]"
                        )
                        enable_bypass_detection = questionary.confirm(
                            "Enable sidecar bypass detection (CloudWatch metrics + SNS alerts)?",
                            default=config.get("quota", {}).get("enable_bypass_detection", False),
                        ).ask()
                        config["quota"]["enable_bypass_detection"] = enable_bypass_detection
                    else:
                        # Central mode runs the collector server-side; users can't stop it.
                        config["quota"]["enable_bypass_detection"] = False

                    console.print("\n[green]✓[/green] Quota monitoring configured:")
                    console.print(f"  • Monthly: {monthly_limit:,} tokens ({monthly_enforcement})")
                    console.print(f"  • Daily:   {daily_limit:,} tokens ({daily_enforcement})")
                    console.print(f"  • Burst buffer: {burst_percent}%")
                    console.print(f"  • Re-check interval: {check_interval} minutes")
                    if config["quota"].get("enable_bypass_detection"):
                        console.print("  • Sidecar bypass detection: enabled")

            # Save monitoring progress
            progress.save_step("monitoring_complete", config)

        # Additional optional features
        console.print("\n[bold]Windows Build Support[/bold]")
        console.print("Build Windows binaries using AWS CodeBuild")
        enable_codebuild = questionary.confirm(
            "Enable Windows builds?", default=config.get("codebuild", {}).get("enabled", False)
        ).ask()

        # Preserve existing codebuild settings, only update enabled flag
        if "codebuild" not in config:
            config["codebuild"] = {}
        config["codebuild"]["enabled"] = enable_codebuild

        if enable_codebuild:
            console.print("[green]✓[/green] CodeBuild for Windows builds will be deployed")

            # The Windows Server 2022 container fleet only exists in some regions.
            # CodeBuild is build-only tooling (not user-facing), so when the main
            # region is unsupported we let the user pick a nearby supported region
            # here in the wizard — deploy then just executes that choice.
            from claude_code_with_bedrock.cli.utils.helpers import (
                CODEBUILD_WINDOWS_REGIONS,
                find_nearest_codebuild_region,
            )

            selected_region = config.get("aws", {}).get("region")
            if selected_region and selected_region not in CODEBUILD_WINDOWS_REGIONS:
                nearest = find_nearest_codebuild_region(selected_region)
                # "nearest" can cross continents when no supported region shares the
                # main region's continent (e.g. af-*/me-* -> us-east-1). Surface that
                # explicitly so a data-residency-sensitive user doesn't accept a
                # cross-continent deployment by reflexively pressing Enter.
                cross_continent = nearest.split("-", 1)[0] != selected_region.split("-", 1)[0]
                console.print(
                    f"\n[yellow]⚠ Windows CodeBuild containers are not available in {selected_region}.[/yellow]"
                )
                console.print(
                    "[dim]CodeBuild is build-only tooling (not user-facing), so deploying it to a "
                    "nearby region is fine — your main infrastructure stays put.[/dim]"
                )
                if cross_continent:
                    console.print(
                        f"[yellow]Note: no supported region shares your continent, so the nearest is "
                        f"{nearest} (different geography). Your source code is uploaded to an S3 bucket "
                        f"there during builds — confirm this is acceptable for data-residency.[/yellow]"
                    )
                nearest_label = (
                    f"{nearest} (nearest supported — DIFFERENT continent)"
                    if cross_continent
                    else f"{nearest} (nearest supported)"
                )
                cb_choice = questionary.select(
                    "Which region should CodeBuild deploy to?",
                    choices=[
                        questionary.Choice(nearest_label, value=nearest),
                        *[questionary.Choice(r, value=r) for r in CODEBUILD_WINDOWS_REGIONS if r != nearest],
                        questionary.Choice("Skip CodeBuild (build Windows binaries manually)", value=None),
                    ],
                ).ask()

                prior_region = config["codebuild"].get("region")
                config["codebuild"]["region"] = cb_choice
                if cb_choice:
                    console.print(
                        f"[green]✓[/green] CodeBuild will deploy to {cb_choice} "
                        f"(main infrastructure stays in {selected_region})"
                    )
                    if prior_region and prior_region != cb_choice:
                        _remember_prior_codebuild_region(config, prior_region)
                        console.print(
                            f"[yellow]⚠ A CodeBuild stack may still exist in {prior_region}; "
                            f"it will be cleaned up on the next [cyan]ccwb destroy[/cyan].[/yellow]"
                        )
                else:
                    # Skipping/disabling CodeBuild. If a stack was already deployed
                    # cross-region, record it so destroy still cleans it up — otherwise
                    # disabling here orphans it (destroy can't reach a region the config
                    # no longer names).
                    if prior_region:
                        _remember_prior_codebuild_region(config, prior_region)
                        console.print(
                            f"[yellow]⚠ A CodeBuild stack may still exist in {prior_region}; "
                            f"it will be cleaned up on the next [cyan]ccwb destroy[/cyan].[/yellow]"
                        )
                    config["codebuild"]["enabled"] = False
                    console.print("[yellow]CodeBuild disabled — build Windows binaries manually.[/yellow]")
            else:
                # Supported region: CodeBuild deploys alongside the main stacks.
                prior_region = config["codebuild"].get("region")
                if prior_region and prior_region != selected_region:
                    _remember_prior_codebuild_region(config, prior_region)
                    console.print(
                        f"[yellow]⚠ CodeBuild now deploys to the main region {selected_region}. "
                        f"A CodeBuild stack may still exist in {prior_region}; it will be cleaned up "
                        f"on the next [cyan]ccwb destroy[/cyan].[/yellow]"
                    )
                config["codebuild"]["region"] = None

        # Claude Cowork 3P MDM configuration
        console.print("\n[bold]Claude Cowork (Desktop) Support[/bold]")
        console.print("Generate MDM configuration for Claude Cowork with third-party platforms")
        console.print("Enables Claude Desktop to use the same credential helper for Amazon Bedrock")
        enable_cowork = questionary.confirm(
            "Generate CoWork 3P MDM configuration during packaging?",
            default=config.get("cowork_3p", {}).get("enabled", True),
        ).ask()

        if "cowork_3p" not in config:
            config["cowork_3p"] = {}
        config["cowork_3p"]["enabled"] = enable_cowork

        if enable_cowork:
            console.print("[green]✓[/green] CoWork 3P configs will be generated during packaging")

            # Preserve existing custom MDM keys; advise JSON editing for additions
            existing_extra = config.get("cowork_3p", {}).get("extra_keys", {})
            if existing_extra:
                console.print(f"[dim]Custom MDM keys configured: {len(existing_extra)} key(s)[/dim]")
            else:
                console.print(
                    "[dim]To add custom MDM keys (e.g. coworkWebSearchEnabled), edit your profile JSON directly.[/dim]"
                )
                console.print("[dim]See: assets/docs/COWORK_3P.md → Custom MDM Keys[/dim]")
            config["cowork_3p"]["extra_keys"] = existing_extra

            # Generate CoWork service token for ALB auth bypass (central mode only).
            # CoWork can't do OIDC, so this static token in X-Cowork-Token header
            # bypasses JWT validation on the ALB listener.
            monitoring_mode = config.get("monitoring", {}).get("mode", "central")
            if monitoring_mode == "central":
                existing_token = config.get("cowork_3p", {}).get("service_token", "")
                if not existing_token:
                    import uuid

                    token = str(uuid.uuid4())
                    config["cowork_3p"]["service_token"] = token
                    console.print("[green]✓[/green] Generated CoWork service token for ALB auth bypass")
                    console.print(
                        "[dim]  Pass this as CoWorkServiceToken parameter when deploying the monitoring stack[/dim]"
                    )
                else:
                    console.print("[dim]CoWork service token already configured[/dim]")

        # Settings deployment target
        console.print("\n[bold]Settings Deployment Target[/bold]")
        console.print("Choose where Claude Code settings are installed on user machines:")
        console.print("  • User scope: ~/.claude/settings.json (users can override)")
        console.print("  • Managed (org enforcement): OS-level path (highest precedence, non-overridable)")

        saved_target = config.get("settings_target", "user")
        # --managed flag overrides the wizard default
        if self._io and self.option("managed"):
            saved_target = "managed"

        settings_target_choices = [
            questionary.Choice("User scope (~/.claude/settings.json)", value="user"),
            questionary.Choice("Managed (organization-wide enforcement, requires sudo/admin)", value="managed"),
        ]
        settings_target = questionary.select(
            "Settings deployment target:",
            choices=settings_target_choices,
            default=saved_target,
        ).ask()
        config["settings_target"] = settings_target or "user"

        if config["settings_target"] == "managed":
            console.print("[green]✓[/green] Settings will be deployed to OS-level managed path")
            console.print("[dim]  Users will need sudo (Unix) or Administrator (Windows) to install[/dim]")

            # Ask whether to lock model selection in managed settings
            console.print()
            saved_lock = config.get("lock_default_model", False)
            lock_model = questionary.confirm(
                "Lock default model for all users? (Prevents users from changing model via /model)",
                default=saved_lock,
            ).ask()
            config["lock_default_model"] = lock_model if lock_model is not None else False
            if not config["lock_default_model"]:
                console.print("[green]✓[/green] Users can freely select models via /model (CRIS routing still applied)")
            else:
                console.print("[yellow]![/yellow] Default model will be enforced for all users via managed-settings")
        else:
            console.print("[green]✓[/green] Settings will be deployed to user-scope path")

        # Package distribution support
        console.print("\n[bold]Package Distribution[/bold]")
        console.print("Choose how to distribute Claude Code packages to end users:")
        console.print("  • Presigned S3 URLs: Simple, no authentication (good for < 20 users)")
        console.print("  • Landing Page: IdP authentication with web UI (good for 20-100 users)")

        distribution_choices = [
            questionary.Choice("Presigned S3 URLs (simple, no authentication)", value="presigned-s3"),
            questionary.Choice("Authenticated Landing Page (IdP + ALB)", value="landing-page"),
            questionary.Choice("Disabled", value=None),
        ]

        # Get saved value or default to None
        saved_dist_type = config.get("distribution", {}).get("type")
        default_choice = saved_dist_type if saved_dist_type else None

        distribution_type = questionary.select(
            "Distribution method:",
            choices=distribution_choices,
            default=default_choice,
        ).ask()

        # Preserve existing distribution settings, only update enabled/type
        if "distribution" not in config:
            config["distribution"] = {}
        config["distribution"]["enabled"] = distribution_type is not None
        config["distribution"]["type"] = distribution_type

        # If landing-page selected, prompt for additional configuration
        if distribution_type == "landing-page":
            console.print("\n[bold]Landing Page Configuration[/bold]")
            console.print("Configure IdP authentication for the distribution landing page")

            # Resolve region for landing-page infra ops (Cognito detection + Secrets Manager) even
            # when AWS setup was skipped (skip_aws=True), so region is bound for all IdP providers.
            region = config.get("aws", {}).get("region", get_current_region())

            # IdP provider selection
            idp_choices = [
                questionary.Choice("Okta", value="okta"),
                questionary.Choice("Azure AD / Entra ID", value="azure"),
                questionary.Choice("Auth0", value="auth0"),
                questionary.Choice("AWS Cognito User Pool", value="cognito"),
                questionary.Choice("Google", value="google"),
                questionary.Choice("Generic OIDC (PingFederate, Keycloak, ForgeRock, etc.)", value="generic"),
            ]

            idp_provider = questionary.select(
                "Identity provider for web authentication:",
                choices=idp_choices,
                default=config.get("distribution", {}).get("idp_provider", "okta"),
            ).ask()

            # Auto-detection for Cognito User Pool
            cognito_auto_configured = False
            if idp_provider == "cognito":
                from claude_code_with_bedrock.cli.utils.aws import (
                    detect_cognito_stack,
                    validate_cognito_stack_for_distribution,
                )

                console.print("\n[bold]Cognito Configuration Detection[/bold]")
                console.print("Searching for deployed Cognito User Pool stack...")

                # Try to auto-detect Cognito stack (region resolved at top of landing-page block)
                cognito_stack_info = detect_cognito_stack(region)

                if cognito_stack_info:
                    console.print(f"[green]✓[/green] Found Cognito stack: {cognito_stack_info['stack_name']}")

                    # Validate it has distribution support
                    is_valid, message = validate_cognito_stack_for_distribution(
                        cognito_stack_info["stack_name"], region
                    )

                    if is_valid:
                        console.print(f"[green]✓[/green] {message}")

                        # Show detected values
                        outputs = cognito_stack_info["outputs"]
                        console.print("\n[cyan]Detected Configuration:[/cyan]")
                        console.print(f"  • User Pool ID: {outputs.get('UserPoolId', 'N/A')}")

                        # Extract domain prefix from full domain
                        full_domain = outputs.get("UserPoolDomain", "")
                        domain_prefix = full_domain.split(".")[0] if full_domain else "N/A"
                        console.print(f"  • Domain: {domain_prefix}")

                        console.print(f"  • Client ID: {outputs.get('DistributionWebClientId', 'N/A')}")
                        console.print(f"  • Secret ARN: {outputs.get('DistributionWebClientSecretArn', 'N/A')}")

                        use_detected = questionary.confirm("\nUse these detected values?", default=True).ask()

                        if use_detected:
                            # Auto-populate configuration
                            idp_domain = domain_prefix
                            idp_client_id = outputs["DistributionWebClientId"]
                            secret_arn = outputs["DistributionWebClientSecretArn"]

                            # Store in config immediately
                            config.setdefault("distribution", {}).update(
                                {
                                    "idp_provider": "cognito",
                                    "idp_domain": idp_domain,
                                    "idp_client_id": idp_client_id,
                                    "idp_client_secret_arn": secret_arn,
                                }
                            )

                            # Also store Cognito User Pool ID for auth
                            if "cognito_user_pool_id" not in config:
                                config["cognito_user_pool_id"] = outputs["UserPoolId"]

                            console.print("[green]✓[/green] Configuration auto-populated from stack outputs")
                            cognito_auto_configured = True
                        else:
                            console.print("[yellow]Manual configuration selected[/yellow]")
                    else:
                        console.print(f"[yellow]⚠[/yellow] {message}")
                        console.print("[yellow]Falling back to manual configuration...[/yellow]")
                else:
                    console.print("[yellow]No Cognito User Pool stack detected[/yellow]")
                    console.print("You can either:")
                    console.print("  1. Deploy the Cognito stack first")
                    console.print("  2. Enter configuration manually")

            # Only prompt for manual configuration if not auto-configured
            if not cognito_auto_configured:
                # IdP domain
                # Use `or ""`, not just the .get default: a reloaded profile stores these
                # keys with an explicit None (see _build_config_from_profile), so the key
                # is present and .get returns None — and questionary.text(default=None)
                # crashes with "object of type 'NoneType' has no len()".
                idp_domain = questionary.text(
                    "IdP domain (e.g., company.okta.com for Okta, company.auth0.com for Auth0):",
                    default=config.get("distribution", {}).get("idp_domain") or "",
                ).ask()

                # Web app client ID
                idp_client_id = questionary.text(
                    "Web application client ID (separate from CLI native app):",
                    default=config.get("distribution", {}).get("idp_client_id") or "",
                ).ask()

                # Web app client secret
                idp_client_secret = questionary.password(
                    "Web application client secret:",
                ).ask()

            # Generic OIDC providers (PingFederate, Keycloak, ForgeRock, custom IdP) can't have
            # their ALB authenticate-oidc endpoints derived from a single domain the way
            # Okta/Azure/Auth0/Cognito can, so collect each one explicitly. Try OIDC discovery
            # first (mirrors the SSO generic flow) and fall back to manual entry.
            dist_oidc_issuer = None
            dist_oidc_authorization_endpoint = None
            dist_oidc_token_endpoint = None
            dist_oidc_userinfo_endpoint = None
            if idp_provider == "generic":
                from claude_code_with_bedrock.cli.utils.oidc_discovery import (
                    OidcDiscoveryError,
                    discover_oidc_endpoints,
                )

                console.print("\n[bold]Generic OIDC Landing Page Configuration[/bold]")
                console.print(
                    "[dim]We'll try to auto-discover endpoints via the standard well-known URL,[/dim]\n"
                    "[dim]and fall back to manual entry if your IdP doesn't expose one.[/dim]\n"
                )

                # Use the domain entered above as the default issuer; let the user override.
                default_issuer = (
                    idp_domain
                    if idp_domain and idp_domain.startswith(("http://", "https://"))
                    else (f"https://{idp_domain}" if idp_domain else "")
                ).rstrip("/")

                dist_oidc_issuer = questionary.text(
                    "OIDC issuer URL:",
                    validate=lambda x: x.startswith("https://") or "Issuer must start with https://",
                    default=config.get("distribution", {}).get("idp_issuer", default_issuer),
                    instruction="(must match the 'iss' claim in tokens)",
                ).ask()
                if not dist_oidc_issuer:
                    return None
                dist_oidc_issuer = dist_oidc_issuer.rstrip("/")

                discovered: dict[str, str] = {}
                console.print(f"[dim]Querying {dist_oidc_issuer}/.well-known/openid-configuration ...[/dim]")
                try:
                    discovered = discover_oidc_endpoints(dist_oidc_issuer)
                    console.print("[green]✓ Discovery succeeded.[/green]")
                except OidcDiscoveryError as e:
                    console.print(f"[yellow]Discovery failed: {e}[/yellow]")
                    console.print("[dim]Falling back to manual entry.[/dim]")

                dist_oidc_authorization_endpoint = questionary.text(
                    "Authorization endpoint:",
                    validate=lambda x: bool(x) or "Authorization endpoint cannot be empty",
                    default=(
                        discovered.get("authorization_endpoint")
                        or config.get("distribution", {}).get("idp_authorization_endpoint")
                        or f"{dist_oidc_issuer}/as/authorization.oauth2"
                    ),
                    instruction="(full URL)",
                ).ask()
                if not dist_oidc_authorization_endpoint:
                    return None

                dist_oidc_token_endpoint = questionary.text(
                    "Token endpoint:",
                    validate=lambda x: bool(x) or "Token endpoint cannot be empty",
                    default=(
                        discovered.get("token_endpoint")
                        or config.get("distribution", {}).get("idp_token_endpoint")
                        or f"{dist_oidc_issuer}/as/token.oauth2"
                    ),
                    instruction="(full URL)",
                ).ask()
                if not dist_oidc_token_endpoint:
                    return None

                dist_oidc_userinfo_endpoint = questionary.text(
                    "UserInfo endpoint:",
                    validate=lambda x: bool(x) or "UserInfo endpoint cannot be empty",
                    default=(
                        discovered.get("userinfo_endpoint")
                        or config.get("distribution", {}).get("idp_userinfo_endpoint")
                        or f"{dist_oidc_issuer}/idp/userinfo.openid"
                    ),
                    instruction="(full URL)",
                ).ask()
                if not dist_oidc_userinfo_endpoint:
                    return None

            # Store secret in AWS Secrets Manager (only if not auto-configured)
            import boto3

            if not cognito_auto_configured:
                try:
                    secrets_client = boto3.client("secretsmanager", region_name=region)
                    account_id = boto3.client("sts").get_caller_identity()["Account"]

                    secret_name = f"{config['aws']['identity_pool_name']}-distribution-idp-secret"

                    secret_arn = self._store_idp_secret(
                        secrets_client,
                        secret_name,
                        idp_client_secret,
                        description=f"IdP client secret for "
                        f"{config['aws']['identity_pool_name']} distribution landing page",
                    )

                    console.print(f"[green]✓[/green] IdP client secret stored in Secrets Manager: {secret_name}")

                except Exception as e:
                    console.print(f"[red]Error storing secret in Secrets Manager: {e}[/red]")
                    console.print("[yellow]You'll need to configure the secret manually before deployment[/yellow]")
                    # Storing failed, so we have no API response. Recover the real
                    # ARN (with its random suffix) via describe_secret if the secret
                    # exists; only fall back to a hand-built ARN as a last resort.
                    try:
                        secret_arn = secrets_client.describe_secret(SecretId=secret_name)["ARN"]
                    except Exception:
                        secret_arn = (
                            f"arn:aws:secretsmanager:{region}:{account_id}:secret:{secret_name}"  # allow-handbuilt-arn
                        )

            # Custom domain (REQUIRED for authenticated landing page)
            console.print("\n[bold]Custom Domain Configuration (REQUIRED)[/bold]")
            console.print("[yellow]⚠️  Custom domain with HTTPS is required for ALB OIDC authentication[/yellow]")
            console.print("You will need:")
            console.print("  • A custom domain (e.g., downloads.company.com)")
            console.print("  • An ACM certificate for this domain in the same region")

            custom_domain = questionary.text(
                "Custom domain (e.g., downloads.company.com):",
                default=config.get("distribution", {}).get("custom_domain") or "",
                validate=lambda text: (
                    len(text.strip()) > 0 or "Custom domain is required for authenticated landing page"
                ),
            ).ask()

            # Check for Route53 hosted zones
            console.print("\n[bold]Route53 Configuration[/bold]")
            console.print("Looking for Route53 hosted zones...")

            hosted_zone_id = None
            try:
                route53_client = boto3.client("route53")
                zones_response = route53_client.list_hosted_zones()
                hosted_zones = zones_response.get("HostedZones", [])

                if hosted_zones:
                    console.print(f"Found {len(hosted_zones)} hosted zone(s)")

                    # Get existing hosted zone if configured
                    existing_zone_id = config.get("distribution", {}).get("hosted_zone_id")

                    # Create zone choices
                    zone_choices = [
                        questionary.Choice(
                            f"{zone['Name']} (ID: {zone['Id'].split('/')[-1]})", value=zone["Id"].split("/")[-1]
                        )
                        for zone in hosted_zones
                    ]
                    zone_choices.append(questionary.Choice("Skip (no Route53 managed domain)", value=None))

                    # Find the default choice based on existing zone
                    default_choice = None
                    if existing_zone_id:
                        for choice in zone_choices:
                            if choice.value == existing_zone_id:
                                default_choice = choice
                                break

                    hosted_zone_id = questionary.select(
                        "Select Route53 hosted zone:",
                        choices=zone_choices,
                        default=default_choice if default_choice else zone_choices[0],
                    ).ask()
                else:
                    console.print("[yellow]No Route53 hosted zones found in this account[/yellow]")
                    console.print("You can still use custom domain if it's managed externally")
                    hosted_zone_id = None

            except Exception as e:
                console.print(f"[yellow]Could not list Route53 zones: {e}[/yellow]")
                hosted_zone_id = None

            # Save landing page configuration
            config["distribution"].update(
                {
                    "idp_provider": idp_provider,
                    "idp_domain": idp_domain,
                    "idp_client_id": idp_client_id,
                    "idp_client_secret_arn": secret_arn,
                    "custom_domain": custom_domain,
                    "hosted_zone_id": hosted_zone_id,
                }
            )

            # Generic OIDC: persist the explicit endpoints (only set for provider == "generic")
            if idp_provider == "generic":
                config["distribution"].update(
                    {
                        "idp_issuer": dist_oidc_issuer,
                        "idp_authorization_endpoint": dist_oidc_authorization_endpoint,
                        "idp_token_endpoint": dist_oidc_token_endpoint,
                        "idp_userinfo_endpoint": dist_oidc_userinfo_endpoint,
                    }
                )

            console.print("\n[green]✓[/green] Landing page distribution will be deployed with IdP authentication")

        elif distribution_type == "presigned-s3":
            console.print("[green]✓[/green] Presigned S3 distribution will be deployed")

        # Bedrock model and cross-region configuration
        if not skip_bedrock:
            console.print("\n[bold blue]Step 3: Bedrock Model Selection[/bold blue]")
            console.print("─" * 40)

            # Import centralized model configuration
            from claude_code_with_bedrock.models import (
                CLAUDE_MODELS,
                get_available_profiles_for_model,
                get_destination_regions_for_model_profile,
                get_model_id_for_profile,
                get_profile_description,
                get_source_regions_for_model_profile,
            )

            # Check for saved model
            saved_model = config.get("aws", {}).get("selected_model")
            saved_model_key = None
            if saved_model:
                # Find the key for the saved model by checking all model IDs
                for key, model_info in CLAUDE_MODELS.items():
                    for _profile_key, profile_config in model_info["profiles"].items():
                        if profile_config["model_id"] == saved_model:
                            saved_model_key = key
                            break
                    if saved_model_key:
                        break

            # Step 1: Select Claude model
            model_choices = []
            default_model_key = saved_model_key or "sonnet-4-5"
            for model_key, model_info in CLAUDE_MODELS.items():
                # Build region list from available profiles
                available_profiles = get_available_profiles_for_model(model_key)
                regions = []
                if "global" in available_profiles:
                    regions.append("Global")
                if "us" in available_profiles:
                    regions.append("US")
                if "europe" in available_profiles:
                    regions.append("Europe")
                if "apac" in available_profiles:
                    regions.append("APAC")
                regions_text = ", ".join(regions)

                choice_text = f"{model_info['name']} ({regions_text})"
                model_choices.append(questionary.Choice(title=choice_text, value=model_key))

            selected_model_key = questionary.select(
                "Select Claude model:",
                choices=model_choices,
                default=default_model_key,
                instruction="(Use arrow keys to select, Enter to confirm)",
            ).ask()

            if selected_model_key is None:  # User cancelled
                return None

            selected_model = CLAUDE_MODELS[selected_model_key]
            # Don't set the model ID yet - we need to adjust it based on the region profile

            # Step 2: Select cross-region profile based on model
            console.print(f"\n[green]Selected:[/green] {selected_model['name']}")

            available_profiles = get_available_profiles_for_model(selected_model_key)

            # Check for saved profile
            saved_profile = config.get("aws", {}).get("cross_region_profile")
            if saved_profile not in available_profiles:
                saved_profile = available_profiles[0]  # Default to first available

            # Always show the selection, even if there's only one option
            profile_choices = []
            for profile_key in available_profiles:
                # Get model-specific description
                description = get_profile_description(selected_model_key, profile_key)
                region_profile_label = profile_key.upper() if profile_key != "us" else "US"
                choice_text = f"{region_profile_label} Cross-Region - {description}"
                profile_choices.append(questionary.Choice(title=choice_text, value=profile_key))

            # Adjust the prompt based on number of options
            if len(available_profiles) == 1:
                prompt_text = "Cross-region inference profile for this model:"
                instruction_text = "(Press Enter to continue)"
            else:
                prompt_text = "Select cross-region inference profile:"
                instruction_text = "(Use arrow keys to select, Enter to confirm)"

            selected_profile = questionary.select(
                prompt_text, choices=profile_choices, default=saved_profile, instruction=instruction_text
            ).ask()

            if selected_profile is None:  # User cancelled
                return None

            # Get the correct model ID for the selected profile
            model_id = get_model_id_for_profile(selected_model_key, selected_profile)
            config["aws"]["selected_model"] = model_id
            config["aws"]["cross_region_profile"] = selected_profile

            # Get destination regions for the model/profile combination
            destination_regions = get_destination_regions_for_model_profile(selected_model_key, selected_profile)

            # Use the destination regions from the model profile
            if not destination_regions:
                console.print(
                    f"[red]Error:[/red] No destination regions configured for {selected_model_key} "
                    f"with {selected_profile} profile"
                )
                raise ValueError("No destination regions configured for model/profile combination")

            config["aws"]["allowed_bedrock_regions"] = destination_regions

            # Step 3: Select source region for the selected model/profile combination
            region_profile_label = selected_profile.upper() if selected_profile != "us" else "US"
            console.print(f"\n[green]Selected:[/green] {region_profile_label} Cross-Region")

            # Get available source regions for this model/profile combination
            available_source_regions = get_source_regions_for_model_profile(selected_model_key, selected_profile)

            # Check for saved source region
            saved_source_region = config.get("aws", {}).get("selected_source_region")
            if saved_source_region not in available_source_regions:
                saved_source_region = available_source_regions[0] if available_source_regions else None

            if available_source_regions:
                # Present source region selection
                source_region_choices = []
                for region in available_source_regions:
                    choice_text = f"{region}"
                    source_region_choices.append(questionary.Choice(title=choice_text, value=region))

                # Adjust prompt based on number of options
                if len(available_source_regions) == 1:
                    prompt_text = "Source region for this model:"
                    instruction_text = "(Press Enter to continue)"
                else:
                    prompt_text = "Select source region for AWS configuration:"
                    instruction_text = "(Use arrow keys to select, Enter to confirm)"

                selected_source_region = questionary.select(
                    prompt_text,
                    choices=source_region_choices,
                    default=saved_source_region,
                    instruction=instruction_text,
                ).ask()

                if selected_source_region is None:  # User cancelled
                    return None

                config["aws"]["selected_source_region"] = selected_source_region
                console.print(f"[green]✓[/green] Source region: {selected_source_region}")
            else:
                # No source regions available - use default fallback
                console.print(
                    "[yellow]No source regions configured for this model. Using default region logic.[/yellow]"
                )
                config["aws"]["selected_source_region"] = None

            # Get model-specific description for confirmation
            profile_description = get_profile_description(selected_model_key, selected_profile)

            console.print(
                f"\n[green]✓[/green] Configured {selected_model['name']} with {region_profile_label} "
                f"Cross-Region ({profile_description})"
            )

            # Optional: Application Inference Profiles
            has_saved_arns = any(
                config.get("aws", {}).get(k)
                for k in ["inference_profile_opus_arn", "inference_profile_sonnet_arn", "inference_profile_haiku_arn"]
            )
            use_inference_profiles = questionary.confirm(
                "Configure Application Inference Profiles?",
                default=has_saved_arns,
            ).ask()

            if use_inference_profiles:
                from claude_code_with_bedrock.validators import ProfileValidator

                console.print("[dim]Provide an inference profile ARN for each model tier (press Enter to skip).[/dim]")

                for tier_name, config_key in [
                    ("Opus", "inference_profile_opus_arn"),
                    ("Sonnet", "inference_profile_sonnet_arn"),
                    ("Haiku", "inference_profile_haiku_arn"),
                ]:
                    saved_arn = config.get("aws", {}).get(config_key)
                    while True:
                        arn = questionary.text(
                            f"  {tier_name} inference profile ARN:",
                            default=saved_arn or "",
                        ).ask()

                        if arn is None:  # User cancelled
                            config["aws"][config_key] = None
                            break

                        if not arn.strip():
                            config["aws"][config_key] = None
                            break

                        error = ProfileValidator.validate_application_inference_profile_arn(arn)
                        if error:
                            console.print(f"[red]{error}[/red]")
                            continue

                        config["aws"][config_key] = arn.strip()
                        console.print(f"[green]✓[/green] {tier_name} inference profile configured")
                        break
            else:
                config["aws"]["inference_profile_opus_arn"] = None
                config["aws"]["inference_profile_sonnet_arn"] = None
                config["aws"]["inference_profile_haiku_arn"] = None

            # Save progress
            progress.save_step("bedrock_complete", config)

        # Resource Tags (optional)
        console.print("\n[bold blue]Resource Tags (Optional)[/bold blue]")
        console.print("─" * 30)
        console.print("[dim]Tags are applied to all deployed CloudFormation stacks.[/dim]")

        add_tags = questionary.confirm(
            "Would you like to add resource tags?",
            default=bool(config.get("tags")),
        ).ask()

        if add_tags:
            existing_tags = dict(config.get("tags", {}))
            tags = {}

            # Let user confirm/edit existing tags first
            if existing_tags:
                console.print("[dim]Existing tags (edit value or leave empty to remove):[/dim]")
                for key, value in existing_tags.items():
                    tag_value = questionary.text(
                        f"  {key}:",
                        default=value,
                    ).ask()
                    if tag_value is None:
                        return None
                    if tag_value:
                        tags[key] = tag_value
                        console.print(f"[green]✓[/green] Tag: {key}={tag_value}")
                    else:
                        console.print(f"[yellow]✗[/yellow] Removed tag: {key}")

            # Then allow adding new tags
            while True:
                tag_key = questionary.text(
                    "New tag key (empty to finish):",
                    default="",
                ).ask()
                tag_key = (tag_key or "").strip()
                if not tag_key:
                    break
                if tag_key.lower().startswith("aws:"):
                    console.print("[red]✗ Tag keys cannot start with 'aws:' (reserved by AWS)[/red]")
                    continue
                if len(tag_key) > 128:
                    console.print("[red]✗ Tag key exceeds 128 character limit[/red]")
                    continue
                tag_value = questionary.text(
                    f"Value for '{tag_key}':",
                    default=tags.get(tag_key, ""),
                ).ask()
                if tag_value is None:
                    break
                if len(tag_value) > 256:
                    console.print("[red]✗ Tag value exceeds 256 character limit[/red]")
                    continue
                tags[tag_key] = tag_value
                console.print(f"[green]✓[/green] Tag: {tag_key}={tag_value}")
            config["tags"] = tags
        elif add_tags is None:
            return None
        else:
            config["tags"] = config.get("tags", {})

        return config

    @staticmethod
    def _store_idp_secret(secrets_client, secret_name: str, secret_value: str, description: str = "") -> str:
        """Create or update the distribution IdP client secret; return its full ARN.

        Always returns the ARN from the Secrets Manager API response. Secrets
        Manager appends a random 6-char suffix to every secret ARN (e.g.
        ``-FhLi4n``); a hand-built ``arn:...:secret:<name>`` omits it, and the
        ``{{resolve:secretsmanager:<arn>}}`` reference in the landing-page ALB
        HTTPS listener then fails with ResourceNotFoundException. Using the
        response ARN keeps create and update paths consistent.
        """
        try:
            response = secrets_client.create_secret(
                Name=secret_name,
                SecretString=secret_value,
                Description=description,
            )
        except secrets_client.exceptions.ResourceExistsException:
            response = secrets_client.update_secret(
                SecretId=secret_name,
                SecretString=secret_value,
            )
        return response["ARN"]

    def _review_configuration(self, config: dict[str, Any]) -> bool:
        """Review configuration with user."""
        console = Console()

        console.print("\n[bold blue]Step 4: Review Configuration[/bold blue]")
        console.print("─" * 30)

        # Create a nice table using Rich
        table = Table(title="Configuration Summary", box=box.ROUNDED, show_header=True, header_style="bold cyan")

        table.add_column("Setting", style="white", no_wrap=True)
        table.add_column("Value", style="green")

        sso_enabled = config.get("sso_enabled", True)
        if sso_enabled:
            okta_config = config.get("okta", {})
            okta_domain = okta_config.get("domain", "")
            okta_client_id = okta_config.get("client_id", "")
            table.add_row("OIDC Provider", okta_domain or "—")
            table.add_row(
                "OIDC Client ID",
                (okta_client_id[:20] + "..." if len(okta_client_id) > 20 else (okta_client_id or "—")),
            )
        else:
            table.add_row("Authentication", "AWS SSO / IAM Identity Center (no OIDC)")
        table.add_row(
            "Credential Storage",
            (
                "Keyring (OS secure storage)"
                if config.get("credential_storage") == "keyring"
                else "Session Files (temporary)"
            ),
        )
        table.add_row("Infrastructure Region", f"{config['aws']['region']} (Cognito, IAM, Monitoring)")
        table.add_row("Identity Pool", config["aws"]["identity_pool_name"])
        table.add_row("Monitoring", "✓ Enabled" if config["monitoring"]["enabled"] else "✗ Disabled")
        if config.get("monitoring", {}).get("enabled"):
            mode = config.get("monitoring", {}).get("mode", "sidecar")
            mode_label = "Central (ECS Fargate)" if mode == "central" else "Sidecar (local collector)"
            table.add_row("Monitoring Mode", mode_label)

            quota_config = config.get("quota", {})
            if quota_config.get("enabled", False):
                monthly = quota_config.get("monthly_limit", 225000000)
                daily = quota_config.get("daily_limit")
                monthly_mode = quota_config.get("monthly_enforcement_mode", "block")
                daily_mode = quota_config.get("daily_enforcement_mode", "alert")
                check_interval = quota_config.get("check_interval", 30)
                quota_status = f"✓ Monthly: {monthly:,} ({monthly_mode})"
                if daily:
                    quota_status += f"\n  Daily: {daily:,} ({daily_mode})"
                quota_status += f"\n  Re-check: {check_interval} min"
                table.add_row("Quota Monitoring", quota_status)
            else:
                table.add_row("Quota Monitoring", "✗ Disabled")

            if mode == "central":
                table.add_row(
                    "Athena SQL Pipeline",
                    "✓ Enabled" if config.get("analytics", {}).get("enabled", True) else "✗ Disabled",
                )
            else:
                table.add_row("Athena SQL Pipeline", "N/A (sidecar mode — PromQL dashboards included)")

        # Show VPC config if monitoring is enabled in central mode
        if (
            config.get("monitoring", {}).get("enabled")
            and config.get("monitoring", {}).get("mode", "sidecar") == "central"
        ):
            vpc_config = config.get("monitoring", {}).get("vpc_config", {})
            if vpc_config.get("create_vpc"):
                table.add_row("Monitoring VPC", "New VPC will be created")
            else:
                vpc_info = f"Existing: {vpc_config.get('vpc_id', 'Unknown')}"
                if vpc_config.get("subnet_ids"):
                    vpc_info += f"\n{len(vpc_config['subnet_ids'])} subnets selected"
                table.add_row("Monitoring VPC", vpc_info)

        # Show selected model
        selected_model = config["aws"].get("selected_model", "")
        from claude_code_with_bedrock.models import get_all_model_display_names

        model_display = get_all_model_display_names()
        if selected_model:
            table.add_row("Claude Model", model_display.get(selected_model, selected_model))

        # Show application inference profiles if configured
        for tier, key in [
            ("Opus", "inference_profile_opus_arn"),
            ("Sonnet", "inference_profile_sonnet_arn"),
            ("Haiku", "inference_profile_haiku_arn"),
        ]:
            arn = config["aws"].get(key)
            if arn:
                table.add_row(f"{tier} Inference Profile", arn)

        # Show cross-region profile
        cross_region_profile = config["aws"].get("cross_region_profile", "us")
        profile_display = {
            "us": "US Cross-Region (us-east-1, us-east-2, us-west-2)",
            "europe": "Europe Cross-Region (eu-west-1, eu-west-3, eu-central-1, eu-north-1)",
            "apac": "APAC Cross-Region (ap-northeast-1, ap-southeast-1/2, ap-south-1)",
        }
        table.add_row("Bedrock Regions", profile_display.get(cross_region_profile, cross_region_profile))

        # Show AWS account ID
        account_id = get_account_id()
        if account_id:
            table.add_row("AWS Account", account_id)
        else:
            table.add_row("AWS Account", "[yellow]Unable to determine[/yellow]")

        # Show resource tags
        if config.get("tags"):
            table.add_row("Resource Tags", ", ".join(f"{k}={v}" for k, v in config["tags"].items()))

        # Show custom MDM keys
        extra_keys = config.get("cowork_3p", {}).get("extra_keys", {})
        if extra_keys:
            table.add_row("Custom MDM Keys", ", ".join(f"{k}={v}" for k, v in extra_keys.items()))

        console.print(table)

        # Show what will be created
        console.print("\n[bold yellow]Resources to be created:[/bold yellow]")
        if config.get("federation_type") == "direct":
            console.print("• IAM OIDC Provider for authentication")
        else:
            console.print("• Cognito Identity Pool for authentication")
        console.print("• IAM roles and policies for Bedrock access")
        if config.get("monitoring", {}).get("enabled"):
            mode = config.get("monitoring", {}).get("mode", "sidecar")
            if mode == "central":
                console.print("• CloudWatch dashboards for usage monitoring")
                console.print("• OpenTelemetry collector for metrics aggregation")
                console.print("• ECS cluster and load balancer for collector")
                if config.get("analytics", {}).get("enabled", True):
                    console.print("• Kinesis Firehose for analytics data streaming")
                    console.print("• S3 bucket for analytics data storage")
                    console.print("• Glue catalog and Athena tables for analytics")
            else:
                console.print("• Local OTEL Collector sidecar (no server infrastructure)")
                console.print("• CloudWatch PromQL dashboard for metrics visualization")
            if config.get("quota", {}).get("enabled", False):
                console.print("• DynamoDB tables for quota tracking")
                console.print("• Lambda function for quota checking")
                console.print("• API Gateway for real-time quota API")
        if config.get("codebuild", {}).get("enabled", False):
            console.print("• CodeBuild project for Windows binary builds")
            console.print("• S3 bucket for build artifacts")
        if config.get("distribution", {}).get("enabled", False):
            dist_type = config.get("distribution", {}).get("type")
            if dist_type == "landing-page":
                console.print("• Authenticated landing page distribution (ALB + Lambda + S3)")
                idp_provider = config.get("distribution", {}).get("idp_provider", "")
                idp_display_names = {
                    "okta": "Okta",
                    "azure": "Azure AD / Entra ID",
                    "auth0": "Auth0",
                    "cognito": "AWS Cognito User Pool",
                }
                idp_label = idp_display_names.get(idp_provider, idp_provider.upper() if idp_provider else "configured")
                console.print(f"• IdP authentication: {idp_label}")
                if config.get("distribution", {}).get("custom_domain"):
                    console.print(f"• Custom domain: {config['distribution']['custom_domain']}")
            elif dist_type == "presigned-s3":
                console.print("• Presigned S3 URL distribution")
                console.print("• IAM user for presigned URL generation")
                console.print("• Secrets Manager secret for credentials")

        return True

    def _deploy(self, config: dict[str, Any], profile_name: str = "default") -> int:
        """Deploy the infrastructure.

        Args:
            config: Configuration data
            profile_name: Name of the profile to save

        Returns:
            Exit code
        """
        console = Console()

        # Save configuration first
        self._save_configuration(config, profile_name)

        # Create a progress display
        console.print("\n[bold]Deploying infrastructure...[/bold]")

        # Deploy authentication stack
        with console.status("[yellow]Deploying authentication stack...[/yellow]"):
            try:
                # Get the parameters file path
                params_file = (
                    Path(__file__).parent.parent.parent.parent.parent.parent
                    / "deployment"
                    / "infrastructure"
                    / "parameters.json"
                )

                # Update parameters with our configuration
                self._update_parameters_file(params_file, config)

                # Deploy the stack
                stack_name = config["aws"]["stacks"]["auth"]
                template_file = (
                    Path(__file__).parent.parent.parent.parent.parent.parent
                    / "deployment"
                    / "infrastructure"
                    / "cognito-identity-pool.yaml"
                )

                if self._deploy_stack(stack_name, template_file, params_file, config["aws"]["region"]):
                    console.print("  [green]✓[/green] Authentication stack deployed")
                else:
                    console.print("  [red]✗[/red] Authentication stack deployment failed")
                    return 1
            except Exception as e:
                console.print(f"  [red]✗[/red] Authentication stack deployment failed: {e}")
                return 1

        # Deploy monitoring stack if enabled
        if config["monitoring"]["enabled"]:
            with console.status("[yellow]Deploying monitoring stack...[/yellow]"):
                try:
                    # Deploy OTel collector
                    collector_stack = config["aws"]["stacks"]["monitoring"]
                    collector_template = (
                        Path(__file__).parent.parent.parent.parent.parent.parent
                        / "deployment"
                        / "infrastructure"
                        / "otel-collector.yaml"
                    )

                    if self._deploy_stack(collector_stack, collector_template, params_file, config["aws"]["region"]):
                        console.print("  [green]✓[/green] Monitoring collector deployed")
                    else:
                        console.print("  [yellow]![/yellow] Monitoring deployment skipped or failed")

                    # Deploy dashboard
                    dashboard_stack = config["aws"]["stacks"]["dashboard"]
                    dashboard_template = (
                        Path(__file__).parent.parent.parent.parent.parent.parent
                        / "deployment"
                        / "infrastructure"
                        / "monitoring-dashboard.yaml"
                    )

                    if self._deploy_stack(dashboard_stack, dashboard_template, params_file, config["aws"]["region"]):
                        console.print("  [green]✓[/green] Monitoring dashboard deployed")
                    else:
                        console.print("  [yellow]![/yellow] Dashboard deployment skipped or failed")

                except Exception as e:
                    console.print(f"  [yellow]![/yellow] Monitoring deployment partially failed: {e}")

        console.print("  [green]✓[/green] Configuration saved")

        # Success message
        success_panel = Panel.fit(
            "[bold green]✓ Setup complete![/bold green]\n\n"
            "Next steps:\n"
            "1. Create package: [cyan]poetry run ccwb package[/cyan]\n"
            "2. Test authentication: [cyan]poetry run ccwb test[/cyan]\n"
            "3. Distribute to users (see dist/ folder)",
            border_style="green",
            padding=(1, 2),
        )
        console.print("\n", success_panel)

        return 0

    def _save_configuration(self, config_data: dict[str, Any], profile_name: str) -> None:
        """Save configuration to file.

        Loads the existing profile (if any) and updates only the fields managed
        by the init wizard. Fields not present in config_data are preserved from
        the existing profile, preventing silent resets of settings like
        include_coauthored_by, quota_fail_mode, federated_role_arn, etc.

        Args:
            config_data: Configuration data gathered by the wizard
            profile_name: Name of the profile to save
        """
        config = Config.load()

        # Build monitoring_config with all monitoring settings
        monitoring_dict = config_data.get("monitoring", {})
        monitoring_config = {}
        if monitoring_dict.get("vpc_config"):
            # Flatten vpc_config to match deploy.py expectations (lines 588-593)
            monitoring_config.update(monitoring_dict["vpc_config"])
        if monitoring_dict.get("custom_domain"):
            monitoring_config["custom_domain"] = monitoring_dict["custom_domain"]
        if monitoring_dict.get("hosted_zone_id"):
            monitoring_config["hosted_zone_id"] = monitoring_dict["hosted_zone_id"]

        # Get SSO configuration or use defaults if SSO is disabled
        sso_enabled = config_data.get("sso_enabled", True)
        provider_domain = config_data.get("okta", {}).get("domain", "none") if sso_enabled else "none"
        client_id = config_data.get("okta", {}).get("client_id", "none") if sso_enabled else "none"

        # Load existing profile to preserve fields not managed by the wizard
        existing_profile = config.get_profile(profile_name)

        # Fields gathered by the init wizard — these always get overwritten
        wizard_fields = {
            "name": profile_name,
            "provider_domain": provider_domain,
            "client_id": client_id,
            "credential_storage": config_data.get("credential_storage", "session"),
            "aws_region": config_data["aws"]["region"],
            "identity_pool_name": config_data["aws"]["identity_pool_name"],
            "stack_names": config_data["aws"]["stacks"],
            "monitoring_enabled": config_data["monitoring"]["enabled"],
            "monitoring_mode": config_data.get("monitoring", {}).get("mode", "sidecar"),
            "monitoring_config": monitoring_config,
            "analytics_enabled": (
                config_data.get("analytics", {}).get("enabled", True)
                if config_data.get("monitoring", {}).get("enabled")
                else False
            ),
            "allowed_bedrock_regions": config_data["aws"]["allowed_bedrock_regions"],
            "cross_region_profile": config_data["aws"].get("cross_region_profile", "us"),
            "selected_model": config_data["aws"].get("selected_model"),
            "model_alias": config_data["aws"].get("model_alias"),
            "selected_source_region": config_data["aws"].get("selected_source_region"),
            "inference_profile_opus_arn": config_data["aws"].get("inference_profile_opus_arn"),
            "inference_profile_sonnet_arn": config_data["aws"].get("inference_profile_sonnet_arn"),
            "inference_profile_haiku_arn": config_data["aws"].get("inference_profile_haiku_arn"),
            "provider_type": config_data.get("provider_type"),
            "cognito_user_pool_id": config_data.get("cognito_user_pool_id"),
            "oidc_issuer_url": config_data.get("oidc_issuer_url"),
            "oidc_authorization_endpoint": config_data.get("oidc_authorization_endpoint"),
            "oidc_token_endpoint": config_data.get("oidc_token_endpoint"),
            "oidc_jwks_uri": config_data.get("oidc_jwks_uri"),
            "oidc_thumbprint": config_data.get("oidc_thumbprint"),
            "federation_type": config_data.get("federation_type", "cognito"),
            "max_session_duration": config_data.get("max_session_duration", 28800),
            "sso_enabled": config_data.get("sso_enabled", True),
            "auth_type": config_data.get("auth_type", "oidc"),
            "idc_start_url": config_data.get("idc_start_url"),
            "idc_account_id": config_data.get("idc_account_id"),
            "idc_permission_set_name": config_data.get("idc_permission_set_name"),
            "sso_region": config_data.get("sso_region"),
            "azure_auth_mode": config_data.get("azure_auth_mode"),
            "client_certificate_path": config_data.get("client_certificate_path"),
            "client_certificate_key_path": config_data.get("client_certificate_key_path"),
            "enable_codebuild": config_data.get("codebuild", {}).get("enabled", False),
            "codebuild_region": config_data.get("codebuild", {}).get("region"),
            "codebuild_prior_regions": config_data.get("codebuild", {}).get("prior_regions", []),
            "enable_distribution": config_data.get("distribution", {}).get("enabled", False),
            "distribution_type": config_data.get("distribution", {}).get("type"),
            "distribution_idp_provider": config_data.get("distribution", {}).get("idp_provider"),
            "distribution_idp_domain": config_data.get("distribution", {}).get("idp_domain"),
            "distribution_idp_client_id": config_data.get("distribution", {}).get("idp_client_id"),
            "distribution_idp_client_secret_arn": config_data.get("distribution", {}).get("idp_client_secret_arn"),
            "distribution_custom_domain": config_data.get("distribution", {}).get("custom_domain"),
            "distribution_hosted_zone_id": config_data.get("distribution", {}).get("hosted_zone_id"),
            "distribution_idp_issuer": config_data.get("distribution", {}).get("idp_issuer"),
            "distribution_idp_authorization_endpoint": config_data.get("distribution", {}).get(
                "idp_authorization_endpoint"
            ),
            "distribution_idp_token_endpoint": config_data.get("distribution", {}).get("idp_token_endpoint"),
            "distribution_idp_userinfo_endpoint": config_data.get("distribution", {}).get("idp_userinfo_endpoint"),
            "quota_monitoring_enabled": (
                config_data.get("quota", {}).get("enabled", False)
                if config_data.get("monitoring", {}).get("enabled")
                else False
            ),
            "monthly_token_limit": config_data.get("quota", {}).get("monthly_limit", 300000000),
            "warning_threshold_80": config_data.get("quota", {}).get("warning_threshold_80", 240000000),
            "warning_threshold_90": config_data.get("quota", {}).get("warning_threshold_90", 270000000),
            "daily_token_limit": config_data.get("quota", {}).get("daily_limit"),
            "burst_buffer_percent": config_data.get("quota", {}).get("burst_buffer_percent", 10),
            "daily_enforcement_mode": config_data.get("quota", {}).get("daily_enforcement_mode", "alert"),
            "monthly_enforcement_mode": config_data.get("quota", {}).get("monthly_enforcement_mode", "block"),
            "quota_check_interval": config_data.get("quota", {}).get("check_interval", 30),
            "enable_bypass_detection": config_data.get("quota", {}).get("enable_bypass_detection", False),
            "cowork_3p_enabled": config_data.get("cowork_3p", {}).get("enabled", True),
            "cowork_3p_extra_keys": config_data.get("cowork_3p", {}).get("extra_keys", {}),
            "cowork_service_token": config_data.get("cowork_3p", {}).get("service_token", ""),
            "settings_target": "managed"
            if (self._io and self.option("managed"))
            else config_data.get("settings_target", "user"),
            "lock_default_model": config_data.get("lock_default_model", False),
            "tags": config_data.get("tags", {}),
            "redirect_port": config_data.get("redirect_port"),
        }

        if existing_profile:
            # Update existing profile — preserves fields not managed by the wizard
            # (e.g. include_coauthored_by, federated_role_arn, quota_fail_mode,
            # otel_collector_endpoint, model_alias, okta_auth_server, etc.)
            for field, value in wizard_fields.items():
                setattr(existing_profile, field, value)
            profile = existing_profile
        else:
            # New profile — construct from scratch
            profile = Profile(**wizard_fields)

        config.add_profile(profile)
        # Set as active profile when creating/updating
        config.set_active_profile(profile_name)
        config.save()

    def _check_aws_cli(self) -> bool:
        """Check if AWS CLI is installed."""
        try:
            import subprocess

            result = subprocess.run(["aws", "--version"], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def _check_aws_credentials(self) -> bool:
        """Check if AWS credentials are configured."""
        console = Console()
        try:
            boto3.client("sts").get_caller_identity()
            return True
        except Exception as e:
            err = str(e)
            console.print(f"    [dim red]Credential error: {err}[/dim red]")
            if "ExpiredToken" in err or "expired" in err.lower():
                console.print(
                    "    [dim]Hint: Expired credentials in ~/.aws/credentials are blocking the EC2 instance role.\n"
                    "    Run: [cyan]unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN[/cyan]\n"
                    "    Then clear the [default] section from ~/.aws/credentials and retry.[/dim]"
                )
            elif "NoCredentialProviders" in err or "Unable to locate credentials" in err:
                console.print(
                    "    [dim]Hint: No credentials found. Configure via env vars, ~/.aws/credentials,\n"
                    "    an IAM instance profile, or AWS SSO.[/dim]"
                )
            return False

    def _check_python_version(self) -> bool:
        """Check Python version."""
        import sys

        return sys.version_info >= (3, 10)

    def _check_go_version(self) -> bool:
        """Check if Go >= 1.23 is installed (needed for OTEL collector build)."""
        try:
            result = subprocess.run(["go", "version"], capture_output=True, text=True)
            if result.returncode != 0:
                return False
            match = re.search(r"go(\d+)\.(\d+)", result.stdout)
            if not match:
                return False
            major, minor = int(match.group(1)), int(match.group(2))
            return (major, minor) >= (1, 23)
        except Exception:
            return False

    def _get_bedrock_regions(self) -> list[str]:
        """Get list of regions where Bedrock is available."""
        try:
            # These are the regions where Bedrock is currently available
            # This list should be updated as AWS expands Bedrock availability
            bedrock_regions = [
                "us-east-1",  # N. Virginia
                "us-east-2",  # Ohio
                "us-west-2",  # Oregon
                "ap-northeast-1",  # Tokyo
                "ap-southeast-1",  # Singapore
                "ap-southeast-2",  # Sydney
                "eu-central-1",  # Frankfurt
                "eu-west-1",  # Ireland
                "eu-west-3",  # Paris
                "ap-south-1",  # Mumbai
                "ca-central-1",  # Canada
            ]

            # For now, return the known list without checking each one
            # (checking each region takes time and requires permissions)
            return bedrock_regions
        except Exception:
            # Return default list if we can't check
            return [
                "us-east-1",
                "us-west-2",
                "eu-west-1",
                "eu-central-1",
                "ap-northeast-1",
                "ap-southeast-1",
                "ap-southeast-2",
            ]

    def _update_parameters_file(self, params_file: Path, config: dict[str, Any]) -> None:
        """Update the CloudFormation parameters file with our configuration."""
        # Load existing parameters
        if params_file.exists():
            with open(params_file, encoding="utf-8") as f:
                params = json.load(f)
        else:
            params = []

        # Update with our values
        sso_enabled = config.get("sso_enabled", True)
        okta_domain = config.get("okta", {}).get("domain", "none") if sso_enabled else "none"
        okta_client_id = config.get("okta", {}).get("client_id", "none") if sso_enabled else "none"
        param_map = {
            "OktaDomain": okta_domain,
            "OktaClientId": okta_client_id,
            "IdentityPoolName": config["aws"]["identity_pool_name"],
            "AllowedBedrockRegions": ",".join(config["aws"]["allowed_bedrock_regions"]),
            "EnableMonitoring": "true" if config["monitoring"]["enabled"] else "false",
            "MaxSessionDuration": "28800",  # 8 hours
        }

        # Add VPC configuration if monitoring is enabled
        if config.get("monitoring", {}).get("enabled"):
            vpc_config = config.get("monitoring", {}).get("vpc_config", {})
            if vpc_config.get("create_vpc", True):
                param_map["CreateVPC"] = "true"
            else:
                param_map["CreateVPC"] = "false"
                param_map["VpcId"] = vpc_config.get("vpc_id", "")
                param_map["SubnetIds"] = ",".join(vpc_config.get("subnet_ids", []))

        # Update or add parameters
        for key, value in param_map.items():
            found = False
            for param in params:
                if param["ParameterKey"] == key:
                    param["ParameterValue"] = value
                    found = True
                    break
            if not found:
                params.append({"ParameterKey": key, "ParameterValue": value})

        # Save updated parameters
        params_file.parent.mkdir(parents=True, exist_ok=True)
        with open(params_file, "w", encoding="utf-8") as f:
            json.dump(params, f, indent=2)

    def _deploy_stack(self, stack_name: str, template_file: Path, params_file: Path, region: str) -> bool:
        """Deploy a CloudFormation stack."""
        try:
            console = Console()

            # Check if template exists
            if not template_file.exists():
                console.print(f"[yellow]Template not found: {template_file.name}[/yellow]")
                return False

            # Build the AWS CLI command
            cmd = [
                "aws",
                "cloudformation",
                "deploy",
                "--template-file",
                str(template_file),
                "--stack-name",
                stack_name,
                "--parameter-overrides",
                f"file://{params_file}",
                "--capabilities",
                "CAPABILITY_IAM",
                "CAPABILITY_NAMED_IAM",
                "--region",
                region,
                "--no-fail-on-empty-changeset",
            ]

            # Show command in verbose mode
            if self.io.is_verbose():
                console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

            # Run the deployment
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return True
            else:
                console = Console()
                # Check for common issues
                if "No changes to deploy" in result.stderr:
                    return True  # Stack already up to date
                elif "does not exist" in result.stderr and "CREATE_IN_PROGRESS" not in result.stderr:
                    # Stack doesn't exist, but we're trying to update
                    console.print(f"[yellow]Creating new stack: {stack_name}[/yellow]")
                    # Try create instead of deploy
                    create_cmd = cmd.copy()
                    create_cmd[2] = "create-stack"
                    create_result = subprocess.run(create_cmd, capture_output=True, text=True)
                    if create_result.returncode == 0:
                        # Wait for stack to complete
                        wait_cmd = [
                            "aws",
                            "cloudformation",
                            "wait",
                            "stack-create-complete",
                            "--stack-name",
                            stack_name,
                            "--region",
                            region,
                        ]
                        subprocess.run(wait_cmd)
                        return True

                # Show the actual error
                error_msg = result.stderr if result.stderr else result.stdout
                console.print("[red]Deployment error:[/red]")
                console.print(f"[dim]{error_msg}[/dim]")
                return False

        except Exception as e:
            console = Console()
            console.print(f"[red]Deployment error: {e}[/red]")
            return False

    def _check_existing_deployment(self, profile_name: str) -> dict[str, Any]:
        """Check if there's an existing deployment and return its configuration.

        Args:
            profile_name: Name of the profile to check

        Returns:
            Configuration dict if profile exists, None otherwise
        """
        try:
            # Check if we have a saved configuration for this profile
            config = Config.load()
            profile = config.get_profile(profile_name)

            if not profile:
                return None

            # Try to check if the auth stack exists, but don't fail if AWS creds are missing
            region = profile.aws_region
            auth_stack = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")

            # Only check stack if we have AWS credentials
            console = Console()
            stacks_found = False
            try:
                console.print("\n[dim]Checking deployment status in current AWS account...[/dim]")
                if self._stack_exists(auth_stack, region):
                    # Get stack outputs to verify it's our stack
                    self._get_stack_outputs(auth_stack, region)
                    console.print(f"[dim]  ✓ Found auth stack: {auth_stack}[/dim]")
                    stacks_found = True
                else:
                    # Stack doesn't exist, but we have config
                    console.print(f"[dim]  ✗ Auth stack not found: {auth_stack}[/dim]")
            except Exception:
                # Can't check AWS - maybe no credentials
                console.print("[dim]  ! Could not verify stack status[/dim]")
                # Assume stacks exist if we can't check
                stacks_found = True

            # Build config from saved profile and stack outputs
            # Extract VPC-related keys from flattened monitoring_config back into nested structure
            vpc_config = None
            if profile.monitoring_config:
                vpc_keys = ["create_vpc", "vpc_id", "subnet_ids", "vpc_cidr", "subnet1_cidr", "subnet2_cidr"]
                vpc_data = {k: v for k, v in profile.monitoring_config.items() if k in vpc_keys and v is not None}
                if vpc_data:
                    vpc_config = vpc_data

            existing_config = {
                "_stacks_found": stacks_found,
                "okta": {"domain": profile.provider_domain, "client_id": profile.client_id},
                "credential_storage": getattr(profile, "credential_storage", "session"),
                "aws": {
                    "region": region,
                    "identity_pool_name": profile.identity_pool_name,
                    "stacks": profile.stack_names,
                    "allowed_bedrock_regions": profile.allowed_bedrock_regions,
                },
                "monitoring": {
                    "enabled": profile.monitoring_enabled,
                    "mode": getattr(profile, "monitoring_mode", "central"),
                    "vpc_config": vpc_config,
                    "custom_domain": profile.monitoring_config.get("custom_domain")
                    if profile.monitoring_config
                    else None,
                    "hosted_zone_id": profile.monitoring_config.get("hosted_zone_id")
                    if profile.monitoring_config
                    else None,
                },
            }

            # Add provider type if present (critical to preserve during updates)
            if hasattr(profile, "provider_type") and profile.provider_type:
                existing_config["provider_type"] = profile.provider_type

            # Add federation type if present (critical to preserve during updates)
            if hasattr(profile, "federation_type") and profile.federation_type:
                existing_config["federation_type"] = profile.federation_type

            # Add max session duration if present
            if hasattr(profile, "max_session_duration") and profile.max_session_duration:
                existing_config["max_session_duration"] = profile.max_session_duration

            # Add Cognito User Pool ID if present
            if hasattr(profile, "cognito_user_pool_id") and profile.cognito_user_pool_id:
                existing_config["cognito_user_pool_id"] = profile.cognito_user_pool_id

            # Add Generic OIDC fields if present
            for oidc_field in (
                "oidc_issuer_url",
                "oidc_authorization_endpoint",
                "oidc_token_endpoint",
                "oidc_jwks_uri",
                "oidc_thumbprint",
            ):
                if getattr(profile, oidc_field, None):
                    existing_config[oidc_field] = getattr(profile, oidc_field)

            # Add selected model if present
            if hasattr(profile, "selected_model") and profile.selected_model:
                existing_config["aws"]["selected_model"] = profile.selected_model

            # Add lock_default_model if present
            if hasattr(profile, "lock_default_model"):
                existing_config["lock_default_model"] = profile.lock_default_model

            # Add cross-region profile if present
            if hasattr(profile, "cross_region_profile") and profile.cross_region_profile:
                existing_config["aws"]["cross_region_profile"] = profile.cross_region_profile

            # Add application inference profile ARNs if present
            for arn_key in [
                "inference_profile_opus_arn",
                "inference_profile_sonnet_arn",
                "inference_profile_haiku_arn",
            ]:
                if getattr(profile, arn_key, None):
                    existing_config["aws"][arn_key] = getattr(profile, arn_key)

            # Add CodeBuild configuration if present
            if hasattr(profile, "enable_codebuild"):
                existing_config["codebuild"] = {"enabled": profile.enable_codebuild}
                if getattr(profile, "codebuild_region", None):
                    existing_config["codebuild"]["region"] = profile.codebuild_region
                if getattr(profile, "codebuild_prior_regions", None):
                    existing_config["codebuild"]["prior_regions"] = profile.codebuild_prior_regions

            # Add CoWork 3P configuration
            cowork_3p_config = {"enabled": profile.cowork_3p_enabled}
            if profile.cowork_3p_extra_keys:
                cowork_3p_config["extra_keys"] = profile.cowork_3p_extra_keys
            if profile.cowork_service_token:
                cowork_3p_config["service_token"] = profile.cowork_service_token
            existing_config["cowork_3p"] = cowork_3p_config

            # Add distribution configuration if present
            if hasattr(profile, "enable_distribution"):
                existing_config["distribution"] = {
                    "enabled": profile.enable_distribution,
                    "type": getattr(profile, "distribution_type", None),
                    "idp_provider": getattr(profile, "distribution_idp_provider", None),
                    "idp_domain": getattr(profile, "distribution_idp_domain", None),
                    "idp_client_id": getattr(profile, "distribution_idp_client_id", None),
                    "idp_client_secret_arn": getattr(profile, "distribution_idp_client_secret_arn", None),
                    "custom_domain": getattr(profile, "distribution_custom_domain", None),
                    "hosted_zone_id": getattr(profile, "distribution_hosted_zone_id", None),
                    "idp_issuer": getattr(profile, "distribution_idp_issuer", None),
                    "idp_authorization_endpoint": getattr(profile, "distribution_idp_authorization_endpoint", None),
                    "idp_token_endpoint": getattr(profile, "distribution_idp_token_endpoint", None),
                    "idp_userinfo_endpoint": getattr(profile, "distribution_idp_userinfo_endpoint", None),
                }

            # Add quota monitoring configuration if present.
            # Must mirror every quota field that _save_configuration persists, or a
            # re-run of `ccwb init` silently resets the omitted fields to their prompt
            # defaults (e.g. quota_check_interval -> 30). Note the key-name mapping:
            # the config dict uses "check_interval" while the Profile attribute is
            # "quota_check_interval" (see _save_configuration), so reverse it here.
            if hasattr(profile, "quota_monitoring_enabled"):
                existing_config["quota"] = {
                    "enabled": profile.quota_monitoring_enabled,
                    "monthly_limit": getattr(profile, "monthly_token_limit", 300000000),
                    "warning_threshold_80": getattr(profile, "warning_threshold_80", 240000000),
                    "warning_threshold_90": getattr(profile, "warning_threshold_90", 270000000),
                    "daily_limit": getattr(profile, "daily_token_limit", None),
                    "burst_buffer_percent": getattr(profile, "burst_buffer_percent", 10),
                    "daily_enforcement_mode": getattr(profile, "daily_enforcement_mode", "alert"),
                    "monthly_enforcement_mode": getattr(profile, "monthly_enforcement_mode", "block"),
                    "check_interval": getattr(profile, "quota_check_interval", 30),
                    "enable_bypass_detection": getattr(profile, "enable_bypass_detection", False),
                }

            # Add analytics configuration if present
            if hasattr(profile, "analytics_enabled"):
                existing_config["analytics"] = {"enabled": profile.analytics_enabled}

            # Preserve confidential client configuration if present
            # client_secret is never written to config — it lives in the OS keyring
            if getattr(profile, "azure_auth_mode", None):
                existing_config["azure_auth_mode"] = profile.azure_auth_mode
            if getattr(profile, "client_certificate_path", None):
                existing_config["client_certificate_path"] = profile.client_certificate_path
                existing_config["client_certificate_key_path"] = profile.client_certificate_key_path

            # Add selected source region if present
            if hasattr(profile, "selected_source_region") and profile.selected_source_region:
                existing_config["aws"]["selected_source_region"] = profile.selected_source_region

            # Add resource tags if present
            if hasattr(profile, "tags") and profile.tags:
                existing_config["tags"] = profile.tags

            return existing_config

        except Exception:
            return None

    def _show_existing_deployment(self, config: dict[str, Any]) -> None:
        """Show summary of existing deployment."""
        console = Console()

        if config.get("sso_enabled", True) and "okta" in config and "domain" in config["okta"]:
            console.print(f"• OIDC Provider: [cyan]{config['okta']['domain']}[/cyan]")
        else:
            console.print("• Authentication: [cyan]AWS SSO / IAM Identity Center (no OIDC)[/cyan]")

        # Show Cognito-specific fields if using Cognito User Pool
        if "cognito_user_pool_id" in config:
            console.print(f"• Cognito User Pool ID: [cyan]{config['cognito_user_pool_id']}[/cyan]")
        if "okta" in config and "client_id" in config["okta"]:
            console.print(f"• Client ID: [cyan]{config['okta']['client_id']}[/cyan]")

        cred_storage = "Keyring" if config.get("credential_storage") == "keyring" else "Session Files"
        console.print(f"• Credential Storage: [cyan]{cred_storage}[/cyan]")
        console.print(f"• AWS Region: [cyan]{config['aws']['region']}[/cyan]")
        console.print(f"• Identity Pool: [cyan]{config['aws']['identity_pool_name']}[/cyan]")

        # Show selected model if present
        selected_model = config["aws"].get("selected_model")
        if selected_model:
            from claude_code_with_bedrock.models import get_all_model_display_names

            model_names = get_all_model_display_names()
            console.print(f"• Claude Model: [cyan]{model_names.get(selected_model, selected_model)}[/cyan]")

        # Show application inference profiles if configured
        for tier, key in [
            ("Opus", "inference_profile_opus_arn"),
            ("Sonnet", "inference_profile_sonnet_arn"),
            ("Haiku", "inference_profile_haiku_arn"),
        ]:
            arn = config["aws"].get(key)
            if arn:
                console.print(f"• {tier} Inference Profile: [cyan]{arn}[/cyan]")

        # Show cross-region profile
        cross_region_profile = config["aws"].get("cross_region_profile", "us")
        profile_names = {
            "us": "US Cross-Region (us-east-1, us-east-2, us-west-2)",
            "europe": "Europe Cross-Region",
            "apac": "APAC Cross-Region",
        }
        console.print(
            f"• Bedrock Regions: [cyan]{profile_names.get(cross_region_profile, cross_region_profile)}[/cyan]"
        )
        console.print(f"• Monitoring: [cyan]{'Enabled' if config['monitoring']['enabled'] else 'Disabled'}[/cyan]")

    def _stack_exists(self, stack_name: str, region: str) -> bool:
        """Check if a CloudFormation stack exists."""
        try:
            cmd = [
                "aws",
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--region",
                region,
                "--query",
                "Stacks[0].StackStatus",
                "--output",
                "text",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                status = result.stdout.strip()
                # Stack exists if it's in any valid state
                valid_statuses = ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]
                return status in valid_statuses
            return False
        except Exception:
            return False

    def _get_stack_outputs(self, stack_name: str, region: str) -> dict[str, str]:
        """Get outputs from a CloudFormation stack."""
        try:
            cmd = [
                "aws",
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--region",
                region,
                "--query",
                "Stacks[0].Outputs",
                "--output",
                "json",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                outputs_list = json.loads(result.stdout)
                outputs = {}
                for output in outputs_list:
                    outputs[output["OutputKey"]] = output["OutputValue"]
                return outputs
            return {}
        except Exception:
            return {}

    def _get_hosted_zones(self) -> tuple[list[dict[str, Any]], str | None]:
        """Get available Route53 hosted zones.

        Returns:
            Tuple of (zones list, error message or None).
            On success: (zones, None). On failure: ([], error_string).
        """
        try:
            import boto3

            client = boto3.client("route53")
            response = client.list_hosted_zones()
            return response.get("HostedZones", []), None
        except Exception as e:
            return [], str(e)

    def _configure_vpc(self, region: str, existing_vpc_config: dict[str, Any] = None) -> dict[str, Any]:
        """Configure VPC for monitoring stack."""
        console = Console()

        console.print("\n[bold]VPC Configuration for Monitoring[/bold]")
        console.print("The monitoring stack requires a VPC for the OpenTelemetry collector.")

        # If we already have a VPC config, show it and ask if user wants to keep it
        if existing_vpc_config:
            if existing_vpc_config.get("create_vpc"):
                console.print("[dim]Current configuration: Create new VPC (managed by stack)[/dim]")
            elif existing_vpc_config.get("vpc_id"):
                vpc_id = existing_vpc_config.get("vpc_id")
                subnet_ids = existing_vpc_config.get("subnet_ids", [])
                console.print(f"[dim]Current configuration: VPC {vpc_id} with {len(subnet_ids)} subnets[/dim]")

            keep_config = questionary.confirm("Keep existing VPC configuration?", default=True).ask()

            if keep_config:
                return existing_vpc_config

        # Check if monitoring stack already exists with a VPC
        monitoring_stack = None
        stack_vpc_info = None
        try:
            # Check for existing monitoring stack
            config = Config.load()
            profile = config.get_profile()
            if profile and profile.stack_names:
                monitoring_stack = profile.stack_names.get("monitoring")
                if monitoring_stack:
                    from claude_code_with_bedrock.cli.utils.aws import check_stack_exists, get_stack_outputs

                    if check_stack_exists(monitoring_stack, region):
                        outputs = get_stack_outputs(monitoring_stack, region)
                        if outputs.get("VpcSource") == "stack-created":
                            stack_vpc_info = {
                                "vpc_id": outputs.get("VpcId"),
                                "subnet_ids": (
                                    outputs.get("SubnetIds", "").split(",") if outputs.get("SubnetIds") else []
                                ),
                            }
                            console.print(
                                f"\n[green]Found existing monitoring stack with VPC: {stack_vpc_info['vpc_id']}[/green]"
                            )
        except Exception:
            # If we can't check, continue with normal flow
            pass

        # If we found a stack-created VPC, offer to keep using it
        if stack_vpc_info and stack_vpc_info["vpc_id"]:
            use_stack_vpc = questionary.confirm(
                "The monitoring stack already has a VPC. Continue using it?", default=True
            ).ask()

            if use_stack_vpc:
                return {"create_vpc": True}  # Keep CreateVPC=true to maintain the stack-created VPC

        # Check for existing VPCs
        console.print("\n[yellow]Searching for existing VPCs...[/yellow]")
        vpcs = get_vpcs(region)

        if vpcs:
            # Found existing VPCs
            vpc_choices = []
            vpc_choices.append(questionary.Choice("Create new VPC", value="create_new"))

            for vpc in vpcs:
                label = f"{vpc['id']} - {vpc['cidr']}"
                if vpc["name"]:
                    label = f"{vpc['name']} ({label})"
                if vpc["is_default"]:
                    label = f"{label} [DEFAULT]"
                vpc_choices.append(questionary.Choice(label, value=vpc["id"]))

            vpc_choice = questionary.select("Select VPC for monitoring infrastructure:", choices=vpc_choices).ask()

            if vpc_choice == "create_new":
                return {"create_vpc": True}
            else:
                # User selected an existing VPC
                next(v for v in vpcs if v["id"] == vpc_choice)
                console.print(f"\n[green]Selected VPC: {vpc_choice}[/green]")

                # Get subnets
                console.print("\n[yellow]Searching for subnets...[/yellow]")
                subnets = get_subnets(region, vpc_choice)

                if len(subnets) < 2:
                    console.print("[red]Error: ALB requires at least 2 subnets in different availability zones[/red]")
                    create_new = questionary.confirm("Would you like to create a new VPC instead?", default=True).ask()
                    if create_new:
                        return {"create_vpc": True}
                    else:
                        return None

                # Let user select subnets
                subnet_choices = []
                for subnet in subnets:
                    label = f"{subnet['id']} - {subnet['cidr']} ({subnet['availability_zone']})"
                    if subnet["name"]:
                        label = f"{subnet['name']} - {label}"
                    if subnet["is_public"]:
                        label = f"{label} [PUBLIC]"
                    subnet_choices.append(questionary.Choice(label, value=subnet["id"], checked=subnet["is_public"]))

                selected_subnets = questionary.checkbox(
                    "Select at least 2 subnets for the ALB (in different AZs):",
                    choices=subnet_choices,
                    validate=lambda x: len(x) >= 2 or "Please select at least 2 subnets",
                ).ask()

                if not selected_subnets:
                    return None

                # Validate subnets are in different AZs
                selected_subnet_details = [s for s in subnets if s["id"] in selected_subnets]
                azs = {s["availability_zone"] for s in selected_subnet_details}

                if len(azs) < 2:
                    console.print("[red]Error: Selected subnets must be in different availability zones[/red]")
                    return None

                return {"create_vpc": False, "vpc_id": vpc_choice, "subnet_ids": selected_subnets}
        else:
            # No VPCs found or can't list them
            console.print("[yellow]No existing VPCs found or unable to list VPCs.[/yellow]")
            create_new = questionary.confirm("Create a new VPC for monitoring?", default=True).ask()

            if create_new:
                return {"create_vpc": True}
            else:
                # Manual entry
                vpc_id = questionary.text(
                    "Enter existing VPC ID:", validate=lambda x: x.startswith("vpc-") or "Invalid VPC ID format"
                ).ask()

                if not vpc_id:
                    return None

                subnet_ids_str = questionary.text(
                    "Enter at least 2 subnet IDs (comma-separated):",
                    validate=lambda x: len(x.split(",")) >= 2 or "Please provide at least 2 subnet IDs",
                ).ask()

                if not subnet_ids_str:
                    return None

                subnet_ids = [s.strip() for s in subnet_ids_str.split(",")]

                return {"create_vpc": False, "vpc_id": vpc_id, "subnet_ids": subnet_ids}

    def _prompt_for_profile_name(self, console: Console) -> str | None:
        """Prompt user for a profile name with validation.

        Args:
            console: Rich console for output

        Returns:
            Profile name if valid, None if cancelled
        """
        console.print("\n[bold cyan]Profile Name[/bold cyan]")
        console.print("Choose a descriptive name for this deployment profile.")
        console.print("[dim]Suggested format: {project}-{environment}-{region}[/dim]")
        console.print("[dim]Examples: acme-prod-us-east-1, internal-dev-us-west-2[/dim]\n")

        while True:
            profile_name = questionary.text(
                "Profile name:",
                validate=lambda x: bool(x) or "Profile name cannot be empty",
            ).ask()

            if profile_name is None:  # User cancelled
                return None

            # Validate profile name
            if not Config._is_valid_profile_name(profile_name):
                console.print(
                    "[red]Invalid profile name.[/red] Must be alphanumeric with hyphens only, max 64 characters.\n"
                )
                continue

            # Check if profile already exists
            config = Config.load()
            if profile_name in config.list_profiles():
                console.print(f"[red]Profile '{profile_name}' already exists.[/red]\n")
                overwrite = questionary.confirm(f"Update existing profile '{profile_name}'?", default=False).ask()
                if overwrite:
                    return profile_name
                else:
                    continue

            return profile_name

    def _select_or_create_profile(self, console: Console) -> tuple[str, bool, str]:
        """Interactive profile selection or creation.

        Args:
            console: Rich console for output

        Returns:
            Tuple of (profile_name, is_new_profile, action) where action is "create", "update", or "switch"
        """
        config = Config.load()
        existing_profiles = config.list_profiles()

        # If --profile flag was provided, use it
        profile_option = self.option("profile")
        if profile_option and profile_option != "default":
            # Check if profile exists
            if profile_option in existing_profiles:
                console.print(f"\n[cyan]Using profile:[/cyan] {profile_option}")
                return (profile_option, False, "update")  # Assume user wants to update when using --profile flag
            else:
                console.print(f"\n[cyan]Creating new profile:[/cyan] {profile_option}")
                # Validate the profile name
                if not Config._is_valid_profile_name(profile_option):
                    console.print(
                        f"[red]Invalid profile name '{profile_option}'.[/red] "
                        "Must be alphanumeric with hyphens only, max 64 characters."
                    )
                    return (None, False, "cancelled")
                return (profile_option, True, "create")

        # No profiles exist - first time setup
        if not existing_profiles:
            console.print("\n[cyan]No profiles found. Let's create your first profile![/cyan]")
            profile_name = self._prompt_for_profile_name(console)
            if not profile_name:
                return (None, False, "cancelled")
            return (profile_name, True, "create")

        # Profiles exist - offer choices
        console.print(f"\n[cyan]Found {len(existing_profiles)} existing profile(s):[/cyan]")
        for profile in existing_profiles:
            is_active = profile == config.active_profile
            marker = "★" if is_active else " "
            console.print(f"  {marker} {profile}")

        choices = [
            "Create new profile for different account/region",
            "Update existing profile",
            "Switch to existing profile (no changes)",
        ]

        action = questionary.select(
            "\nWhat would you like to do?",
            choices=choices,
        ).ask()

        if action is None:  # User cancelled
            return (None, False, "cancelled")

        if action == choices[0]:  # Create new
            profile_name = self._prompt_for_profile_name(console)
            if not profile_name:
                return (None, False, "cancelled")
            return (profile_name, True, "create")

        elif action == choices[1]:  # Update existing
            if len(existing_profiles) == 1:
                profile_name = existing_profiles[0]
                console.print(f"\n[cyan]Updating profile:[/cyan] {profile_name}")
            else:
                profile_name = questionary.select(
                    "\nSelect profile to update:",
                    choices=existing_profiles,
                ).ask()
                if profile_name is None:
                    return (None, False, "cancelled")
            return (profile_name, False, "update")

        else:  # Switch to existing
            if len(existing_profiles) == 1:
                profile_name = existing_profiles[0]
            else:
                profile_name = questionary.select(
                    "\nSelect profile to activate:",
                    choices=existing_profiles,
                ).ask()
                if profile_name is None:
                    return (None, False, "cancelled")

            # Switch active profile
            config.set_active_profile(profile_name)
            console.print(f"\n[green]✓ Switched to profile:[/green] {profile_name}")
            console.print("\nNext steps:")
            console.print("• Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]")
            console.print("• View profile details: [cyan]poetry run ccwb context show[/cyan]")
            return (None, False, "switch")
