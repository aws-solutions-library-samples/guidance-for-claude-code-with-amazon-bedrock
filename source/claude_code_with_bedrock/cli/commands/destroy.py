# ABOUTME: Destroy command for cleaning up AWS resources
# ABOUTME: Safely removes deployed stacks and configurations

"""Destroy command - Remove deployed infrastructure."""

from cleo.commands.command import Command
from cleo.helpers import argument, option
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from claude_code_with_bedrock.cli.utils.cloudformation import CloudFormationManager
from claude_code_with_bedrock.config import Config


class DestroyCommand(Command):
    name = "destroy"
    description = "Remove deployed AWS infrastructure"

    arguments = [
        argument(
            "stack",
            description="Specific stack to destroy (auth/networking/monitoring/dashboard/analytics)",
            optional=True,
        )
    ]

    options = [
        option("profile", description="Configuration profile to use", flag=False),
        option("force", description="Skip confirmation prompts", flag=True),
    ]

    def handle(self) -> int:
        """Execute the destroy command."""
        console = Console()

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

        # Determine which stacks to destroy
        stack_arg = self.argument("stack")
        force = self.option("force")

        stacks_to_destroy = []
        if stack_arg:
            if stack_arg in ["auth", "networking", "monitoring", "dashboard", "analytics", "s3bucket"]:
                stacks_to_destroy.append(stack_arg)
            else:
                console.print(f"[red]Unknown stack: {stack_arg}[/red]")
                console.print("Valid stacks: auth, networking, monitoring, dashboard, analytics, s3bucket")
                return 1
        else:
            # Destroy all stacks in reverse order
            stacks_to_destroy = ["analytics", "dashboard", "monitoring", "networking", "s3bucket", "auth"]

        # Show what will be destroyed
        console.print(
            Panel.fit(
                "[bold red]⚠️  Infrastructure Destruction Warning[/bold red]\n\n"
                "This will permanently delete the following AWS resources:",
                border_style="red",
                padding=(1, 2),
            )
        )

        for stack in stacks_to_destroy:
            stack_name = profile.stack_names.get(stack, f"{profile.identity_pool_name}-{stack}")
            console.print(f"• {stack.capitalize()} stack: [cyan]{stack_name}[/cyan]")

        console.print("\n[yellow]Note: Some resources may require manual cleanup:[/yellow]")
        console.print("• CloudWatch LogGroups (/ecs/otel-collector, /aws/claude-code/metrics)")
        console.print("• S3 Buckets and Athena resources created by analytics stack")
        console.print("• Any custom resources created outside of CloudFormation")

        # Confirm destruction
        if not force:
            if not Confirm.ask("\n[bold red]Are you sure you want to destroy these resources?[/bold red]"):
                console.print("\n[yellow]Destruction cancelled.[/yellow]")
                return 0

        # Destroy stacks
        console.print("\n[bold]Destroying stacks...[/bold]\n")

        all_failed_resources = []  # Collect failed resources from all stacks
        stacks_with_failures = []

        for stack in stacks_to_destroy:
            if stack == "monitoring" and not profile.monitoring_enabled:
                continue
            if stack == "dashboard" and not profile.monitoring_enabled:
                continue
            if stack == "networking" and not profile.monitoring_enabled:
                continue
            if stack == "analytics" and not profile.monitoring_enabled:
                continue
            if stack == "s3bucket" and not profile.monitoring_enabled:
                continue

            stack_name = profile.stack_names.get(stack, f"{profile.identity_pool_name}-{stack}")
            console.print(f"Destroying {stack} stack: [cyan]{stack_name}[/cyan]")

            result = self._delete_stack(stack_name, profile.aws_region, console)
            if result != 0:
                # Don't break - collect failed resources and continue
                failed = self._get_failed_resources(stack_name, profile.aws_region)
                if failed:
                    all_failed_resources.extend(failed)
                    stacks_with_failures.append(stack_name)
                console.print(
                    f"[yellow]⚠ {stack.capitalize()} stack has resources requiring manual cleanup[/yellow]\n"
                )
            else:
                console.print(f"[green]✓ {stack.capitalize()} stack destroyed[/green]\n")

        # Show cleanup summary at the end
        self._show_cleanup_summary(all_failed_resources, stacks_with_failures, profile, console)

        return 0

    def _delete_stack(self, stack_name: str, region: str, console: Console) -> int:
        """Delete a CloudFormation stack using boto3.

        Returns:
            0: Success (stack deleted or doesn't exist)
            1: Partial success (DELETE_FAILED - some resources need manual cleanup)
            2: Actual error (permissions, network, etc.)
        """
        cf_manager = CloudFormationManager(region=region)

        # Check if stack exists
        status = cf_manager.get_stack_status(stack_name)
        if not status:
            console.print(f"[yellow]Stack {stack_name} not found or already deleted[/yellow]")
            return 0

        # If already in DELETE_FAILED, report it (don't retry)
        if status == "DELETE_FAILED":
            console.print(f"[yellow]Stack {stack_name} is in DELETE_FAILED state[/yellow]")
            return 1  # Signal that manual cleanup is needed

        # Use progress indicator
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            task = progress.add_task(f"Deleting stack {stack_name}...", total=None)

            # Delete the stack with event tracking
            result = cf_manager.delete_stack(
                stack_name=stack_name,
                force=True,
                on_event=lambda e: progress.update(
                    task, description=f"Deleting {e.get('LogicalResourceId', stack_name)}..."
                ),
                timeout=300,
            )

            progress.update(task, completed=True)

            if result.success:
                return 0

            # Check if it ended up in DELETE_FAILED (some resources retained)
            new_status = cf_manager.get_stack_status(stack_name)
            if new_status == "DELETE_FAILED":
                return 1  # Not an error, just needs manual cleanup

            # Actual error
            console.print(f"[red]Error deleting stack: {result.error}[/red]")
            return 2

    def _get_failed_resources(self, stack_name: str, region: str) -> list[dict]:
        """Get list of resources that failed to delete from a stack."""
        cf_manager = CloudFormationManager(region=region)
        return cf_manager.get_failed_resources(stack_name)

    def _show_cleanup_summary(
        self,
        failed_resources: list[dict],
        stacks: list[str],
        profile,
        console: Console,
    ) -> None:
        """Show cleanup instructions for failed resources."""
        if not failed_resources and not stacks:
            console.print("\n[green]✓ All stacks destroyed successfully![/green]")
            return

        console.print("\n[yellow]⚠ Manual cleanup required for the following resources:[/yellow]\n")

        # Group by resource type for organized output
        by_type: dict[str, list[dict]] = {}
        for r in failed_resources:
            rtype = r["resource_type"]
            if rtype not in by_type:
                by_type[rtype] = []
            by_type[rtype].append(r)

        region = profile.aws_region

        # S3 Buckets
        if "AWS::S3::Bucket" in by_type:
            console.print("[bold]S3 Buckets (must be emptied first):[/bold]")
            for r in by_type["AWS::S3::Bucket"]:
                bucket = r["physical_id"]
                console.print(f"  • {bucket}")
                console.print(f"    [cyan]aws s3 rm s3://{bucket} --recursive[/cyan]")
                console.print(f"    [cyan]aws s3 rb s3://{bucket}[/cyan]")
            console.print()

        # CloudWatch Log Groups
        if "AWS::Logs::LogGroup" in by_type:
            console.print("[bold]CloudWatch Log Groups:[/bold]")
            for r in by_type["AWS::Logs::LogGroup"]:
                log_group = r["physical_id"]
                console.print(f"  • {log_group}")
                console.print(
                    f"    [cyan]aws logs delete-log-group --log-group-name {log_group} --region {region}[/cyan]"
                )
            console.print()

        # DynamoDB Tables
        if "AWS::DynamoDB::Table" in by_type:
            console.print("[bold]DynamoDB Tables:[/bold]")
            for r in by_type["AWS::DynamoDB::Table"]:
                table = r["physical_id"]
                console.print(f"  • {table}")
                console.print(f"    [cyan]aws dynamodb delete-table --table-name {table} --region {region}[/cyan]")
            console.print()

        # ECR Repositories
        if "AWS::ECR::Repository" in by_type:
            console.print("[bold]ECR Repositories (must delete images first):[/bold]")
            for r in by_type["AWS::ECR::Repository"]:
                repo = r["physical_id"]
                console.print(f"  • {repo}")
                console.print(
                    f"    [cyan]aws ecr delete-repository --repository-name {repo} --force --region {region}[/cyan]"
                )
            console.print()

        # Other resources
        known_types = ["AWS::S3::Bucket", "AWS::Logs::LogGroup", "AWS::DynamoDB::Table", "AWS::ECR::Repository"]
        other_types = [t for t in by_type if t not in known_types]
        if other_types:
            console.print("[bold]Other Resources:[/bold]")
            for rtype in other_types:
                for r in by_type[rtype]:
                    console.print(f"  • {r['logical_id']} ({rtype}): {r['physical_id']}")
                    console.print(f"    Reason: {r['status_reason']}")
            console.print()

        # Final instructions
        if stacks:
            console.print("[yellow]After manual cleanup, delete the failed stacks:[/yellow]")
            for stack in stacks:
                console.print(f"  [cyan]aws cloudformation delete-stack --stack-name {stack} --region {region}[/cyan]")
            console.print()

        console.print("For more information, see: assets/docs/TROUBLESHOOTING.md")
