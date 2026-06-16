# ABOUTME: Deploy command for AWS infrastructure stacks using boto3
# ABOUTME: Handles deployment of auth, monitoring, and dashboard stacks

"""Deploy command - Deploy AWS infrastructure using boto3."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import argument, option
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.cli.utils.cf_exceptions import (
    CloudFormationError,
    ResourceConflictError,
    StackRollbackError,
)
from claude_code_with_bedrock.cli.utils.cloudformation import CloudFormationManager
from claude_code_with_bedrock.config import Config

# Azure tenant ID GUID pattern — matches UUIDs in various URL formats:
#   login.microsoftonline.com/{tenant-id}/v2.0
#   https://login.microsoftonline.com/{tenant-id}
#   {tenant-id} (bare GUID)
_AZURE_GUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _extract_azure_tenant_id(domain: str) -> str:
    """Extract Azure AD tenant GUID from provider domain or URL.

    Supports: full URLs, domain/tenant/v2.0, or bare GUIDs.
    Returns the bare GUID, or the original input if no GUID found.
    """
    match = _AZURE_GUID_PATTERN.search(domain)
    return match.group(0) if match else domain


class DeployCommand(Command):
    name = "deploy"
    description = "Deploy AWS infrastructure (auth, monitoring, dashboards)"

    arguments = [
        argument(
            "stack",
            description="Specific stack (auth/networking/monitoring/dashboard/analytics/quota/persona/budgets)",
            optional=True,
        )
    ]

    options = [
        option(
            "profile", description="Configuration profile to use (defaults to active profile)", flag=False, default=None
        ),
        option("dry-run", description="Show what would be deployed without executing", flag=True),
        option("show-commands", description="Show AWS CLI commands instead of executing", flag=True),
    ]

    def handle(self) -> int:
        """Execute the deploy command."""
        console = Console()

        # Welcome
        console.print(
            Panel.fit(
                "[bold cyan]Claude Code Infrastructure Deployment[/bold cyan]\n\n"
                "Deploy or update CloudFormation stacks",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Load configuration
        config = Config.load()

        # Get profile name (use active profile if not specified)
        profile_name = self.option("profile")
        if not profile_name:
            profile_name = config.active_profile
            console.print(f"[dim]Using active profile: {profile_name}[/dim]\n")
        else:
            console.print(f"[dim]Using profile: {profile_name}[/dim]\n")

        profile = config.get_profile(profile_name)

        if not profile:
            if profile_name:
                console.print(f"[red]Profile '{profile_name}' not found. Run 'poetry run ccwb init' first.[/red]")
            else:
                console.print(
                    "[red]No active profile set. Run 'poetry run ccwb init' or "
                    "'poetry run ccwb context use <profile>' first.[/red]"
                )
            return 1

        # Get deployment options
        stack_arg = self.argument("stack")
        dry_run = self.option("dry-run")
        show_commands = self.option("show-commands")

        # Determine which stacks to deploy
        stacks_to_deploy = []

        if stack_arg:
            # Deploy specific stack
            if stack_arg == "auth":
                if not getattr(profile, "sso_enabled", True):
                    console.print("[yellow]SSO authentication is disabled in your configuration.[/yellow]")
                    console.print("Enable it by running: [cyan]poetry run ccwb init[/cyan]")
                    return 1
                stacks_to_deploy.append(("auth", "Authentication Stack (Cognito + IAM)"))
            elif stack_arg == "networking":
                if profile.monitoring_enabled:
                    stacks_to_deploy.append(("networking", "VPC Networking for OTEL Collector"))
                else:
                    console.print("[yellow]Monitoring is not enabled in your configuration.[/yellow]")
                    return 1
            elif stack_arg == "monitoring":
                if profile.monitoring_enabled:
                    stacks_to_deploy.append(("monitoring", "OpenTelemetry Collector"))
                else:
                    console.print("[yellow]Monitoring is not enabled in your configuration.[/yellow]")
                    return 1
            elif stack_arg == "dashboard":
                if profile.monitoring_enabled:
                    stacks_to_deploy.append(("dashboard", "CloudWatch Dashboard"))
                else:
                    console.print("[yellow]Monitoring is not enabled in your configuration.[/yellow]")
                    return 1
            elif stack_arg == "cowork-dashboard":
                if not profile.monitoring_enabled:
                    console.print("[yellow]Monitoring is not enabled in your configuration.[/yellow]")
                    return 1
                if getattr(profile, "monitoring_mode", "central") == "sidecar":
                    console.print(
                        "[yellow]CoWork dashboard requires central monitoring mode "
                        "(Cowork cannot export telemetry in sidecar mode).[/yellow]"
                    )
                    return 1
                stacks_to_deploy.append(("cowork-dashboard", "CoWork CloudWatch Dashboard"))
            elif stack_arg == "analytics":
                if profile.monitoring_enabled:
                    stacks_to_deploy.append(("analytics", "Analytics Pipeline (Kinesis Firehose + Athena)"))
                else:
                    console.print("[yellow]Analytics requires monitoring to be enabled in your configuration.[/yellow]")
                    return 1
            elif stack_arg == "quota":
                if not getattr(profile, "sso_enabled", True):
                    console.print(
                        "[yellow]Quota monitoring requires SSO authentication "
                        "(per-user JWT tokens) and cannot be deployed when SSO is disabled.[/yellow]"
                    )
                    console.print(
                        "[dim]See issue #454. Re-run 'ccwb init' with SSO enabled to use quota monitoring.[/dim]"
                    )
                    return 1
                if profile.monitoring_enabled:
                    if getattr(profile, "quota_monitoring_enabled", False):
                        stacks_to_deploy.append(("quota", "Quota Monitoring (Per-User Token Limits)"))
                    else:
                        console.print("[yellow]Quota monitoring is not enabled in your configuration.[/yellow]")
                        return 1
                else:
                    console.print(
                        "[yellow]Quota monitoring requires monitoring to be enabled in your configuration.[/yellow]"
                    )
                    return 1
            elif stack_arg in ("persona", "budgets"):
                # Persona-based access + per-persona budgets. Both require OIDC
                # (group claims drive role selection) and at least one persona.
                if profile.effective_auth_type != "oidc":
                    console.print(
                        "[yellow]Persona-based access requires OIDC authentication "
                        "(group claims) and cannot be deployed for auth type "
                        f"'{profile.effective_auth_type}'.[/yellow]"
                    )
                    console.print("[dim]See quota-requires-oidc.md. Re-run 'ccwb init' with an OIDC provider.[/dim]")
                    return 1
                if not getattr(profile, "personas", []):
                    console.print("[yellow]No personas are configured in this profile.[/yellow]")
                    console.print("[dim]Re-run 'ccwb init' to define personas.[/dim]")
                    return 1
                if stack_arg == "persona":
                    stacks_to_deploy.append(("persona", "Persona-Based Access Control (IAM roles + policies)"))
                else:
                    stacks_to_deploy.append(("budgets", "Per-Persona Cost Budgets"))
            elif stack_arg == "distribution":
                if profile.enable_distribution:
                    stacks_to_deploy.append(("distribution", "Distribution infrastructure (S3 + IAM)"))
                else:
                    console.print("[yellow]Distribution features not enabled in profile.[/yellow]")
                    console.print("Run 'poetry run ccwb init' and enable distribution features.")
                    return 1
            elif stack_arg == "codebuild":
                if profile.enable_codebuild:
                    stacks_to_deploy.append(("codebuild", "CodeBuild for Windows binary builds"))
                else:
                    console.print("[yellow]CodeBuild is not enabled in your configuration.[/yellow]")
                    return 1
            else:
                console.print(f"[red]Unknown stack: {stack_arg}[/red]")
                console.print(
                    "Valid stacks: auth, distribution, networking, monitoring, dashboard, "
                    "cowork-dashboard, analytics, quota, persona, budgets, codebuild\n"
                )
                console.print("[dim]Tip: Use 'ccwb deploy' without arguments to deploy all enabled stacks.[/dim]")
                console.print("[dim]Use 'ccwb deploy quota' for quota-specific updates or late enablement.[/dim]")
                return 1
        else:
            # Deploy all configured stacks in dependency order.
            #
            # Ordering constraints:
            # - auth always comes first (produces the IAM role + OIDC provider
            #   every other stack may reference). Skipped when sso_enabled=False
            #   (anonymous mode).
            # - networking must precede any stack that needs VPC/subnet
            #   outputs: monitoring (OTel ECS ALB) and landing-page
            #   distribution (distribution ALB).
            # - distribution comes after networking to satisfy the
            #   landing-page variant; the presigned-s3 variant doesn't need
            #   networking but scheduling it here is harmless.
            # - dashboard / analytics / quota all follow monitoring.
            # - codebuild is independent and can trail.
            if getattr(profile, "sso_enabled", True):
                stacks_to_deploy.append(("auth", "Authentication Stack (Cognito + IAM)"))

            # Networking first so any downstream stack can read its outputs.
            need_networking = profile.monitoring_enabled or profile.enable_distribution
            if need_networking:
                vpc_config = profile.monitoring_config or {}
                if vpc_config.get("create_vpc", True):
                    stacks_to_deploy.append(("networking", "VPC Networking for OTEL Collector"))

            # Distribution (landing-page reads networking outputs; presigned-s3
            # doesn't, but the scheduling order is a no-op either way).
            if profile.enable_distribution:
                stacks_to_deploy.append(("distribution", "Distribution infrastructure (S3 + IAM)"))

            # Monitoring and its dependents.
            if profile.monitoring_enabled:
                stacks_to_deploy.append(("s3bucket", "S3 Bucket"))
                stacks_to_deploy.append(("monitoring", "OpenTelemetry Collector"))
                stacks_to_deploy.append(("dashboard", "CloudWatch Dashboard"))
                stacks_to_deploy.append(("cowork-dashboard", "CoWork CloudWatch Dashboard"))
                # Check if analytics is enabled (default to True for backward compatibility)
                if getattr(profile, "analytics_enabled", True):
                    stacks_to_deploy.append(("analytics", "Analytics Pipeline (Kinesis Firehose + Athena)"))
                # Check if quota monitoring is enabled
                # Quota enforcement requires SSO — the API Gateway JWT authorizer
                # has no valid issuer URL otherwise. Skip with a warning rather
                # than letting CloudFormation fail mid-deploy (issue #454).
                if getattr(profile, "quota_monitoring_enabled", False):
                    if getattr(profile, "sso_enabled", True):
                        stacks_to_deploy.append(("quota", "Quota Monitoring (Per-User Token Limits)"))
                    else:
                        console.print(
                            "[yellow]⚠ Skipping quota monitoring stack: quota enforcement requires "
                            "SSO authentication (per-user JWT tokens) but SSO is disabled in this profile.[/yellow]"
                        )
                        console.print(
                            "[dim]Re-run 'ccwb init' with SSO enabled to deploy quota monitoring. "
                            "See issue #454.[/dim]"
                        )

            # Persona-based access control + per-persona budgets.
            # Gated on OIDC (group claims drive role selection — quota-requires-oidc.md)
            # and at least one configured persona. Scheduled after auth/quota so the
            # persona stack can import the auth stack's OIDCProviderArn and seed GROUP
            # quota policies into the quota table (stack-ordering.md). The Cognito
            # FederationType skip (no OIDC provider export) happens at deploy time.
            if getattr(profile, "personas", []):
                if profile.effective_auth_type == "oidc":
                    # Single-line append (matches every other append): the destroy-coverage
                    # test detects deployable types via a single-line regex, so keep this on
                    # one line or `persona` becomes invisible to it.
                    stacks_to_deploy.append(("persona", "Persona-Based Access Control (IAM roles + policies)"))
                    stacks_to_deploy.append(("budgets", "Per-Persona Cost Budgets"))
                    # The per-persona dashboard is deployed inline by _deploy_persona_stack
                    # (after seeding), not as a separate scheduled stack — so the persona
                    # metric dimension exists before the dashboard references it (FR-7).
                else:
                    console.print(
                        "[yellow]⚠ Skipping persona stacks: persona-based access requires OIDC "
                        f"authentication (group claims) but auth type is '{profile.effective_auth_type}'.[/yellow]"
                    )
                    console.print("[dim]See quota-requires-oidc.md. Re-run 'ccwb init' with an OIDC provider.[/dim]")

            # Check if CodeBuild is enabled
            if getattr(profile, "enable_codebuild", False):
                stacks_to_deploy.append(("codebuild", "CodeBuild for Windows binary builds"))

        # Initialize CloudFormation manager
        cf_manager = CloudFormationManager(region=profile.aws_region)

        # Show deployment plan
        console.print("\n[bold]Deployment Plan:[/bold]")
        table = Table(box=box.SIMPLE)
        table.add_column("Stack", style="cyan")
        table.add_column("Description")
        table.add_column("Status")

        for stack_type, description in stacks_to_deploy:
            stack_name = profile.stack_names.get(stack_type, f"{profile.identity_pool_name}-{stack_type}")
            status = cf_manager.get_stack_status(stack_name)
            if status and status in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]:
                status_display = "[green]Update[/green]"
            else:
                status_display = "[yellow]Create[/yellow]"
            table.add_row(stack_type, description, status_display)

        console.print(table)

        # Check for orphaned stacks (exist but disabled in config)
        # Only check when deploying ALL stacks, not when deploying a specific stack
        orphaned_stacks = []
        if not stack_arg:  # Only check for orphaned stacks when deploying all stacks
            orphaned_stacks = self._check_orphaned_stacks(stacks_to_deploy, profile, cf_manager, console)

        if orphaned_stacks and not dry_run and not show_commands:
            import questionary

            console.print("\n[yellow]⚠️  Found stacks that exist but are disabled in your configuration:[/yellow]")
            for stack_type, stack_name, status in orphaned_stacks:
                console.print(f"  • {stack_type}: {stack_name} ({status})")

            should_delete = questionary.confirm("Would you like to delete these orphaned stacks?", default=False).ask()

            if should_delete:
                console.print("\n[bold]Cleaning up orphaned stacks...[/bold]\n")
                # Delete in reverse deployment order (dependents first)
                for stack_type, stack_name, _status in reversed(orphaned_stacks):
                    try:
                        console.print(f"[yellow]Deleting {stack_type} stack: {stack_name}...[/yellow]")
                        cf_manager.delete_stack(stack_name)
                        console.print(f"[green]✓ {stack_type} stack deletion initiated[/green]")
                    except Exception as e:
                        console.print(f"[red]✗ Failed to delete {stack_type} stack: {e}[/red]")
                console.print("")

        if dry_run:
            console.print("\n[yellow]Dry run mode - no changes will be made[/yellow]")
            return 0

        if show_commands:
            # Just show the commands that would be executed
            self._show_all_deployment_commands(stacks_to_deploy, profile, console)
            return 0

        # Deploy stacks
        console.print("\n[bold]Deploying stacks...[/bold]\n")

        failed = False
        for stack_type, description in stacks_to_deploy:
            console.print(f"[bold]{description}[/bold]")

            result = self._deploy_stack(stack_type, profile, console, cf_manager)
            if result != 0:
                failed = True
                console.print(f"[red]Failed to deploy {stack_type} stack[/red]")
                break
            console.print("")

        if failed:
            console.print("\n[red]Deployment failed. Check the errors above.[/red]")
            return 1

        # Show summary
        console.print("\n[bold green]Deployment complete![/bold green]")

        console.print("\n[bold]Stack Outputs:[/bold]")
        self._show_stack_outputs(profile, console, config)

        return 0

    def _convert_params_to_boto3(self, params: list) -> list:
        """Convert CLI parameter format to boto3 format.

        From: ["Key1=Value1", "Key2=Value2"]
        To: [{"ParameterKey": "Key1", "ParameterValue": "Value1"}, ...]
        """
        result = []
        for param in params:
            if "=" in param:
                key, value = param.split("=", 1)
                result.append({"ParameterKey": key, "ParameterValue": value})
        return result

    def _deploy_stack(self, stack_type: str, profile, console: Console, cf_manager: CloudFormationManager) -> int:
        """Deploy a CloudFormation stack using boto3."""
        project_root = Path(__file__).parents[4]

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # Common deployment function
            def deploy_with_cf(
                template_path, stack_name, params, capabilities=None, task_description="Deploying stack..."
            ):
                """Helper function to deploy a stack with CloudFormation manager."""
                task = progress.add_task(task_description, total=None)

                try:
                    # Convert parameters to boto3 format
                    boto3_params = self._convert_params_to_boto3(params) if params else None

                    # Deploy stack
                    result = cf_manager.deploy_stack(
                        stack_name=stack_name,
                        template_path=template_path,
                        parameters=boto3_params,
                        capabilities=capabilities or ["CAPABILITY_IAM"],
                        on_event=lambda e: progress.update(
                            task,
                            description=f"{e.get('LogicalResourceId', 'Stack')} - {e.get('ResourceStatus', '')}"
                            if isinstance(e, dict)
                            else str(e),
                        ),
                    )

                    progress.update(task, completed=True)

                    if result.success:
                        console.print(f"[green]✓ {stack_type} stack deployed successfully[/green]")
                        return 0
                    else:
                        console.print(f"[red]✗ Failed to deploy {stack_type} stack: {result.error}[/red]")
                        return 1

                except ResourceConflictError as e:
                    progress.update(task, completed=True)
                    console.print(f"[yellow]Resource conflict: {e.message}[/yellow]")
                    if e.get_cleanup_command():
                        console.print(f"Run: [cyan]{e.get_cleanup_command()}[/cyan]")
                    return 1

                except StackRollbackError as e:
                    progress.update(task, completed=True)
                    console.print(f"[yellow]Stack rollback: {e.message}[/yellow]")
                    console.print(f"Recovery: {e.recovery_action}")
                    return 1

                except CloudFormationError as e:
                    progress.update(task, completed=True)
                    console.print(f"[red]CloudFormation error: {e.message}[/red]")
                    return 1

                except Exception as e:
                    progress.update(task, completed=True)
                    console.print(f"[red]Unexpected error: {str(e)}[/red]")
                    return 1

            # Deploy based on stack type
            if stack_type == "auth":
                # Select template based on provider type
                provider_type = profile.provider_type or "okta"
                template_map = {
                    "okta": "bedrock-auth-okta.yaml",
                    "auth0": "bedrock-auth-auth0.yaml",
                    "azure": "bedrock-auth-azure.yaml",
                    "cognito": "bedrock-auth-cognito-pool.yaml",
                    "google": "bedrock-auth-google.yaml",
                    "generic": "bedrock-auth-generic.yaml",
                }

                template_file = template_map.get(provider_type, "bedrock-auth-okta.yaml")
                template = project_root / "deployment" / "infrastructure" / template_file

                # Verify template exists
                if not template.exists():
                    console.print(f"[red]Error: Template not found: {template_file}[/red]")
                    console.print(f"[yellow]Supported provider types: {', '.join(template_map.keys())}[/yellow]")
                    return 1

                stack_name = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")

                # Build parameters
                params = []
                params.append(f"FederationType={profile.federation_type}")

                if provider_type == "okta":
                    params.extend(
                        [
                            f"OktaDomain={profile.provider_domain}",
                            f"OktaClientId={profile.client_id}",
                        ]
                    )
                elif provider_type == "auth0":
                    params.extend(
                        [
                            f"Auth0Domain={profile.provider_domain}",
                            f"Auth0ClientId={profile.client_id}",
                        ]
                    )
                elif provider_type == "azure":
                    # Azure uses tenant ID (GUID) — extract from provider_domain URL
                    tenant_id = _extract_azure_tenant_id(profile.provider_domain)

                    params.extend(
                        [
                            f"AzureTenantId={tenant_id}",
                            f"AzureClientId={profile.client_id}",
                        ]
                    )
                elif provider_type == "cognito":
                    # Extract domain prefix from full domain
                    # e.g., "us-east-1p8mdr8zxe" from "us-east-1p8mdr8zxe.auth.us-east-1.amazoncognito.com"
                    cognito_domain = (
                        profile.provider_domain.split(".")[0]
                        if "." in profile.provider_domain
                        else profile.provider_domain
                    )
                    params.extend(
                        [
                            f"CognitoUserPoolId={profile.cognito_user_pool_id}",
                            f"CognitoUserPoolClientId={profile.client_id}",
                            f"CognitoUserPoolDomain={cognito_domain}",
                        ]
                    )
                elif provider_type == "google":
                    params.extend(
                        [
                            f"GoogleDomain={profile.provider_domain}",
                            f"GoogleClientId={profile.client_id}",
                        ]
                    )
                elif provider_type == "generic":
                    if not (profile.oidc_issuer_url and profile.oidc_thumbprint):
                        console.print(
                            "[red]Generic OIDC provider requires oidc_issuer_url and oidc_thumbprint."
                            " Re-run `ccwb init` to configure them.[/red]"
                        )
                        return 1
                    params.extend(
                        [
                            f"OidcIssuerUrl={profile.oidc_issuer_url}",
                            f"OidcClientId={profile.client_id}",
                            f"OidcThumbprintList={profile.oidc_thumbprint}",
                        ]
                    )

                # Use profile regions, or fall back to all known Bedrock regions
                bedrock_regions = profile.allowed_bedrock_regions
                if not bedrock_regions:
                    from claude_code_with_bedrock.models import get_all_bedrock_regions
                    bedrock_regions = [r for r in get_all_bedrock_regions() if "gov" not in r]

                params.extend(
                    [
                        f"IdentityPoolName={profile.identity_pool_name}",
                        f"AllowedBedrockRegions={','.join(bedrock_regions)}",
                        f"EnableMonitoring={str(profile.monitoring_enabled).lower()}",
                    ]
                )

                return deploy_with_cf(
                    template,
                    stack_name,
                    params,
                    ["CAPABILITY_NAMED_IAM"],
                    task_description="Deploying authentication stack...",
                )

            elif stack_type == "distribution":
                stack_name = profile.stack_names.get("distribution", f"{profile.identity_pool_name}-distribution")

                # Select template based on distribution type
                if profile.distribution_type == "landing-page":
                    template = project_root / "deployment" / "infrastructure" / "landing-page-distribution.yaml"

                    # Get VPC outputs from networking stack
                    networking_stack_name = profile.stack_names.get(
                        "networking", f"{profile.identity_pool_name}-networking"
                    )
                    networking_outputs = get_stack_outputs(networking_stack_name, profile.aws_region)

                    if not networking_outputs:
                        console.print(
                            "[red]Error: Networking stack outputs not found. Deploy networking stack first.[/red]"
                        )
                        return 1

                    vpc_id = networking_outputs.get("VpcId", "")
                    # Networking stack only has public subnets (SubnetIds), use for both ALB and Lambda
                    subnet_ids = networking_outputs.get("SubnetIds", "")

                    if not vpc_id or not subnet_ids:
                        console.print("[red]Error: Missing required VPC/subnet outputs from networking stack.[/red]")
                        console.print("[yellow]Expected: VpcId, SubnetIds[/yellow]")
                        console.print(f"[yellow]Got: {list(networking_outputs.keys())}[/yellow]")
                        return 1

                    # Use same subnets for both public (ALB) and private (Lambda)
                    public_subnets = subnet_ids
                    private_subnets = subnet_ids

                    # Build parameters for landing page
                    params = [
                        f"IdentityPoolName={profile.identity_pool_name}",
                        f"VpcId={vpc_id}",
                        f"PublicSubnetIds={public_subnets}",
                        f"PrivateSubnetIds={private_subnets}",
                        f"IdPProvider={profile.distribution_idp_provider}",
                    ]

                    # Add IdP-specific parameters
                    if profile.distribution_idp_provider == "okta":
                        params.extend(
                            [
                                f"OktaDomain={profile.distribution_idp_domain}",
                                f"OktaClientId={profile.distribution_idp_client_id}",
                                f"OktaClientSecretArn={profile.distribution_idp_client_secret_arn}",
                            ]
                        )
                    elif profile.distribution_idp_provider == "azure":
                        # Extract tenant ID from domain or use full domain
                        params.extend(
                            [
                                f"AzureTenantId={_extract_azure_tenant_id(profile.distribution_idp_domain or '')}",
                                f"AzureClientId={profile.distribution_idp_client_id}",
                                f"AzureClientSecretArn={profile.distribution_idp_client_secret_arn}",
                            ]
                        )
                    elif profile.distribution_idp_provider == "auth0":
                        params.extend(
                            [
                                f"Auth0Domain={profile.distribution_idp_domain}",
                                f"Auth0ClientId={profile.distribution_idp_client_id}",
                                f"Auth0ClientSecretArn={profile.distribution_idp_client_secret_arn}",
                            ]
                        )
                    elif profile.distribution_idp_provider == "cognito":
                        # Split domain to get user pool ID and domain prefix
                        params.extend(
                            [
                                f"CognitoUserPoolId={profile.cognito_user_pool_id or ''}",
                                f"CognitoUserPoolDomain={profile.distribution_idp_domain}",
                                f"CognitoClientId={profile.distribution_idp_client_id}",
                                f"CognitoClientSecretArn={profile.distribution_idp_client_secret_arn}",
                            ]
                        )

                    # Add optional custom domain parameters
                    if profile.distribution_custom_domain:
                        params.append(f"CustomDomainName={profile.distribution_custom_domain}")
                    if profile.distribution_hosted_zone_id:
                        params.append(f"HostedZoneId={profile.distribution_hosted_zone_id}")

                    # Add deployment timestamp to force custom resource re-execution
                    import datetime

                    deployment_timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    params.append(f"DeploymentTimestamp={deployment_timestamp}")

                    result = deploy_with_cf(
                        template,
                        stack_name,
                        params,
                        ["CAPABILITY_NAMED_IAM"],
                        task_description="Deploying landing page distribution stack...",
                    )

                    # Display outputs for landing page
                    if result == 0:
                        outputs = get_stack_outputs(stack_name, profile.aws_region)
                        console.print("\n[bold green]✓ Landing page deployed successfully![/bold green]")
                        console.print(f"\n[bold]Distribution URL:[/bold] {outputs.get('DistributionURL', 'N/A')}")
                        console.print("\n[bold yellow]⚠️  Configure your IdP web application:[/bold yellow]")
                        console.print(f"   [cyan]Redirect URI:[/cyan] {outputs.get('IdPRedirectURI', 'N/A')}")
                        console.print(
                            "\n   Add this redirect URI to your IdP web application settings "
                            "before users can authenticate."
                        )

                    return result

                else:  # presigned-s3 or legacy
                    template = project_root / "deployment" / "infrastructure" / "presigned-s3-distribution.yaml"
                    params = [f"IdentityPoolName={profile.identity_pool_name}"]
                    return deploy_with_cf(
                        template,
                        stack_name,
                        params,
                        ["CAPABILITY_NAMED_IAM"],
                        task_description="Deploying presigned S3 distribution stack...",
                    )

            elif stack_type == "networking":
                template = project_root / "deployment" / "infrastructure" / "networking.yaml"
                stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
                vpc_config = profile.monitoring_config or {}

                params = [
                    f"VpcCidr={vpc_config.get('vpc_cidr', '10.0.0.0/16')}",
                    f"PublicSubnet1Cidr={vpc_config.get('subnet1_cidr', '10.0.1.0/24')}",
                    f"PublicSubnet2Cidr={vpc_config.get('subnet2_cidr', '10.0.2.0/24')}",
                ]
                return deploy_with_cf(
                    template, stack_name, params, task_description="Deploying networking infrastructure..."
                )

            elif stack_type == "s3bucket":
                template = project_root / "deployment" / "infrastructure" / "s3bucket.yaml"
                stack_name = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
                params = []
                return deploy_with_cf(template, stack_name, params, task_description="Deploying S3 Bucket...")
            elif stack_type == "monitoring":
                # Ensure ECS service linked role exists before deploying
                self._ensure_ecs_service_linked_role(console)

                template = project_root / "deployment" / "infrastructure" / "otel-collector.yaml"
                stack_name = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
                params = []
                vpc_config = profile.monitoring_config or {}

                if not vpc_config.get("create_vpc", True):
                    params.append(f"VpcId={vpc_config.get('vpc_id', '')}")
                    subnet_ids = ",".join(vpc_config.get("subnet_ids", []))
                    params.append(f"SubnetIds={subnet_ids}")
                else:
                    # Get VPC outputs from networking stack
                    networking_stack_name = profile.stack_names.get(
                        "networking", f"{profile.identity_pool_name}-networking"
                    )
                    networking_outputs = get_stack_outputs(networking_stack_name, profile.aws_region)

                    if networking_outputs:
                        vpc_id = networking_outputs.get("VpcId", "")
                        subnet_ids = networking_outputs.get("SubnetIds", "")
                        if vpc_id:
                            params.append(f"VpcId={vpc_id}")
                        if subnet_ids:
                            params.append(f"SubnetIds={subnet_ids}")

                # Add HTTPS domain parameters if configured
                monitoring_config = getattr(profile, "monitoring_config", {})
                if monitoring_config.get("custom_domain"):
                    params.append(f"CustomDomainName={monitoring_config['custom_domain']}")
                    params.append(f"HostedZoneId={monitoring_config['hosted_zone_id']}")
                    # Add OIDC JWT validation parameters for ALB (all IdP types)
                    provider_type = profile.provider_type or ""
                    provider_domain = profile.provider_domain
                    if provider_type and provider_domain:
                        oidc_issuer = ""
                        oidc_jwks = ""
                        if provider_type == "azure":
                            uuid_pat = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
                            tenant_match = re.search(uuid_pat, provider_domain)
                            if tenant_match:
                                tid = tenant_match.group(0)
                                oidc_issuer = f"https://login.microsoftonline.com/{tid}/v2.0"
                                oidc_jwks = f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys"
                        elif provider_type == "okta":
                            # provider_domain is e.g. "company.okta.com"
                            domain = provider_domain.rstrip("/")
                            oidc_issuer = f"https://{domain}/oauth2/default"
                            oidc_jwks = f"https://{domain}/oauth2/default/v1/keys"
                        elif provider_type == "auth0":
                            domain = provider_domain.rstrip("/")
                            oidc_issuer = f"https://{domain}/"
                            oidc_jwks = f"https://{domain}/.well-known/jwks.json"
                        elif provider_type == "cognito":
                            # Cognito issuer uses cognito-idp endpoint, not the hosted UI domain
                            pool_id = getattr(profile, "cognito_user_pool_id", "")
                            if pool_id:
                                # Extract region from pool ID (format: us-east-1_AbCdEfGhI)
                                pool_region = pool_id.split("_")[0] if "_" in pool_id else profile.aws_region
                                oidc_issuer = f"https://cognito-idp.{pool_region}.amazonaws.com/{pool_id}"
                                oidc_jwks = (
                                    f"https://cognito-idp.{pool_region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
                                )
                        if oidc_issuer and oidc_jwks:
                            params.append(f"OidcIssuerUrl={oidc_issuer}")
                            params.append(f"OidcJwksEndpoint={oidc_jwks}")
                            params.append(f"OidcClientId={profile.client_id}")

                # Pass analytics flag to control dual-export (OTLP + EMF)
                analytics_enabled = "true" if getattr(profile, "analytics_enabled", True) else "false"
                params.append(f"EnableAnalytics={analytics_enabled}")

                console.print(f"[dim]Using parameters: {params}[/dim]")
                result = deploy_with_cf(
                    template, stack_name, params, task_description="Deploying monitoring collector..."
                )

                # Save OTel collector endpoint to profile immediately after deploy
                if result == 0:
                    monitoring_outputs = get_stack_outputs(stack_name, profile.aws_region)
                    if monitoring_outputs:
                        endpoint = monitoring_outputs.get("CollectorEndpoint")
                        if endpoint and endpoint != "N/A":
                            profile.otel_collector_endpoint = endpoint
                            try:
                                Config.load().save_profile(profile)
                                console.print(f"[dim]Saved OTel endpoint to profile: {endpoint}[/dim]")
                            except Exception:
                                pass

                return result

            elif stack_type == "dashboard":
                template = project_root / "deployment" / "infrastructure" / "claude-code-dashboard.yaml"
                stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
                params = [f"MetricsRegion={profile.aws_region}"]
                return deploy_with_cf(
                    template, stack_name, params, task_description="Deploying monitoring dashboard..."
                )

            elif stack_type == "cowork-dashboard":
                template = project_root / "deployment" / "infrastructure" / "cowork-dashboard.yaml"
                stack_name = profile.stack_names.get(
                    "cowork-dashboard", f"{profile.identity_pool_name}-cowork-dashboard"
                )
                params = [
                    f"MetricsRegion={profile.aws_region}",
                ]
                return deploy_with_cf(
                    template, stack_name, params, task_description="Deploying CoWork dashboard..."
                )

            elif stack_type == "analytics":
                template = project_root / "deployment" / "infrastructure" / "analytics-pipeline.yaml"
                stack_name = profile.stack_names.get("analytics", f"{profile.identity_pool_name}-analytics")
                params = [
                    f"MetricsLogGroup={profile.metrics_log_group}",
                    f"DataRetentionDays={profile.data_retention_days}",
                    f"FirehoseBufferInterval={profile.firehose_buffer_interval}",
                    f"DebugMode={str(profile.analytics_debug_mode).lower()}",
                ]
                return deploy_with_cf(template, stack_name, params, task_description="Deploying analytics pipeline...")

            elif stack_type == "quota":
                template = project_root / "deployment" / "infrastructure" / "quota-monitoring.yaml"
                stack_name = profile.stack_names.get("quota", f"{profile.identity_pool_name}-quota")

                # Get S3 bucket from s3bucket stack for packaging
                s3_stack = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
                s3_outputs = get_stack_outputs(s3_stack, profile.aws_region)

                if not s3_outputs or not s3_outputs.get("CfnArtifactsBucket"):
                    console.print(f"[red]Could not get S3 bucket from s3bucket stack {s3_stack}[/red]")
                    console.print("[yellow]The s3bucket stack must be deployed first.[/yellow]")
                    console.print("Run: [cyan]ccwb deploy s3bucket[/cyan]")
                    return 1

                s3_bucket = s3_outputs["CfnArtifactsBucket"]

                # Build parameters
                monthly_limit = getattr(profile, "monthly_token_limit", 225000000)
                daily_limit = getattr(profile, "daily_token_limit", None)
                daily_enforcement = getattr(profile, "daily_enforcement_mode", "alert")
                monthly_enforcement = getattr(profile, "monthly_enforcement_mode", "block")
                warning_80 = getattr(profile, "warning_threshold_80", int(monthly_limit * 0.8))
                warning_90 = getattr(profile, "warning_threshold_90", int(monthly_limit * 0.9))

                # Get OIDC configuration for JWT authentication (only when SSO is enabled)
                oidc_issuer_url, oidc_client_id = self._resolve_oidc_config(profile)

                # Pass explicitly so the profile is the source of truth; the CF template
                # default is 'false' to match the opt-in intent of this field.
                enable_finegrained_quotas = profile.enable_finegrained_quotas

                # Sidecar bypass detection: opt-in detective control (default off).
                enable_bypass_detection = getattr(profile, "enable_bypass_detection", False)

                # Persona declared-order for PBAC quota resolution. Empty when no
                # personas are configured, which keeps the Lambdas in legacy
                # most-restrictive mode (D3). When set, the quota Lambdas resolve
                # by the FIRST matching group in this list — matching the
                # credential helper's persona resolution. Wired to the
                # PersonaOrder CFN param / PERSONA_ORDER env var (task #19).
                persona_order = self._compute_persona_order(profile)

                params = [
                    f"MonthlyTokenLimit={monthly_limit}",
                    f"WarningThreshold80={warning_80}",
                    f"WarningThreshold90={warning_90}",
                    f"DailyTokenLimit={daily_limit or 0}",
                    f"DailyEnforcementMode={daily_enforcement}",
                    f"MonthlyEnforcementMode={monthly_enforcement}",
                    f"OidcIssuerUrl={oidc_issuer_url}",
                    f"OidcClientId={oidc_client_id}",
                    f"EnableFinegrainedQuotas={str(enable_finegrained_quotas).lower()}",
                    f"EnableBypassDetection={str(enable_bypass_detection).lower()}",
                    f"PersonaOrder={persona_order}",
                ]

                # Package the template using AWS CLI
                task = progress.add_task("Packaging quota monitoring Lambda functions...", total=None)

                try:
                    # Create temp file for packaged template
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                        packaged_template_path = f.name

                    # Run AWS CLI package command
                    cmd = [
                        "aws",
                        "cloudformation",
                        "package",
                        "--template-file",
                        str(template),
                        "--s3-bucket",
                        s3_bucket,
                        "--s3-prefix",
                        "claude-code/quota",
                        "--output-template-file",
                        packaged_template_path,
                        "--region",
                        profile.aws_region,
                    ]

                    result_pkg = subprocess.run(cmd, capture_output=True, text=True)

                    if result_pkg.returncode != 0:
                        console.print(f"[red]Failed to package template: {result_pkg.stderr}[/red]")
                        return 1

                    progress.update(
                        task, description="Quota monitoring Lambda functions packaged successfully", completed=True
                    )

                    # Deploy the packaged template
                    result = deploy_with_cf(
                        packaged_template_path, stack_name, params, task_description="Deploying quota monitoring..."
                    )

                    # Seed default quota policy on successful deploy
                    if result == 0:
                        self._create_default_quota_policy(profile, stack_name, console)

                    return result

                finally:
                    # Clean up temp file
                    if "packaged_template_path" in locals():
                        try:
                            os.unlink(packaged_template_path)
                        except Exception:
                            pass

            elif stack_type == "persona":
                return self._deploy_persona_stack(profile, console, cf_manager, deploy_with_cf)

            elif stack_type == "budgets":
                return self._deploy_budgets_stack(profile, console, deploy_with_cf)

            elif stack_type == "codebuild":
                # WINDOWS_SERVER_2022_CONTAINER is only available in select regions
                codebuild_supported_regions = [
                    "us-east-1", "us-east-2", "us-west-2",
                    "eu-central-1", "eu-west-1",
                    "ap-northeast-1", "ap-southeast-2",
                    "sa-east-1",
                ]
                if profile.aws_region not in codebuild_supported_regions:
                    console.print(
                        f"[red]Windows CodeBuild is not available in {profile.aws_region}.[/red]\n"
                        f"Supported regions: {', '.join(codebuild_supported_regions)}"
                    )
                    return 1
                template = project_root / "deployment" / "infrastructure" / "codebuild-windows.yaml"
                stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
                params = [f"ProjectNamePrefix={profile.identity_pool_name}"]
                return deploy_with_cf(
                    template, stack_name, params, task_description="Deploying CodeBuild for Windows builds..."
                )

            else:
                console.print(f"[red]Unknown stack type: {stack_type}[/red]")
                return 1

    def _show_all_deployment_commands(self, stacks_to_deploy, profile, console):
        """Show AWS CLI commands that would be executed."""
        console.print("\n[bold]AWS CLI Commands:[/bold]")
        for stack_type, description in stacks_to_deploy:
            console.print(f"\n[dim]# {description}[/dim]")
            self._show_deployment_commands(stack_type, profile, console)

    def _show_deployment_commands(self, stack_type: str, profile, console: Console) -> None:
        """Show AWS CLI commands for manual deployment."""
        project_root = Path(__file__).parents[4]
        region = profile.aws_region

        def print_deploy_cmd(template, stack_name, params, capabilities=None):
            caps_str = " ".join(capabilities or ["CAPABILITY_IAM"])
            lines = [
                "aws cloudformation deploy \\",
                f"    --template-file {template} \\",
                f"    --stack-name {stack_name} \\",
            ]
            if params:
                param_str = " \\\n    ".join(params)
                lines.append(f"    --parameter-overrides {param_str} \\")
            lines.append(f"    --capabilities {caps_str} \\")
            lines.append(f"    --region {region}")
            console.print("\n[cyan]" + "\n".join(lines) + "[/cyan]")

        if stack_type == "auth":
            bedrock_regions = profile.allowed_bedrock_regions
            if not bedrock_regions:
                from claude_code_with_bedrock.models import get_all_bedrock_regions
                bedrock_regions = [r for r in get_all_bedrock_regions() if "gov" not in r]

            stack_name = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")
            auth_type = getattr(profile, "auth_type", "oidc" if getattr(profile, "sso_enabled", True) else "none")

            if auth_type == "idc":
                template = project_root / "deployment" / "infrastructure" / "bedrock-auth-idc.yaml"
                idc_role_name = getattr(profile, "idc_permission_set_name", None) or "BedrockIDCFederatedRole"
                params = [
                    f"FederatedRoleName={idc_role_name}",
                    f"IdentityPoolName={profile.identity_pool_name}",
                    f"AllowedBedrockRegions={','.join(bedrock_regions)}",
                    f"EnableMonitoring={str(profile.monitoring_enabled).lower()}",
                ]
                print_deploy_cmd(template, stack_name, params, ["CAPABILITY_NAMED_IAM"])
            else:
                provider_type = profile.provider_type or "okta"
                template_map = {
                    "okta": "bedrock-auth-okta.yaml",
                    "auth0": "bedrock-auth-auth0.yaml",
                    "azure": "bedrock-auth-azure.yaml",
                    "cognito": "bedrock-auth-cognito-pool.yaml",
                    "google": "bedrock-auth-google.yaml",
                    "generic": "bedrock-auth-generic.yaml",
                }
                template_file = template_map.get(provider_type, "bedrock-auth-okta.yaml")
                template = project_root / "deployment" / "infrastructure" / template_file
                params = [f"FederationType={profile.federation_type}"]
                if provider_type == "okta":
                    params.extend([f"OktaDomain={profile.provider_domain}", f"OktaClientId={profile.client_id}"])
                elif provider_type == "auth0":
                    params.extend([f"Auth0Domain={profile.provider_domain}", f"Auth0ClientId={profile.client_id}"])
                elif provider_type == "azure":
                    tenant_id = _extract_azure_tenant_id(profile.provider_domain)
                    params.extend([f"AzureTenantId={tenant_id}", f"AzureClientId={profile.client_id}"])
                elif provider_type == "cognito":
                    cognito_domain = (
                        profile.provider_domain.split(".")[0]
                        if "." in profile.provider_domain
                        else profile.provider_domain
                    )
                    params.extend([
                        f"CognitoUserPoolId={profile.cognito_user_pool_id}",
                        f"CognitoUserPoolClientId={profile.client_id}",
                        f"CognitoUserPoolDomain={cognito_domain}",
                    ])
                params.extend([
                    f"IdentityPoolName={profile.identity_pool_name}",
                    f"AllowedBedrockRegions={','.join(bedrock_regions)}",
                    f"EnableMonitoring={str(profile.monitoring_enabled).lower()}",
                ])
                print_deploy_cmd(template, stack_name, params, ["CAPABILITY_NAMED_IAM"])

        elif stack_type == "networking":
            template = project_root / "deployment" / "infrastructure" / "networking.yaml"
            stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
            vpc_config = profile.monitoring_config or {}
            params = [
                f"VpcCidr={vpc_config.get('vpc_cidr', '10.0.0.0/16')}",
                f"PublicSubnet1Cidr={vpc_config.get('subnet1_cidr', '10.0.1.0/24')}",
                f"PublicSubnet2Cidr={vpc_config.get('subnet2_cidr', '10.0.2.0/24')}",
            ]
            print_deploy_cmd(template, stack_name, params)

        elif stack_type == "s3bucket":
            template = project_root / "deployment" / "infrastructure" / "s3bucket.yaml"
            stack_name = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
            print_deploy_cmd(template, stack_name, [])

        elif stack_type == "monitoring":
            template = project_root / "deployment" / "infrastructure" / "otel-collector.yaml"
            stack_name = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
            console.print("[dim]  Note: VpcId/SubnetIds are resolved from the networking stack at deploy time[/dim]")
            params = ["VpcId=<from-networking-stack>", "SubnetIds=<from-networking-stack>"]
            monitoring_config = getattr(profile, "monitoring_config", {})
            if monitoring_config.get("custom_domain"):
                params.append(f"CustomDomainName={monitoring_config['custom_domain']}")
                params.append(f"HostedZoneId={monitoring_config.get('hosted_zone_id', '<hosted-zone-id>')}")
            print_deploy_cmd(template, stack_name, params)

        elif stack_type == "dashboard":
            template = project_root / "deployment" / "infrastructure" / "claude-code-dashboard.yaml"
            stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
            s3_stack = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
            console.print(
                f"\n[cyan]# Step 1: Package Lambda functions\n"
                f"aws cloudformation package \\\n"
                f"    --template-file {template} \\\n"
                f"    --s3-bucket <CfnArtifactsBucket from {s3_stack}> \\\n"
                f"    --s3-prefix claude-code/dashboard \\\n"
                f"    --output-template-file /tmp/claude-code-dashboard-packaged.yaml \\\n"
                f"    --region {region}[/cyan]"
            )
            console.print("\n[dim]# Step 2: Deploy packaged template[/dim]")
            print_deploy_cmd(
                "/tmp/claude-code-dashboard-packaged.yaml",
                stack_name,
                [f"MetricsRegion={region}"],
            )

        elif stack_type == "cowork-dashboard":
            template = project_root / "deployment" / "infrastructure" / "cowork-dashboard.yaml"
            stack_name = profile.stack_names.get("cowork-dashboard", f"{profile.identity_pool_name}-cowork-dashboard")
            params = [
                f"MetricsRegion={region}",
            ]
            print_deploy_cmd(template, stack_name, params)

        elif stack_type == "analytics":
            template = project_root / "deployment" / "infrastructure" / "analytics-pipeline.yaml"
            stack_name = profile.stack_names.get("analytics", f"{profile.identity_pool_name}-analytics")
            params = [
                f"MetricsLogGroup={profile.metrics_log_group}",
                f"DataRetentionDays={profile.data_retention_days}",
                f"FirehoseBufferInterval={profile.firehose_buffer_interval}",
                f"DebugMode={str(profile.analytics_debug_mode).lower()}",
            ]
            print_deploy_cmd(template, stack_name, params)

        elif stack_type == "quota":
            template = project_root / "deployment" / "infrastructure" / "quota-monitoring.yaml"
            stack_name = profile.stack_names.get("quota", f"{profile.identity_pool_name}-quota")
            s3_stack = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
            console.print(
                f"\n[cyan]# Step 1: Package Lambda functions\n"
                f"aws cloudformation package \\\n"
                f"    --template-file {template} \\\n"
                f"    --s3-bucket <CfnArtifactsBucket from {s3_stack}> \\\n"
                f"    --s3-prefix claude-code/quota \\\n"
                f"    --output-template-file /tmp/quota-monitoring-packaged.yaml \\\n"
                f"    --region {region}[/cyan]"
            )
            console.print("\n[dim]# Step 2: Deploy packaged template[/dim]")
            monthly_limit = getattr(profile, "monthly_token_limit", 225000000)
            daily_limit = getattr(profile, "daily_token_limit", None)
            params = [
                f"MonthlyTokenLimit={monthly_limit}",
                f"WarningThreshold80={getattr(profile, 'warning_threshold_80', int(monthly_limit * 0.8))}",
                f"WarningThreshold90={getattr(profile, 'warning_threshold_90', int(monthly_limit * 0.9))}",
                f"DailyTokenLimit={daily_limit or 0}",
                f"DailyEnforcementMode={getattr(profile, 'daily_enforcement_mode', 'alert')}",
                f"MonthlyEnforcementMode={getattr(profile, 'monthly_enforcement_mode', 'block')}",
                f"OidcIssuerUrl={profile.provider_domain}",
                f"OidcClientId={profile.client_id}",
                f"EnableFinegrainedQuotas={str(profile.enable_finegrained_quotas).lower()}",
                f"EnableBypassDetection={str(getattr(profile, 'enable_bypass_detection', False)).lower()}",
            ]
            print_deploy_cmd("/tmp/quota-monitoring-packaged.yaml", stack_name, params)

        elif stack_type == "codebuild":
            template = project_root / "deployment" / "infrastructure" / "codebuild-windows.yaml"
            stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
            params = [f"ProjectNamePrefix={profile.identity_pool_name}"]
            print_deploy_cmd(template, stack_name, params)

        elif stack_type == "distribution":
            stack_name = profile.stack_names.get("distribution", f"{profile.identity_pool_name}-distribution")
            if profile.distribution_type == "landing-page":
                template = project_root / "deployment" / "infrastructure" / "landing-page-distribution.yaml"
                networking_stack = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
                params = [
                    f"IdentityPoolName={profile.identity_pool_name}",
                    f"VpcId=<VpcId from {networking_stack}>",
                    f"PublicSubnetIds=<SubnetIds from {networking_stack}>",
                    f"PrivateSubnetIds=<SubnetIds from {networking_stack}>",
                    f"IdPProvider={profile.distribution_idp_provider}",
                ]
            else:
                template = project_root / "deployment" / "infrastructure" / "presigned-s3-distribution.yaml"
                params = [f"IdentityPoolName={profile.identity_pool_name}"]
            print_deploy_cmd(template, stack_name, params, ["CAPABILITY_NAMED_IAM"])

        else:
            console.print(f"[yellow]  No command template available for stack type: {stack_type}[/yellow]")

    def _show_stack_outputs(self, profile, console: Console, config: Config) -> None:
        """Show outputs from deployed stacks."""
        # Get auth stack outputs
        auth_stack = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")
        outputs = get_stack_outputs(auth_stack, profile.aws_region)

        if outputs:
            console.print("\n[bold]Authentication Stack:[/bold]")
            console.print(f"• Federation Type: [cyan]{outputs.get('FederationType', 'cognito')}[/cyan]")
            if outputs.get("FederationType") == "direct" or outputs.get("DirectSTSRoleArn", "").startswith("arn:"):
                console.print(f"• Direct STS Role ARN: [cyan]{outputs.get('DirectSTSRoleArn', 'N/A')}[/cyan]")
            if outputs.get("IdentityPoolId"):
                console.print(f"• Identity Pool ID: [cyan]{outputs.get('IdentityPoolId', 'N/A')}[/cyan]")
            # FederatedRoleArn is the new output name from split templates
            role_arn = outputs.get("FederatedRoleArn") or outputs.get("BedrockRoleArn", "N/A")
            console.print(f"• Role ARN: [cyan]{role_arn}[/cyan]")
            console.print(f"• OIDC Provider: [cyan]{outputs.get('OIDCProviderArn', 'N/A')}[/cyan]")

            # Save federated_role_arn to profile for direct STS federation
            direct_sts_role = outputs.get("DirectSTSRoleArn")
            if direct_sts_role and direct_sts_role != "N/A" and direct_sts_role.startswith("arn:"):
                profile.federated_role_arn = direct_sts_role
                config.save_profile(profile)

        # Get networking outputs if enabled
        if profile.monitoring_enabled:
            networking_stack = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
            networking_outputs = get_stack_outputs(networking_stack, profile.aws_region)

            if networking_outputs:
                console.print("\n[bold]Networking Stack:[/bold]")
                vpc_id = networking_outputs.get("VpcId", "N/A")
                subnet_ids = networking_outputs.get("SubnetIds", "N/A")
                console.print(f"• VPC ID: [cyan]{vpc_id}[/cyan]")
                console.print(f"• Subnet IDs: [cyan]{subnet_ids}[/cyan]")

            # Get monitoring stack endpoint
            monitoring_stack = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
            monitoring_outputs = get_stack_outputs(monitoring_stack, profile.aws_region)

            if monitoring_outputs:
                console.print("\n[bold]Monitoring Stack:[/bold]")
                endpoint = monitoring_outputs.get("CollectorEndpoint", "N/A")
                console.print(f"• OTLP Endpoint: [cyan]{endpoint}[/cyan]")

                # Save endpoint to profile so ccwb package doesn't need to read CF outputs
                if endpoint and endpoint != "N/A":
                    profile.otel_collector_endpoint = endpoint
                    config.save_profile(profile)
                    console.print("[dim]  Saved to profile for package generation[/dim]")

            dashboard_stack = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
            dashboard_outputs = get_stack_outputs(dashboard_stack, profile.aws_region)

            if dashboard_outputs:
                console.print("\n[bold]Dashboard Stack:[/bold]")
                dashboard_url = dashboard_outputs.get("DashboardURL", "")
                if dashboard_url:
                    console.print(f"• Dashboard URL: [cyan][link={dashboard_url}]{dashboard_url}[/link][/cyan]")

            # Get quota monitoring stack outputs if enabled
            if profile.quota_monitoring_enabled:
                quota_stack = profile.stack_names.get("quota", f"{profile.identity_pool_name}-quota")
                quota_outputs = get_stack_outputs(quota_stack, profile.aws_region)

                if quota_outputs:
                    console.print("\n[bold]Quota Monitoring Stack:[/bold]")
                    quota_endpoint = quota_outputs.get("QuotaCheckApiEndpoint")
                    console.print(f"• Quota API Endpoint: [cyan]{quota_endpoint or 'N/A'}[/cyan]")
                    console.print(f"• Alert Topic ARN: [cyan]{quota_outputs.get('QuotaAlertTopicArn', 'N/A')}[/cyan]")
                    console.print(f"• User Metrics Table: [cyan]{quota_outputs.get('QuotaTableName', 'N/A')}[/cyan]")
                    console.print(f"• Policies Table: [cyan]{quota_outputs.get('PoliciesTableName', 'N/A')}[/cyan]")

                    # Show configured limits
                    monthly_limit = getattr(profile, "monthly_token_limit", 225000000)
                    monthly_mode = getattr(profile, "monthly_enforcement_mode", "block")
                    daily_limit = getattr(profile, "daily_token_limit", None)
                    daily_mode = getattr(profile, "daily_enforcement_mode", "alert")

                    console.print(f"• Monthly Limit: [cyan]{monthly_limit:,}[/cyan] tokens ({monthly_mode})")
                    if daily_limit:
                        console.print(f"• Daily Limit: [cyan]{daily_limit:,}[/cyan] tokens ({daily_mode})")

                    # Save quota outputs to profile for test command and credential provider
                    if quota_endpoint and quota_endpoint != "N/A":
                        profile.quota_api_endpoint = quota_endpoint
                    if quota_outputs.get("PoliciesTableName"):
                        profile.quota_policies_table = quota_outputs["PoliciesTableName"]
                    if quota_outputs.get("QuotaTableName"):
                        profile.user_quota_metrics_table = quota_outputs["QuotaTableName"]
                    config.save_profile(profile)

    def _create_default_quota_policy(self, profile, quota_stack_name: str, console: Console) -> None:
        """Auto-create default quota policy in DynamoDB after quota stack deployment."""
        try:
            from claude_code_with_bedrock.models import EnforcementMode, PolicyType
            from claude_code_with_bedrock.quota_policies import PolicyAlreadyExistsError, QuotaPolicyManager

            # Get the policies table name from stack outputs
            quota_outputs = get_stack_outputs(quota_stack_name, profile.aws_region)
            if not quota_outputs or not quota_outputs.get("PoliciesTableName"):
                console.print("[yellow]Warning: Could not get policies table name from stack outputs[/yellow]")
                return

            table_name = quota_outputs["PoliciesTableName"]
            manager = QuotaPolicyManager(table_name, profile.aws_region)

            monthly_limit = getattr(profile, "monthly_token_limit", 225000000)
            daily_limit = getattr(profile, "daily_token_limit", None)
            monthly_enforcement = getattr(profile, "monthly_enforcement_mode", "block")

            enforcement_mode = EnforcementMode.BLOCK if monthly_enforcement == "block" else EnforcementMode.ALERT

            try:
                manager.create_policy(
                    policy_type=PolicyType.DEFAULT,
                    identifier="default",
                    monthly_token_limit=monthly_limit,
                    daily_token_limit=daily_limit,
                    enforcement_mode=enforcement_mode,
                )
                console.print(
                    f"[green]Created default quota policy "
                    f"(monthly: {monthly_limit:,} tokens, enforcement: {monthly_enforcement})[/green]"
                )
            except PolicyAlreadyExistsError:
                console.print("[dim]Default quota policy already exists (skipping)[/dim]")

        except Exception as e:
            console.print(f"[yellow]Warning: Could not create default quota policy: {str(e)}[/yellow]")
            console.print("[dim]Run 'ccwb quota set-default' manually to configure quota limits[/dim]")

    def _resolve_issuer_host(self, profile) -> str:
        """Return the OIDC issuer host for the persona trust condition key.

        The persona role's STS trust policy keys on ``<issuer_host>:<groups_claim>``,
        where ``<issuer_host>`` MUST equal the auth stack's registered OIDC-provider
        ``Url`` with ONLY the ``https://`` scheme stripped — preserving every
        provider-specific quirk (issuer-url-format.md):
          - Auth0:  ``company.auth0.com/``                  (trailing slash REQUIRED — the
                    provider is registered as ``https://${Auth0Domain}/``)
          - Azure:  ``login.microsoftonline.com/<tenant>/v2.0`` (no trailing slash)
          - Okta:   ``company.okta.com``                    (bare domain — the provider is
                    registered at ``https://${OktaDomain}``, NOT the /oauth2/default issuer)
          - Google: ``accounts.google.com`` / domain         (bare)
          - Generic:the configured ``oidc_issuer_url``       (scheme-stripped)

        The condition key MUST equal the IAM OIDC-provider ``Url`` each auth
        template registers, scheme-stripped:
          - Okta/Azure/Auth0/Google: the provider is registered from
            ``provider_domain`` (Auth0 with a trailing slash), which is what
            ``_resolve_oidc_config`` returns — so we reuse it for those.
          - Generic OIDC (e.g. Keycloak, PingFederate, **Teleport**): the
            provider is registered as ``Url: !Ref OidcIssuerUrl`` (fed from
            ``profile.oidc_issuer_url``, deploy.py generic branch), which is a
            DISTINCT field from ``provider_domain`` and commonly carries a path
            (``…/realms/<r>``). ``_resolve_oidc_config`` returns
            ``provider_domain`` for generic, so reusing it would emit the WRONG
            condition key and silently hard-deny every generic-provider persona
            user. We therefore derive generic's host from ``oidc_issuer_url``.

        We strip ONLY the scheme. We MUST NOT ``rstrip('/')`` — that drops Auth0's
        required trailing slash and hard-denies Auth0 persona users. Regression:
        see test_deploy_personas (Auth0/Azure/Okta/generic cases).
        """
        # Generic OIDC registers the provider from oidc_issuer_url, NOT
        # provider_domain — match the registered Url exactly (see docstring).
        if getattr(profile, "provider_type", None) == "generic" and getattr(profile, "oidc_issuer_url", None):
            issuer_url = profile.oidc_issuer_url
        else:
            issuer_url, _client_id = self._resolve_oidc_config(profile)
        host = issuer_url
        for scheme in ("https://", "http://"):
            if host.startswith(scheme):
                host = host[len(scheme):]
                break
        # Strip the scheme only — preserve the trailing slash (Auth0) and path
        # suffix (Azure /v2.0, generic /realms/<r>) so the condition key matches
        # the registered OIDC-provider URL exactly.
        return host

    def _deploy_persona_stack(self, profile, console: Console, cf_manager, deploy_with_cf) -> int:
        """Render and deploy the persona-based access stack, then seed group policies + AIPs.

        Steps (spec design.md#2.3, decisions D1/D5/D6/D8):
          1. Gate on OIDC + non-empty personas (defensive; handle() also gates).
          2. Read ``<AuthStack>-FederationType``; if ``cognito`` -> skip + warn (D5).
          3. Read ``<AuthStack>-OIDCProviderArn``; if absent -> clear stack-ordering error.
          4. Render persona YAML and deploy via CloudFormationManager (CAPABILITY_NAMED_IAM).
          5. Seed one GROUP quota policy per persona (D6).
          6. Create tagged Application Inference Profiles per persona (idempotent).
        Returns a process exit code (0 = success).
        """
        # Step 1 — gate (defensive: the scheduler already checks this).
        if profile.effective_auth_type != "oidc" or not getattr(profile, "personas", []):
            console.print("[dim]Skipping persona stack: requires OIDC auth and at least one persona.[/dim]")
            return 0

        # Step 1b — validate the persona definitions BEFORE rendering. config.yaml is
        # hand-editable (spec §4.1), so a bad persona (dup name, missing group, an
        # enforcement_mode typo that would silently downgrade block→alert, etc.) must
        # fail loudly here rather than render silently-wrong infra. The init wizard
        # validates too, but a hand-edited or programmatically-built profile would
        # otherwise bypass that check.
        from claude_code_with_bedrock.persona_validation import validate_personas

        persona_errors = validate_personas(profile.personas, getattr(profile, "fallback_persona", None))
        if persona_errors:
            console.print("[red]Persona configuration is invalid — fix config.yaml before deploying:[/red]")
            for err in persona_errors:
                console.print(f"  [red]•[/red] {err}")
            return 1

        from claude_code_with_bedrock.persona_template import render_personas_stack

        project_root = Path(__file__).parents[4]
        auth_stack = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")

        # Steps 2 & 3 — read auth stack outputs; do not assume they exist.
        auth_outputs = get_stack_outputs(auth_stack, profile.aws_region) or {}

        federation_type = auth_outputs.get("FederationType", getattr(profile, "federation_type", ""))
        if federation_type == "cognito":
            console.print(
                "[yellow]⚠ Skipping persona provisioning: this deployment uses Cognito federation, "
                "which has no OIDC provider for the persona role trust policy.[/yellow]"
            )
            console.print(
                "[dim]Persona-based access requires direct IAM federation (spec D5, FR-2.7). "
                "Personas were not provisioned.[/dim]"
            )
            return 0

        if not auth_outputs.get("OIDCProviderArn"):
            # stack-ordering.md: fail with a clear pointer rather than a CFN ImportValue error.
            console.print(
                f"[red]Could not find OIDCProviderArn output on auth stack '{auth_stack}'.[/red]"
            )
            console.print("[yellow]Deploy the authentication stack first:[/yellow] [cyan]ccwb deploy auth[/cyan]")
            return 1

        # Step 4 — render to a build dir (utf-8 per windows-platform-guards.md) and deploy.
        groups_claim = getattr(profile, "groups_claim_name", "groups") or "groups"
        issuer_host = self._resolve_issuer_host(profile)
        if not issuer_host:
            console.print("[red]Could not resolve the OIDC issuer host for the persona trust policy.[/red]")
            return 1

        try:
            rendered = render_personas_stack(profile.personas, groups_claim, issuer_host)
        except ValueError as e:
            console.print(f"[red]Failed to render persona stack: {e}[/red]")
            return 1

        build_dir = project_root / "build" / "personas"
        build_dir.mkdir(parents=True, exist_ok=True)
        template_path = build_dir / "bedrock-personas.yaml"
        template_path.write_text(rendered, encoding="utf-8")

        bedrock_regions = self._persona_bedrock_regions(profile)
        params = [
            f"AuthStackName={auth_stack}",
            f"AllowedBedrockRegions={','.join(bedrock_regions)}",
        ]
        # Stack-name default uses the "persona" type verbatim so `ccwb destroy`
        # (which derives names as "{identity_pool_name}-{stack_type}") tears it
        # down — keep this in sync with destroy.py's DESTROYABLE_STACKS.
        stack_name = profile.stack_names.get("persona", f"{profile.identity_pool_name}-persona")

        result = deploy_with_cf(
            str(template_path),
            stack_name,
            params,
            ["CAPABILITY_NAMED_IAM"],
            task_description="Deploying persona access stack...",
        )
        if result != 0:
            return result

        # Write each persona's resolved role ARN back into the profile dicts from
        # the stack's {Stem}RoleArn outputs, so `ccwb package` can serialize
        # role_arn per spec §4.2 (the credential helper assumes this exact ARN).
        self._write_back_persona_role_arns(profile, stack_name, console)

        # Steps 5 & 6 — best-effort post-deploy seeding; do not fail the deploy if these hit
        # transient issues (the stack itself is already up).
        self._seed_persona_group_policies(profile, console)
        self._create_persona_inference_profiles(profile, console)
        # Step 7 — deploy the per-persona observability dashboard last, so the
        # `persona` metric dimension exists before the dashboard references it
        # (FR-7). Its own CFN stack; best-effort (won't fail the persona deploy).
        self._deploy_persona_dashboard(profile, console, deploy_with_cf)
        return 0

    def _write_back_persona_role_arns(self, profile, persona_stack_name: str, console: Console) -> None:
        """Populate each persona dict's ``role_arn`` from the persona stack outputs.

        The renderer exports ``{Stem}RoleArn`` per persona where ``Stem`` is the
        sanitized logical-id stem of the persona name. We reuse the renderer's
        ``_logical_id`` so the lookup key cannot drift from what was emitted.
        This mutates ``profile.personas`` in place; ``ccwb package`` reads
        ``role_arn`` off these dicts (spec §4.2). Best-effort: a missing output is
        logged but does not fail the deploy (the role still exists in IAM).
        """
        try:
            from claude_code_with_bedrock.persona_template import _logical_id

            outputs = get_stack_outputs(persona_stack_name, profile.aws_region) or {}
            resolved_any = False
            for persona in profile.personas:
                name = persona.get("name")
                if not name:
                    continue
                output_key = f"{_logical_id(name)}RoleArn"
                role_arn = outputs.get(output_key)
                if role_arn:
                    persona["role_arn"] = role_arn
                    resolved_any = True
                else:
                    console.print(
                        f"[yellow]⚠ No {output_key} output found for persona '{name}'; "
                        "role_arn will be empty in config.json.[/yellow]"
                    )

            # Persist so the NEXT command invocation (`ccwb package`) sees the
            # resolved ARNs — get_profile()/load_profile() return a fresh Profile,
            # so the in-memory mutation above would otherwise be lost. Best-effort.
            if resolved_any:
                try:
                    from claude_code_with_bedrock.config import Config

                    Config.load().save_profile(profile)
                except Exception as save_err:
                    console.print(
                        f"[yellow]Warning: resolved persona role ARNs but could not persist them "
                        f"to the profile ({str(save_err)}). Re-run 'ccwb deploy persona' if "
                        "'ccwb package' shows empty role_arns.[/yellow]"
                    )
        except Exception as e:
            console.print(f"[yellow]Warning: Could not read persona role ARNs from stack outputs: {str(e)}[/yellow]")

    def _compute_persona_order(self, profile) -> str:
        """Comma-separated persona group values in DECLARED order for the quota Lambdas.

        This is the bridge that activates declared-order (PBAC) quota resolution
        (spec D3): the quota Lambdas read it via the ``PERSONA_ORDER`` env var
        (CFN ``PersonaOrder`` param) and let the FIRST matching group win,
        matching the credential helper's persona resolution. Returns an empty
        string when there are no personas or auth isn't OIDC — which keeps the
        Lambdas in legacy most-restrictive mode (the existing behavior for
        non-persona deployments is untouched). Order follows ``profile.personas``
        exactly; groups are de-duplicated while preserving first-seen order.
        """
        if profile.effective_auth_type != "oidc" or not getattr(profile, "personas", []):
            return ""
        ordered_groups: list[str] = []
        for persona in profile.personas:
            group = persona.get("group")
            if group and group not in ordered_groups:
                ordered_groups.append(group)
        return ",".join(ordered_groups)

    def _persona_bedrock_regions(self, profile) -> list:
        """Resolve the allowed Bedrock regions for persona roles (mirrors the auth stack)."""
        bedrock_regions = getattr(profile, "allowed_bedrock_regions", None)
        if not bedrock_regions:
            from claude_code_with_bedrock.models import get_all_bedrock_regions

            bedrock_regions = [r for r in get_all_bedrock_regions() if "gov" not in r]
        return bedrock_regions

    def _seed_persona_group_policies(self, profile, console: Console) -> None:
        """Seed one GROUP quota policy per persona (spec D6).

        A persona's ``group`` value IS the GROUP-policy identifier the quota
        Lambdas already resolve (``POLICY#group#<value>``), so we reuse
        ``QuotaPolicyManager`` verbatim — no new policy type. Requires the quota
        stack (and its policies table) to exist; if it doesn't, we note it and
        move on rather than failing the persona deploy.
        """
        try:
            from claude_code_with_bedrock.models import EnforcementMode, PolicyType
            from claude_code_with_bedrock.quota_policies import PolicyAlreadyExistsError, QuotaPolicyManager

            quota_stack = profile.stack_names.get("quota", f"{profile.identity_pool_name}-quota")
            quota_outputs = get_stack_outputs(quota_stack, profile.aws_region) or {}
            table_name = quota_outputs.get("PoliciesTableName")
            if not table_name:
                console.print(
                    "[yellow]⚠ Skipping persona GROUP quota policies: quota policies table not found "
                    f"(stack '{quota_stack}').[/yellow]"
                )
                console.print("[dim]Deploy quota monitoring first to enforce per-persona token limits.[/dim]")
                return

            manager = QuotaPolicyManager(table_name, profile.aws_region)
            for persona in profile.personas:
                group = persona.get("group")
                if not group:
                    continue
                monthly_limit = persona.get("monthly_token_limit") or getattr(
                    profile, "monthly_token_limit", 225000000
                )
                daily_limit = persona.get("daily_token_limit")
                mode = persona.get("enforcement_mode", "block")
                enforcement_mode = EnforcementMode.BLOCK if mode == "block" else EnforcementMode.ALERT
                try:
                    manager.create_policy(
                        policy_type=PolicyType.GROUP,
                        identifier=group,
                        monthly_token_limit=monthly_limit,
                        daily_token_limit=daily_limit,
                        enforcement_mode=enforcement_mode,
                    )
                    console.print(
                        f"[green]Seeded GROUP quota policy for persona "
                        f"'{persona.get('name', group)}' (group '{group}', monthly: {monthly_limit:,})[/green]"
                    )
                except PolicyAlreadyExistsError:
                    console.print(
                        f"[dim]GROUP quota policy for group '{group}' already exists (skipping)[/dim]"
                    )
        except Exception as e:
            console.print(f"[yellow]Warning: Could not seed persona GROUP quota policies: {str(e)}[/yellow]")
            console.print("[dim]Run 'ccwb quota set-group' manually to configure per-persona limits.[/dim]")

    def _create_persona_inference_profiles(self, profile, console: Console) -> None:
        """Create one tagged Application Inference Profile per persona TIER (FR-5.1).

        Each AIP carries the persona's cost-allocation tags so Bedrock usage is
        attributable per persona, and its ARN is wired into the persona's
        per-tier model routing (read back into ``persona["inference_profile_arns"]``
        so ``ccwb package`` serializes it and the credential helper can emit
        ANTHROPIC_*_MODEL exports). Key properties:

        * **One AIP per ENTITLED tier** (haiku/sonnet/opus the persona may invoke),
          not one AIP per persona — so each tier routes to its own cost-tagged
          profile and a restricted persona only gets profiles it can actually use.
        * **copyFrom a cross-Region (system-defined) inference profile**, NOT a
          single-Region foundation model. AWS requires a CRIS modelSource to
          produce a multi-Region AIP; a foundation-model source would pin the AIP
          to one Region and break Claude Code's CRIS routing.
        * **Partition-aware** source ARNs (aws / aws-us-gov) — fixes the prior
          hardcoded ``arn:aws:`` (region-availability.md, NFR-8 GovCloud).

        Idempotent check-then-create by name; ARNs are read back even when the AIP
        already exists. Any failure here is logged but never fails the deploy (the
        IAM roles — the access-control core — are already in place).
        """
        try:
            import boto3

            from claude_code_with_bedrock.persona_models import (
                aip_name,
                cris_source_arn,
                entitled_tiers,
                partition_for_region,
            )

            client = boto3.client("bedrock", region_name=profile.aws_region)
            region = profile.aws_region
            partition = partition_for_region(region)
            cris_prefix = getattr(profile, "cross_region_profile", None) or "us"

            # Map existing APPLICATION profiles name -> ARN so creation is idempotent
            # AND we can read back the ARN of a profile that already exists.
            existing: dict[str, str] = {}
            try:
                paginator = client.get_paginator("list_inference_profiles")
                for page in paginator.paginate(typeEquals="APPLICATION"):
                    for summary in page.get("inferenceProfileSummaries", []):
                        nm = summary.get("inferenceProfileName")
                        if nm:
                            existing[nm] = summary.get("inferenceProfileArn", "")
            except Exception:
                # Listing is best-effort; if it fails we still attempt create and
                # rely on the per-create try/except to absorb "already exists".
                pass

            resolved_any = False
            for persona in profile.personas:
                name = persona.get("name")
                if not name:
                    continue
                tiers = entitled_tiers(persona)
                if not tiers:
                    console.print(
                        f"[dim]Persona '{name}' is entitled to no model tier; skipping inference profiles.[/dim]"
                    )
                    continue

                cost_tags = persona.get("cost_tags") or {}
                base_tags = [{"key": k, "value": v} for k, v in cost_tags.items()]
                base_tags.append({"key": "Persona", "value": name})

                tier_arns: dict[str, str] = {}
                for tier in tiers:
                    aip = aip_name(profile.identity_pool_name, name, tier)
                    if aip in existing:
                        if existing[aip]:
                            tier_arns[tier] = existing[aip]
                        console.print(f"[dim]Inference profile '{aip}' already exists (reusing)[/dim]")
                        continue

                    source = cris_source_arn(tier, cris_prefix, region, partition)
                    if not source:
                        console.print(
                            f"[dim]No '{tier}' model available for region prefix '{cris_prefix}'; "
                            f"skipping that tier for persona '{name}'.[/dim]"
                        )
                        continue

                    tags = [*base_tags, {"key": "Tier", "value": tier}]
                    # Wrapped so an already-exists / access error never aborts the deploy.
                    try:
                        resp = client.create_inference_profile(
                            inferenceProfileName=aip,
                            description=f"Cost-attribution inference profile for persona {name} ({tier})",
                            modelSource={"copyFrom": source},
                            tags=tags,
                        )
                        arn = resp.get("inferenceProfileArn", "")
                        if arn:
                            tier_arns[tier] = arn
                        console.print(
                            f"[green]Created tagged inference profile '{aip}' for persona '{name}' ({tier})[/green]"
                        )
                    except Exception as create_err:
                        console.print(
                            f"[dim]Inference profile '{aip}' not created "
                            f"({str(create_err).splitlines()[0]}); continuing.[/dim]"
                        )

                # Wire the resolved tier ARNs into the persona dict so `ccwb package`
                # serializes them and the credential helper can route per persona.
                if tier_arns:
                    persona["inference_profile_arns"] = tier_arns
                    resolved_any = True

            # Persist the resolved ARNs so the NEXT command (`ccwb package`) sees
            # them — load_profile() returns a fresh Profile, so the in-memory
            # mutation above would otherwise be lost. Best-effort (mirrors the
            # role-ARN write-back).
            if resolved_any:
                try:
                    from claude_code_with_bedrock.config import Config

                    Config.load().save_profile(profile)
                except Exception as save_err:
                    console.print(
                        f"[yellow]Warning: created persona inference profiles but could not persist their "
                        f"ARNs to the profile ({str(save_err)}). Re-run 'ccwb deploy persona' if "
                        "'ccwb package' shows no per-persona model routing.[/yellow]"
                    )

            # Orphan detection: a persona removed from config.yaml (or a tier it lost)
            # leaves its tagged inference profile behind (create/teardown only iterate
            # CURRENT personas+tiers). Surface it rather than auto-delete — billing/cost
            # resources should not be removed implicitly by a deploy.
            current_names = {
                aip_name(profile.identity_pool_name, p.get("name"), tier)
                for p in profile.personas
                if p.get("name")
                for tier in entitled_tiers(p)
            }
            prefix = f"{profile.identity_pool_name}-"
            orphans = sorted(n for n in existing if n and n.startswith(prefix) and n not in current_names)
            for orphan in orphans:
                console.print(
                    f"[yellow]⚠ Inference profile '{orphan}' has no matching persona/tier in config "
                    "(persona removed or tier access changed?). It is NOT auto-deleted — "
                    "remove it manually if unused:[/yellow]"
                )
                console.print(
                    f"[dim]    aws bedrock delete-inference-profile "
                    f"--inference-profile-identifier '{orphan}' --region {profile.aws_region}[/dim]"
                )
        except Exception as e:
            console.print(f"[yellow]Warning: Could not create persona inference profiles: {str(e)}[/yellow]")
            console.print("[dim]Cost attribution by inference profile is optional; access control is unaffected.[/dim]")

    def _deploy_budgets_stack(self, profile, console: Console, deploy_with_cf) -> int:
        """Render and deploy the per-persona + account budgets stack (spec FR-6, D7).

        Only personas with a ``budget_amount_usd`` produce a budget; an account
        total is added when ``account_budget_amount_usd`` is set. Skips cleanly
        when neither is configured.
        """
        if profile.effective_auth_type != "oidc" or not getattr(profile, "personas", []):
            return 0

        account_budget = getattr(profile, "account_budget_amount_usd", None)
        any_persona_budget = any(p.get("budget_amount_usd") for p in profile.personas)
        if not any_persona_budget and not account_budget:
            console.print("[dim]Skipping budgets stack: no per-persona or account budget configured.[/dim]")
            return 0

        from claude_code_with_bedrock.budgets_template import render_budgets_stack

        project_root = Path(__file__).parents[4]
        try:
            rendered = render_budgets_stack(profile.personas, account_budget)
        except ValueError as e:
            console.print(f"[red]Failed to render budgets stack: {e}[/red]")
            return 1

        build_dir = project_root / "build" / "personas"
        build_dir.mkdir(parents=True, exist_ok=True)
        template_path = build_dir / "bedrock-budgets.yaml"
        template_path.write_text(rendered, encoding="utf-8")

        stack_name = profile.stack_names.get("budgets", f"{profile.identity_pool_name}-budgets")
        return deploy_with_cf(
            str(template_path),
            stack_name,
            None,
            ["CAPABILITY_IAM"],
            task_description="Deploying per-persona budgets...",
        )

    def _deploy_persona_dashboard(self, profile, console: Console, deploy_with_cf) -> int:
        """Deploy the per-persona CloudWatch dashboard (spec FR-7 observability).

        Invoked at the tail of ``_deploy_persona_stack`` (after the persona stack +
        post-deploy seeding) so the ``persona`` metric dimension — emitted by the
        otel-helper (#14) and mapped by the collector (#26) — exists before this
        dashboard references it. The dashboard is its own CloudFormation stack named
        ``{identity_pool_name}-persona-dashboard``; because it is deployed inline by
        the persona flow rather than as a scheduled stack type, ``ccwb destroy`` does
        not list it in DESTROYABLE_STACKS, but ``_check_orphaned_stacks`` still
        surfaces it if it is left behind.

        Uses the committed static template (no render), mirroring the existing
        ``dashboard`` stack-type branch. Best-effort: if the template file is missing
        (e.g. a partial checkout) it logs and skips rather than failing the deploy —
        the dashboard is observability, not access control.

        Returns a process exit code (0 = success or skipped).
        """
        project_root = Path(__file__).parents[4]
        template = project_root / "deployment" / "infrastructure" / "bedrock-personas-dashboard.yaml"
        if not template.exists():
            console.print(
                "[dim]Persona dashboard template not found; skipping dashboard deploy "
                "(observability only — persona access is unaffected).[/dim]"
            )
            return 0

        stack_name = profile.stack_names.get(
            "persona-dashboard", f"{profile.identity_pool_name}-persona-dashboard"
        )
        params = [
            f"DashboardName={profile.identity_pool_name}-personas",
            f"MetricsRegion={profile.aws_region}",
        ]
        return deploy_with_cf(
            str(template),
            stack_name,
            params,
            task_description="Deploying per-persona dashboard...",
        )

    def _check_orphaned_stacks(self, stacks_to_deploy, profile, cf_manager, console: Console) -> list:
        """Check for stacks that exist but are disabled in config.

        Returns:
            List of (stack_type, stack_name, status) tuples for orphaned stacks.
        """
        # All possible stack types
        all_stack_types = {
            "auth": "Authentication Stack",
            "distribution": "Distribution infrastructure",
            "networking": "VPC Networking",
            "monitoring": "OpenTelemetry Collector",
            "dashboard": "CloudWatch Dashboard",
            "cowork-dashboard": "CoWork CloudWatch Dashboard",
            "analytics": "Analytics Pipeline",
            "quota": "Quota Monitoring",
            "persona": "Persona-Based Access Control",
            "budgets": "Per-Persona Cost Budgets",
            "persona-dashboard": "Per-Persona CloudWatch Dashboard",
            "codebuild": "CodeBuild",
        }

        # Stack types that are being deployed
        deploying_types = {stack_type for stack_type, _ in stacks_to_deploy}

        # Check for orphaned stacks
        orphaned = []
        for stack_type in all_stack_types:
            if stack_type not in deploying_types:
                # This stack type is not being deployed - check if it exists
                stack_name = profile.stack_names.get(stack_type, f"{profile.identity_pool_name}-{stack_type}")
                status = cf_manager.get_stack_status(stack_name)

                if status and status not in ["DELETE_COMPLETE", "DELETE_IN_PROGRESS"]:
                    orphaned.append((stack_type, stack_name, status))

        return orphaned

    def _ensure_ecs_service_linked_role(self, console: Console) -> None:
        """Ensure ECS service linked role exists, create if needed."""
        try:
            import boto3

            iam_client = boto3.client("iam")

            # Check if role exists
            try:
                iam_client.get_role(RoleName="AWSServiceRoleForECS")
                console.print("[dim]✓ ECS service linked role exists[/dim]")
            except iam_client.exceptions.NoSuchEntityException:
                # Role doesn't exist, create it
                console.print("[yellow]Creating ECS service linked role...[/yellow]")
                try:
                    iam_client.create_service_linked_role(AWSServiceName="ecs.amazonaws.com")
                    console.print("[green]✓ ECS service linked role created[/green]")
                    # Wait for IAM propagation before proceeding with ECS cluster creation
                    import time
                    console.print("[dim]Waiting for IAM role propagation...[/dim]")
                    time.sleep(10)
                except iam_client.exceptions.InvalidInputException as e:
                    # Role might already exist (race condition)
                    if "has been taken in this account" in str(e):
                        console.print("[dim]✓ ECS service linked role already exists[/dim]")
                    else:
                        raise

        except Exception as e:
            console.print(f"[yellow]Warning: Could not verify ECS service linked role: {str(e)}[/yellow]")
            console.print("[dim]If deployment fails, manually create the role with:[/dim]")
            console.print("[dim]aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com[/dim]")

    def _resolve_oidc_config(self, profile) -> tuple:
        """Resolve OIDC issuer URL and client ID for quota JWT authentication.

        Returns ("", "") when SSO is disabled — the CF template's HasJwtAuth
        condition will disable the JWT authorizer and use an open route instead.
        """
        if not getattr(profile, "sso_enabled", True):
            return "", ""

        if profile.provider_type == "cognito":
            pool_id = getattr(profile, "cognito_user_pool_id", "")
            if not pool_id:
                raise ValueError(
                    "Cognito User Pool ID is required for quota monitoring JWT authentication. "
                    "Please set cognito_user_pool_id in your profile configuration."
                )
            pool_region = pool_id.split("_")[0] if "_" in pool_id else profile.aws_region
            issuer_url = f"https://cognito-idp.{pool_region}.amazonaws.com/{pool_id}"
        else:
            issuer_url = profile.provider_domain
            if issuer_url and not issuer_url.startswith(("http://", "https://")):
                issuer_url = f"https://{issuer_url}"

        # Auth0 tokens include trailing slash in iss claim, so authorizer must match
        if profile.provider_type == "auth0" and issuer_url and not issuer_url.endswith("/"):
            issuer_url += "/"

        return issuer_url, profile.client_id
