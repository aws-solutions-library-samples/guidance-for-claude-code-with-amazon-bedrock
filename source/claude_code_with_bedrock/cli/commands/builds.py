# ABOUTME: Command for listing and managing CodeBuild builds
# ABOUTME: Supports all platforms: Windows, Linux x64, and Linux ARM64

"""Builds command for listing and managing CodeBuild builds."""

import json
import zipfile
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.table import Table

from claude_code_with_bedrock.cli.commands.package_cb import CODEBUILD_PLATFORMS
from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config


class BuildsCommand(Command):
    """
    List and manage CodeBuild builds

    Shows recent builds, their status, and duration across all platforms.
    """

    name = "builds"
    description = "List and manage CodeBuild builds"

    options = [
        option(
            "profile", description="Configuration profile to use (defaults to active profile)", flag=False, default=None
        ),
        option("limit", description="Number of builds to show per project", flag=False, default="5"),
        option("project", description="CodeBuild project name (default: auto-detect all)", flag=False),
        option("status", description="Check status of builds (use 'latest' for most recent)", flag=False),
        option("download", description="Download completed artifacts to dist folder", flag=True),
    ]

    def handle(self) -> int:
        """Execute the builds command."""
        console = Console()

        config = Config.load()
        profile_name = self.option("profile")
        if not profile_name:
            profile_name = config.active_profile
        profile = config.get_profile(profile_name)

        if not profile:
            if profile_name:
                console.print(f"[red]Profile '{profile_name}' not found. Run 'ccwb init' first.[/red]")
            else:
                console.print(
                    "[red]No active profile set. Run 'ccwb init' or 'ccwb context use <profile>' first.[/red]"
                )
            return 1

        if self.option("status"):
            return self._check_all_builds(profile, profile_name, console)

        return self._list_all_builds(profile, console)

    def _get_codebuild_projects(self, profile) -> dict[str, str]:
        """Get all CodeBuild project names from stack outputs."""
        stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
        try:
            stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
        except Exception:
            return {}

        if not stack_outputs:
            return {}

        projects = {}
        for plat, plat_config in CODEBUILD_PLATFORMS.items():
            project_name = stack_outputs.get(plat_config["output_key"])
            if project_name:
                projects[plat] = project_name
        return projects

    def _list_all_builds(self, profile, console: Console) -> int:
        """List recent builds across all platforms."""
        projects = self._get_codebuild_projects(profile)
        if not projects:
            console.print("[yellow]No CodeBuild projects found. Run 'ccwb deploy codebuild' first.[/yellow]")
            return 1

        codebuild = boto3.client("codebuild", region_name=profile.aws_region)
        limit = int(self.option("limit"))

        for plat, project_name in projects.items():
            try:
                response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")
                build_ids = response.get("ids", [])[:limit]

                if not build_ids:
                    console.print(f"\n[dim]{plat}: No builds found[/dim]")
                    continue

                builds_response = codebuild.batch_get_builds(ids=build_ids)

                table = Table(title=f"{plat} ({CODEBUILD_PLATFORMS[plat]['description']})")
                table.add_column("Build ID", style="cyan")
                table.add_column("Status", style="bold")
                table.add_column("Started", style="dim")
                table.add_column("Duration", style="dim")

                for build in builds_response.get("builds", []):
                    build_id = build["id"].split(":")[1][:8]
                    status = build["buildStatus"]

                    if status == "SUCCEEDED":
                        status_display = "[green]Succeeded[/green]"
                    elif status == "IN_PROGRESS":
                        status_display = "[yellow]In Progress[/yellow]"
                    elif status == "FAILED":
                        status_display = "[red]Failed[/red]"
                    else:
                        status_display = f"[dim]{status}[/dim]"

                    start_time = build.get("startTime")
                    started = start_time.strftime("%Y-%m-%d %H:%M") if start_time else "Unknown"

                    if "endTime" in build and "startTime" in build:
                        duration = build["endTime"] - build["startTime"]
                        duration_display = f"{int(duration.total_seconds() / 60)} min"
                    elif status == "IN_PROGRESS" and start_time:
                        elapsed = datetime.now(start_time.tzinfo) - start_time
                        duration_display = f"{int(elapsed.total_seconds() / 60)} min (running)"
                    else:
                        duration_display = "-"

                    table.add_row(build_id, status_display, started, duration_display)

                console.print()
                console.print(table)

            except ClientError as e:
                console.print(f"\n[yellow]{plat}: Could not list builds — {e}[/yellow]")

        console.print()
        console.print("[dim]Check latest build status:[/dim]  poetry run ccwb builds --status latest")
        console.print("[dim]Download artifacts:[/dim]         poetry run ccwb builds --status latest --download")
        return 0

    def _check_all_builds(self, profile, profile_name: str, console: Console) -> int:
        """Check status of all platform builds and optionally download artifacts."""
        build_id_input = self.option("status")

        # Load stored build info
        all_build_ids = {}
        if build_id_input == "latest":
            build_info_file = Path.home() / ".claude-code" / "latest-build.json"
            if not build_info_file.exists():
                console.print("[red]No recent builds found. Start builds with 'ccwb package_cb'.[/red]")
                return 1
            with open(build_info_file, encoding="utf-8") as f:
                build_info = json.load(f)
            all_build_ids = build_info.get("all_builds", {})
            if not all_build_ids:
                # Fallback for old format (single build_id)
                old_id = build_info.get("build_id")
                if old_id:
                    all_build_ids = {"windows": old_id}
        else:
            # Single build ID provided — try to detect which platform
            all_build_ids = {"unknown": build_id_input}

        if not all_build_ids:
            console.print("[red]No build IDs found.[/red]")
            return 1

        codebuild = boto3.client("codebuild", region_name=profile.aws_region)

        # Resolve all build IDs and check status
        succeeded = {}
        failed = {}
        in_progress = {}

        console.print()
        console.print("[bold]Build Status[/bold]")
        console.print()

        for plat, bid in all_build_ids.items():
            # Resolve short IDs
            if ":" not in bid:
                projects = self._get_codebuild_projects(profile)
                if plat in projects:
                    bid = f"{projects[plat]}:{bid}"

            try:
                response = codebuild.batch_get_builds(ids=[bid])
                if not response.get("builds"):
                    console.print(f"  [red]{plat}: Build not found ({bid})[/red]")
                    failed[plat] = bid
                    continue

                build = response["builds"][0]
                status = build["buildStatus"]
                duration_str = ""
                if "endTime" in build and "startTime" in build:
                    duration = build["endTime"] - build["startTime"]
                    duration_str = f" ({int(duration.total_seconds() / 60)} min)"
                elif status == "IN_PROGRESS" and "startTime" in build:
                    elapsed = datetime.now(build["startTime"].tzinfo) - build["startTime"]
                    duration_str = f" ({int(elapsed.total_seconds() / 60)} min elapsed)"

                if status == "SUCCEEDED":
                    console.print(f"  [green]OK[/green]  {plat}{duration_str}")
                    succeeded[plat] = bid
                elif status == "IN_PROGRESS":
                    phase = build.get("currentPhase", "")
                    console.print(f"  [yellow]...[/yellow] {plat} — {phase}{duration_str}")
                    in_progress[plat] = bid
                else:
                    console.print(f"  [red]FAIL[/red] {plat} — {status}{duration_str}")
                    if "phases" in build:
                        for phase in build["phases"]:
                            if phase.get("phaseStatus") == "FAILED":
                                console.print(f"        Failed in: {phase.get('phaseType')}")
                    failed[plat] = bid

            except ClientError as e:
                console.print(f"  [red]ERR[/red]  {plat} — {e}")
                failed[plat] = bid

        # Summary
        console.print()
        total = len(all_build_ids)
        if len(succeeded) == total:
            console.print(f"[bold green]All {total} builds succeeded.[/bold green]")
        else:
            parts = []
            if succeeded:
                parts.append(f"[green]{len(succeeded)} succeeded[/green]")
            if in_progress:
                parts.append(f"[yellow]{len(in_progress)} in progress[/yellow]")
            if failed:
                parts.append(f"[red]{len(failed)} failed[/red]")
            console.print(f"Summary: {', '.join(parts)} (of {total})")

        # Download if requested
        if self.option("download"):
            if not succeeded:
                console.print("\n[yellow]No successful builds to download.[/yellow]")
                if in_progress:
                    console.print("[dim]Wait for in-progress builds to complete, then retry.[/dim]")
                return 1

            return self._download_artifacts(profile, profile_name, succeeded, console)
        else:
            if succeeded and not self.option("download"):
                console.print()
                console.print("[dim]Download artifacts:[/dim]  poetry run ccwb builds --status latest --download")
            if in_progress:
                console.print("[dim]Re-check status:[/dim]    poetry run ccwb builds --status latest")

        return 0

    def _download_artifacts(self, profile, profile_name: str, succeeded: dict[str, str], console: Console) -> int:
        """Download artifacts for all succeeded builds."""
        # Get CodeBuild bucket
        stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
        try:
            stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
        except Exception:
            console.print("[red]CodeBuild stack not found.[/red]")
            return 1

        bucket_name = stack_outputs.get("BuildBucket")
        if not bucket_name:
            console.print("[red]Could not get CodeBuild bucket from stack outputs.[/red]")
            return 1

        # Find target directory
        target_dir = self._find_latest_package_directory()
        if not target_dir:
            console.print("[red]No package directory found in dist/.[/red]")
            console.print("[yellow]Run 'ccwb package_cb' first to create a package directory.[/yellow]")
            return 1

        try:
            display_path = target_dir.relative_to(Path.cwd())
        except ValueError:
            display_path = target_dir

        console.print()
        console.print(f"[bold]Downloading to:[/bold] {display_path}")
        console.print()

        s3 = boto3.client("s3", region_name=profile.aws_region)
        downloaded = []
        download_failed = []

        for plat in succeeded:
            if plat not in CODEBUILD_PLATFORMS:
                download_failed.append((plat, "Unknown platform"))
                continue

            artifact_key = CODEBUILD_PLATFORMS[plat]["artifact_key"]

            try:
                zip_path = target_dir / artifact_key
                s3.download_file(bucket_name, artifact_key, str(zip_path))

                # Extract binaries one-by-one using read/write to avoid
                # Windows Defender file locking issues with extractall()
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    names = zip_ref.namelist()
                    for member in names:
                        if member.endswith("/"):
                            continue
                        filename = Path(member).name
                        if not filename:
                            continue
                        target_path = target_dir / filename
                        data = zip_ref.read(member)
                        for attempt in range(3):
                            try:
                                target_path.write_bytes(data)
                                break
                            except PermissionError:
                                if attempt < 2:
                                    import time
                                    time.sleep(1)
                                else:
                                    raise

                zip_path.unlink()
                downloaded.append((plat, names))
                console.print(f"  [green]OK[/green]  {plat}: {', '.join(names)}")

            except ClientError as e:
                download_failed.append((plat, str(e)))
                console.print(f"  [red]FAIL[/red] {plat}: {e}")
                console.print(f"        [dim]Tried: s3://{bucket_name}/{artifact_key}[/dim]")
            except Exception as e:
                download_failed.append((plat, str(e)))
                console.print(f"  [red]FAIL[/red] {plat}: {e}")

        # Download summary
        console.print()
        if downloaded and not download_failed:
            console.print(f"[bold green]All {len(downloaded)} artifacts downloaded.[/bold green]")
        elif downloaded:
            console.print(
                f"[yellow]Downloaded {len(downloaded)} of {len(downloaded) + len(download_failed)} artifacts.[/yellow]"
            )
        else:
            console.print("[red]No artifacts downloaded.[/red]")
            return 1

        console.print()
        console.print("[bold]Next step:[/bold]  poetry run ccwb distribute")
        return 0

    def _find_latest_package_directory(self) -> Path | None:
        """Find the latest package directory in dist/."""
        source_dir = Path(__file__).parents[3]
        dist_dir = source_dir / "dist"

        if not dist_dir.exists():
            return None

        latest_dir = None
        latest_timestamp = None

        for profile_dir in dist_dir.iterdir():
            if not profile_dir.is_dir():
                continue
            for timestamp_dir in profile_dir.iterdir():
                if not timestamp_dir.is_dir():
                    continue
                if (timestamp_dir / "config.json").exists():
                    timestamp = timestamp_dir.name
                    if latest_timestamp is None or timestamp > latest_timestamp:
                        latest_timestamp = timestamp
                        latest_dir = timestamp_dir

        return latest_dir
