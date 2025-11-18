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
        option("profile", description="Configuration profile to use", flag=False, default="default"),
        option("force", description="Skip confirmation prompts", flag=True),
    ]

    def handle(self) -> int:
        """Execute the destroy command."""
        console = Console()

        # Load configuration
        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found.[/red]")
            return 1

        # Determine which stacks to destroy
        stack_arg = self.argument("stack")
        force = self.option("force")

        stacks_to_destroy = []
        if stack_arg:
            if stack_arg in ["auth", "networking", "monitoring", "dashboard", "analytics"]:
                stacks_to_destroy.append(stack_arg)
            else:
                console.print(f"[red]Unknown stack: {stack_arg}[/red]")
                console.print("Valid stacks: auth, networking, monitoring, dashboard, analytics")
                return 1
        else:
            # Destroy all stacks in reverse order
            stacks_to_destroy = ["analytics", "dashboard", "monitoring", "networking", "auth"]

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

        failed = False
        for stack in stacks_to_destroy:
            if stack == "monitoring" and not profile.monitoring_enabled:
                continue
            if stack == "dashboard" and not profile.monitoring_enabled:
                continue
            if stack == "networking" and not profile.monitoring_enabled:
                continue
            if stack == "analytics" and not profile.monitoring_enabled:
                continue

            stack_name = profile.stack_names.get(stack, f"{profile.identity_pool_name}-{stack}")
            console.print(f"Destroying {stack} stack: [cyan]{stack_name}[/cyan]")

            result = self._delete_stack(stack_name, profile.aws_region, console)
            if result != 0:
                failed = True
                console.print(f"[red]Failed to destroy {stack} stack[/red]")
                break
            console.print(f"[green]✓ {stack.capitalize()} stack destroyed[/green]\n")

        if failed:
            console.print("\n[red]Destruction failed. Some resources may still exist.[/red]")
            return 1

        # Show cleanup instructions
        console.print("\n[green]Stack destruction complete![/green]")
        console.print("\n[yellow]Manual cleanup may be required for:[/yellow]")
        console.print("1. CloudWatch LogGroups:")
        console.print(
            f"   [cyan]aws logs delete-log-group --log-group-name /ecs/otel-collector "
            f"--region {profile.aws_region}[/cyan]"
        )
        console.print(
            f"   [cyan]aws logs delete-log-group --log-group-name /aws/claude-code/metrics "
            f"--region {profile.aws_region}[/cyan]"
        )
        console.print("\n2. Check CloudFormation console for any DELETE_FAILED resources")
        console.print("\nFor more information, see: assets/docs/TROUBLESHOOTING.md")

        return 0

    def _delete_stack(self, stack_name: str, region: str, console: Console) -> int:
        """Delete a CloudFormation stack using boto3."""
        cf_manager = CloudFormationManager(region=region)

        # Check if stack exists
        status = cf_manager.get_stack_status(stack_name)
        if not status:
            console.print(f"[yellow]Stack {stack_name} not found or already deleted[/yellow]")
            return 0

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
            else:
                if "DELETE_FAILED" in str(result.error):
                    console.print("[red]Stack deletion failed. Check CloudFormation console for details.[/red]")
                else:
                    console.print(f"[red]Error deleting stack: {result.error}[/red]")
                return 1
