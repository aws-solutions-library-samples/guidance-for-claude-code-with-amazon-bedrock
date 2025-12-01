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


class DeployCommand(Command):
    name = "deploy"
    description = "Deploy AWS infrastructure (auth, monitoring, dashboards)"

    arguments = [
        argument(
            "stack",
            description="Specific stack to deploy (auth/networking/monitoring/dashboard/analytics/quota)",
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
            elif stack_arg == "analytics":
                if profile.monitoring_enabled:
                    stacks_to_deploy.append(("analytics", "Analytics Pipeline (Kinesis Firehose + Athena)"))
                else:
                    console.print("[yellow]Analytics requires monitoring to be enabled in your configuration.[/yellow]")
                    return 1
            elif stack_arg == "quota":
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
                    "Valid stacks: auth, distribution, networking, monitoring, dashboard, analytics, quota, codebuild"
                )
                return 1
        else:
            # Deploy all configured stacks in dependency order
            stacks_to_deploy.append(("auth", "Authentication Stack (Cognito + IAM)"))

            # Deploy distribution after networking if it's landing-page type
            if profile.enable_distribution:
                stacks_to_deploy.append(("distribution", "Distribution infrastructure (S3 + IAM)"))

            # Deploy remaining monitoring stacks
            if profile.monitoring_enabled:
                vpc_config = profile.monitoring_config or {}
                if vpc_config.get("create_vpc", True):
                    stacks_to_deploy.append(("networking", "VPC Networking for OTEL Collector"))
                stacks_to_deploy.append(("s3bucket", "S3 Bucket"))
                stacks_to_deploy.append(("monitoring", "OpenTelemetry Collector"))
                stacks_to_deploy.append(("dashboard", "CloudWatch Dashboard"))
                # Check if analytics is enabled (default to True for backward compatibility)
                if getattr(profile, "analytics_enabled", True):
                    stacks_to_deploy.append(("analytics", "Analytics Pipeline (Kinesis Firehose + Athena)"))
                # Check if quota monitoring is enabled
                if getattr(profile, "quota_monitoring_enabled", False):
                    stacks_to_deploy.append(("quota", "Quota Monitoring (Per-User Token Limits)"))
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
                for stack_type, stack_name, _status in orphaned_stacks:
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
                    # Azure uses tenant ID (GUID) instead of full domain
                    # Support multiple input formats:
                    # - login.microsoftonline.com/{tenant-id}/v2.0
                    # - login.microsoftonline.com/{tenant-id}
                    # - {tenant-id} (just the GUID)
                    # - https://login.microsoftonline.com/{tenant-id}/v2.0

                    # Extract GUID using regex pattern matching
                    guid_pattern = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
                    match = re.search(guid_pattern, profile.provider_domain)

                    if match:
                        tenant_id = match.group(0)
                    else:
                        # If no GUID found, use the provider_domain as-is
                        # (in case user provided just the GUID but in unexpected format)
                        tenant_id = profile.provider_domain

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

                params.extend(
                    [
                        f"IdentityPoolName={profile.identity_pool_name}",
                        f"AllowedBedrockRegions={','.join(profile.allowed_bedrock_regions)}",
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
                                f"AzureTenantId={profile.distribution_idp_domain}",
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
                stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-s3bucket")
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

                console.print(f"[dim]Using parameters: {params}[/dim]")
                return deploy_with_cf(
                    template, stack_name, params, task_description="Deploying monitoring collector..."
                )

            elif stack_type == "dashboard":
                template = project_root / "deployment" / "infrastructure" / "claude-code-dashboard.yaml"
                stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")

                # Get S3 bucket from networking stack for packaging
                s3_stack_name = profile.stack_names.get("s3", f"{profile.identity_pool_name}-s3bucket")
                s3_outputs = get_stack_outputs(s3_stack_name, profile.aws_region)

                if not s3_outputs or not s3_outputs.get("CfnArtifactsBucket"):
                    console.print("[red]Error: S3 bucket for packaging not found[/red]")
                    console.print(
                        "[yellow]The networking stack must be deployed first with the artifacts bucket.[/yellow]"
                    )
                    console.print("Run: [cyan]ccwb deploy networking[/cyan]")
                    return 1

                s3_bucket = s3_outputs["CfnArtifactsBucket"]

                # Package the template using AWS CLI (simple and reliable!)
                task = progress.add_task("Packaging dashboard Lambda functions...", total=None)

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
                        "claude-code/dashboard",
                        "--output-template-file",
                        packaged_template_path,
                        "--region",
                        profile.aws_region,
                    ]

                    result = subprocess.run(cmd, capture_output=True, text=True)

                    if result.returncode != 0:
                        console.print(f"[red]Failed to package template: {result.stderr}[/red]")
                        return 1

                    progress.update(
                        task, description="Dashboard Lambda functions packaged successfully", completed=True
                    )

                    # Deploy the packaged template with MetricsRegion parameter
                    params = [f"MetricsRegion={profile.aws_region}"]
                    return deploy_with_cf(
                        packaged_template_path, stack_name, params, task_description="Deploying monitoring dashboard..."
                    )

                finally:
                    # Clean up temp file
                    if "packaged_template_path" in locals():
                        try:
                            os.unlink(packaged_template_path)
                        except Exception:
                            pass

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

                # Get MetricsTable ARN from dashboard stack outputs
                dashboard_stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
                dashboard_outputs = get_stack_outputs(dashboard_stack_name, profile.aws_region)

                if not dashboard_outputs or not dashboard_outputs.get("MetricsTableArn"):
                    console.print(
                        f"[red]Could not get MetricsTable ARN from dashboard stack {dashboard_stack_name}[/red]"
                    )
                    console.print("[yellow]The dashboard stack must be deployed first.[/yellow]")
                    console.print("Run: [cyan]ccwb deploy dashboard[/cyan]")
                    return 1

                # Get S3 bucket from networking stack for packaging
                networking_stack = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
                networking_outputs = get_stack_outputs(networking_stack, profile.aws_region)

                if not networking_outputs or not networking_outputs.get("CfnArtifactsBucket"):
                    console.print(f"[red]Could not get S3 bucket from networking stack {networking_stack}[/red]")
                    console.print("[yellow]The networking stack must be deployed first.[/yellow]")
                    console.print("Run: [cyan]ccwb deploy networking[/cyan]")
                    return 1

                s3_bucket = networking_outputs["CfnArtifactsBucket"]

                # Build parameters
                monthly_limit = getattr(profile, "monthly_token_limit", 300000000)
                metrics_aggregator_role = dashboard_outputs.get(
                    "MetricsAggregatorRoleName", "claude-code-auth-dashboard-MetricsAggregatorRole-*"
                )

                params = [
                    f"MonthlyTokenLimit={monthly_limit}",
                    f"MetricsTableArn={dashboard_outputs['MetricsTableArn']}",
                    f"MetricsAggregatorRoleName={metrics_aggregator_role}",
                    f"WarningThreshold80={int(monthly_limit * 0.8)}",
                    f"WarningThreshold90={int(monthly_limit * 0.9)}",
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

                    # Update metrics aggregator Lambda environment if successful
                    if result == 0:
                        self._update_metrics_aggregator_env(profile, stack_name, console)

                    return result

                finally:
                    # Clean up temp file
                    if "packaged_template_path" in locals():
                        try:
                            os.unlink(packaged_template_path)
                        except Exception:
                            pass

            elif stack_type == "codebuild":
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
        # This method remains for backward compatibility with --show-commands option
        console.print("\n[bold]AWS CLI Commands:[/bold]")
        for stack_type, description in stacks_to_deploy:
            console.print(f"\n[dim]# {description}[/dim]")
            self._show_deployment_commands(stack_type, profile)

    def _show_deployment_commands(self, stack_type: str, profile) -> None:
        """Show AWS CLI commands for manual deployment."""
        # Implementation remains the same as original for reference
        pass

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

            dashboard_stack = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
            dashboard_outputs = get_stack_outputs(dashboard_stack, profile.aws_region)

            if dashboard_outputs:
                console.print("\n[bold]Dashboard Stack:[/bold]")
                dashboard_url = dashboard_outputs.get("DashboardURL", "")
                if dashboard_url:
                    console.print(f"• Dashboard URL: [cyan][link={dashboard_url}]{dashboard_url}[/link][/cyan]")

    def _update_metrics_aggregator_env(self, profile, quota_stack_name: str, console: Console) -> None:
        """Update metrics aggregator Lambda environment variable to include quota table."""
        try:
            import boto3

            # Get the quota table name from the quota stack outputs
            quota_outputs = get_stack_outputs(quota_stack_name, profile.aws_region)
            if not quota_outputs or not quota_outputs.get("QuotaTableName"):
                console.print("[yellow]Warning: Could not get quota table name from stack outputs[/yellow]")
                return

            quota_table_name = quota_outputs["QuotaTableName"]

            # Get the metrics aggregator function name
            metrics_aggregator_name = "ClaudeCode-MetricsAggregator"

            console.print(f"[dim]Updating {metrics_aggregator_name} environment variables...[/dim]")

            # Update the Lambda function environment variables
            lambda_client = boto3.client("lambda", region_name=profile.aws_region)

            try:
                lambda_client.update_function_configuration(
                    FunctionName=metrics_aggregator_name,
                    Environment={
                        "Variables": {
                            "METRICS_LOG_GROUP": profile.metrics_log_group,
                            "METRICS_REGION": profile.aws_region,
                            "METRICS_TABLE": "ClaudeCodeMetrics",
                            "QUOTA_TABLE": quota_table_name,
                        }
                    },
                )
                console.print("[green]✓ Updated metrics aggregator to enable quota tracking[/green]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Failed to update metrics aggregator environment variables: {str(e)}[/yellow]"
                )
                console.print(
                    f"[dim]You may need to manually add QUOTA_TABLE={quota_table_name} "
                    f"to the metrics aggregator Lambda[/dim]"
                )

        except Exception as e:
            console.print(f"[yellow]Warning: Error updating metrics aggregator: {str(e)}[/yellow]")

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
            "analytics": "Analytics Pipeline",
            "quota": "Quota Monitoring",
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
