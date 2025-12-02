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
        option("profile", description="Configuration profile to use (defaults to active profile)", flag=False, default=None),
        option("limit", description="Number of builds to show", flag=False, default="10"),
        option("project", description="CodeBuild project name (default: auto-detect)", flag=False),
        option("status", description="Check status of a specific build by ID", flag=False),
        option("download", description="Download completed Windows artifacts to dist folder", flag=True),
    ]

    def handle(self) -> int:
        """Execute the builds command."""
        console = Console()

        # Check if this is a status check for a specific build
        if self.option("status"):
            return self._check_build_status(self.option("status"), console)

        try:
            # Load configuration
            from ...config import Config

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

            # Auto-detect project name from config if not provided
            project_name = self.option("project")
            if not project_name:
                project_name = f"{profile.identity_pool_name}-windows-build"

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
            console.print("\n[dim]To download completed Windows artifacts:[/dim]")
            console.print("  poetry run ccwb builds --status latest --download")
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
            # Load configuration
            from ...config import Config

            config = Config.load()

            # Get profile name (use active profile if not specified)
            profile_name = self.option("profile")
            if not profile_name:
                profile_name = config.active_profile

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

                # Calculate duration
                if "endTime" in build and "startTime" in build:
                    duration = build["endTime"] - build["startTime"]
                    duration_min = int(duration.total_seconds() / 60)
                    console.print(f"Duration: {duration_min} minutes")
                else:
                    console.print("Duration: Unknown")

                console.print("\n[bold]Windows build artifacts are ready![/bold]")

                # Download artifacts if --download flag is provided
                if self.option("download"):
                    console.print("\n[cyan]Finding latest package directory...[/cyan]")
                    from pathlib import Path

                    # Find the correct package directory to download into
                    target_dir = self._find_latest_package_directory(console)

                    if not target_dir:
                        console.print("[red]✗ No package directory found in dist/[/red]")
                        console.print("[yellow]Run 'poetry run ccwb package' first to create a package[/yellow]")
                        return 1

                    # Try to show relative path, fall back to absolute if not possible
                    try:
                        display_path = target_dir.relative_to(Path.cwd())
                    except ValueError:
                        display_path = target_dir

                    console.print(f"[dim]Target: {display_path}[/dim]")
                    console.print("\n[cyan]Downloading Windows artifacts...[/cyan]")

                    if self._download_windows_artifacts(profile, target_dir, console):
                        console.print("[green]✓ Downloaded Windows artifacts[/green]")
                        console.print(f"Location: {display_path}")
                        console.print("\n[bold]Next steps:[/bold]")
                        console.print("  Run: [cyan]poetry run ccwb distribute[/cyan]")
                        console.print("  This will create your distribution package with Windows binaries included")
                    else:
                        console.print("[red]✗ Failed to download artifacts[/red]")
                else:
                    console.print("\nNext steps:")
                    console.print("  Run: [cyan]poetry run ccwb distribute[/cyan]")
                    console.print("  This will download Windows artifacts and create distribution package")
                    console.print("\n  Or run: [cyan]poetry run ccwb builds --status latest --download[/cyan]")
                    console.print("  This will download Windows artifacts to your latest package directory")
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

    def _find_latest_package_directory(self, console: Console):
        """Find the latest package directory in dist/."""
        from pathlib import Path

        # Get the source directory (where dist/ is located)
        source_dir = Path(__file__).parents[3]
        dist_dir = source_dir / "dist"

        if not dist_dir.exists():
            return None

        # Scan for organized structure: dist/<profile>/<timestamp>/
        latest_dir = None
        latest_timestamp = None

        for profile_dir in dist_dir.iterdir():
            if not profile_dir.is_dir():
                continue

            # Look for timestamp directories within this profile
            for timestamp_dir in profile_dir.iterdir():
                if not timestamp_dir.is_dir():
                    continue

                # Check if this looks like a package directory (has config.json)
                if (timestamp_dir / "config.json").exists():
                    # Use directory name as timestamp for comparison
                    timestamp = timestamp_dir.name

                    # Keep track of the latest
                    if latest_timestamp is None or timestamp > latest_timestamp:
                        latest_timestamp = timestamp
                        latest_dir = timestamp_dir

        return latest_dir

    def _download_windows_artifacts(self, profile, package_path, console: Console) -> bool:
        """Download Windows build artifacts from S3."""
        import zipfile

        from botocore.exceptions import ClientError

        try:
            # Windows artifacts are in the CodeBuild bucket
            if not profile.enable_codebuild:
                console.print("[red]CodeBuild is not enabled for this profile[/red]")
                return False

            # Get CodeBuild stack outputs
            from ...cli.utils.aws import get_stack_outputs

            codebuild_stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
            codebuild_outputs = get_stack_outputs(codebuild_stack_name, profile.aws_region)

            if not codebuild_outputs:
                console.print("[red]CodeBuild stack not found[/red]")
                return False

            bucket_name = codebuild_outputs.get("BuildBucket")
            if not bucket_name:
                console.print("[red]Could not get CodeBuild bucket from stack outputs[/red]")
                return False

            # Download from S3
            s3 = boto3.client("s3", region_name=profile.aws_region)
            zip_path = package_path / "windows-binaries.zip"

            # CodeBuild stores artifacts at root of bucket
            artifact_key = "windows-binaries.zip"

            try:
                s3.download_file(bucket_name, artifact_key, str(zip_path))

                # Extract binaries
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(package_path)

                # Clean up zip file
                zip_path.unlink()
                return True

            except ClientError as e:
                console.print(f"[red]Failed to download artifacts: {e}[/red]")
                console.print(f"[dim]Tried: s3://{bucket_name}/{artifact_key}[/dim]")
                return False

        except Exception as e:
            console.print(f"[red]Error downloading Windows artifacts: {e}[/red]")
            return False
