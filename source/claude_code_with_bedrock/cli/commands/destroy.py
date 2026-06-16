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
from claude_code_with_bedrock.cli.utils.helpers import clear_cached_credentials
from claude_code_with_bedrock.config import Config

# All destroyable stacks in reverse dependency order (destroy-all uses this sequence).
# Keep in sync with deploy.py's stack types when adding new stacks.
# Ordered REVERSE-dependency teardown list: leaf-most dependents first, the
# root `auth` stack last. Persona-based access adds two leaf stacks — `budgets`
# depends on `persona` (per-persona cost tags / inference profiles), and
# `persona` depends on `auth` (it imports the OIDC provider ARN) — so they are
# torn down early, before `quota`. The per-persona dashboard is deployed inline
# by the persona flow (not a scheduled stack type), so it is not listed here.
# Keep this list in sync with the deployable stack types in deploy.py
# (enforced by tests/cli/commands/test_destroy_stacks.py).
DESTROYABLE_STACKS = [
    "codebuild",
    "budgets",
    "persona",
    "analytics",
    "quota",
    "cowork-dashboard",
    "dashboard",
    "monitoring",
    "distribution",
    "networking",
    "s3bucket",
    "auth",
]


class DestroyCommand(Command):
    name = "destroy"
    description = "Remove deployed AWS infrastructure"

    arguments = [
        argument(
            "stack",
            description=f"Specific stack to destroy ({'/'.join(DESTROYABLE_STACKS)})",
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
            if stack_arg in DESTROYABLE_STACKS:
                stacks_to_destroy.append(stack_arg)
            else:
                console.print(f"[red]Unknown stack: {stack_arg}[/red]")
                console.print(f"Valid stacks: {', '.join(DESTROYABLE_STACKS)}")
                return 1
        else:
            # Destroy all stacks in reverse dependency order
            stacks_to_destroy = list(DESTROYABLE_STACKS)

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
        all_retained_resources = []  # Collect intentionally retained resources
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
            # Skip ECS-related stacks in sidecar mode
            monitoring_mode = getattr(profile, "monitoring_mode", "central")
            if monitoring_mode == "sidecar" and stack in ("networking", "monitoring", "analytics", "s3bucket"):
                continue
            if stack == "quota" and not getattr(profile, "quota_monitoring_enabled", False):
                continue
            if stack == "distribution" and not getattr(profile, "enable_distribution", False):
                continue
            if stack == "codebuild" and not getattr(profile, "enable_codebuild", False):
                continue
            # Persona / budgets stacks only exist when personas were configured
            # (deploy gates them on OIDC + non-empty personas) — skip otherwise.
            # The persona-dashboard stack is NOT a DESTROYABLE_STACKS entry (it is
            # deployed inline, not as a scheduled stack type), so it is torn down
            # explicitly in the persona branch below via _delete_persona_dashboard_stack.
            if stack in ("persona", "budgets") and not getattr(profile, "personas", []):
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
                    console.print(f"[yellow]⚠ {stack.capitalize()} stack — failed resources:[/yellow]")
                    for r in failed:
                        console.print(f"    • {r['logical_id']} ({r['resource_type']}): {r['physical_id']}")
                else:
                    console.print(
                        f"[yellow]⚠ {stack.capitalize()} stack has resources requiring manual cleanup[/yellow]"
                    )
                console.print()
            else:
                # Check for silently retained resources (DeletionPolicy: Retain)
                retained = self._get_retained_resources(stack_name, profile.aws_region)
                if retained:
                    all_retained_resources.extend(retained)
                    console.print(f"[yellow]ℹ {stack.capitalize()} stack — retained resources (by policy):[/yellow]")
                    for r in retained:
                        console.print(f"    • {r['logical_id']} ({r['resource_type']}): {r['physical_id']}")
                    console.print()
                else:
                    console.print(f"[green]✓ {stack.capitalize()} stack destroyed[/green]\n")

            # The persona-dashboard CFN stack and the tagged Application Inference
            # Profiles are both created by `ccwb deploy` OUTSIDE the scheduled
            # DESTROYABLE_STACKS list (the dashboard is deployed inline; AIPs via
            # boto3), so the main loop never tears them down. Clean both up
            # best-effort in the persona branch so a teardown doesn't leave them
            # orphaned (FR-9.5). Dashboard first (independent CloudWatch stack),
            # then the inference profiles.
            if stack == "persona":
                self._delete_persona_dashboard_stack(profile, console)
                self._delete_persona_inference_profiles(profile, console)

        # Clean up cached credentials for this profile
        if clear_cached_credentials(profile_name):
            console.print(f"[green]✓ Cleared cached credentials for profile '{profile_name}'[/green]")

        # Show cleanup summary at the end
        self._show_cleanup_summary(all_failed_resources, all_retained_resources, stacks_with_failures, profile, console)

        return 0

    def _delete_persona_dashboard_stack(self, profile, console: Console) -> None:
        """Best-effort deletion of the inline persona-dashboard CFN stack.

        ``ccwb deploy`` provisions a standalone CloudFormation stack named
        ``{identity_pool_name}-persona-dashboard`` *inline* within the persona
        flow (not as a scheduled DESTROYABLE_STACKS entry), so the main teardown
        loop never removes it. Delete it explicitly here — mirroring the
        deploy-side stack name exactly — or ``ccwb destroy`` would orphan it
        (FR-9.5). Skips cleanly when no personas were configured (the dashboard
        only exists in that case). Failures are logged but never abort the
        destroy; the persona IAM stack is the primary resource and is handled by
        the main loop.
        """
        if not getattr(profile, "personas", []):
            return
        stack_name = profile.stack_names.get("persona-dashboard", f"{profile.identity_pool_name}-persona-dashboard")
        console.print(f"Destroying persona-dashboard stack: [cyan]{stack_name}[/cyan]")
        # _delete_stack returns 0 when the stack is absent/already deleted, so a
        # profile that never deployed the dashboard is a clean no-op here.
        result = self._delete_stack(stack_name, profile.aws_region, console)
        if result == 0:
            console.print("[green]✓ Persona-dashboard stack destroyed[/green]\n")
        else:
            console.print("[yellow]⚠ Persona-dashboard stack has resources requiring manual cleanup[/yellow]\n")

    def _delete_persona_inference_profiles(self, profile, console: Console) -> None:
        """Best-effort deletion of the per-persona-tier Application Inference Profiles.

        Deploy creates one AIP per ENTITLED persona TIER named
        ``{identity_pool_name}-{name}-{tier}`` (via boto3, outside any CFN stack),
        so they must be deleted explicitly on teardown or they orphan. Naming comes
        from the shared ``persona_models`` helpers so deploy and destroy can never
        drift. Failures are logged but never abort the destroy — the persona CFN
        stack (the IAM roles) is the primary resource and is handled separately.
        Also sweeps any legacy single-AIP-per-persona name (``{pool}-{name}``)
        created by pre-FR-5.1 deploys.

        Teardown iterates ALL tiers (not just the persona's *currently* entitled
        tiers): if a persona's ``allowed_models``/``denied_models`` were narrowed
        after deploy, the AIP created for the no-longer-entitled tier still exists
        and must be swept, or it orphans (FR-9.5). Attempting a delete for a tier
        whose AIP was never created is a harmless no-op (logged and skipped).
        """
        personas = getattr(profile, "personas", None)
        if not personas:
            return
        try:
            import boto3

            from claude_code_with_bedrock.persona_models import TIERS, aip_name

            client = boto3.client("bedrock", region_name=profile.aws_region)
            for persona in personas:
                name = persona.get("name")
                if not name:
                    continue
                # Every possible per-tier AIP (FR-5.1) — not just currently-entitled
                # tiers, so an AIP left by a since-narrowed persona is still removed —
                # plus the legacy single-name AIP for back-compat.
                candidates = [aip_name(profile.identity_pool_name, name, tier) for tier in TIERS]
                candidates.append(f"{profile.identity_pool_name}-{name}")  # legacy pre-FR-5.1 name
                for aip in candidates:
                    try:
                        client.delete_inference_profile(inferenceProfileIdentifier=aip)
                        console.print(f"[green]✓ Deleted inference profile '{aip}'[/green]")
                    except Exception as del_err:
                        # Already gone / never created / in use — log first line and continue.
                        console.print(
                            f"[dim]Inference profile '{aip}' not deleted "
                            f"({str(del_err).splitlines()[0]}); skipping.[/dim]"
                        )
        except Exception as e:
            console.print(f"[yellow]Warning: Could not clean up persona inference profiles: {str(e)}[/yellow]")

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

        # If already in DELETE_FAILED, pre-clean and retry
        if status == "DELETE_FAILED":
            console.print(f"[yellow]Stack {stack_name} is in DELETE_FAILED state, retrying after cleanup...[/yellow]")

        # Pre-clean resources that block deletion (non-empty S3 buckets, Athena workgroups)
        cf_manager.pre_cleanup_stack(
            stack_name,
            on_event=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
        )

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

    def _get_retained_resources(self, stack_name: str, region: str) -> list[dict]:
        """Get resources silently retained (DeletionPolicy: Retain) during deletion."""
        cf_manager = CloudFormationManager(region=region)
        return cf_manager.get_retained_resources(stack_name)

    def _show_cleanup_summary(
        self,
        failed_resources: list[dict],
        retained_resources: list[dict],
        stacks: list[str],
        profile,
        console: Console,
    ) -> None:
        """Show cleanup instructions for failed and retained resources."""
        if not failed_resources and not retained_resources and not stacks:
            console.print("\n[green]✓ All stacks destroyed successfully![/green]")
            return

        if retained_resources:
            console.print("\n[bold]Retained resources (DeletionPolicy: Retain):[/bold]")
            console.print("[dim]These were kept intentionally. Delete manually if no longer needed:[/dim]\n")
            for r in retained_resources:
                console.print(f"  • {r['logical_id']} ({r['resource_type']}): {r['physical_id']}")
            console.print()

        if not failed_resources:
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
