# ABOUTME: CodeBuild package command for building binaries via AWS CodeBuild
# ABOUTME: Supports Windows, Linux x64, and Linux ARM64 builds from any platform

"""Package CodeBuild command - Build binaries using AWS CodeBuild from any platform."""

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config

# Platform to CodeBuild project suffix and artifact key mapping
CODEBUILD_PLATFORMS = {
    "windows": {
        "project_suffix": "windows-build",
        "output_key": "ProjectName",
        "artifact_key": "windows-binaries.zip",
        "description": "Windows (Nuitka + MinGW)",
    },
    "linux-x64": {
        "project_suffix": "linux-x64-build",
        "output_key": "LinuxX64ProjectName",
        "artifact_key": "linux-x64-binaries.zip",
        "description": "Linux x64 (PyInstaller)",
    },
    "linux-arm64": {
        "project_suffix": "linux-arm64-build",
        "output_key": "LinuxArm64ProjectName",
        "artifact_key": "linux-arm64-binaries.zip",
        "description": "Linux ARM64 (PyInstaller)",
    },
}


class PackageCbCommand(Command):
    """
    Build binaries using AWS CodeBuild

    Packages source code, uploads to S3, and starts CodeBuild projects
    to compile binaries for selected platforms. Use 'ccwb builds' to
    monitor progress and 'ccwb builds --download' to retrieve artifacts.

    package_cb
    """

    name = "package_cb"
    description = "Build binaries using AWS CodeBuild (Windows, Linux x64, Linux ARM64)"

    options = [
        option(
            "profile",
            description="Configuration profile to use (defaults to active profile)",
            flag=False,
            default=None,
        ),
        option(
            "platform",
            description="Platform(s) to build: windows, linux-x64, linux-arm64, all (comma-separated)",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:
        """Execute the package_cb command."""
        console = Console()

        console.print()
        console.print("[bold]CodeBuild Package Builder[/bold]")
        console.print("Builds binaries using AWS CodeBuild infrastructure")
        console.print()

        # Load configuration
        config = Config.load()
        profile_name = self.option("profile")
        if not profile_name:
            profile_name = config.active_profile

        profile = config.get_profile(profile_name)

        if not profile:
            if profile_name:
                console.print(f"[red]Profile '{profile_name}' not found. Run 'ccwb init' first.[/red]")
            else:
                console.print("[red]No active profile set. Run 'ccwb init' or 'ccwb context use <profile>' first.[/red]")
            return 1

        # Check CodeBuild is enabled
        if not getattr(profile, "enable_codebuild", False):
            console.print("[red]CodeBuild is not enabled for this profile.[/red]")
            console.print("To enable CodeBuild:")
            console.print("  1. Run: poetry run ccwb init")
            console.print("  2. Answer 'Yes' when asked about Windows build support")
            console.print("  3. Run: poetry run ccwb deploy codebuild")
            return 1

        # Get CodeBuild stack outputs
        stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
        try:
            stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
        except Exception:
            console.print(f"[red]CodeBuild stack not found: {stack_name}[/red]")
            console.print("Run: poetry run ccwb deploy codebuild")
            return 1

        bucket_name = stack_outputs.get("BuildBucket")
        if not bucket_name:
            console.print("[red]CodeBuild stack outputs incomplete (missing bucket)[/red]")
            return 1

        # Determine which platforms to build
        selected_platforms = self._select_platforms(console, stack_outputs)
        if not selected_platforms:
            console.print("[yellow]No platforms selected.[/yellow]")
            return 0

        # Check for in-progress builds
        codebuild = boto3.client("codebuild", region_name=profile.aws_region)
        for plat in selected_platforms:
            project_name = stack_outputs.get(CODEBUILD_PLATFORMS[plat]["output_key"])
            if not project_name:
                continue
            try:
                response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")
                if response.get("ids"):
                    builds_response = codebuild.batch_get_builds(ids=response["ids"][:3])
                    for build in builds_response.get("builds", []):
                        if build["buildStatus"] == "IN_PROGRESS":
                            console.print(
                                f"[yellow]{plat} build already in progress "
                                f"(started {build['startTime'].strftime('%Y-%m-%d %H:%M')})[/yellow]"
                            )
                            selected_platforms = [p for p in selected_platforms if p != plat]
            except Exception:
                pass

        if not selected_platforms:
            console.print("\n[yellow]All selected platforms have builds in progress.[/yellow]")
            console.print("Check status: [cyan]poetry run ccwb builds[/cyan]")
            return 0

        # Show configuration
        console.print(f"  Profile:   [cyan]{profile_name}[/cyan]")
        console.print(f"  Bucket:    [cyan]{bucket_name}[/cyan]")
        console.print(f"  Region:    [cyan]{profile.aws_region}[/cyan]")
        console.print(f"  Platforms: [cyan]{', '.join(selected_platforms)}[/cyan]")
        console.print()

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # Step 1: Package source code
            task = progress.add_task("Packaging source code...", total=None)
            source_zip = self._package_source()
            progress.update(task, description=f"Source packaged ({source_zip.stat().st_size // 1024} KB)")
            progress.update(task, completed=True)

            # Step 2: Upload to S3
            task = progress.add_task("Uploading source to S3...", total=None)
            s3 = boto3.client("s3", region_name=profile.aws_region)
            try:
                s3.upload_file(str(source_zip), bucket_name, "source.zip")
            except ClientError as e:
                console.print(f"[red]Failed to upload source: {e}[/red]")
                return 1
            finally:
                source_zip.unlink(missing_ok=True)
            progress.update(task, description="Source uploaded to S3")
            progress.update(task, completed=True)

            # Step 3: Start builds for each platform
            build_ids = {}
            for plat in selected_platforms:
                plat_config = CODEBUILD_PLATFORMS[plat]
                project_name = stack_outputs.get(plat_config["output_key"])
                if not project_name:
                    console.print(f"[yellow]Project not found for {plat} — deploy codebuild stack to add it[/yellow]")
                    continue

                task = progress.add_task(f"Starting {plat} build...", total=None)
                try:
                    response = codebuild.start_build(projectName=project_name)
                    build_id = response["build"]["id"]
                    build_ids[plat] = build_id
                    progress.update(task, description=f"{plat} build started")
                except ClientError as e:
                    progress.update(task, description=f"[red]{plat} failed to start: {e}[/red]")
                progress.update(task, completed=True)

        if not build_ids:
            console.print("[red]No builds were started.[/red]")
            return 1

        # Store build info for 'ccwb builds --status latest'
        build_info_file = Path.home() / ".claude-code" / "latest-build.json"
        build_info_file.parent.mkdir(exist_ok=True)

        # Store the first build as "latest" for backwards compatibility
        first_build_id = next(iter(build_ids.values()))
        first_project = first_build_id.split(":")[0]
        with open(build_info_file, "w") as f:
            json.dump(
                {
                    "build_id": first_build_id,
                    "started_at": datetime.now().isoformat(),
                    "project": first_project,
                    "bucket": bucket_name,
                    "all_builds": {plat: bid for plat, bid in build_ids.items()},
                },
                f,
            )

        # Summary
        console.print()
        console.print("[bold green]CodeBuild started![/bold green]")
        console.print()
        for plat, bid in build_ids.items():
            console.print(f"  {CODEBUILD_PLATFORMS[plat]['description']}")
            console.print(f"    [dim]Build ID: {bid}[/dim]")
        console.print()
        console.print("Builds will take approximately 10-15 minutes each.")

        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Check progress:    [cyan]poetry run ccwb builds[/cyan]")
        console.print("  2. Check completion:  [cyan]poetry run ccwb builds --status latest[/cyan]")
        console.print("  3. Download binaries: [cyan]poetry run ccwb builds --status latest --download[/cyan]")
        console.print("  4. Distribute:        [cyan]poetry run ccwb distribute[/cyan]")

        console.print()
        console.print("[dim]View logs in AWS Console:[/dim]")
        for plat, bid in build_ids.items():
            project_name = bid.split(":")[0]
            build_uuid = bid.split(":")[1]
            console.print(
                f"  [dim]{plat}: https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_uuid}[/dim]"
            )

        return 0

    def _select_platforms(self, console: Console, stack_outputs: dict) -> list[str]:
        """Let user select which platforms to build."""
        platform_opt = self.option("platform")

        if platform_opt:
            # Parse comma-separated platforms
            if platform_opt == "all":
                return [p for p in CODEBUILD_PLATFORMS if stack_outputs.get(CODEBUILD_PLATFORMS[p]["output_key"])]
            platforms = [p.strip() for p in platform_opt.split(",")]
            valid = []
            for p in platforms:
                if p in CODEBUILD_PLATFORMS:
                    if stack_outputs.get(CODEBUILD_PLATFORMS[p]["output_key"]):
                        valid.append(p)
                    else:
                        console.print(f"[yellow]{p} project not deployed — skipping[/yellow]")
                else:
                    console.print(f"[yellow]Unknown platform: {p} (valid: {', '.join(CODEBUILD_PLATFORMS.keys())})[/yellow]")
            return valid

        # Interactive selection
        try:
            import questionary

            # Build choices based on what's deployed
            choices = []
            for plat, config in CODEBUILD_PLATFORMS.items():
                if stack_outputs.get(config["output_key"]):
                    choices.append(questionary.Choice(f"{plat} — {config['description']}", value=plat, checked=True))
                else:
                    choices.append(questionary.Choice(f"{plat} — {config['description']} (not deployed)", value=plat, disabled="deploy codebuild stack first"))

            selected = questionary.checkbox(
                "Select platform(s) to build (space to select, enter to confirm):",
                choices=choices,
                validate=lambda x: len(x) > 0 or "Select at least one platform",
            ).ask()

            return selected if selected else []
        except (ImportError, EOFError):
            # Non-interactive fallback: build all available
            return [p for p in CODEBUILD_PLATFORMS if stack_outputs.get(CODEBUILD_PLATFORMS[p]["output_key"])]

    def _package_source(self) -> Path:
        """Package source code into a zip for CodeBuild."""
        temp_dir = Path(tempfile.mkdtemp())
        source_zip = temp_dir / "source.zip"

        # Go up to source/ directory
        source_dir = Path(__file__).parents[3]

        with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for py_file in source_dir.rglob("*.py"):
                # Use forward slashes in zip (POSIX format) for CodeBuild compatibility
                arcname = py_file.relative_to(source_dir.parent).as_posix()
                zf.write(py_file, arcname)

            pyproject_file = source_dir / "pyproject.toml"
            if pyproject_file.exists():
                zf.write(pyproject_file, "pyproject.toml")

        return source_zip
