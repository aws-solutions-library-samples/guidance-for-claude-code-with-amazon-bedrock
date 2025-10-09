# ABOUTME: Command for listing and managing CodeBuild builds
# ABOUTME: Provides visibility into Windows binary build status and history

"""Builds command for listing and managing CodeBuild builds."""

from datetime import datetime

import boto3
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.table import Table


class BuildsCommand(Command):
    """
    List and manage CodeBuild builds for Windows binaries

    Shows recent builds, their status, and duration.
    """

    name = "builds"
    description = "List and manage CodeBuild builds"

    options = [
        option("limit", description="Number of builds to show", flag=False, default="10"),
        option("project", description="CodeBuild project name (default: auto-detect)", flag=False),
        option("status", description="Check status of a specific build by ID", flag=False),
    ]

    def handle(self) -> int:
        """Execute the builds command."""
        console = Console()

        # Check if this is a status check for a specific build
        if self.option("status"):
            return self._check_build_status(self.option("status"), console)

        try:
            # Auto-detect project name from config if not provided
            project_name = self.option("project")
            if not project_name:
                from ...config import Config

                config = Config.load()
                profile = config.get_profile("default")
                if profile:
                    project_name = f"{profile.identity_pool_name}-windows-build"
                else:
                    console.print("[red]No configuration found. Run 'poetry run ccwb init' first.[/red]")
                    return 1

            # Get builds from CodeBuild
            codebuild = boto3.client("codebuild", region_name=profile.aws_region)
            limit = int(self.option("limit"))

            # List builds for project
            response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")

            if not response.get("ids"):
                console.print("[yellow]No builds found[/yellow]")
                return 0

            # Get detailed build info
            build_ids = response["ids"][:limit]
            builds_response = codebuild.batch_get_builds(ids=build_ids)

            # Create table
            table = Table(title=f"Recent Builds for {project_name}")
            table.add_column("Build ID", style="cyan")
            table.add_column("Status", style="bold")
            table.add_column("Started", style="dim")
            table.add_column("Duration", style="dim")
            table.add_column("Phase", style="yellow")

            for build in builds_response.get("builds", []):
                build_id = build["id"].split(":")[1][:8]  # Short ID
                status = build["buildStatus"]

                # Color code status
                if status == "SUCCEEDED":
                    status_display = "[green]✓ Succeeded[/green]"
                elif status == "IN_PROGRESS":
                    status_display = "[yellow]⏳ In Progress[/yellow]"
                elif status == "FAILED":
                    status_display = "[red]✗ Failed[/red]"
                else:
                    status_display = f"[dim]{status}[/dim]"

                # Format start time
                start_time = build.get("startTime")
                if start_time:
                    started = start_time.strftime("%Y-%m-%d %H:%M")
                else:
                    started = "Unknown"

                # Calculate duration
                if "endTime" in build and "startTime" in build:
                    duration = build["endTime"] - build["startTime"]
                    duration_min = int(duration.total_seconds() / 60)
                    duration_display = f"{duration_min} min"
                elif status == "IN_PROGRESS" and "startTime" in build:
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    duration_display = f"{int(elapsed.total_seconds() / 60)} min"
                else:
                    duration_display = "-"

                # Current phase
                phase = build.get("currentPhase", "-")

                table.add_row(build_id, status_display, started, duration_display, phase)

            console.print(table)

            # Show command hints
            console.print("\n[dim]To check specific build status:[/dim]")
            console.print("  poetry run ccwb builds --status <build-id>")
            console.print("\n[dim]To start a new build:[/dim]")
            console.print("  poetry run ccwb package --target-platform windows")

            return 0

        except Exception as e:
            console.print(f"[red]Error listing builds: {e}[/red]")
            return 1

    def _check_build_status(self, build_id: str, console: Console) -> int:
        """Check the status of a specific CodeBuild build."""
        import json
        from pathlib import Path

        try:
            # If no build ID provided or it's "latest", check for latest
            if not build_id or build_id == "latest":
                build_info_file = Path.home() / ".claude-code" / "latest-build.json"
                if not build_info_file.exists():
                    console.print("[red]No recent builds found. Start a build with 'poetry run ccwb package'[/red]")
                    return 1

                with open(build_info_file) as f:
                    build_info = json.load(f)
                    build_id = build_info["build_id"]
                    console.print(f"[dim]Checking latest build: {build_id}[/dim]")
            else:
                # If it's a short ID (8 chars) or full UUID without project prefix
                if ":" not in build_id:
                    from ...config import Config

                    config = Config.load()
                    profile = config.get_profile("default")
                    if profile:
                        project_name = f"{profile.identity_pool_name}-windows-build"

                        # If it's a short ID (like from the table), find the full UUID
                        if len(build_id) == 8:
                            # List recent builds to find the matching one
                            codebuild = boto3.client("codebuild", region_name=profile.aws_region)
                            response = codebuild.list_builds_for_project(
                                projectName=project_name, sortOrder="DESCENDING"
                            )

                            # Find the build that starts with this short ID
                            for full_build_id in response.get("ids", []):
                                # Extract the UUID part after the colon
                                if ":" in full_build_id:
                                    uuid_part = full_build_id.split(":")[1]
                                    if uuid_part.startswith(build_id):
                                        build_id = full_build_id
                                        break
                            else:
                                # If we didn't find it, try with the project prefix anyway
                                build_id = f"{project_name}:{build_id}"
                        else:
                            # It's likely a full UUID, just add the project prefix
                            build_id = f"{project_name}:{build_id}"

            # Get build status from CodeBuild
            # Need to get profile to determine region
            from ...config import Config

            config = Config.load()
            profile = config.get_profile("default")
            if not profile:
                console.print("[red]No configuration found. Run 'poetry run ccwb init' first.[/red]")
                return 1

            codebuild = boto3.client("codebuild", region_name=profile.aws_region)
            response = codebuild.batch_get_builds(ids=[build_id])

            if not response.get("builds"):
                console.print(f"[red]Build not found: {build_id}[/red]")
                return 1

            build = response["builds"][0]
            status = build["buildStatus"]

            # Display status
            if status == "IN_PROGRESS":
                console.print("[yellow]⏳ Build in progress[/yellow]")
                console.print(f"Phase: {build.get('currentPhase', 'Unknown')}")
                if "startTime" in build:
                    start_time = build["startTime"]
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    console.print(f"Elapsed: {int(elapsed.total_seconds() / 60)} minutes")
            elif status == "SUCCEEDED":
                console.print("[green]✓ Build succeeded![/green]")
                console.print(f"Duration: {build.get('buildDurationInMinutes', 'Unknown')} minutes")
                console.print("\n[bold]Windows build artifacts are ready![/bold]")
                console.print("Next steps:")
                console.print("  1. Run: [cyan]poetry run ccwb package --target-platform all[/cyan]")
                console.print("     (This will download the Windows artifacts)")
                console.print("  2. Run: [cyan]poetry run ccwb distribute[/cyan]")
                console.print("     (This will create the distribution URL)")
            else:
                console.print(f"[red]✗ Build {status.lower()}[/red]")
                if "phases" in build:
                    for phase in build["phases"]:
                        if phase.get("phaseStatus") == "FAILED":
                            console.print(f"[red]Failed in phase: {phase.get('phaseType')}[/red]")

            # Show console link
            project_name = build_id.split(":")[0]
            build_uuid = build_id.split(":")[1]
            console.print(
                f"\n[dim]View logs: https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_uuid}[/dim]"
            )

            return 0

        except Exception as e:
            console.print(f"[red]Error checking build status: {e}[/red]")
            return 1
