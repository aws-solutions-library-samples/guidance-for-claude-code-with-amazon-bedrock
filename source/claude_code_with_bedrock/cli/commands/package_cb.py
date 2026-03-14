# ABOUTME: CodeBuild package command for building binaries via AWS CodeBuild
# ABOUTME: Supports Windows, Linux x64, and Linux ARM64 builds from any platform
# ABOUTME: On macOS, also builds Mac binaries locally alongside CodeBuild remote builds

"""Package CodeBuild command - Build binaries using AWS CodeBuild from any platform."""

import json
import platform as platform_mod
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import boto3
import questionary
from botocore.exceptions import ClientError
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.models import get_source_region_for_profile

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
    description = "Build distribution packages using CodeBuild (+ local macOS builds on Mac)"

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
        option("build-verbose", description="Enable verbose logging for build processes", flag=True),
    ]

    def handle(self) -> int:
        """Execute the package_cb command."""
        console = Console()

        console.print()
        console.print("[bold]CodeBuild Package Builder[/bold]")
        console.print("Builds binaries using AWS CodeBuild infrastructure")
        if platform_mod.system().lower() == "darwin":
            console.print("[dim]macOS binaries will be built locally[/dim]")
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
                console.print(
                    "[red]No active profile set. Run 'ccwb init' or 'ccwb context use <profile>' first.[/red]"
                )
            return 1

        # Check CodeBuild is enabled
        if not getattr(profile, "enable_codebuild", False):
            console.print("[red]CodeBuild is not enabled for this profile.[/red]")
            console.print("To enable CodeBuild:")
            console.print("  1. Run: poetry run ccwb init")
            console.print("  2. Answer 'Yes' when asked about Windows build support")
            console.print("  3. Run: poetry run ccwb deploy codebuild")
            return 1

        # Prompt for co-authorship preference
        include_coauthored_by = questionary.confirm(
            "Include 'Co-Authored-By: Claude' in git commits?",
            default=False,
        ).ask()

        # Prompt for custom OTel resource attributes (only when monitoring is enabled)
        otel_resource_attributes = None
        if profile.monitoring_enabled:
            customize_otel = questionary.confirm(
                "Customize telemetry resource attributes? (department, team, cost center)",
                default=False,
            ).ask()

            if customize_otel:
                console.print(
                    "[dim]Example: department=platform, team.id=infra-core, "
                    "cost_center=CC-4521, organization=acme-corp[/dim]"
                )
                department = questionary.text("Department:", default="engineering").ask()
                team_id = questionary.text("Team ID:", default="default").ask()
                cost_center = questionary.text("Cost center:", default="default").ask()
                organization = questionary.text("Organization:", default="default").ask()
                otel_resource_attributes = (
                    f"department={department},team.id={team_id},"
                    f"cost_center={cost_center},organization={organization}"
                )

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

        # Determine which platforms to build via CodeBuild
        selected_platforms = self._select_platforms(console, stack_outputs)
        if not selected_platforms:
            console.print("[yellow]No CodeBuild platforms selected.[/yellow]")

        # Check for in-progress builds
        codebuild = boto3.client("codebuild", region_name=profile.aws_region)
        for plat in list(selected_platforms):
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
            console.print("\n[yellow]All selected CodeBuild platforms have builds in progress.[/yellow]")
            console.print("Check status: [cyan]poetry run ccwb builds[/cyan]")

        # Create timestamped output directory
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_dir = Path("./dist") / profile_name / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build local macOS binaries if running on Mac
        built_executables: list[tuple[str, Path]] = []
        built_otel_helpers: list[tuple[str, Path]] = []
        if platform_mod.system().lower() == "darwin":
            console.print("\n[cyan]Building local macOS binaries...[/cyan]")
            current_machine = platform_mod.machine().lower()
            mac_platform = "macos-arm64" if current_machine == "arm64" else "macos-intel"

            from claude_code_with_bedrock.cli.commands.package import PackageCommand

            pkg_cmd = PackageCommand()
            # Wire the build-verbose option through
            pkg_cmd._application = self._application

            try:
                console.print(f"[cyan]Building credential process for {mac_platform}...[/cyan]")
                arch = "arm64" if current_machine == "arm64" else "x86_64"
                exe_path = pkg_cmd._build_macos_pyinstaller(output_dir, arch)
                if exe_path and exe_path.exists():
                    built_executables.append((mac_platform, exe_path))
            except Exception as e:
                console.print(f"[yellow]Warning: Could not build credential process for {mac_platform}: {e}[/yellow]")

            if profile.monitoring_enabled:
                try:
                    console.print(f"[cyan]Building OTEL helper for {mac_platform}...[/cyan]")
                    otel_path = pkg_cmd._build_otel_helper_pyinstaller(output_dir, "macos", arch)
                    if otel_path and otel_path.exists():
                        built_otel_helpers.append((mac_platform, otel_path))
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not build OTEL helper for {mac_platform}: {e}[/yellow]")

        # Get auth stack outputs for config/installer creation
        auth_stack_outputs = get_stack_outputs(
            profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack"), profile.aws_region
        )
        federation_type = (
            auth_stack_outputs.get("FederationType", profile.federation_type)
            if auth_stack_outputs
            else profile.federation_type
        )

        # Create configuration, installer, docs, and settings
        from claude_code_with_bedrock.cli.commands.package import PackageCommand as _PkgCmd

        pkg = _PkgCmd()
        pkg._application = self._application

        if auth_stack_outputs:
            federation_identifier = (
                auth_stack_outputs.get("DirectSTSRoleArn") or auth_stack_outputs.get("FederatedRoleArn")
                if federation_type == "direct"
                else auth_stack_outputs.get("IdentityPoolId")
            )
            if federation_identifier:
                console.print("\n[cyan]Creating configuration...[/cyan]")
                pkg._create_config(output_dir, profile, federation_identifier, federation_type, profile_name)

                console.print("[cyan]Creating installer script...[/cyan]")
                pkg._create_installer(output_dir, profile, built_executables, built_otel_helpers)

                console.print("[cyan]Creating documentation...[/cyan]")
                pkg._create_documentation(output_dir, profile, timestamp)

        console.print("[cyan]Creating Claude Code settings...[/cyan]")
        self._create_claude_settings(
            output_dir, profile, include_coauthored_by, profile_name, otel_resource_attributes
        )

        # Show configuration
        console.print()
        console.print(f"  Profile:   [cyan]{profile_name}[/cyan]")
        console.print(f"  Bucket:    [cyan]{bucket_name}[/cyan]")
        console.print(f"  Region:    [cyan]{profile.aws_region}[/cyan]")
        console.print(f"  Output:    [cyan]{output_dir}[/cyan]")
        if selected_platforms:
            console.print(f"  CodeBuild: [cyan]{', '.join(selected_platforms)}[/cyan]")
        if built_executables:
            console.print(f"  Local:     [cyan]{', '.join(p for p, _ in built_executables)}[/cyan]")
        console.print()

        # Start CodeBuild builds
        build_ids = {}
        if selected_platforms:
            with Progress(
                SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
            ) as progress:
                # Package and upload source
                task = progress.add_task("Packaging source code...", total=None)
                source_zip = self._package_source()
                progress.update(task, description=f"Source packaged ({source_zip.stat().st_size // 1024} KB)")
                progress.update(task, completed=True)

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

                # Start builds
                for plat in selected_platforms:
                    plat_config = CODEBUILD_PLATFORMS[plat]
                    project_name = stack_outputs.get(plat_config["output_key"])
                    if not project_name:
                        console.print(
                        f"[yellow]Project not found for {plat} — deploy codebuild stack to add it[/yellow]"
                    )
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

        # Store build info for 'ccwb builds --status latest'
        if build_ids:
            build_info_file = Path.home() / ".claude-code" / "latest-build.json"
            build_info_file.parent.mkdir(exist_ok=True)

            first_build_id = next(iter(build_ids.values()))
            first_project = first_build_id.split(":")[0]
            with open(build_info_file, "w") as f:
                json.dump(
                    {
                        "build_id": first_build_id,
                        "started_at": datetime.now().isoformat(),
                        "project": first_project,
                        "bucket": bucket_name,
                        "all_builds": dict(build_ids.items()),
                    },
                    f,
                )

        # Summary
        console.print()
        if built_executables:
            console.print("[bold green]Local macOS binaries built![/bold green]")
            for plat_name, exe_path in built_executables:
                console.print(f"  {exe_path.name} ({plat_name})")
            for plat_name, otel_path in built_otel_helpers:
                console.print(f"  {otel_path.name} ({plat_name})")

        if build_ids:
            console.print("[bold green]CodeBuild started![/bold green]")
            for plat, bid in build_ids.items():
                console.print(f"  {CODEBUILD_PLATFORMS[plat]['description']}")
                console.print(f"    [dim]Build ID: {bid}[/dim]")
            console.print()
            console.print("CodeBuild will take approximately 10-15 minutes per platform.")

        console.print()
        console.print("[bold]Next steps:[/bold]")
        if build_ids:
            console.print("  1. Check progress:    [cyan]poetry run ccwb builds[/cyan]")
            console.print("  2. Check completion:  [cyan]poetry run ccwb builds --status latest[/cyan]")
            console.print("  3. Download binaries: [cyan]poetry run ccwb builds --status latest --download[/cyan]")
            console.print("  4. Distribute:        [cyan]poetry run ccwb distribute[/cyan]")
        else:
            console.print("  1. Distribute:  [cyan]poetry run ccwb distribute[/cyan]")
            console.print(f"  2. Or send the package directory to users: [cyan]{output_dir}[/cyan]")

        if build_ids:
            console.print()
            console.print("[dim]View logs in AWS Console:[/dim]")
            for plat, bid in build_ids.items():
                project_name = bid.split(":")[0]
                build_uuid = bid.split(":")[1]
                console.print(
                    f"  [dim]{plat}: https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_uuid}[/dim]"
                )

        return 0

    def _create_claude_settings(
        self,
        output_dir: Path,
        profile: object,
        include_coauthored_by: bool,
        profile_name: str,
        otel_resource_attributes: str | None = None,
    ) -> None:
        """Create Claude Code settings.json with Bedrock and optional monitoring configuration."""
        console = Console()

        try:
            claude_dir = output_dir / "claude-settings"
            claude_dir.mkdir(exist_ok=True)

            settings: dict = {
                "env": {
                    "AWS_REGION": get_source_region_for_profile(profile),
                    "CLAUDE_CODE_USE_BEDROCK": "1",
                    "AWS_PROFILE": profile_name,
                }
            }

            if not include_coauthored_by:
                settings["includeCoAuthoredBy"] = False

            if profile.credential_storage == "session":
                settings["awsAuthRefresh"] = f"__CREDENTIAL_PROCESS_PATH__ --profile {profile_name}"

            if hasattr(profile, "selected_model") and profile.selected_model:
                settings["env"]["ANTHROPIC_MODEL"] = profile.selected_model
                if "opus" in profile.selected_model:
                    prefix = profile.selected_model.split(".anthropic")[0]
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = (
                        f"{prefix}.anthropic.claude-3-5-haiku-20241022-v1:0"
                    )
                else:
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = profile.selected_model

            if profile.monitoring_enabled:
                monitoring_stack = profile.stack_names.get(
                    "monitoring", f"{profile.identity_pool_name}-otel-collector"
                )
                cmd = [
                    "aws", "cloudformation", "describe-stacks",
                    "--stack-name", monitoring_stack,
                    "--region", profile.aws_region,
                    "--query", "Stacks[0].Outputs",
                    "--output", "json",
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    outputs = json.loads(result.stdout)
                    endpoint = None
                    for output in outputs:
                        if output["OutputKey"] == "CollectorEndpoint":
                            endpoint = output["OutputValue"]
                            break

                    if endpoint:
                        resource_attrs = otel_resource_attributes or (
                            "department=engineering,team.id=default,"
                            "cost_center=default,organization=default"
                        )
                        settings["env"].update(
                            {
                                "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
                                "OTEL_METRICS_EXPORTER": "otlp",
                                "OTEL_LOGS_EXPORTER": "otlp",
                                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                                "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
                                "OTEL_RESOURCE_ATTRIBUTES": resource_attrs,
                            }
                        )
                        settings["otelHeadersHelper"] = "__OTEL_HELPER_PATH__"

                        is_https = endpoint.startswith("https://")
                        console.print(
                            f"[dim]Added monitoring with {'HTTPS' if is_https else 'HTTP'} endpoint[/dim]"
                        )
                    else:
                        console.print("[yellow]Warning: No monitoring endpoint found in stack outputs[/yellow]")
                else:
                    console.print("[yellow]Warning: Could not fetch monitoring stack outputs[/yellow]")

            settings_path = claude_dir / "settings.json"
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)

            console.print("[dim]Created Claude Code settings for Bedrock configuration[/dim]")

        except Exception as e:
            console.print(f"[yellow]Warning: Could not create Claude Code settings: {e}[/yellow]")

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
                    valid_names = ", ".join(CODEBUILD_PLATFORMS.keys())
                    console.print(f"[yellow]Unknown platform: {p} (valid: {valid_names})[/yellow]")
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
                    choices.append(questionary.Choice(
                        f"{plat} — {config['description']} (not deployed)",
                        value=plat,
                        disabled="deploy codebuild stack first",
                    ))

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
