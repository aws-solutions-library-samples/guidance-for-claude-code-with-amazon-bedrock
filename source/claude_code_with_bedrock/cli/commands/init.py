# ABOUTME: Interactive setup wizard for first-time users
# ABOUTME: Guides through complete Claude Code with Bedrock deployment

"""Init command - Interactive setup wizard."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

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
    if value and re.match(r"^[a-zA-Z0-9_-]+$", value):
        return True
    return "Invalid pool name (alphanumeric, underscore, hyphen only)"


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
        )
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
            config = self._gather_configuration(progress, existing_config)
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
                config = self._gather_configuration(progress, existing_config)
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
        config = self._gather_configuration(progress)
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
            "AWS CLI installed": self._check_aws_cli(),
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
        self, progress: WizardProgress, existing_config: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
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

        # OIDC Provider Configuration
        if not skip_okta:
            console.print("\n[bold blue]Step 1: OIDC Provider Configuration[/bold blue]")
            console.print("─" * 30)

            provider_domain = questionary.text(
                "Enter your OIDC provider domain:",
                validate=lambda x: validate_oidc_provider_domain(x)
                or "Invalid provider domain format (e.g., company.okta.com)",
                instruction=(
                    "(e.g., company.okta.com, company.auth0.com, "
                    "login.microsoftonline.com/{tenant-id}/v2.0, "
                    "my-app.auth.us-east-1.amazoncognito.com, or "
                    "my-app.auth-fips.us-gov-west-1.amazoncognito.com for GovCloud, "
                    "or keycloak.example.com/realms/my-realm for Keycloak)"
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
                    elif '/realms/' in provider_domain:
                        provider_type = "keycloak"
                    elif questionary.confirm("Is this a custom domain for AWS Cognito User Pool?", default=False).ask():
                        provider_type = "cognito"
            except Exception:
                pass  # Continue to manual selection if parsing fails

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

            # For Keycloak, ask for TLS thumbprint
            keycloak_thumbprint = None
            if provider_type == "keycloak":
                console.print("\n[yellow]Keycloak TLS Certificate Thumbprint[/yellow]")
                console.print("The IAM OIDC Provider requires a TLS certificate thumbprint.")
                console.print("Get it with:")
                kc_host = provider_domain.split('/realms/')[0] if '/realms/' in provider_domain else provider_domain
                openssl_cmd = (
                    f"openssl s_client -connect {kc_host}:443 2>/dev/null"
                    " | openssl x509 -fingerprint -sha1 -noout"
                    " | sed 's/://g' | cut -d= -f2 | tr '[:upper:]' '[:lower:]'"
                )
                console.print(f"  [cyan]{openssl_cmd}[/cyan]")
                console.print("[dim]Leave empty to use default (all-zeros). Some regions reject all-zeros.[/dim]")

                keycloak_thumbprint = questionary.text(
                    "Keycloak TLS thumbprint (40 hex chars, or Enter to skip):",
                    default=config.get("keycloak_thumbprint", ""),
                    validate=lambda x: (
                        x == ""
                        or (len(x) == 40 and all(c in "0123456789abcdefABCDEF" for c in x))
                        or "Must be 40 hex characters or empty"
                    ),
                ).ask()

                if keycloak_thumbprint:
                    keycloak_thumbprint = keycloak_thumbprint.lower()

            client_id = questionary.text(
                "Enter your OIDC Client ID:",
                validate=lambda x: bool(x and len(x) >= 10) or "Client ID must be at least 10 characters",
                default=config.get("okta", {}).get("client_id", ""),
            ).ask()

            if not client_id:
                return None

            # Credential Storage Method
            console.print("\n[bold]Credential Storage Method[/bold]")
            console.print("Choose how to store AWS credentials locally:")
            console.print("  • [cyan]Keyring[/cyan]: Uses OS secure storage (may prompt for password)")
            console.print("  • [cyan]Session Files[/cyan]: Temporary files (deleted on logout)\n")

            _cs_choices = [
                questionary.Choice("Keyring (Secure OS storage)", value="keyring"),
                questionary.Choice("Session Files (Temporary storage)", value="session"),
            ]
            _cs_saved = config.get("credential_storage", "session")
            credential_storage = questionary.select(
                "Select credential storage method:",
                choices=_cs_choices,
                default=next((c for c in _cs_choices if c.value == _cs_saved), _cs_choices[1]),
            ).ask()

            if not credential_storage:
                return None

            # Preserve existing okta settings, only update domain/client_id
            if "okta" not in config:
                config["okta"] = {}
            config["okta"]["domain"] = provider_domain
            config["okta"]["client_id"] = client_id
            config["credential_storage"] = credential_storage
            config["provider_type"] = provider_type
            if cognito_user_pool_id:
                config["cognito_user_pool_id"] = cognito_user_pool_id
            if keycloak_thumbprint:
                config["keycloak_thumbprint"] = keycloak_thumbprint

            # Ask about federation type
            console.print("\n[cyan]Federation Type Selection[/cyan]")
            console.print("Direct STS.")
            console.print("Cognito Identity Pool.\n")

            # Use existing federation type as default if available
            existing_federation_type = config.get("federation_type", "direct")

            _fed_choices = [
                questionary.Choice("Direct STS", value="direct"),
                questionary.Choice("Cognito Identity Pool", value="cognito"),
            ]
            federation_type = questionary.select(
                "Choose federation type:",
                choices=_fed_choices,
                default=next((c for c in _fed_choices if c.value == existing_federation_type), _fed_choices[0]),
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
                "ap-southeast-7",
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

            # If monitoring is enabled, configure VPC
            if enable_monitoring:
                # Pass existing vpc_config if available
                existing_vpc_config = config.get("monitoring", {}).get("vpc_config")
                vpc_config = self._configure_vpc(
                    config.get("aws", {}).get("region", get_current_region()), existing_vpc_config
                )
                if not vpc_config:
                    return None
                config["monitoring"]["vpc_config"] = vpc_config

                # Optional: Configure HTTPS with custom domain
                console.print("\n[yellow]Optional: Configure HTTPS for secure telemetry[/yellow]")

                # Check if HTTPS is already configured
                existing_custom_domain = config["monitoring"].get("custom_domain")
                existing_zone_id = config["monitoring"].get("hosted_zone_id")
                already_configured = bool(existing_custom_domain)

                if already_configured:
                    console.print(f"[dim]Current configuration: {existing_custom_domain}[/dim]")

                enable_https = questionary.confirm("Enable HTTPS with custom domain?", default=already_configured).ask()

                if enable_https:
                    custom_domain = questionary.text(
                        "Enter custom domain name (e.g., telemetry.company.com):",
                        validate=lambda x: len(x) > 0 and "." in x,
                        default=existing_custom_domain if existing_custom_domain else "",
                    ).ask()

                    # Get Route53 hosted zones
                    hosted_zones = self._get_hosted_zones()
                    if hosted_zones:
                        zone_choices = [
                            f"{zone['Name'].rstrip('.')} ({zone['Id'].split('/')[-1]})" for zone in hosted_zones
                        ]
                        zone_choices.append("Skip (use external DNS provider)")

                        # Pre-select existing zone if available
                        default_zone = None
                        if existing_zone_id:
                            for choice in zone_choices:
                                if existing_zone_id in choice:
                                    default_zone = choice
                                    break

                        # If HTTPS was previously configured without Route53 (Skip), restore that choice
                        if default_zone is None and existing_custom_domain and not existing_zone_id:
                            default_zone = zone_choices[-1]  # "Skip (use external DNS provider)" is always last

                        selected_zone = questionary.select(
                            "Select DNS management for the domain:",
                            choices=zone_choices,
                            default=default_zone if default_zone else zone_choices[0],
                        ).ask()

                        if selected_zone == "Skip (use external DNS provider)":
                            config["monitoring"]["custom_domain"] = custom_domain
                            config["monitoring"]["hosted_zone_id"] = None
                            console.print(
                                f"[green]✓[/green] HTTPS will be enabled with domain: {custom_domain}"
                            )
                            console.print(
                                "[yellow]You will need to create DNS records manually during deployment.[/yellow]"
                            )
                        else:
                            # Extract zone ID
                            zone_id = selected_zone.split("(")[-1].rstrip(")")
                            config["monitoring"]["custom_domain"] = custom_domain
                            config["monitoring"]["hosted_zone_id"] = zone_id
                            console.print(f"[green]✓[/green] HTTPS will be enabled with domain: {custom_domain}")
                    else:
                        config["monitoring"]["custom_domain"] = custom_domain
                        config["monitoring"]["hosted_zone_id"] = None
                        console.print(f"[green]✓[/green] HTTPS will be enabled with domain: {custom_domain}")
                        console.print(
                            "[yellow]No Route53 zones found. You will need to create DNS records manually.[/yellow]"
                        )
                else:
                    # User disabled HTTPS, clear any existing config
                    config["monitoring"]["custom_domain"] = None
                    config["monitoring"]["hosted_zone_id"] = None

                # Analytics configuration (only if monitoring is enabled)
                console.print("\n[bold]Analytics Pipeline[/bold]")
                console.print("Advanced user metrics and reporting through AWS Athena (~$5/month)")
                enable_analytics = questionary.confirm(
                    "Enable analytics?",
                    default=config.get("analytics", {}).get("enabled", True),
                ).ask()

                # Preserve existing analytics settings, only update enabled flag
                if "analytics" not in config:
                    config["analytics"] = {}
                config["analytics"]["enabled"] = enable_analytics

                if enable_analytics:
                    console.print("[green]✓[/green] Analytics pipeline will be deployed with your monitoring stack")

                # Quota monitoring configuration (only if monitoring is enabled)
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

                    # Monthly token limit
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

                    _daily_enf_choices = [
                        questionary.Choice("alert (warn only)", value="alert"),
                        questionary.Choice("block (deny access)", value="block"),
                    ]
                    _daily_saved = config.get("quota", {}).get("daily_enforcement_mode", "alert")
                    daily_enforcement = questionary.select(
                        "Daily limit enforcement:",
                        choices=_daily_enf_choices,
                        default=next((c for c in _daily_enf_choices if c.value == _daily_saved), _daily_enf_choices[0]),
                    ).ask()

                    _monthly_enf_choices = [
                        questionary.Choice("alert (warn only)", value="alert"),
                        questionary.Choice("block (deny access)", value="block"),
                    ]
                    _monthly_saved = config.get("quota", {}).get("monthly_enforcement_mode", "block")
                    monthly_enforcement = questionary.select(
                        "Monthly limit enforcement:",
                        choices=_monthly_enf_choices,
                        default=next(
                            (c for c in _monthly_enf_choices if c.value == _monthly_saved), _monthly_enf_choices[1]
                        ),
                    ).ask()

                    config["quota"]["daily_enforcement_mode"] = daily_enforcement
                    config["quota"]["monthly_enforcement_mode"] = monthly_enforcement

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

                    console.print("\n[green]✓[/green] Quota monitoring configured:")
                    console.print(f"  • Monthly: {monthly_limit:,} tokens ({monthly_enforcement})")
                    console.print(f"  • Daily:   {daily_limit:,} tokens ({daily_enforcement})")
                    console.print(f"  • Burst buffer: {burst_percent}%")
                    console.print(f"  • Re-check interval: {check_interval} minutes")

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

        # Package distribution support
        console.print("\n[bold]Package Distribution[/bold]")
        console.print("Choose how to distribute Claude Code packages to end users:")
        console.print("  • Presigned S3 URLs: Simple, no authentication (good for < 20 users)")
        console.print("  • Landing Page: IdP authentication with web UI (good for 20-100 users)")

        distribution_choices = [
            questionary.Choice("Presigned S3 URLs (simple, no authentication)", value="presigned-s3"),
            questionary.Choice("Authenticated Landing Page (IdP + ALB)", value="landing-page"),
            questionary.Choice("Disabled", value="__disabled__"),
        ]

        # Get saved value or default to None
        saved_dist_type = config.get("distribution", {}).get("type")
        default_choice = next((c for c in distribution_choices if c.value == saved_dist_type), None)

        distribution_type = questionary.select(
            "Distribution method:",
            choices=distribution_choices,
            default=default_choice,
        ).ask()
        if distribution_type == "__disabled__":
            distribution_type = None

        # Preserve existing distribution settings, only update enabled/type
        if "distribution" not in config:
            config["distribution"] = {}
        config["distribution"]["enabled"] = distribution_type is not None
        config["distribution"]["type"] = distribution_type

        # If landing-page selected, prompt for additional configuration
        if distribution_type == "landing-page":
            console.print("\n[bold]Landing Page Configuration[/bold]")
            console.print("Configure IdP authentication for the distribution landing page")

            # IdP provider selection
            idp_choices = [
                questionary.Choice("Okta", value="okta"),
                questionary.Choice("Azure AD / Entra ID", value="azure"),
                questionary.Choice("Auth0", value="auth0"),
                questionary.Choice("AWS Cognito User Pool", value="cognito"),
                questionary.Choice("Keycloak", value="keycloak"),
            ]

            _idp_saved = config.get("distribution", {}).get("idp_provider", "okta")
            idp_provider = questionary.select(
                "Identity provider for web authentication:",
                choices=idp_choices,
                default=next((c for c in idp_choices if c.value == _idp_saved), idp_choices[0]),
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

                # Try to auto-detect Cognito stack
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
                idp_domain = questionary.text(
                    "IdP domain (e.g., company.okta.com for Okta, company.auth0.com for Auth0):",
                    default=config.get("distribution", {}).get("idp_domain", ""),
                ).ask()

                # Web app client ID
                idp_client_id = questionary.text(
                    "Web application client ID (separate from CLI native app):",
                    default=config.get("distribution", {}).get("idp_client_id", ""),
                ).ask()

                # Web app client secret
                existing_secret_arn = config.get("distribution", {}).get("idp_client_secret_arn")
                _secret_prompt = (
                    "Web application client secret (leave blank to keep existing):"
                    if existing_secret_arn
                    else "Web application client secret:"
                )
                idp_client_secret = questionary.password(_secret_prompt).ask()

                # First-time setup: a secret is required — re-prompt until provided
                if not idp_client_secret and not existing_secret_arn:
                    while not idp_client_secret:
                        console.print("[red]Client secret is required for initial setup.[/red]")
                        idp_client_secret = questionary.password("Web application client secret:").ask()

            # Store secret in AWS Secrets Manager (only if not auto-configured)
            import boto3

            if not cognito_auto_configured:
                if idp_client_secret:
                    try:
                        secrets_client = boto3.client("secretsmanager", region_name=region)
                        account_id = boto3.client("sts").get_caller_identity()["Account"]

                        secret_name = f"{config['aws']['identity_pool_name']}-distribution-idp-secret"

                        # Try to create or update secret
                        try:
                            secret_response = secrets_client.create_secret(
                                Name=secret_name,
                                SecretString=idp_client_secret,
                                Description=f"IdP client secret for "
                                f"{config['aws']['identity_pool_name']} distribution landing page",
                            )
                            secret_arn = secret_response["ARN"]
                        except secrets_client.exceptions.ResourceExistsException:
                            # Secret already exists, update it
                            secret_response = secrets_client.update_secret(
                                SecretId=secret_name,
                                SecretString=idp_client_secret,
                            )
                            secret_arn = secret_response["ARN"]

                        console.print(f"[green]✓[/green] IdP client secret stored in Secrets Manager: {secret_name}")

                    except Exception as e:
                        console.print(f"[red]Error storing secret in Secrets Manager: {e}[/red]")
                        console.print("[yellow]You'll need to configure the secret manually before deployment[/yellow]")
                        secret_arn = f"arn:aws:secretsmanager:{region}:{account_id}:secret:{secret_name}"
                else:
                    # Blank input — keep the existing secret unchanged
                    secret_arn = existing_secret_arn
                    console.print("[green]✓[/green] Keeping existing IdP client secret.")

            # Custom domain (REQUIRED for authenticated landing page)
            console.print("\n[bold]Custom Domain Configuration (REQUIRED)[/bold]")
            console.print("[yellow]⚠️  Custom domain with HTTPS is required for ALB OIDC authentication[/yellow]")
            console.print("You will need:")
            console.print("  • A custom domain (e.g., downloads.company.com)")
            console.print("  • An ACM certificate for this domain in the same region")

            custom_domain = questionary.text(
                "Custom domain (e.g., downloads.company.com):",
                default=config.get("distribution", {}).get("custom_domain", ""),
                validate=lambda text: len(text.strip()) > 0
                or "Custom domain is required for authenticated landing page",
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
                    zone_choices.append(questionary.Choice("Skip (no Route53 managed domain)", value="__skip__"))

                    # Find the default choice based on existing zone
                    default_choice = None
                    if existing_zone_id:
                        for choice in zone_choices:
                            if choice.value == existing_zone_id:
                                default_choice = choice
                                break

                    # If user previously chose Skip (zone_id saved as None but custom_domain is set), restore Skip
                    dist_has_domain = config.get("distribution", {}).get("custom_domain")
                    if default_choice is None and dist_has_domain and not existing_zone_id:
                        default_choice = zone_choices[-1]  # "Skip (no Route53 managed domain)" is always last

                    hosted_zone_id = questionary.select(
                        "Select Route53 hosted zone:",
                        choices=zone_choices,
                        default=default_choice if default_choice else zone_choices[0],
                    ).ask()
                    if hosted_zone_id == "__skip__":
                        hosted_zone_id = None
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
                get_all_destination_regions_for_profile,
                get_all_source_regions,
                get_destination_regions_for_model_profile,
                get_model_id_for_profile,
                get_models_for_tier,
                get_profiles_for_region,
                resolve_profile_key,
            )

            # Restore saved values — model fields stored as model IDs, need reverse-lookup for keys
            saved_source_region = config.get("aws", {}).get("selected_source_region")
            saved_profile = config.get("aws", {}).get("cross_region_profile")  # None = auto-select

            _saved_model_id = config.get("aws", {}).get("selected_model")
            saved_model_key = None
            if _saved_model_id:
                for _mk, _mi in CLAUDE_MODELS.items():
                    for _pc in cast(dict[str, Any], _mi)["profiles"].values():
                        if cast(dict[str, Any], _pc)["model_id"] == _saved_model_id:
                            saved_model_key = _mk
                            break
                    if saved_model_key:
                        break

            def _key_for_model_id(model_id: str) -> str | None:
                for mk, mi in CLAUDE_MODELS.items():
                    for pc in cast(dict[str, Any], mi)["profiles"].values():
                        if cast(dict[str, Any], pc).get("model_id") == model_id:
                            return mk
                return None

            saved_tier_keys: dict[str, str | None] = {
                "opus": _key_for_model_id(config.get("aws", {}).get("default_opus_model") or ""),
                "sonnet": _key_for_model_id(config.get("aws", {}).get("default_sonnet_model") or ""),
                "haiku": _key_for_model_id(config.get("aws", {}).get("default_haiku_model") or ""),
            }

            # Q1: Source region (always required)
            all_regions = get_all_source_regions()
            region_choices = [questionary.Choice(r, value=r) for r in all_regions]
            _default_region = next(
                (c for c in region_choices if c.value == saved_source_region), region_choices[0]
            )
            selected_source_region = questionary.select(
                "Select source region for AWS configuration:",
                choices=region_choices,
                default=_default_region,
                instruction="(Use arrow keys to select, Enter to confirm)",
            ).ask()

            if selected_source_region is None:  # User cancelled
                return None

            config["aws"]["selected_source_region"] = selected_source_region
            console.print(f"[green]✓[/green] Source region: {selected_source_region}")

            # Q2: Cross-region profile (filtered by region; Auto-select exits early)
            available_profiles = get_profiles_for_region(selected_source_region)

            _AUTO_PROFILE = "__auto__"
            _PROFILE_LABELS = {
                "us": "US Cross-Region — US regions",
                "eu": "EU Cross-Region — European regions",
                "europe": "EU Cross-Region — European regions",
                "japan": "Japan Cross-Region — Japan regions",
                "australia": "Australia Cross-Region — Australia regions",
                "apac": "APAC Cross-Region — Asia-Pacific regions",
                "global": "Global Cross-Region — All regions worldwide",
                "us-gov": "US GovCloud Cross-Region — US GovCloud regions",
            }
            profile_choices = [
                questionary.Choice(
                    "Auto-select (recommended) — Claude Code picks model for your region",
                    value=_AUTO_PROFILE,
                )
            ]
            for pk in available_profiles:
                label = _PROFILE_LABELS.get(pk, f"{pk.upper()} Cross-Region")
                profile_choices.append(questionary.Choice(label, value=pk))

            _default_profile = next(
                (c for c in profile_choices if c.value == (saved_profile or _AUTO_PROFILE)),
                profile_choices[0],
            )
            selected_profile = questionary.select(
                "Select cross-region inference profile:",
                choices=profile_choices,
                default=_default_profile,
                instruction="(Use arrow keys to select, Enter to confirm)",
            ).ask()

            if selected_profile is None:  # User cancelled
                return None

            if selected_profile == _AUTO_PROFILE:
                config["aws"]["cross_region_profile"] = None
                config["aws"]["selected_model"] = None
                config["aws"]["allowed_bedrock_regions"] = ["*"]
                config["aws"]["default_opus_model"] = None
                config["aws"]["default_sonnet_model"] = None
                config["aws"]["default_haiku_model"] = None
                console.print("[green]✓[/green] Auto-select: Claude Code will select models for your region")
                progress.save_step("bedrock_complete", config)
                return config

            config["aws"]["cross_region_profile"] = selected_profile
            console.print(f"[green]✓[/green] Profile: {selected_profile}")

            # Q3: Claude model (filtered by profile; Auto-select exits Q4-Q6)
            _AUTO_MODEL = "__auto__"
            model_choices: list[questionary.Choice] = [
                questionary.Choice("Auto-select — don't set ANTHROPIC_MODEL", value=_AUTO_MODEL)
            ]
            for model_key, model_config in CLAUDE_MODELS.items():
                if resolve_profile_key(model_key, selected_profile) is None:
                    continue
                model_choices.append(questionary.Choice(cast(str, model_config["name"]), value=model_key))

            _default_model = next(
                (c for c in model_choices if c.value == (saved_model_key or _AUTO_MODEL)),
                model_choices[0],
            )
            selected_model_key = questionary.select(
                "Select Claude model:",
                choices=model_choices,
                default=_default_model,
                instruction="(Use arrow keys to select, Enter to confirm)",
            ).ask()

            if selected_model_key is None:  # User cancelled
                return None

            if selected_model_key == _AUTO_MODEL:
                config["aws"]["selected_model"] = None
                # Profile is known; use its destination regions instead of wildcard
                profile_dest_regions = get_all_destination_regions_for_profile(selected_profile)
                config["aws"]["allowed_bedrock_regions"] = profile_dest_regions if profile_dest_regions else ["*"]
                console.print("[green]✓[/green] Auto-select: Claude Code will choose the model automatically")
            else:
                model_id = get_model_id_for_profile(selected_model_key, selected_profile)
                config["aws"]["selected_model"] = model_id
                console.print(f"[green]✓[/green] Model: {CLAUDE_MODELS[selected_model_key]['name']}")

                destination_regions = get_destination_regions_for_model_profile(selected_model_key, selected_profile)
                if not destination_regions:
                    console.print(
                        f"[red]Error:[/red] No destination regions configured for {selected_model_key} "
                        f"with {selected_profile} profile"
                    )
                    raise ValueError("No destination regions configured for model/profile combination")
                config["aws"]["allowed_bedrock_regions"] = destination_regions

            # Q4-Q6: Default tier models (per-tier Auto-select = don't set that env var)
            _AUTO_TIER = "__auto__"
            tier_config_keys = {
                "opus": "default_opus_model",
                "sonnet": "default_sonnet_model",
                "haiku": "default_haiku_model",
            }
            for tier in ["opus", "sonnet", "haiku"]:
                tier_models = get_models_for_tier(tier, selected_profile)
                if not tier_models:
                    config["aws"][tier_config_keys[tier]] = None
                    continue

                tc: list[questionary.Choice] = [
                    questionary.Choice(
                        f"Auto-select — don't set ANTHROPIC_DEFAULT_{tier.upper()}_MODEL",
                        value=_AUTO_TIER,
                    )
                ]
                for mk, display_name, _mid in reversed(tier_models):
                    tc.append(questionary.Choice(display_name, value=mk))

                _saved_key = saved_tier_keys[tier]
                _default_t = next((c for c in tc if c.value == (_saved_key or _AUTO_TIER)), tc[0])
                chosen = questionary.select(
                    f"Select default {tier.capitalize()} model:",
                    choices=tc,
                    default=_default_t,
                    instruction="(Use arrow keys to select, Enter to confirm)",
                ).ask()

                if chosen is None:  # User cancelled
                    return None

                if chosen == _AUTO_TIER:
                    config["aws"][tier_config_keys[tier]] = None
                    console.print(f"[green]✓[/green] Default {tier}: Auto-select")
                else:
                    tier_model_id = get_model_id_for_profile(chosen, selected_profile)
                    config["aws"][tier_config_keys[tier]] = tier_model_id
                    console.print(f"[green]✓[/green] Default {tier}: {CLAUDE_MODELS[chosen]['name']}")

            # Save progress
            progress.save_step("bedrock_complete", config)

        return config

    def _review_configuration(self, config: dict[str, Any]) -> bool:
        """Review configuration with user."""
        console = Console()

        console.print("\n[bold blue]Step 4: Review Configuration[/bold blue]")
        console.print("─" * 30)

        # Create a nice table using Rich
        table = Table(title="Configuration Summary", box=box.ROUNDED, show_header=True, header_style="bold cyan")

        table.add_column("Setting", style="white", no_wrap=True)
        table.add_column("Value", style="green")

        table.add_row("OIDC Provider", config["okta"]["domain"])
        table.add_row(
            "OIDC Client ID",
            (
                config["okta"]["client_id"][:20] + "..."
                if len(config["okta"]["client_id"]) > 20
                else config["okta"]["client_id"]
            ),
        )
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
            table.add_row(
                "Analytics Pipeline", "✓ Enabled" if config.get("analytics", {}).get("enabled", True) else "✗ Disabled"
            )

        # Show VPC config if monitoring is enabled
        if config.get("monitoring", {}).get("enabled"):
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
        model_display = {
            "global.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (Global)",
            "us.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6",
            "eu.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (EU)",
            "au.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (AU)",
            "us.anthropic.claude-opus-4-1-20250805-v1:0": "Claude Opus 4.1",
            "us.anthropic.claude-opus-4-20250514-v1:0": "Claude Opus 4",
            "us.anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
            "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude Sonnet 4",
        }
        if selected_model:
            table.add_row("Claude Model", model_display.get(selected_model, selected_model))

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

        console.print(table)

        # Show what will be created
        console.print("\n[bold yellow]Resources to be created:[/bold yellow]")
        if config.get("federation_type") == "direct":
            console.print("• IAM OIDC Provider for authentication")
        else:
            console.print("• Cognito Identity Pool for authentication")
        console.print("• IAM roles and policies for Bedrock access")
        if config.get("monitoring", {}).get("enabled"):
            console.print("• CloudWatch dashboards for usage monitoring")
            console.print("• OpenTelemetry collector for metrics aggregation")
            console.print("• ECS cluster and load balancer for collector")
            if config.get("analytics", {}).get("enabled", True):
                console.print("• Kinesis Firehose for analytics data streaming")
                console.print("• S3 bucket for analytics data storage")
                console.print("• Glue catalog and Athena tables for analytics")
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
                console.print(f"• IdP authentication: {idp_provider.upper() if idp_provider else 'configured'}")
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

        Args:
            config_data: Configuration data to save
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

        profile = Profile(
            name=profile_name,
            provider_domain=config_data["okta"]["domain"],
            client_id=config_data["okta"]["client_id"],
            credential_storage=config_data.get("credential_storage", "session"),
            aws_region=config_data["aws"]["region"],
            identity_pool_name=config_data["aws"]["identity_pool_name"],
            stack_names=config_data["aws"]["stacks"],
            monitoring_enabled=config_data["monitoring"]["enabled"],
            monitoring_config=monitoring_config,
            analytics_enabled=(
                config_data.get("analytics", {}).get("enabled", True)
                if config_data.get("monitoring", {}).get("enabled")
                else False
            ),
            allowed_bedrock_regions=config_data["aws"]["allowed_bedrock_regions"],
            cross_region_profile=config_data["aws"].get("cross_region_profile", "us"),
            selected_model=config_data["aws"].get("selected_model"),
            selected_source_region=config_data["aws"].get("selected_source_region"),
            default_opus_model=config_data["aws"].get("default_opus_model"),
            default_sonnet_model=config_data["aws"].get("default_sonnet_model"),
            default_haiku_model=config_data["aws"].get("default_haiku_model"),
            provider_type=config_data.get("provider_type"),
            cognito_user_pool_id=config_data.get("cognito_user_pool_id"),
            keycloak_thumbprint=config_data.get("keycloak_thumbprint"),
            federation_type=config_data.get("federation_type", "cognito"),
            max_session_duration=config_data.get("max_session_duration", 28800),
            enable_codebuild=config_data.get("codebuild", {}).get("enabled", False),
            enable_distribution=config_data.get("distribution", {}).get("enabled", False),
            distribution_type=config_data.get("distribution", {}).get("type"),
            distribution_idp_provider=config_data.get("distribution", {}).get("idp_provider"),
            distribution_idp_domain=config_data.get("distribution", {}).get("idp_domain"),
            distribution_idp_client_id=config_data.get("distribution", {}).get("idp_client_id"),
            distribution_idp_client_secret_arn=config_data.get("distribution", {}).get("idp_client_secret_arn"),
            distribution_custom_domain=config_data.get("distribution", {}).get("custom_domain"),
            distribution_hosted_zone_id=config_data.get("distribution", {}).get("hosted_zone_id"),
            quota_monitoring_enabled=(
                config_data.get("quota", {}).get("enabled", False)
                if config_data.get("monitoring", {}).get("enabled")
                else False
            ),
            monthly_token_limit=config_data.get("quota", {}).get("monthly_limit", 300000000),
            warning_threshold_80=config_data.get("quota", {}).get("warning_threshold_80", 240000000),
            warning_threshold_90=config_data.get("quota", {}).get("warning_threshold_90", 270000000),
            daily_token_limit=config_data.get("quota", {}).get("daily_limit"),
            burst_buffer_percent=config_data.get("quota", {}).get("burst_buffer_percent", 10),
            daily_enforcement_mode=config_data.get("quota", {}).get("daily_enforcement_mode", "alert"),
            monthly_enforcement_mode=config_data.get("quota", {}).get("monthly_enforcement_mode", "block"),
            quota_check_interval=config_data.get("quota", {}).get("check_interval", 30),
        )

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
        try:
            boto3.client("sts").get_caller_identity()
            return True
        except Exception:
            return False

    def _check_python_version(self) -> bool:
        """Check Python version."""
        import sys

        return sys.version_info >= (3, 10)

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
            with open(params_file) as f:
                params = json.load(f)
        else:
            params = []

        # Update with our values
        param_map = {
            "OktaDomain": config["okta"]["domain"],
            "OktaClientId": config["okta"]["client_id"],
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
        with open(params_file, "w") as f:
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
                    "default_opus_model": getattr(profile, "default_opus_model", None),
                    "default_sonnet_model": getattr(profile, "default_sonnet_model", None),
                    "default_haiku_model": getattr(profile, "default_haiku_model", None),
                },
                "monitoring": {
                    "enabled": profile.monitoring_enabled,
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

            # Add Keycloak thumbprint if present
            if hasattr(profile, "keycloak_thumbprint") and profile.keycloak_thumbprint:
                existing_config["keycloak_thumbprint"] = profile.keycloak_thumbprint

            # Add selected model if present
            if hasattr(profile, "selected_model") and profile.selected_model:
                existing_config["aws"]["selected_model"] = profile.selected_model

            # Add cross-region profile (None is valid and means auto-select)
            existing_config["aws"]["cross_region_profile"] = getattr(profile, "cross_region_profile", None)

            # Add CodeBuild configuration if present
            if hasattr(profile, "enable_codebuild"):
                existing_config["codebuild"] = {"enabled": profile.enable_codebuild}

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
                }

            # Add quota monitoring configuration if present
            if hasattr(profile, "quota_monitoring_enabled"):
                monthly_tokens = getattr(profile, "monthly_token_limit", 225000000)
                existing_config["quota"] = {
                    "enabled": profile.quota_monitoring_enabled,
                    "monthly_limit": monthly_tokens,
                    "monthly_limit_millions": monthly_tokens // 1000000,
                    "warning_threshold_80": getattr(profile, "warning_threshold_80", 0),
                    "warning_threshold_90": getattr(profile, "warning_threshold_90", 0),
                    "burst_buffer_percent": getattr(profile, "burst_buffer_percent", 10),
                    "daily_limit": getattr(profile, "daily_token_limit", None),
                    "daily_enforcement_mode": getattr(profile, "daily_enforcement_mode", "alert"),
                    "monthly_enforcement_mode": getattr(profile, "monthly_enforcement_mode", "block"),
                    "check_interval": getattr(profile, "quota_check_interval", 30),
                }

            # Add analytics configuration if present
            if hasattr(profile, "analytics_enabled"):
                existing_config["analytics"] = {"enabled": profile.analytics_enabled}

            # Add selected source region if present
            if hasattr(profile, "selected_source_region") and profile.selected_source_region:
                existing_config["aws"]["selected_source_region"] = profile.selected_source_region

            return existing_config

        except Exception:
            return None

    def _show_existing_deployment(self, config: dict[str, Any]) -> None:
        """Show summary of existing deployment."""
        console = Console()

        console.print(f"• OIDC Provider: [cyan]{config['okta']['domain']}[/cyan]")

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
            model_names = {
                "global.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (Global)",
                "us.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6",
                "eu.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (EU)",
                "au.anthropic.claude-opus-4-6-v1": "Claude Opus 4.6 (AU)",
                "us.anthropic.claude-opus-4-1-20250805-v1:0": "Claude Opus 4.1",
                "us.anthropic.claude-opus-4-20250514-v1:0": "Claude Opus 4",
                "us.anthropic.claude-3-7-sonnet-20250219-v1:0": "Claude 3.7 Sonnet",
                "us.anthropic.claude-sonnet-4-20250514-v1:0": "Claude Sonnet 4",
            }
            console.print(f"• Claude Model: [cyan]{model_names.get(selected_model, selected_model)}[/cyan]")

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

    def _get_hosted_zones(self) -> list[dict[str, Any]]:
        """Get available Route53 hosted zones."""
        try:
            import boto3

            client = boto3.client("route53")
            response = client.list_hosted_zones()
            return response.get("HostedZones", [])
        except Exception:
            return []

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
                    "[red]Invalid profile name.[/red] " "Must be alphanumeric with hyphens only, max 64 characters.\n"
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
