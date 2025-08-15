# ABOUTME: Deploy command for AWS infrastructure stacks
# ABOUTME: Handles deployment of auth, monitoring, and dashboard stacks

"""Deploy command - Deploy AWS infrastructure."""

import subprocess
from pathlib import Path
from typing import Optional

from cleo.commands.command import Command
from cleo.helpers import argument, option
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config


class DeployCommand(Command):
    name = "deploy"
    description = "Deploy AWS infrastructure (auth, monitoring, dashboards)"

    arguments = [
        argument(
            "stack",
            description="Specific stack to deploy (auth/networking/monitoring/dashboard/analytics)",
            optional=True
        )
    ]

    options = [
        option(
            "profile",
            description="Configuration profile to use",
            flag=False,
            default="default"
        ),
        option(
            "dry-run",
            description="Show what would be deployed without executing",
            flag=True
        ),
        option(
            "show-commands",
            description="Show AWS CLI commands instead of executing",
            flag=True
        )
    ]


    def handle(self) -> int:
        """Execute the deploy command."""
        console = Console()

        # Welcome
        console.print(Panel.fit(
            "[bold cyan]Claude Code Infrastructure Deployment[/bold cyan]\n\n"
            "Deploy or update CloudFormation stacks",
            border_style="cyan",
            padding=(1, 2)
        ))

        # Load configuration
        config = Config.load()

        # Get profile name
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found. Run 'poetry run ccwb init' first.[/red]")
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
            else:
                console.print(f"[red]Unknown stack: {stack_arg}[/red]")
                console.print("Valid stacks: auth, networking, monitoring, dashboard, analytics")
                return 1
        else:
            # Deploy all configured stacks
            stacks_to_deploy.append(("auth", "Authentication Stack (Cognito + IAM)"))
            if profile.monitoring_enabled:
                stacks_to_deploy.append(("networking", "VPC Networking for OTEL Collector"))
                stacks_to_deploy.append(("monitoring", "OpenTelemetry Collector"))
                stacks_to_deploy.append(("dashboard", "CloudWatch Dashboard"))
                # Check if analytics is enabled (default to True for backward compatibility)
                if getattr(profile, 'analytics_enabled', True):
                    stacks_to_deploy.append(("analytics", "Analytics Pipeline (Kinesis Firehose + Athena)"))

        # Show deployment plan
        console.print("\n[bold]Deployment Plan:[/bold]")
        table = Table(box=box.SIMPLE)
        table.add_column("Stack", style="cyan")
        table.add_column("Description")
        table.add_column("Status")

        for stack_type, description in stacks_to_deploy:
            stack_name = profile.stack_names.get(stack_type, f"{profile.identity_pool_name}-{stack_type}")
            exists = self._check_stack_exists(stack_name, profile.aws_region)
            status = "[green]Update[/green]" if exists else "[yellow]Create[/yellow]"
            table.add_row(stack_type, description, status)

        console.print(table)

        if dry_run:
            console.print("\n[yellow]Dry run mode - no changes will be made[/yellow]")
            return 0

        # Deploy stacks
        console.print("\n[bold]Deploying stacks...[/bold]\n")

        failed = False
        for stack_type, description in stacks_to_deploy:
            console.print(f"[bold]{description}[/bold]")

            if show_commands:
                self._show_deployment_commands(stack_type, profile)
                console.print("")
            else:
                result = self._deploy_stack(stack_type, profile, console)
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

        if not show_commands:
            console.print("\n[bold]Stack Outputs:[/bold]")
            self._show_stack_outputs(profile, console)

        return 0

    def _check_stack_exists(self, stack_name: str, region: str) -> bool:
        """Check if a CloudFormation stack exists and is in a valid state."""
        try:
            cmd = [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                status = result.stdout.strip()
                # These statuses mean the stack exists and can be updated
                valid_statuses = [
                    "CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"
                ]
                # ROLLBACK_COMPLETE means the stack failed to create and must be deleted
                if status == "ROLLBACK_COMPLETE":
                    # Delete the failed stack automatically
                    console = Console()
                    console.print(f"[yellow]Stack {stack_name} is in ROLLBACK_COMPLETE state. Deleting...[/yellow]")
                    delete_cmd = [
                        "aws", "cloudformation", "delete-stack",
                        "--stack-name", stack_name,
                        "--region", region
                    ]
                    subprocess.run(delete_cmd, capture_output=True, text=True)
                    # Wait a moment for deletion to start
                    import time
                    time.sleep(2)
                    return False
                return status in valid_statuses
            return False
        except:
            return False

    def _show_deployment_commands(self, stack_type: str, profile) -> None:
        """Show AWS CLI commands for manual deployment."""
        console = Console()

        # The infrastructure files are at the repository root, not in source
        # Go up from deploy.py -> commands -> cli -> claude_code_with_bedrock -> source -> repo root
        project_root = Path(__file__).parents[4]

        # Helper function to get networking outputs
        def get_networking_outputs():
            networking_stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
            return get_stack_outputs(networking_stack_name, profile.aws_region)

        if stack_type == "auth":
            template = project_root / "deployment" / "infrastructure" / "cognito-identity-pool.yaml"
            stack_name = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")

            # Build parameters based on provider type
            params = []

            # Check if this is a Cognito User Pool provider
            if profile.provider_type == 'cognito':
                params.extend([
                    "ParameterKey=AuthProviderType,ParameterValue=CognitoUserPool",
                    f"ParameterKey=CognitoUserPoolId,ParameterValue={profile.cognito_user_pool_id}",
                    f"ParameterKey=CognitoUserPoolClientId,ParameterValue={profile.client_id}",
                ])
            else:
                # External OIDC provider
                params.extend([
                    "ParameterKey=AuthProviderType,ParameterValue=ExternalOIDC",
                    f"ParameterKey=OIDCProviderDomain,ParameterValue={profile.provider_domain}",
                    f"ParameterKey=OIDCClientId,ParameterValue={profile.client_id}",
                ])

            # Common parameters
            params.extend([
                f"ParameterKey=IdentityPoolName,ParameterValue={profile.identity_pool_name}",
                f"ParameterKey=AllowedBedrockRegions,ParameterValue=\"{','.join(profile.allowed_bedrock_regions)}\"",
                f"ParameterKey=EnableMonitoring,ParameterValue={str(profile.monitoring_enabled).lower()}",
                "ParameterKey=EnableBedrockTracking,ParameterValue=true"
            ])

            console.print("[dim]# Deploy authentication stack[/dim]")
            console.print("aws cloudformation deploy \\")
            console.print(f"  --template-file {template} \\")
            console.print(f"  --stack-name {stack_name} \\")
            console.print("  --capabilities CAPABILITY_NAMED_IAM \\")
            console.print(f"  --region {profile.aws_region} \\")
            console.print("  --parameter-overrides \\")
            for param in params:
                console.print(f"    {param} \\")
            console.print("")

        elif stack_type == "networking":
            template = project_root / "deployment" / "infrastructure" / "networking.yaml"
            stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")

            # VPC CIDR parameters
            vpc_config = profile.monitoring_config or {}
            params = [
                f"ParameterKey=VpcCidr,ParameterValue={vpc_config.get('vpc_cidr', '10.0.0.0/16')}",
                f"ParameterKey=PublicSubnet1Cidr,ParameterValue={vpc_config.get('subnet1_cidr', '10.0.1.0/24')}",
                f"ParameterKey=PublicSubnet2Cidr,ParameterValue={vpc_config.get('subnet2_cidr', '10.0.2.0/24')}"
            ]

            console.print("[dim]# Deploy networking infrastructure[/dim]")
            console.print("aws cloudformation deploy \\")
            console.print(f"  --template-file {template} \\")
            console.print(f"  --stack-name {stack_name} \\")
            console.print("  --capabilities CAPABILITY_IAM \\")
            console.print(f"  --region {profile.aws_region} \\")
            if params:
                console.print("  --parameter-overrides \\")
                for param in params:
                    console.print(f"    {param} \\")
            console.print("")

        elif stack_type == "monitoring":
            template = project_root / "deployment" / "infrastructure" / "otel-collector.yaml"
            stack_name = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")

            # Get VPC ID and subnet IDs from networking stack
            networking_outputs = get_networking_outputs()

            params = []
            if networking_outputs:
                vpc_id = networking_outputs.get('VpcId', '')
                subnet_ids = networking_outputs.get('SubnetIds', '')
                params.append(f"ParameterKey=VpcId,ParameterValue={vpc_id}")
                params.append(f"ParameterKey=SubnetIds,ParameterValue=\"{subnet_ids}\"")

            # Add HTTPS domain parameters if configured
            vpc_config = profile.monitoring_config or {}
            if vpc_config.get('custom_domain'):
                params.append(f"ParameterKey=CustomDomainName,ParameterValue={vpc_config['custom_domain']}")
                params.append(f"ParameterKey=HostedZoneId,ParameterValue={vpc_config['hosted_zone_id']}")

            console.print("[dim]# Deploy monitoring collector[/dim]")
            console.print("aws cloudformation deploy \\")
            console.print(f"  --template-file {template} \\")
            console.print(f"  --stack-name {stack_name} \\")
            console.print("  --capabilities CAPABILITY_IAM \\")
            console.print(f"  --region {profile.aws_region} \\")
            if params:
                console.print("  --parameter-overrides \\")
                for param in params:
                    console.print(f"    {param} \\")
            console.print("")

        elif stack_type == "dashboard":
            template = project_root / "deployment" / "infrastructure" / "monitoring-dashboard.yaml"
            stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")

            console.print("[dim]# Deploy monitoring dashboard[/dim]")
            console.print("aws cloudformation deploy \\")
            console.print(f"  --template-file {template} \\")
            console.print(f"  --stack-name {stack_name} \\")
            console.print(f"  --region {profile.aws_region}")
            console.print("")

        elif stack_type == "analytics":
            template = project_root / "deployment" / "infrastructure" / "analytics-pipeline.yaml"
            stack_name = profile.stack_names.get("analytics", f"{profile.identity_pool_name}-analytics")

            # Build parameters from profile configuration
            params = [
                f"ParameterKey=MetricsLogGroup,ParameterValue={profile.metrics_log_group}",
                f"ParameterKey=DataRetentionDays,ParameterValue={profile.data_retention_days}",
                f"ParameterKey=FirehoseBufferInterval,ParameterValue={profile.firehose_buffer_interval}",
                f"ParameterKey=DebugMode,ParameterValue={str(profile.analytics_debug_mode).lower()}"
            ]

            console.print("[dim]# Deploy analytics pipeline[/dim]")
            console.print("aws cloudformation deploy \\")
            console.print(f"  --template-file {template} \\")
            console.print(f"  --stack-name {stack_name} \\")
            console.print("  --capabilities CAPABILITY_IAM \\")
            console.print(f"  --region {profile.aws_region} \\")
            console.print("  --parameter-overrides \\")
            for param in params:
                console.print(f"    {param} \\")
            console.print("")

    def _deploy_stack(self, stack_type: str, profile, console: Console) -> int:
        """Deploy a CloudFormation stack."""
        # The infrastructure files are at the repository root, not in source
        # Go up from deploy.py -> commands -> cli -> claude_code_with_bedrock -> source -> repo root
        project_root = Path(__file__).parents[4]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:

            if stack_type == "auth":
                task = progress.add_task("Deploying authentication stack...", total=None)

                template = project_root / "deployment" / "infrastructure" / "cognito-identity-pool.yaml"
                stack_name = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")

                # Build parameters based on provider type - use simple Key=Value format
                params = []

                # Check if this is a Cognito User Pool provider
                if profile.provider_type == 'cognito':
                    params.extend([
                        "AuthProviderType=CognitoUserPool",
                        f"CognitoUserPoolId={profile.cognito_user_pool_id}",
                        f"CognitoUserPoolClientId={profile.client_id}",
                    ])
                else:
                    # External OIDC provider
                    params.extend([
                        "AuthProviderType=ExternalOIDC",
                        f"OIDCProviderDomain={profile.provider_domain}",
                        f"OIDCClientId={profile.client_id}",
                    ])

                # Common parameters
                params.extend([
                    f"IdentityPoolName={profile.identity_pool_name}",
                    f"AllowedBedrockRegions={','.join(profile.allowed_bedrock_regions)}",
                    f"EnableMonitoring={str(profile.monitoring_enabled).lower()}"
                ])

                cmd = [
                    "aws", "cloudformation", "deploy",
                    "--template-file", str(template),
                    "--stack-name", stack_name,
                    "--capabilities", "CAPABILITY_NAMED_IAM",
                    "--region", profile.aws_region,
                    "--parameter-overrides"
                ] + params

            elif stack_type == "networking":
                task = progress.add_task("Deploying networking infrastructure...", total=None)

                template = project_root / "deployment" / "infrastructure" / "networking.yaml"
                stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")

                # VPC CIDR parameters
                vpc_config = profile.monitoring_config or {}
                params = [
                    f"VpcCidr={vpc_config.get('vpc_cidr', '10.0.0.0/16')}",
                    f"PublicSubnet1Cidr={vpc_config.get('subnet1_cidr', '10.0.1.0/24')}",
                    f"PublicSubnet2Cidr={vpc_config.get('subnet2_cidr', '10.0.2.0/24')}"
                ]

                cmd = [
                    "aws", "cloudformation", "deploy",
                    "--template-file", str(template),
                    "--stack-name", stack_name,
                    "--region", profile.aws_region,
                    "--parameter-overrides"
                ] + params

            elif stack_type == "monitoring":
                task = progress.add_task("Deploying monitoring collector...", total=None)

                template = project_root / "deployment" / "infrastructure" / "otel-collector.yaml"
                stack_name = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")

                # Get VPC ID and subnet IDs from networking stack
                networking_stack_name = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
                networking_outputs = get_stack_outputs(networking_stack_name, profile.aws_region)

                params = []
                if networking_outputs:
                    vpc_id = networking_outputs.get('VpcId', '')
                    subnet_ids = networking_outputs.get('SubnetIds', '')
                    params.append(f"VpcId={vpc_id}")
                    params.append(f"SubnetIds={subnet_ids}")

                # Add HTTPS domain parameters if configured
                monitoring_config = getattr(profile, 'monitoring_config', {})
                if monitoring_config.get('custom_domain'):
                    params.append(f"CustomDomainName={monitoring_config['custom_domain']}")
                    params.append(f"HostedZoneId={monitoring_config['hosted_zone_id']}")

                cmd = [
                    "aws", "cloudformation", "deploy",
                    "--template-file", str(template),
                    "--stack-name", stack_name,
                    "--capabilities", "CAPABILITY_IAM",
                    "--region", profile.aws_region
                ]
                if params:
                    cmd.extend(["--parameter-overrides"] + params)

            elif stack_type == "dashboard":
                task = progress.add_task("Deploying monitoring dashboard...", total=None)

                template = project_root / "deployment" / "infrastructure" / "monitoring-dashboard.yaml"
                stack_name = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")

                cmd = [
                    "aws", "cloudformation", "deploy",
                    "--template-file", str(template),
                    "--stack-name", stack_name,
                    "--region", profile.aws_region
                ]

            elif stack_type == "analytics":
                task = progress.add_task("Deploying analytics pipeline...", total=None)

                template = project_root / "deployment" / "infrastructure" / "analytics-pipeline.yaml"
                stack_name = profile.stack_names.get("analytics", f"{profile.identity_pool_name}-analytics")

                # Build parameters from profile configuration
                params = [
                    f"MetricsLogGroup={profile.metrics_log_group}",
                    f"DataRetentionDays={profile.data_retention_days}",
                    f"FirehoseBufferInterval={profile.firehose_buffer_interval}",
                    f"DebugMode={str(profile.analytics_debug_mode).lower()}"
                ]

                cmd = [
                    "aws", "cloudformation", "deploy",
                    "--template-file", str(template),
                    "--stack-name", stack_name,
                    "--capabilities", "CAPABILITY_IAM",
                    "--region", profile.aws_region,
                    "--parameter-overrides"
                ] + params

            # Execute deployment
            # For debugging, let's also show what command we're running
            if self.option("show-commands"):
                console.print(f"\n[dim]Executing: {' '.join(cmd)}[/dim]\n")

            result = subprocess.run(cmd, capture_output=True, text=True)
            progress.update(task, completed=True)

            if result.returncode == 0:
                console.print(f"[green]✓ {stack_type} stack deployed successfully[/green]")
                return 0
            else:
                console.print(f"[red]✗ Failed to deploy {stack_type} stack[/red]")

                # Get detailed error from stack events
                error_details = self._get_stack_failure_reason(stack_name, profile.aws_region)

                # Parse and provide helpful error messages
                error_output = error_details or result.stderr or result.stdout
                if error_output:
                    # Check for common resource conflicts
                    if "already exists" in error_output and "LogGroup" in error_output:
                        if "/ecs/otel-collector" in error_output:
                            console.print("\n[yellow]Error: CloudWatch LogGroup '/ecs/otel-collector' already exists.[/yellow]")
                            console.print("\nThis typically happens when a previous deployment failed. To resolve:")
                            console.print("1. Delete the log group manually:")
                            console.print(f"   [cyan]aws logs delete-log-group --log-group-name /ecs/otel-collector --region {profile.aws_region}[/cyan]")
                            console.print("\n2. Then run 'ccwb deploy' again\n")
                        elif "/aws/claude-code/metrics" in error_output:
                            console.print("\n[yellow]Error: CloudWatch LogGroup '/aws/claude-code/metrics' already exists.[/yellow]")
                            console.print("\nTo resolve:")
                            console.print("1. Delete the log group manually:")
                            console.print(f"   [cyan]aws logs delete-log-group --log-group-name /aws/claude-code/metrics --region {profile.aws_region}[/cyan]")
                            console.print("\n2. Then run 'ccwb deploy' again\n")
                    elif "already exists" in error_output:
                        console.print("\n[yellow]Error: A resource already exists from a previous deployment.[/yellow]")
                        console.print("To resolve:")
                        console.print("1. Check the CloudFormation console for the specific resource")
                        console.print("2. Manually delete the conflicting resource")
                        console.print("3. Run 'ccwb deploy' again")
                        console.print("\nFor more help, see: assets/docs/TROUBLESHOOTING.md\n")
                    elif "ROLLBACK_COMPLETE" in error_output:
                        console.print("\n[yellow]Error: Stack is in ROLLBACK_COMPLETE state.[/yellow]")
                        console.print("To resolve:")
                        console.print("1. Delete the failed stack:")
                        console.print(f"   [cyan]aws cloudformation delete-stack --stack-name {stack_name} --region {profile.aws_region}[/cyan]")
                        console.print("\n2. Wait for deletion to complete:")
                        console.print(f"   [cyan]aws cloudformation wait stack-delete-complete --stack-name {stack_name} --region {profile.aws_region}[/cyan]")
                        console.print("\n3. Then run 'ccwb deploy' again\n")
                    else:
                        # Show the raw error for other cases
                        console.print(f"\n[dim]{error_output}[/dim]")
                        console.print("\n[yellow]To see detailed error information, run:[/yellow]")
                        console.print(f"[cyan]aws cloudformation describe-stack-events --stack-name {stack_name} --region {profile.aws_region} --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]' --output table[/cyan]")
                        console.print("\nFor troubleshooting help, see: assets/docs/TROUBLESHOOTING.md")

                return 1

    def _get_stack_failure_reason(self, stack_name: str, region: str) -> Optional[str]:
        """Get the failure reason from CloudFormation stack events."""
        try:
            # First, get all failure events
            cmd = [
                "aws", "cloudformation", "describe-stack-events",
                "--stack-name", stack_name,
                "--region", region,
                "--output", "json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                import json
                data = json.loads(result.stdout)
                events = data.get("StackEvents", [])

                # Find the root cause - look for the first CREATE_FAILED that's not "Resource creation cancelled"
                failures = []
                for event in events:
                    status = event.get("ResourceStatus", "")
                    reason = event.get("ResourceStatusReason", "")

                    if status in ["CREATE_FAILED", "UPDATE_FAILED"]:
                        # Skip generic "cancelled" messages
                        if "cancelled" not in reason.lower():
                            resource_type = event.get("ResourceType", "Unknown")
                            logical_id = event.get("LogicalResourceId", "Unknown")
                            failures.append(f"{resource_type} ({logical_id}): {reason}")
                            # Return the first real failure we find
                            return failures[0]

                # If we only found cancelled messages, return them anyway
                if not failures:
                    for event in events:
                        if event.get("ResourceStatus") in ["CREATE_FAILED", "UPDATE_FAILED"]:
                            resource_type = event.get("ResourceType", "Unknown")
                            logical_id = event.get("LogicalResourceId", "Unknown")
                            reason = event.get("ResourceStatusReason", "Unknown error")
                            return f"{resource_type} ({logical_id}): {reason}"

            return None
        except Exception as e:
            return f"Error fetching stack events: {str(e)}"

    def _show_stack_outputs(self, profile, console: Console) -> None:
        """Show outputs from deployed stacks."""
        # Get auth stack outputs
        auth_stack = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")
        outputs = get_stack_outputs(auth_stack, profile.aws_region)

        if outputs:
            console.print("\n[bold]Authentication Stack:[/bold]")
            console.print(f"• Identity Pool ID: [cyan]{outputs.get('IdentityPoolId', 'N/A')}[/cyan]")
            console.print(f"• Role ARN: [cyan]{outputs.get('BedrockRoleArn', 'N/A')}[/cyan]")
            console.print(f"• OIDC Provider: [cyan]{outputs.get('OIDCProviderArn', 'N/A')}[/cyan]")

        # Get networking outputs if enabled
        if profile.monitoring_enabled:
            networking_stack = profile.stack_names.get("networking", f"{profile.identity_pool_name}-networking")
            networking_outputs = get_stack_outputs(networking_stack, profile.aws_region)

            if networking_outputs:
                console.print("\n[bold]Networking Stack:[/bold]")
                vpc_id = networking_outputs.get('VpcId', 'N/A')
                subnet_ids = networking_outputs.get('SubnetIds', 'N/A')
                console.print(f"• VPC ID: [cyan]{vpc_id}[/cyan]")
                console.print(f"• Subnet IDs: [cyan]{subnet_ids}[/cyan]")

            # Get monitoring stack endpoint
            monitoring_stack = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
            monitoring_outputs = get_stack_outputs(monitoring_stack, profile.aws_region)

            if monitoring_outputs:
                console.print("\n[bold]Monitoring Stack:[/bold]")
                endpoint = monitoring_outputs.get('CollectorEndpoint', 'N/A')
                console.print(f"• OTLP Endpoint: [cyan]{endpoint}[/cyan]")
                if endpoint.startswith('https://'):
                    console.print("• Security: [cyan]HTTPS encryption[/cyan]")
                else:
                    console.print("• Security: [yellow]HTTP (unencrypted)[/yellow]")

            dashboard_stack = profile.stack_names.get("dashboard", f"{profile.identity_pool_name}-dashboard")
            dashboard_outputs = get_stack_outputs(dashboard_stack, profile.aws_region)

            if dashboard_outputs:
                console.print("\n[bold]Dashboard Stack:[/bold]")
                dashboard_url = dashboard_outputs.get('DashboardURL', '')
                if dashboard_url:
                    console.print(f"• Dashboard URL: [cyan][link={dashboard_url}]{dashboard_url}[/link][/cyan]")

            # Get analytics outputs if enabled
            if getattr(profile, 'analytics_enabled', True):
                analytics_stack = profile.stack_names.get("analytics", f"{profile.identity_pool_name}-analytics")
                analytics_outputs = get_stack_outputs(analytics_stack, profile.aws_region)

                if analytics_outputs:
                    console.print("\n[bold]Analytics Stack:[/bold]")
                    athena_url = analytics_outputs.get('AthenaConsoleUrl', '')
                    if athena_url:
                        console.print(f"• Athena Console: [cyan][link={athena_url}]{athena_url}[/link][/cyan]")
                    console.print(f"• Database: [cyan]{analytics_outputs.get('AthenaDatabaseName', 'N/A')}[/cyan]")
                    console.print(f"• S3 Bucket: [cyan]{analytics_outputs.get('AnalyticsBucketName', 'N/A')}[/cyan]")
                    console.print(f"• Workgroup: [cyan]{analytics_outputs.get('AthenaWorkgroupName', 'N/A')}[/cyan]")
