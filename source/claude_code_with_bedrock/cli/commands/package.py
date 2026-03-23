# ABOUTME: Package command for building distribution packages
# ABOUTME: Creates ready-to-distribute packages with embedded configuration

"""Package command - Build distribution packages."""

import json
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import questionary
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.cli.utils.display import display_configuration_info
from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.models import (
    get_source_region_for_profile,
)


class PackageCommand(Command):
    """
    Build distribution packages for your organization

    package
        {--target-platform=macos : Target platform (macos, linux, all)}
    """

    name = "package"
    description = "Build distribution packages with embedded configuration"

    options = [
        option(
            "target-platform", description="Target platform for binary (macos, linux, all)", flag=False, default="all"
        ),
        option(
            "profile", description="Configuration profile to use (defaults to active profile)", flag=False, default=None
        ),
        option(
            "status",
            description="[DEPRECATED] Use 'ccwb builds' instead. Check build status by ID or 'latest'",
            flag=False,
            default=None,
        ),
        option("build-local", description="Build binaries locally instead of downloading pre-built", flag=True),
        option("no-cache", description="Force re-download of pre-built binaries", flag=True),
        option("build-verbose", description="Enable verbose logging for build processes", flag=True),
        option("regenerate-installers", description="Regenerate installer scripts using existing binaries from latest dist", flag=True),
        option("go", description="Build binaries using Go cross-compilation (native binaries, no AV false positives)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the package command."""
        import platform
        import subprocess

        console = Console()

        # Check if this is a status check (deprecated - moved to builds command)
        if self.option("status") is not None:
            console.print("[yellow]⚠️  DEPRECATED: Status check has moved to the builds command[/yellow]")
            console.print("\nUse one of these commands instead:")
            console.print("  • [cyan]poetry run ccwb builds[/cyan]                    (list all recent builds)")
            console.print("  • [cyan]poetry run ccwb builds --status <build-id>[/cyan] (check specific build)")
            console.print("  • [cyan]poetry run ccwb builds --status latest[/cyan]    (check latest build)")
            console.print("\nRedirecting to builds command...\n")
            return self._check_build_status(self.option("status"), console)

        # Load configuration first (needed to check CodeBuild status)
        config = Config.load()
        # Use specified profile or default to active profile, or fall back to "ClaudeCode"
        profile_name = self.option("profile") or config.active_profile or "ClaudeCode"
        profile = config.get_profile(profile_name)

        if not profile:
            console.print("[red]No deployment found. Run 'poetry run ccwb init' first.[/red]")
            return 1

        # Regenerate installers from existing binaries (no rebuild needed)
        if self.option("regenerate-installers"):
            return self._regenerate_installers(profile, profile_name, console)

        # Go build mode: all platforms always available via cross-compilation
        use_go = self.option("go")

        # Interactive prompts if not provided via CLI
        target_platform = self.option("target-platform")
        if target_platform == "all":  # Default value, prompt user
            # Build list of available platform choices
            # Note: "macos" is omitted because it's just a smart alias for the current architecture
            # Users should explicitly choose macos-arm64 or macos-intel for clarity
            platform_choices = [
                "macos-arm64",
                "macos-intel",
                "linux-x64",
                "linux-arm64",
            ]

            # With Go, Windows is always available (cross-compile from any platform)
            if use_go:
                platform_choices.append("windows")
            elif hasattr(profile, "enable_codebuild") and profile.enable_codebuild:
                platform_choices.append("windows")

            # Use checkbox for multiple selection (require at least one)
            selected_platforms = questionary.checkbox(
                "Which platform(s) do you want to build for? (Use space to select, enter to confirm)",
                choices=platform_choices,
                validate=lambda x: len(x) > 0 or "You must select at least one platform",
            ).ask()

            # Use the selected platforms (guaranteed to have at least one due to validation)
            target_platform = selected_platforms if len(selected_platforms) > 1 else selected_platforms[0]

        # Prompt for co-authorship preference (default to No - opt-in approach)
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

        # Validate platform
        valid_platforms = ["macos", "macos-arm64", "macos-intel", "linux", "linux-x64", "linux-arm64", "windows", "all"]
        if isinstance(target_platform, list):
            for platform_name in target_platform:
                if platform_name not in valid_platforms:
                    console.print(
                        f"[red]Invalid platform: {platform_name}. Valid options: {', '.join(valid_platforms)}[/red]"
                    )
                    return 1
        elif target_platform not in valid_platforms:
            console.print(
                f"[red]Invalid platform: {target_platform}. Valid options: {', '.join(valid_platforms)}[/red]"
            )
            return 1

        # Get actual Identity Pool ID or Role ARN from stack outputs
        console.print("[yellow]Fetching deployment information...[/yellow]")
        stack_outputs = get_stack_outputs(
            profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack"), profile.aws_region
        )

        if not stack_outputs:
            console.print("[red]Could not fetch stack outputs. Is the stack deployed?[/red]")
            return 1

        # Check federation type and get appropriate identifier
        federation_type = stack_outputs.get("FederationType", profile.federation_type)
        identity_pool_id = None
        federated_role_arn = None

        if federation_type == "direct":
            # Try DirectSTSRoleArn first (both old and new templates have this for direct mode)
            # Then fallback to FederatedRoleArn (new templates)
            federated_role_arn = stack_outputs.get("DirectSTSRoleArn")
            if not federated_role_arn or federated_role_arn == "N/A":
                federated_role_arn = stack_outputs.get("FederatedRoleArn")
            if not federated_role_arn or federated_role_arn == "N/A":
                console.print("[red]Direct STS Role ARN not found in stack outputs.[/red]")
                return 1
        else:
            identity_pool_id = stack_outputs.get("IdentityPoolId")
            if not identity_pool_id:
                console.print("[red]Identity Pool ID not found in stack outputs.[/red]")
                return 1

        # Welcome
        console.print(
            Panel.fit(
                "[bold cyan]Package Builder[/bold cyan]\n\n"
                f"Creating distribution package for {profile.provider_domain}",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Create timestamped output directory under profile name
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_dir = Path("./dist") / profile_name / timestamp

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create embedded configuration based on federation type
        embedded_config = {
            "provider_domain": profile.provider_domain,
            "client_id": profile.client_id,
            "region": profile.aws_region,
            "allowed_bedrock_regions": profile.allowed_bedrock_regions,
            "package_timestamp": timestamp,
            "package_version": "1.0.0",
            "federation_type": federation_type,
        }

        # Add federation-specific configuration
        if federation_type == "direct":
            embedded_config["federated_role_arn"] = federated_role_arn
            embedded_config["max_session_duration"] = profile.max_session_duration
        else:
            embedded_config["identity_pool_id"] = identity_pool_id

        # Show what will be packaged using shared display utility
        display_configuration_info(profile, identity_pool_id or federated_role_arn, format_type="simple")

        # Build package
        console.print("\n[bold]Building package...[/bold]")

        # Pre-flight check for Intel builds on ARM Macs (not needed for Go cross-compile)
        if not use_go and platform.system().lower() == "darwin" and platform.machine().lower() == "arm64":
            if target_platform in ["macos-intel", "all"]:
                x86_venv_path = Path.home() / "venv-x86"
                if not (x86_venv_path.exists() and (x86_venv_path / "bin" / "pyinstaller").exists()):
                    if target_platform == "macos-intel":
                        console.print("\n[yellow]⚠️  Intel Mac build environment not found[/yellow]")
                        console.print("[dim]Intel builds require an x86_64 Python environment on Apple Silicon.[/dim]")
                        console.print("[dim]ARM64 binaries work on Intel Macs via Rosetta, so this is optional.[/dim]")
                        console.print("\n[dim]To set up Intel builds (optional):[/dim]")
                        console.print("[dim]1. Install x86_64 Homebrew:[/dim]")
                        console.print(
                            '[dim]   arch -x86_64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"[/dim]'
                        )
                        console.print("[dim]2. Install Python and create environment:[/dim]")
                        console.print("[dim]   arch -x86_64 /usr/local/bin/brew install python@3.12[/dim]")
                        console.print("[dim]   arch -x86_64 /usr/local/bin/python3.12 -m venv ~/venv-x86[/dim]")
                        console.print("[dim]   arch -x86_64 ~/venv-x86/bin/pip install pyinstaller boto3 keyring[/dim]")
                        console.print()

        # Build executable(s)
        # With Go, cross-compilation makes all platforms available from any machine
        if use_go and not isinstance(target_platform, list) and target_platform == "all":
            platforms_to_build = ["macos-arm64", "macos-intel", "linux-x64", "linux-arm64", "windows"]
        elif use_go and isinstance(target_platform, list) and "all" in target_platform:
            platforms_to_build = ["macos-arm64", "macos-intel", "linux-x64", "linux-arm64", "windows"]
        elif isinstance(target_platform, list):
            # User selected multiple platforms via checkbox
            platforms_to_build = []
            for platform_choice in target_platform:
                if platform_choice == "all":
                    # If "all" is in the list, expand it based on current OS
                    current_os = platform.system().lower()
                    current_machine = platform.machine().lower()

                    if current_os == "darwin":
                        if current_machine == "arm64":
                            platforms_to_build.append("macos-arm64")
                            x86_venv_path = Path.home() / "venv-x86"
                            if x86_venv_path.exists() and (x86_venv_path / "bin" / "pyinstaller").exists():
                                platforms_to_build.append("macos-intel")
                        else:
                            platforms_to_build.append("macos-intel")

                        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
                        if docker_check.returncode == 0:
                            platforms_to_build.append("linux-x64")
                            platforms_to_build.append("linux-arm64")
                    elif current_os == "linux":
                        platforms_to_build.append("linux")
                    elif current_os == "windows":
                        platforms_to_build.append("windows")

                    if current_os != "windows" and profile and profile.enable_codebuild:
                        platforms_to_build.append("windows")
                else:
                    # Add individual platform choice
                    if platform_choice not in platforms_to_build:
                        platforms_to_build.append(platform_choice)
        elif target_platform == "all":
            # For "all", try to build what's possible on current platform
            platforms_to_build = []
            current_os = platform.system().lower()
            current_machine = platform.machine().lower()

            if current_os == "darwin":
                # On macOS, build for current architecture
                if current_machine == "arm64":
                    platforms_to_build.append("macos-arm64")
                    # Check if x86_64 environment is available for Intel builds
                    x86_venv_path = Path.home() / "venv-x86"
                    if x86_venv_path.exists() and (x86_venv_path / "bin" / "pyinstaller").exists():
                        platforms_to_build.append("macos-intel")
                    else:
                        # Check if Rosetta is available (for informational message)
                        rosetta_check = subprocess.run(["arch", "-x86_64", "true"], capture_output=True)
                        if rosetta_check.returncode == 0:
                            console.print(
                                "[dim]Note: Intel Mac builds available with optional setup. See docs for details.[/dim]"
                            )
                else:
                    platforms_to_build.append("macos-intel")

                # Check if Docker is available for Linux builds
                docker_check = subprocess.run(["docker", "--version"], capture_output=True)
                if docker_check.returncode == 0:
                    platforms_to_build.append("linux-x64")
                    platforms_to_build.append("linux-arm64")

            elif current_os == "linux":
                platforms_to_build.append("linux")
            elif current_os == "windows":
                platforms_to_build.append("windows")

            # Always try Windows via CodeBuild if not on Windows
            if current_os != "windows" and profile and profile.enable_codebuild:
                platforms_to_build.append("windows")
        else:
            # Single platform specified
            platforms_to_build = [target_platform]

        built_executables = []
        built_otel_helpers = []

        console.print()

        if use_go:
            # Go cross-compilation: build all selected platforms at once
            console.print("[cyan]Building Go binaries (cross-compilation)...[/cyan]")
            try:
                go_results = self._build_go_binaries(output_dir, platforms_to_build, profile.monitoring_enabled)
                built_executables = go_results["executables"]
                built_otel_helpers = go_results["otel_helpers"]
            except Exception as e:
                console.print(f"[red]Go build failed: {e}[/red]")
                return 1
        else:
            for platform_name in platforms_to_build:
                # Build credential process
                console.print(f"[cyan]Building credential process for {platform_name}...[/cyan]")
                try:
                    executable_path = self._build_executable(output_dir, platform_name)
                    # Check if this was an async Windows build
                    if executable_path is None:
                        # Windows build started in CodeBuild, continue without local binary
                        console.print("[dim]Windows binaries will be built in CodeBuild[/dim]")
                    else:
                        built_executables.append((platform_name, executable_path))
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not build credential process for {platform_name}: {e}[/yellow]")

                # Build OTEL helper if monitoring is enabled
                if profile.monitoring_enabled:
                    # Skip OTEL helper for Windows if being built in CodeBuild
                    if platform_name == "windows" and executable_path is None:
                        console.print("[dim]Windows OTEL helper will be built in CodeBuild[/dim]")
                    else:
                        console.print(f"[cyan]Building OTEL helper for {platform_name}...[/cyan]")
                        try:
                            otel_helper_path = self._build_otel_helper(output_dir, platform_name)
                            # Only add to list if build was successful (not None)
                            if otel_helper_path is not None:
                                built_otel_helpers.append((platform_name, otel_helper_path))
                        except Exception as e:
                            console.print(f"[yellow]Warning: Could not build OTEL helper for {platform_name}: {e}[/yellow]")

        # Check if any binaries were built
        if not built_executables:
            console.print("\n[red]Error: No binaries were successfully built.[/red]")
            console.print("Please check the error messages above.")
            return 1

        # Create configuration
        console.print("\n[cyan]Creating configuration...[/cyan]")
        # Pass the appropriate identifier based on federation type
        federation_identifier = federated_role_arn if federation_type == "direct" else identity_pool_id
        self._create_config(output_dir, profile, federation_identifier, federation_type, profile_name)

        # Create installer
        console.print("[cyan]Creating installer script...[/cyan]")
        self._create_installer(output_dir, profile, built_executables, built_otel_helpers)

        # Create documentation
        console.print("[cyan]Creating documentation...[/cyan]")
        self._create_documentation(output_dir, profile, timestamp)

        # Always create Claude Code settings (required for Bedrock configuration)
        console.print("[cyan]Creating Claude Code settings...[/cyan]")
        self._create_claude_settings(output_dir, profile, include_coauthored_by, profile_name, otel_resource_attributes)

        # Summary
        console.print("\n[green]✓ Package created successfully![/green]")
        console.print(f"\nOutput directory: [cyan]{output_dir}[/cyan]")
        console.print("\nPackage contents:")

        # Show which binaries were built
        for platform_name, executable_path in built_executables:
            binary_name = executable_path.name
            console.print(f"  • {binary_name} - Authentication executable for {platform_name}")

        console.print("  • config.json - Configuration")
        console.print("  • install.sh - Installation script for macOS/Linux")
        # Check if Windows installer exists (created when Windows binaries are present)
        if (output_dir / "install.bat").exists():
            console.print("  • install.bat - Installation script for Windows")
            console.print("  • ccwb-install.ps1 - PowerShell installer (called by install.bat)")
        console.print("  • README.md - Installation instructions")
        if profile.monitoring_enabled and (output_dir / "claude-settings" / "settings.json").exists():
            console.print("  • claude-settings/settings.json - Claude Code telemetry settings")
            for platform_name, otel_helper_path in built_otel_helpers:
                console.print(f"  • {otel_helper_path.name} - OTEL helper executable for {platform_name}")

        # Next steps
        console.print("\n[bold]Distribution steps:[/bold]")
        console.print("1. Send users the entire dist folder")
        console.print("2. Users run: chmod +x install.sh && ./install.sh")
        console.print("3. Authentication is configured automatically")

        console.print("\n[bold]To test locally:[/bold]")
        console.print(f"cd {output_dir}")
        console.print("chmod +x install.sh && ./install.sh")

        # Show next steps
        console.print("\n[bold]Next steps:[/bold]")

        # Only show distribute command if distribution is enabled
        if profile.enable_distribution:
            console.print("To create a distribution package: [cyan]poetry run ccwb distribute[/cyan]")
        else:
            console.print("Share the dist folder with your users for installation")

        return 0

    def _check_build_status(self, build_id: str, console: Console) -> int:
        """Check the status of a CodeBuild build."""
        import json
        from pathlib import Path

        import boto3

        try:
            # If no build ID provided, check for latest
            if not build_id or build_id == "latest":
                build_info_file = Path.home() / ".claude-code" / "latest-build.json"
                if not build_info_file.exists():
                    console.print("[red]No recent builds found. Start a build with 'poetry run ccwb package'[/red]")
                    return 1

                with open(build_info_file) as f:
                    build_info = json.load(f)
                    build_id = build_info["build_id"]
                    console.print(f"[dim]Checking latest build: {build_id}[/dim]")

            # Get build status from CodeBuild
            # Load profile to get the correct region
            config = Config.load()
            profile_name = self.option("profile")
            profile = config.get_profile(profile_name)
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
                    from datetime import datetime

                    start_time = build["startTime"]
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    console.print(f"Elapsed: {int(elapsed.total_seconds() / 60)} minutes")
            elif status == "SUCCEEDED":
                console.print("[green]✓ Build succeeded![/green]")
                console.print(f"Duration: {build.get('buildDurationInMinutes', 'Unknown')} minutes")
                console.print("\n[bold]Windows build artifacts are ready![/bold]")
                console.print("Next steps:")
                console.print("  Run: [cyan]poetry run ccwb distribute[/cyan]")
                console.print("  This will download Windows artifacts from S3 and create your distribution package")
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

    def _build_go_binaries(self, output_dir: Path, platforms: list, monitoring_enabled: bool) -> dict:
        """Build binaries using Go cross-compilation.

        Produces native statically-linked binaries for all platforms from a single machine.
        No Docker, CodeBuild, or per-platform toolchains needed.

        Returns dict with 'executables' and 'otel_helpers' lists of (platform, Path) tuples.
        """
        go_src = Path(__file__).parents[3] / "go"
        if not go_src.exists():
            raise FileNotFoundError(f"Go source directory not found at {go_src}")

        # Verify Go is installed
        try:
            result = subprocess.run(["go", "version"], capture_output=True, text=True, check=True)
            self.line(f"  <info>{result.stdout.strip()}</info>")
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise RuntimeError(
                "Go is not installed or not in PATH. Install from https://go.dev/dl/ "
                "or run: brew install go"
            )

        platform_map = {
            "macos-arm64": ("darwin", "arm64"),
            "macos-intel": ("darwin", "amd64"),
            "macos": ("darwin", "arm64"),  # Default to arm64 for generic macos
            "linux-x64": ("linux", "amd64"),
            "linux-arm64": ("linux", "arm64"),
            "linux": ("linux", "amd64"),  # Default to amd64 for generic linux
            "windows": ("windows", "amd64"),
        }

        executables = []
        otel_helpers = []

        binaries_to_build = ["credential-process"]
        if monitoring_enabled:
            binaries_to_build.append("otel-helper")

        for plat in platforms:
            if plat not in platform_map:
                raise ValueError(f"Unsupported platform for Go build: {plat}")

            goos, goarch = platform_map[plat]

            for binary in binaries_to_build:
                if plat == "windows":
                    suffix = "-windows.exe"
                else:
                    suffix = f"-{plat}"

                output_name = f"{binary}{suffix}"
                output_path = output_dir / output_name

                self.line(f"  Building <comment>{output_name}</comment>...")

                env = {**os.environ, "GOOS": goos, "GOARCH": goarch, "CGO_ENABLED": "0"}
                cmd = [
                    "go", "build",
                    "-ldflags", "-s -w",
                    "-o", str(output_path),
                    f"./cmd/{binary}/",
                ]
                result = subprocess.run(cmd, cwd=str(go_src), env=env, capture_output=True, text=True)
                if result.returncode != 0:
                    raise RuntimeError(f"Go build failed for {output_name}:\n{result.stderr}")

                if binary == "credential-process":
                    executables.append((plat, output_path))
                else:
                    otel_helpers.append((plat, output_path))

        self.line(f"  <info>Built {len(executables) + len(otel_helpers)} binaries</info>")
        return {"executables": executables, "otel_helpers": otel_helpers}

    def _build_executable(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable for target platform using appropriate tool."""
        import platform

        current_system = platform.system().lower()
        current_machine = platform.machine().lower()

        # Windows builds use Nuitka via CodeBuild
        if target_platform == "windows":
            if current_system == "windows":
                # Native Windows build with Nuitka
                return self._build_native_executable_nuitka(output_dir, "windows")
            else:
                # Use CodeBuild for Windows builds on non-Windows platforms
                # Don't return - just start the build and continue
                self._build_windows_via_codebuild(output_dir)
                return None  # No local binary created

        # macOS builds use PyInstaller for cross-architecture support
        if target_platform == "macos-arm64":
            return self._build_macos_pyinstaller(output_dir, "arm64")
        elif target_platform == "macos-intel":
            return self._build_macos_pyinstaller(output_dir, "x86_64")
        elif target_platform == "macos-universal":
            return self._build_macos_pyinstaller(output_dir, "universal2")
        elif target_platform == "linux-x64":
            # Build Linux x64 binary via Docker with PyInstaller
            return self._build_linux_via_docker(output_dir, "x64")
        elif target_platform == "linux-arm64":
            # Build Linux ARM64 binary via Docker with PyInstaller
            return self._build_linux_via_docker(output_dir, "arm64")
        elif target_platform == "linux":
            # Native Linux build with PyInstaller
            return self._build_linux_pyinstaller(output_dir)
        elif target_platform == "macos":
            # Default macOS build for current architecture
            if current_machine == "arm64":
                return self._build_macos_pyinstaller(output_dir, "arm64")
            else:
                return self._build_macos_pyinstaller(output_dir, "x86_64")

        # Fallback - shouldn't reach here
        raise ValueError(f"Unsupported target platform: {target_platform}")

    def _build_native_executable_nuitka(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable using native Nuitka compiler (for Windows only)."""
        import platform

        current_system = platform.system().lower()
        current_machine = platform.machine().lower()

        # Platform compatibility matrix for Nuitka (no cross-compilation)
        PLATFORM_COMPATIBILITY = {
            "macos": {
                "arm64": ["darwin-arm64"],
                "intel": ["darwin-x86_64"],
            },
            "linux": {
                "x86_64": ["linux-x86_64"],
            },
            "windows": {
                "x86_64": ["windows-amd64"],
            },
        }

        # Determine the specific platform variant
        if target_platform == "macos":
            # On macOS, determine if we're building for ARM64 or Intel
            # Check if user requested a specific variant via environment variable
            macos_variant = os.environ.get("CCWB_MACOS_VARIANT", "").lower()

            if macos_variant == "intel":
                # Force Intel build (useful on ARM Macs with Rosetta)
                platform_variant = "intel"
                binary_name = "credential-process-macos-intel"
            elif macos_variant == "arm64":
                # Force ARM64 build
                platform_variant = "arm64"
                binary_name = "credential-process-macos-arm64"
            elif current_machine == "arm64":
                # Default to ARM64 on ARM Macs
                platform_variant = "arm64"
                binary_name = "credential-process-macos-arm64"
            else:
                # Default to Intel on Intel Macs
                platform_variant = "intel"
                binary_name = "credential-process-macos-intel"
        elif target_platform == "linux":
            platform_variant = "x86_64"
            binary_name = "credential-process-linux"
        elif target_platform == "windows":
            platform_variant = "x86_64"
            binary_name = "credential-process-windows.exe"
        else:
            raise ValueError(f"Unsupported target platform: {target_platform}")

        # Check platform compatibility
        current_platform_str = f"{current_system}-{current_machine}"
        compatible_platforms = PLATFORM_COMPATIBILITY.get(target_platform, {}).get(platform_variant, [])

        # Special case: Allow Intel builds on ARM Macs via Rosetta
        if (
            target_platform == "macos"
            and platform_variant == "intel"
            and current_system == "darwin"
            and current_machine == "arm64"
        ):
            # Check if Rosetta is available
            result = subprocess.run(["arch", "-x86_64", "true"], capture_output=True)
            if result.returncode == 0:
                console = Console()
                console.print("[yellow]Building Intel binary on ARM Mac using Rosetta 2[/yellow]")
                # Rosetta is available, allow the build
                pass
            else:
                raise RuntimeError(
                    "Cannot build Intel binary on ARM Mac without Rosetta 2.\n"
                    "Install Rosetta: softwareupdate --install-rosetta"
                )
        elif current_platform_str not in compatible_platforms:
            raise RuntimeError(
                f"Cannot build {target_platform} ({platform_variant}) binary on {current_platform_str}.\n"
                f"Nuitka requires native builds. Please build on a {target_platform} machine."
            )

        # Check if Nuitka is available (through Poetry)
        source_dir = Path(__file__).parent.parent.parent.parent
        nuitka_check = subprocess.run(
            ["poetry", "run", "python", "-m", "nuitka", "--version"], capture_output=True, text=True, cwd=source_dir
        )
        if nuitka_check.returncode != 0:
            raise RuntimeError(
                "Nuitka not found. Please install it:\n"
                "  poetry add --group dev nuitka ordered-set zstandard\n\n"
                "Note: Nuitka requires Python 3.10-3.12."
            )

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent.parent / "source" / "credential_provider" / "__main__.py"

        if not src_file.exists():
            raise FileNotFoundError(f"Source file not found: {src_file}")

        # Build Nuitka command (use poetry run to ensure correct Python version)
        # If building Intel binary on ARM Mac, use Rosetta
        if (
            target_platform == "macos"
            and platform_variant == "intel"
            and current_system == "darwin"
            and current_machine == "arm64"
        ):
            cmd = [
                "arch",
                "-x86_64",  # Run under Rosetta
                "poetry",
                "run",
                "nuitka",
            ]
        else:
            cmd = [
                "poetry",
                "run",
                "nuitka",
            ]

        # Add common Nuitka flags
        nuitka_flags = [
            "--standalone",
            "--onefile",
            "--assume-yes-for-downloads",
            f"--output-filename={binary_name}",
            f"--output-dir={str(output_dir)}",
        ]

        # Only add --quiet if not in verbose mode
        verbose = self.option("build-verbose")
        if not verbose:
            nuitka_flags.append("--quiet")

        nuitka_flags.extend(
            [
                "--remove-output",  # Clean up build artifacts
                "--python-flag=no_site",  # Don't include site packages
            ]
        )

        cmd.extend(nuitka_flags)

        # Add platform-specific flags
        if target_platform == "macos":
            cmd.extend(
                [
                    "--macos-create-app-bundle",
                    "--macos-app-name=Claude Code Credential Process",
                    "--disable-console",  # GUI app on macOS
                ]
            )
        elif target_platform == "linux":
            cmd.extend(
                [
                    "--linux-onefile-icon=NONE",  # No icon for Linux
                ]
            )

        # Add the source file
        cmd.append(str(src_file))

        # Run Nuitka (from source directory where pyproject.toml is located)
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=not verbose, text=True, cwd=source_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Nuitka build failed: {result.stderr}")

        return output_dir / binary_name

    def _build_macos_pyinstaller(self, output_dir: Path, arch: str) -> Path:
        """Build macOS executable using PyInstaller with target architecture."""
        console = Console()
        verbose = self.option("build-verbose")

        # Determine binary name based on architecture
        if arch == "arm64":
            binary_name = "credential-process-macos-arm64"
        elif arch == "x86_64":
            binary_name = "credential-process-macos-intel"
        elif arch == "universal2":
            binary_name = "credential-process-macos-universal"
        else:
            raise ValueError(f"Unsupported macOS architecture: {arch}")

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent.parent / "source" / "credential_provider" / "__main__.py"
        if not src_file.exists():
            raise FileNotFoundError(f"Source file not found: {src_file}")

        console.print(f"[yellow]Building macOS {arch} binary with PyInstaller...[/yellow]")

        # Check if we need to use x86_64 Python for Intel builds
        use_x86_python = False
        x86_venv_path = Path.home() / "venv-x86"

        if arch == "x86_64" and platform.machine().lower() == "arm64":
            # On ARM Mac building Intel binary - check for x86_64 environment
            if x86_venv_path.exists() and (x86_venv_path / "bin" / "pyinstaller").exists():
                use_x86_python = True
                console.print("[dim]Using x86_64 Python environment for Intel build[/dim]")
            else:
                console.print("\n[yellow]⚠️  Intel Mac build skipped (optional)[/yellow]")
                console.print("[dim]Intel binaries are optional. ARM64 binaries work on Intel Macs via Rosetta.[/dim]")
                console.print("[dim]To enable Intel builds on Apple Silicon, see:[/dim]")
                console.print(
                    "[dim]https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock#optional-intel-mac-builds[/dim]\n"
                )
                # Return dummy path - the main loop will handle this gracefully
                return output_dir / binary_name

        # Determine log level based on verbose flag
        log_level = "INFO" if verbose else "WARN"

        # Build PyInstaller command
        if use_x86_python:
            # Use x86_64 Python environment
            cmd = [
                "arch",
                "-x86_64",
                str(x86_venv_path / "bin" / "pyinstaller"),
                "--onefile",
                "--clean",
                "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller-x86",
                "--specpath=/tmp/pyinstaller-x86",
                f"--log-level={log_level}",
                # Hidden imports for our dependencies
                "--hidden-import=keyring.backends.macOS",
                "--hidden-import=keyring.backends.SecretService",
                "--hidden-import=keyring.backends.Windows",
                "--hidden-import=keyring.backends.chainer",
                "--hidden-import=charset_normalizer",
                str(src_file),
            ]
        else:
            # Use regular Poetry environment
            cmd = [
                "poetry",
                "run",
                "pyinstaller",
                "--onefile",
                "--clean",
                "--noconfirm",
                f"--target-arch={arch}",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller",
                "--specpath=/tmp/pyinstaller",
                f"--log-level={log_level}",
                # Hidden imports for our dependencies
                "--hidden-import=keyring.backends.macOS",
                "--hidden-import=keyring.backends.SecretService",
                "--hidden-import=keyring.backends.Windows",
                "--hidden-import=keyring.backends.chainer",
                "--hidden-import=charset_normalizer",
                str(src_file),
            ]

        # Run PyInstaller from source directory
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=not verbose, text=True, cwd=source_dir)

        if result.returncode != 0:
            console.print(f"[red]PyInstaller build failed: {result.stderr}[/red]")
            raise RuntimeError(f"PyInstaller build failed: {result.stderr}")

        binary_path = output_dir / binary_name
        if binary_path.exists():
            binary_path.chmod(0o755)
            console.print(f"[green]✓ macOS {arch} binary built successfully with PyInstaller[/green]")
            return binary_path
        else:
            raise RuntimeError(f"Binary not created: {binary_path}")

    def _build_linux_pyinstaller(self, output_dir: Path) -> Path:
        """Build Linux executable using PyInstaller."""
        console = Console()
        verbose = self.option("build-verbose")

        # Detect architecture and set appropriate binary name
        import platform

        machine = platform.machine().lower()
        if machine in ["aarch64", "arm64"]:
            binary_name = "credential-process-linux-arm64"
        else:
            binary_name = "credential-process-linux-x64"

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent.parent / "source" / "credential_provider" / "__main__.py"
        if not src_file.exists():
            raise FileNotFoundError(f"Source file not found: {src_file}")

        console.print("[yellow]Building Linux binary with PyInstaller...[/yellow]")

        # Determine log level based on verbose flag
        log_level = "INFO" if verbose else "WARN"

        # Build PyInstaller command
        cmd = [
            "poetry",
            "run",
            "pyinstaller",
            "--onefile",
            "--clean",
            "--noconfirm",
            f"--name={binary_name}",
            f"--distpath={str(output_dir)}",
            "--workpath=/tmp/pyinstaller",
            "--specpath=/tmp/pyinstaller",
            f"--log-level={log_level}",
            # Hidden imports for our dependencies
            "--hidden-import=keyring.backends.SecretService",
            "--hidden-import=keyring.backends.chainer",
            "--hidden-import=charset_normalizer",
            "--hidden-import=six",
            "--hidden-import=six.moves",
            "--hidden-import=six.moves._thread",
            "--hidden-import=six.moves.urllib",
            "--hidden-import=six.moves.urllib.parse",
            "--hidden-import=dateutil",
            str(src_file),
        ]

        # Run PyInstaller from source directory
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=not verbose, text=True, cwd=source_dir)

        if result.returncode != 0:
            console.print(f"[red]PyInstaller build failed: {result.stderr}[/red]")
            raise RuntimeError(f"PyInstaller build failed: {result.stderr}")

        binary_path = output_dir / binary_name
        if binary_path.exists():
            binary_path.chmod(0o755)
            console.print("[green]✓ Linux binary built successfully with PyInstaller[/green]")
            return binary_path
        else:
            raise RuntimeError(f"Binary not created: {binary_path}")

    def _build_linux_via_docker(self, output_dir: Path, arch: str = "x64") -> Path:
        """Build Linux binaries using Docker with PyInstaller."""
        import shutil
        import tempfile

        console = Console()
        verbose = self.option("build-verbose")

        # Determine platform and binary name
        if arch == "arm64":
            docker_platform = "linux/arm64"
            binary_name = "credential-process-linux-arm64"
        else:
            docker_platform = "linux/amd64"
            binary_name = "credential-process-linux-x64"

        # Check if Docker is available and running
        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
        if docker_check.returncode != 0:
            console.print(f"\n[yellow]⚠️  Docker not found - skipping Linux {arch} build[/yellow]")
            console.print("[dim]Linux binaries require Docker Desktop to be installed and running.[/dim]")
            console.print("[dim]Install Docker: https://docs.docker.com/get-docker/[/dim]")
            console.print(f"[dim]Skipping credential-process-linux-{arch}[/dim]\n")
            # Return a dummy path that won't be included in the package
            return None

        # Check if Docker daemon is running
        daemon_check = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if daemon_check.returncode != 0:
            console.print(f"\n[yellow]⚠️  Docker daemon not running - skipping Linux {arch} build[/yellow]")
            console.print("[dim]Please start Docker Desktop and try again.[/dim]")
            console.print(f"[dim]Skipping credential-process-linux-{arch}[/dim]\n")
            # Return a dummy path that won't be included in the package
            return None

        # Create a temporary directory for the Docker build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy source files to temp directory
            source_dir = Path(__file__).parent.parent.parent.parent
            shutil.copytree(source_dir / "credential_provider", temp_path / "credential_provider")

            # Create Dockerfile with PyInstaller
            dockerfile_content = f"""FROM --platform={docker_platform} ubuntu:22.04

# Set non-interactive to avoid tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install Python 3.12 and build dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    build-essential \
    binutils \
    curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.12 python3.12-dev python3.12-venv \
    && python3.12 -m ensurepip \
    && python3.12 -m pip install --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install Python packages
RUN python3 -m pip install --no-cache-dir \
    pyinstaller==6.3.0 \
    boto3 \
    requests \
    PyJWT \
    cryptography \
    keyring \
    keyrings.alt \
    questionary \
    rich \
    cleo \
    pydantic \
    pyyaml \
    six==1.16.0 \
    python-dateutil

# Set working directory
WORKDIR /build

# Copy source code
COPY credential_provider /build/credential_provider

# Build the binary with PyInstaller
RUN pyinstaller \
    --onefile \
    --clean \
    --noconfirm \
    --name {binary_name} \
    --distpath /output \
    --workpath /tmp/build \
    --specpath /tmp \
    --log-level WARN \
    --hidden-import keyring.backends.SecretService \
    --hidden-import keyring.backends.chainer \
    --hidden-import charset_normalizer \
    --hidden-import six \
    --hidden-import six.moves \
    --hidden-import six.moves._thread \
    --hidden-import six.moves.urllib \
    --hidden-import six.moves.urllib.parse \
    --hidden-import dateutil \
    credential_provider/__main__.py

# The binary will be in /output/{binary_name}
"""

            (temp_path / "Dockerfile").write_text(dockerfile_content)

            # Generate unique image tag to avoid reusing cached images
            import time

            image_tag = f"ccwb-linux-{arch}-builder-{int(time.time())}"

            # Remove any existing image with similar name to ensure fresh build
            if verbose:
                console.print("[dim]Cleaning up old Docker images...[/dim]")
            subprocess.run(
                ["docker", "rmi", "-f", f"ccwb-linux-{arch}-builder"],
                capture_output=True,
            )

            # Build Docker image
            console.print(f"[yellow]Building Linux {arch} binary via Docker (this may take a few minutes)...[/yellow]")
            if verbose:
                console.print("[dim]Docker build output:[/dim]")
            build_result = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--no-cache",
                    "--platform",
                    docker_platform,
                    "-t",
                    image_tag,
                    "--load",
                    ".",
                ],
                cwd=temp_path,
                capture_output=not verbose,
                text=True,
            )

            if build_result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {build_result.stderr}")

            # Run container and copy binary out
            import time

            container_name = f"ccwb-extract-{arch}-{int(time.time())}"

            # Create container from the newly built image
            run_result = subprocess.run(
                ["docker", "create", "--name", container_name, image_tag],
                capture_output=True,
                text=True,
            )

            if run_result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {run_result.stderr}")

            try:
                # Copy binary from container
                copy_result = subprocess.run(
                    ["docker", "cp", f"{container_name}:/output/{binary_name}", str(output_dir)],
                    capture_output=True,
                    text=True,
                )

                if copy_result.returncode != 0:
                    raise RuntimeError(f"Failed to copy binary from container: {copy_result.stderr}")

                # Verify the binary was created
                binary_path = output_dir / binary_name
                if not binary_path.exists():
                    raise RuntimeError(f"Linux {arch} binary was not created successfully")

                # Make it executable
                binary_path.chmod(0o755)

                console.print(f"[green]✓ Linux {arch} binary built successfully via Docker[/green]")
                return binary_path

            finally:
                # Clean up container and image
                subprocess.run(["docker", "rm", container_name], capture_output=True)
                subprocess.run(["docker", "rmi", image_tag], capture_output=True)

    def _build_linux_otel_helper_via_docker(self, output_dir: Path, arch: str = "x64") -> Path:
        """Build Linux OTEL helper binary using Docker with PyInstaller."""
        import shutil
        import tempfile

        console = Console()
        verbose = self.option("build-verbose")

        # Determine platform and binary name
        if arch == "arm64":
            docker_platform = "linux/arm64"
            binary_name = "otel-helper-linux-arm64"
        else:
            docker_platform = "linux/amd64"
            binary_name = "otel-helper-linux-x64"

        # Check if Docker is available and running
        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
        if docker_check.returncode != 0:
            console.print(f"\n[yellow]⚠️  Docker not found - skipping Linux {arch} OTEL helper build[/yellow]")
            console.print("[dim]Linux binaries require Docker Desktop to be installed and running.[/dim]")
            console.print(f"[dim]Skipping otel-helper-linux-{arch}[/dim]\n")
            # Return a dummy path that won't be included in the package
            return None

        # Check if Docker daemon is running
        daemon_check = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if daemon_check.returncode != 0:
            console.print(f"\n[yellow]⚠️  Docker daemon not running - skipping Linux {arch} OTEL helper build[/yellow]")
            console.print("[dim]Please start Docker Desktop and try again.[/dim]")
            console.print(f"[dim]Skipping otel-helper-linux-{arch}[/dim]\n")
            # Return a dummy path that won't be included in the package
            return None

        # Create a temporary directory for the Docker build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy source files to temp directory
            source_dir = Path(__file__).parent.parent.parent.parent
            shutil.copytree(source_dir / "otel_helper", temp_path / "otel_helper")

            # Create Dockerfile for OTEL helper with PyInstaller
            dockerfile_content = f"""FROM --platform={docker_platform} ubuntu:22.04

# Set non-interactive to avoid tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install Python 3.12 and build dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    build-essential \
    binutils \
    curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.12 python3.12-dev python3.12-venv \
    && python3.12 -m ensurepip \
    && python3.12 -m pip install --upgrade pip \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install Python packages
RUN python3 -m pip install --no-cache-dir \
    pyinstaller==6.3.0 \
    PyJWT \
    cryptography \
    six

# Set working directory
WORKDIR /build

# Copy source code
COPY otel_helper /build/otel_helper

# Build the binary with PyInstaller
RUN pyinstaller \
    --onefile \
    --clean \
    --noconfirm \
    --name {binary_name} \
    --distpath /output \
    --workpath /tmp/build \
    --specpath /tmp \
    --log-level WARN \
    --hidden-import six \
    --hidden-import six.moves \
    otel_helper/__main__.py

# The binary will be in /output/{binary_name}
"""

            (temp_path / "Dockerfile").write_text(dockerfile_content)

            # Generate unique image tag to avoid reusing cached images
            import time

            image_tag = f"ccwb-otel-{arch}-builder-{int(time.time())}"

            # Remove any existing image with similar name to ensure fresh build
            if verbose:
                console.print("[dim]Cleaning up old Docker images...[/dim]")
            subprocess.run(
                ["docker", "rmi", "-f", f"ccwb-otel-{arch}-builder"],
                capture_output=True,
            )

            # Build Docker image
            console.print(f"[yellow]Building Linux {arch} OTEL helper via Docker...[/yellow]")
            if verbose:
                console.print("[dim]Docker build output:[/dim]")
            build_result = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--no-cache",
                    "--platform",
                    docker_platform,
                    "-t",
                    image_tag,
                    "--load",
                    ".",
                ],
                cwd=temp_path,
                capture_output=not verbose,
                text=True,
            )

            if build_result.returncode != 0:
                raise RuntimeError(f"Docker build failed for OTEL helper: {build_result.stderr}")

            # Run container and copy binary out
            import time

            container_name = f"ccwb-otel-extract-{arch}-{int(time.time())}"

            # Create container from the newly built image
            run_result = subprocess.run(
                ["docker", "create", "--name", container_name, image_tag],
                capture_output=True,
                text=True,
            )

            if run_result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {run_result.stderr}")

            try:
                # Copy binary from container
                copy_result = subprocess.run(
                    ["docker", "cp", f"{container_name}:/output/{binary_name}", str(output_dir)],
                    capture_output=True,
                    text=True,
                )

                if copy_result.returncode != 0:
                    raise RuntimeError(f"Failed to copy OTEL binary from container: {copy_result.stderr}")

                # Verify the binary was created
                binary_path = output_dir / binary_name
                if not binary_path.exists():
                    raise RuntimeError(f"Linux {arch} OTEL helper binary was not created successfully")

                # Make it executable
                binary_path.chmod(0o755)

                console.print(f"[green]✓ Linux {arch} OTEL helper built successfully via Docker[/green]")
                return binary_path

            finally:
                # Clean up container and image
                subprocess.run(["docker", "rm", container_name], capture_output=True)
                subprocess.run(["docker", "rmi", image_tag], capture_output=True)

    def _build_windows_via_codebuild(self, output_dir: Path) -> Path:
        """Build Windows binaries using AWS CodeBuild."""
        import json

        import boto3
        from botocore.exceptions import ClientError

        console = Console()

        # Check for in-progress builds only (not completed ones)
        try:
            config = Config.load()
            profile_name = self.option("profile")
            profile = config.get_profile(profile_name)

            if profile:
                project_name = f"{profile.identity_pool_name}-windows-build"
                codebuild = boto3.client("codebuild", region_name=profile.aws_region)

                # List recent builds
                response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")

                if response.get("ids"):
                    # Check only the most recent builds
                    build_ids = response["ids"][:3]
                    builds_response = codebuild.batch_get_builds(ids=build_ids)

                    for build in builds_response.get("builds", []):
                        if build["buildStatus"] == "IN_PROGRESS":
                            console.print(
                                f"[yellow]Windows build already in progress (started "
                                f"{build['startTime'].strftime('%Y-%m-%d %H:%M')})[/yellow]"
                            )
                            console.print("Check status: [cyan]poetry run ccwb builds[/cyan]")
                            console.print("[dim]Note: Package will be created without Windows binaries[/dim]")
                            # Don't return early - continue to create package with available binaries
        except Exception as e:
            console.print(f"[dim]Could not check for recent builds: {e}[/dim]")

        # Load profile to get CodeBuild configuration
        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile or not profile.enable_codebuild:
            console.print("[red]CodeBuild is not enabled for this profile.[/red]")
            console.print("To enable CodeBuild for Windows builds:")
            console.print("  1. Run: poetry run ccwb init")
            console.print("  2. Answer 'Yes' when asked about Windows build support")
            console.print("  3. Run: poetry run ccwb deploy codebuild")
            raise RuntimeError("CodeBuild not enabled")

        # Get CodeBuild stack outputs
        stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
        try:
            stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
        except Exception:
            console.print(f"[red]CodeBuild stack not found: {stack_name}[/red]")
            console.print("Run: poetry run ccwb deploy codebuild")
            raise RuntimeError("CodeBuild stack not deployed") from None

        bucket_name = stack_outputs.get("BuildBucket")
        project_name = stack_outputs.get("ProjectName")

        if not bucket_name or not project_name:
            console.print("[red]CodeBuild stack outputs not found[/red]")
            raise RuntimeError("Invalid CodeBuild stack")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # Package source code
            task = progress.add_task("Packaging source code for CodeBuild...", total=None)
            source_zip = self._package_source_for_codebuild()

            # Upload to S3
            progress.update(task, description="Uploading source to S3...")
            s3 = boto3.client("s3", region_name=profile.aws_region)
            try:
                s3.upload_file(str(source_zip), bucket_name, "source.zip")
            except ClientError as e:
                console.print(f"[red]Failed to upload source: {e}[/red]")
                raise

            # Start build
            progress.update(task, description="Starting CodeBuild project...")
            codebuild = boto3.client("codebuild", region_name=profile.aws_region)
            try:
                response = codebuild.start_build(projectName=project_name)
                build_id = response["build"]["id"]
            except ClientError as e:
                console.print(f"[red]Failed to start build: {e}[/red]")
                raise

            # Monitor build
            progress.update(task, description="Building Windows binaries (20+ minutes)...")
            console.print(f"[dim]Build ID: {build_id}[/dim]")

            # Store build ID for later retrieval
            from pathlib import Path

            build_info_file = Path.home() / ".claude-code" / "latest-build.json"
            build_info_file.parent.mkdir(exist_ok=True)
            with open(build_info_file, "w") as f:
                json.dump(
                    {
                        "build_id": build_id,
                        "started_at": datetime.now().isoformat(),
                        "project": project_name,
                        "bucket": bucket_name,
                    },
                    f,
                )

            # Clean up source zip
            source_zip.unlink()
            progress.update(task, completed=True)

        # Don't wait - return build info immediately
        console.print("\n[bold yellow]Windows build started![/bold yellow]")
        console.print(f"[dim]Build ID: {build_id}[/dim]")
        console.print("Build will take approximately 20+ minutes to complete.")

        console.print("\n[bold]Monitor build progress:[/bold]")
        console.print("  [cyan]poetry run ccwb builds[/cyan]")
        console.print("  This shows the current status and elapsed time")

        console.print("\n[bold]Next steps:[/bold]")
        console.print("  1. Wait for build to complete (you can continue working)")
        console.print("  2. Run [cyan]poetry run ccwb builds[/cyan] to check completion status")
        console.print("  3. Once complete, run [cyan]poetry run ccwb distribute[/cyan]")
        console.print("     This will download Windows binaries and create your distribution package")

        # Get profile to show distribution-specific info
        config = Config.load()
        profile_obj = config.get_profile(self.option("profile"))

        if profile_obj and profile_obj.enable_distribution:
            console.print("\n[dim]Note: Package will be uploaded to S3 with presigned URL or landing page[/dim]")
        else:
            console.print("\n[dim]Note: Package will be saved locally in the dist/ folder[/dim]")

        console.print("\n[dim]View logs in AWS Console:[/dim]")
        console.print(
            f"  [dim]https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_id.split(':')[1]}[/dim]"
        )

        # Return None since we don't have a local binary path
        return None

    def _package_source_for_codebuild(self) -> Path:
        """Package source code for CodeBuild."""
        import tempfile
        import zipfile

        # Create a temporary zip file
        temp_dir = Path(tempfile.mkdtemp())
        source_zip = temp_dir / "source.zip"

        # Get the source directory (parent of package.py)
        source_dir = Path(__file__).parents[3]  # Go up to source/ directory

        with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add all Python files from source directory
            for py_file in source_dir.rglob("*.py"):
                # Use forward slashes in zip (POSIX format) for CodeBuild compatibility
                arcname = py_file.relative_to(source_dir.parent).as_posix()
                zf.write(py_file, arcname)

            # Add pyproject.toml for dependencies
            pyproject_file = source_dir / "pyproject.toml"
            if pyproject_file.exists():
                zf.write(pyproject_file, "pyproject.toml")

        return source_zip

    def _build_otel_helper(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable for OTEL helper script."""
        import platform as platform_mod

        # Windows builds
        if target_platform == "windows":
            if platform_mod.system().lower() == "windows":
                # Native Windows build with Nuitka
                return self._build_native_otel_helper(output_dir, "windows")
            # Check if the Windows binary already exists (built via CodeBuild)
            windows_binary = output_dir / "otel-helper-windows.exe"
            if windows_binary.exists():
                return windows_binary
            else:
                raise RuntimeError("Windows otel-helper should have been built with credential-process")

        # macOS builds use PyInstaller
        if target_platform == "macos-arm64":
            return self._build_otel_helper_pyinstaller(output_dir, "macos", "arm64")
        elif target_platform == "macos-intel":
            return self._build_otel_helper_pyinstaller(output_dir, "macos", "x86_64")
        elif target_platform == "macos-universal":
            return self._build_otel_helper_pyinstaller(output_dir, "macos", "universal2")
        elif target_platform == "macos":
            import platform

            current_machine = platform.machine().lower()
            if current_machine == "arm64":
                return self._build_otel_helper_pyinstaller(output_dir, "macos", "arm64")
            else:
                return self._build_otel_helper_pyinstaller(output_dir, "macos", "x86_64")

        # Linux builds use PyInstaller via Docker
        elif target_platform == "linux-x64":
            return self._build_linux_otel_helper_via_docker(output_dir, "x64")
        elif target_platform == "linux-arm64":
            return self._build_linux_otel_helper_via_docker(output_dir, "arm64")
        elif target_platform == "linux":
            return self._build_otel_helper_pyinstaller(output_dir, "linux", None)

        # Fallback
        raise ValueError(f"Unsupported target platform for OTEL helper: {target_platform}")

    def _build_otel_helper_pyinstaller(self, output_dir: Path, platform_name: str, arch: str | None) -> Path:
        """Build OTEL helper using PyInstaller."""
        import platform as platform_module

        console = Console()
        verbose = self.option("build-verbose")

        # Determine binary name
        if platform_name == "macos":
            if arch == "arm64":
                binary_name = "otel-helper-macos-arm64"
            elif arch == "x86_64":
                binary_name = "otel-helper-macos-intel"
            elif arch == "universal2":
                binary_name = "otel-helper-macos-universal"
            else:
                binary_name = "otel-helper-macos"
        elif platform_name == "linux":
            # Detect architecture and set appropriate binary name
            machine = platform_module.machine().lower()
            if machine in ["aarch64", "arm64"]:
                binary_name = "otel-helper-linux-arm64"
            else:
                binary_name = "otel-helper-linux-x64"
        else:
            raise ValueError(f"Unsupported platform for OTEL helper: {platform_name}")

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent / "otel_helper" / "__main__.py"
        if not src_file.exists():
            raise FileNotFoundError(f"OTEL helper source not found: {src_file}")

        console.print(f"[yellow]Building OTEL helper for {platform_name} {arch or ''} with PyInstaller...[/yellow]")

        # Check if we need to use x86_64 Python for Intel builds on macOS
        use_x86_python = False
        x86_venv_path = Path.home() / "venv-x86"

        if platform_name == "macos" and arch == "x86_64" and platform_module.machine().lower() == "arm64":
            # On ARM Mac building Intel binary - check for x86_64 environment
            if x86_venv_path.exists() and (x86_venv_path / "bin" / "pyinstaller").exists():
                use_x86_python = True
                console.print("[dim]Using x86_64 Python environment for Intel OTEL helper build[/dim]")
            else:
                console.print("[yellow]Warning: x86_64 Python environment not found at ~/venv-x86[/yellow]")
                console.print("[yellow]Skipping Intel OTEL helper build[/yellow]")
                # For OTEL helper, we can skip if not available (it's optional)
                return output_dir / binary_name  # Return expected path even if not built

        # Determine log level based on verbose flag
        log_level = "INFO" if verbose else "WARN"

        # Build PyInstaller command
        if use_x86_python:
            # Use x86_64 Python environment
            cmd = [
                "arch",
                "-x86_64",
                str(x86_venv_path / "bin" / "pyinstaller"),
                "--onefile",
                "--clean",
                "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller-x86",
                "--specpath=/tmp/pyinstaller-x86",
                f"--log-level={log_level}",
                str(src_file),
            ]
        else:
            # Use regular Poetry environment
            cmd = [
                "poetry",
                "run",
                "pyinstaller",
                "--onefile",
                "--clean",
                "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller",
                "--specpath=/tmp/pyinstaller",
                f"--log-level={log_level}",
                str(src_file),
            ]

        # Add target architecture for macOS (only for regular Poetry environment)
        if not use_x86_python and platform_name == "macos" and arch:
            cmd.insert(5, f"--target-arch={arch}")

        # Run PyInstaller from source directory
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=not verbose, text=True, cwd=source_dir)

        if result.returncode != 0:
            console.print(f"[red]PyInstaller build failed for OTEL helper: {result.stderr}[/red]")
            raise RuntimeError(f"PyInstaller build failed: {result.stderr}")

        binary_path = output_dir / binary_name
        if binary_path.exists():
            binary_path.chmod(0o755)
            console.print("[green]✓ OTEL helper built successfully with PyInstaller[/green]")
            return binary_path
        else:
            raise RuntimeError(f"OTEL helper binary not created: {binary_path}")

    def _build_native_otel_helper(self, output_dir: Path, target_platform: str) -> Path:
        """Build OTEL helper using native Nuitka compiler."""
        import platform

        current_system = platform.system().lower()
        current_machine = platform.machine().lower()

        # Determine the binary name based on platform and architecture
        if target_platform == "macos":
            # Check if user requested a specific variant via environment variable
            macos_variant = os.environ.get("CCWB_MACOS_VARIANT", "").lower()

            if macos_variant == "intel":
                platform_variant = "intel"
                binary_name = "otel-helper-macos-intel"
            elif macos_variant == "arm64":
                platform_variant = "arm64"
                binary_name = "otel-helper-macos-arm64"
            elif current_machine == "arm64":
                platform_variant = "arm64"
                binary_name = "otel-helper-macos-arm64"
            else:
                platform_variant = "intel"
                binary_name = "otel-helper-macos-intel"
        elif target_platform == "linux":
            platform_variant = "x86_64"
            binary_name = "otel-helper-linux"
        elif target_platform == "windows":
            platform_variant = "x86_64"
            binary_name = "otel-helper-windows.exe"
        else:
            raise ValueError(f"Unsupported target platform: {target_platform}")

        # Check platform compatibility (same as credential-process)
        if target_platform == "macos" and current_system != "darwin":
            raise RuntimeError(f"Cannot build macOS binary on {current_system}. Nuitka requires native builds.")
        elif target_platform == "linux" and current_system != "linux":
            raise RuntimeError(f"Cannot build Linux binary on {current_system}. Nuitka requires native builds.")
        elif target_platform == "windows" and current_system != "windows":
            raise RuntimeError(f"Cannot build Windows binary on {current_system}. Nuitka requires native builds.")

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent / "otel_helper" / "__main__.py"

        if not src_file.exists():
            raise FileNotFoundError(f"OTEL helper script not found: {src_file}")

        # Build Nuitka command (use poetry run to ensure correct Python version)
        # If building Intel binary on ARM Mac, use Rosetta
        if (
            target_platform == "macos"
            and platform_variant == "intel"
            and current_system == "darwin"
            and current_machine == "arm64"
        ):
            cmd = [
                "arch",
                "-x86_64",  # Run under Rosetta
                "poetry",
                "run",
                "nuitka",
            ]
        else:
            cmd = [
                "poetry",
                "run",
                "nuitka",
            ]

        # Add common Nuitka flags
        cmd.extend(
            [
                "--standalone",
                "--onefile",
                "--assume-yes-for-downloads",
                f"--output-filename={binary_name}",
                f"--output-dir={str(output_dir)}",
                "--quiet",
                "--remove-output",
                "--python-flag=no_site",
            ]
        )

        # Add platform-specific flags
        if target_platform == "macos":
            cmd.extend(
                [
                    "--macos-create-app-bundle",
                    "--macos-app-name=Claude Code OTEL Helper",
                    "--disable-console",
                ]
            )
        elif target_platform == "linux":
            cmd.extend(
                [
                    "--linux-onefile-icon=NONE",
                ]
            )

        # Add the source file
        cmd.append(str(src_file))

        # Run Nuitka (from source directory where pyproject.toml is located)
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=source_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Nuitka build failed for OTEL helper: {result.stderr}")

        return output_dir / binary_name

    def _regenerate_installers(self, profile, profile_name: str, console: Console) -> int:
        """Regenerate installer scripts using existing binaries from the latest dist folder."""
        import shutil

        # Find latest dist folder for this profile
        dist_base = Path("./dist") / profile_name
        if not dist_base.exists():
            console.print(f"[red]No dist folder found for profile '{profile_name}'.[/red]")
            console.print("Run 'ccwb package' first to build binaries.")
            return 1

        # Find the latest timestamped directory
        timestamp_dirs = sorted(
            [d for d in dist_base.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if not timestamp_dirs:
            console.print(f"[red]No builds found in {dist_base}.[/red]")
            return 1

        source_dir = timestamp_dirs[0]
        console.print(f"[cyan]Using existing binaries from: {source_dir}[/cyan]")

        # Detect existing binaries and otel helpers
        binary_patterns = {
            "macos-arm64": "credential-process-macos-arm64",
            "macos-intel": "credential-process-macos-intel",
            "linux-x64": "credential-process-linux-x64",
            "linux-arm64": "credential-process-linux-arm64",
            "windows": "credential-process-windows.exe",
        }
        otel_patterns = {
            "macos-arm64": "otel-helper-macos-arm64",
            "macos-intel": "otel-helper-macos-intel",
            "linux-x64": "otel-helper-linux-x64",
            "linux-arm64": "otel-helper-linux-arm64",
            "windows": "otel-helper-windows.exe",
        }

        built_executables = []
        built_otel_helpers = []
        for plat, binary_name in binary_patterns.items():
            binary_path = source_dir / binary_name
            if binary_path.exists():
                built_executables.append((plat, binary_path))
        for plat, helper_name in otel_patterns.items():
            helper_path = source_dir / helper_name
            if helper_path.exists():
                built_otel_helpers.append((plat, helper_path))

        if not built_executables:
            console.print("[red]No binaries found in the dist folder.[/red]")
            return 1

        console.print(f"[green]Found {len(built_executables)} binaries, {len(built_otel_helpers)} OTEL helpers[/green]")
        for plat, path in built_executables:
            console.print(f"  • {path.name}")

        # Create new timestamped output directory
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_dir = Path("./dist") / profile_name / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy existing binaries to new output dir
        console.print("\n[cyan]Copying binaries...[/cyan]")
        for plat, binary_path in built_executables:
            shutil.copy2(binary_path, output_dir / binary_path.name)
        for plat, helper_path in built_otel_helpers:
            shutil.copy2(helper_path, output_dir / helper_path.name)

        # Get federation info from stack outputs
        console.print("[cyan]Fetching deployment information...[/cyan]")
        stack_outputs = get_stack_outputs(
            profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack"), profile.aws_region
        )
        if not stack_outputs:
            console.print("[red]Could not fetch stack outputs. Is the stack deployed?[/red]")
            return 1

        federation_type = stack_outputs.get("FederationType", profile.federation_type)
        if federation_type == "direct":
            federation_identifier = stack_outputs.get("DirectSTSRoleArn") or stack_outputs.get("FederatedRoleArn")
        else:
            federation_identifier = stack_outputs.get("IdentityPoolId")

        if not federation_identifier or federation_identifier == "N/A":
            console.print("[red]Federation identifier not found in stack outputs.[/red]")
            return 1

        # Prompt for co-authorship and OTEL attributes
        include_coauthored_by = questionary.confirm(
            "Include 'Co-Authored-By: Claude' in git commits?", default=False
        ).ask()

        otel_resource_attributes = None
        if profile.monitoring_enabled:
            customize_otel = questionary.confirm(
                "Customize telemetry resource attributes?", default=False
            ).ask()
            if customize_otel:
                department = questionary.text("Department:", default="engineering").ask()
                team_id = questionary.text("Team ID:", default="default").ask()
                cost_center = questionary.text("Cost center:", default="default").ask()
                organization = questionary.text("Organization:", default="default").ask()
                otel_resource_attributes = (
                    f"department={department},team.id={team_id},"
                    f"cost_center={cost_center},organization={organization}"
                )

        # Regenerate config.json
        console.print("[cyan]Generating configuration...[/cyan]")
        self._create_config(output_dir, profile, federation_identifier, federation_type, profile_name)

        # Regenerate installer scripts
        console.print("[cyan]Generating installer scripts...[/cyan]")
        self._create_installer(output_dir, profile, built_executables, built_otel_helpers)

        # Regenerate documentation
        console.print("[cyan]Generating documentation...[/cyan]")
        self._create_documentation(output_dir, profile, timestamp)

        # Regenerate Claude Code settings
        console.print("[cyan]Generating Claude Code settings...[/cyan]")
        self._create_claude_settings(output_dir, profile, include_coauthored_by, profile_name, otel_resource_attributes)

        # Summary
        console.print(f"\n[green]✓ Installers regenerated successfully![/green]")
        console.print(f"\nOutput directory: [cyan]{output_dir}[/cyan]")
        console.print("\nRegenerated files:")
        console.print("  • config.json")
        console.print("  • install.sh")
        if (output_dir / "install.bat").exists():
            console.print("  • install.bat")
            console.print("  • ccwb-install.ps1")
        console.print("  • README.md")
        if (output_dir / "claude-settings" / "settings.json").exists():
            console.print("  • claude-settings/settings.json")
        console.print(f"\nBinaries copied from: [dim]{source_dir}[/dim]")
        console.print("\n[bold]Next: Run '[cyan]poetry run ccwb distribute --per-os[/cyan]' to create distribution packages.[/bold]")
        return 0

    def _create_config(
        self,
        output_dir: Path,
        profile,
        federation_identifier: str,
        federation_type: str = "cognito",
        profile_name: str = "ClaudeCode",
    ) -> Path:
        """Create the configuration file.

        Args:
            output_dir: Directory to write config.json to
            profile: Profile object with configuration
            federation_identifier: Identity pool ID or role ARN
            federation_type: "cognito" or "direct"
            profile_name: Name to use as key in config.json (defaults to "ClaudeCode" for backward compatibility)
        """
        config = {
            profile_name: {
                "provider_domain": profile.provider_domain,
                "client_id": profile.client_id,
                "aws_region": profile.aws_region,
                "provider_type": profile.provider_type or self._detect_provider_type(profile.provider_domain),
                "credential_storage": profile.credential_storage,
                "cross_region_profile": profile.cross_region_profile or "us",
            }
        }

        # Add the appropriate federation field based on type
        if federation_type == "direct":
            config[profile_name]["federated_role_arn"] = federation_identifier
            config[profile_name]["federation_type"] = "direct"
            config[profile_name]["max_session_duration"] = profile.max_session_duration
        else:
            config[profile_name]["identity_pool_id"] = federation_identifier
            config[profile_name]["federation_type"] = "cognito"

        # Add cognito_user_pool_id if it's a Cognito provider
        if profile.provider_type == "cognito" and profile.cognito_user_pool_id:
            config[profile_name]["cognito_user_pool_id"] = profile.cognito_user_pool_id

        # Add selected_model if available
        if hasattr(profile, "selected_model") and profile.selected_model:
            config[profile_name]["selected_model"] = profile.selected_model

        config_path = output_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        return config_path

    def _get_bedrock_region_for_profile(self, profile) -> str:
        """Get the correct AWS region for Bedrock API calls based on user-selected source region."""
        return get_source_region_for_profile(profile)

    def _detect_provider_type(self, domain: str) -> str:
        """Auto-detect provider type from domain."""
        from urllib.parse import urlparse

        if not domain:
            return "oidc"

        # Handle both full URLs and domain-only inputs
        url_to_parse = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

        try:
            parsed = urlparse(url_to_parse)
            hostname = parsed.hostname

            if not hostname:
                return "oidc"

            hostname_lower = hostname.lower()

            # Check for exact domain match or subdomain match
            # Using endswith with leading dot prevents bypass attacks
            okta_domains = (".okta.com", ".oktapreview.com", ".okta-emea.com")
            if hostname_lower.endswith(okta_domains) or hostname_lower in ("okta.com", "oktapreview.com", "okta-emea.com"):
                return "okta"
            elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                return "auth0"
            elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                return "azure"
            elif hostname_lower.endswith(".windows.net") or hostname_lower == "windows.net":
                return "azure"
            elif hostname_lower.endswith(".amazoncognito.com") or hostname_lower == "amazoncognito.com":
                return "cognito"
            elif hostname_lower.startswith("cognito-idp.") and ".amazonaws.com" in hostname_lower:
                return "cognito"
            else:
                return "auto"  # Let credential_provider auto-detect from domain at runtime
        except Exception:
            return "auto"  # Let credential_provider auto-detect from domain at runtime

    def _create_installer(self, output_dir: Path, profile, built_executables, built_otel_helpers=None) -> Path:
        """Create simple installer script."""

        # Determine which binaries were built
        platforms_built = [platform for platform, _ in built_executables]
        [platform for platform, _ in built_otel_helpers] if built_otel_helpers else []

        installer_content = f"""#!/bin/bash
# Claude Code Authentication Installer
# Organization: {profile.provider_domain}
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

set -e

echo "======================================"
echo "Claude Code Authentication Installer"
echo "======================================"
echo
echo "Organization: {profile.provider_domain}"
echo


# Check prerequisites
echo "Checking prerequisites..."
HAS_ERRORS=false

if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI is not installed"
    echo "       Please install from https://aws.amazon.com/cli/"
    HAS_ERRORS=true
fi

if [ ! -f "config.json" ]; then
    echo "ERROR: config.json not found in current directory"
    echo "       Make sure you are running this from the extracted package folder"
    HAS_ERRORS=true
fi

# Find a Python interpreter (needed for config parsing)
PYTHON=""
if command -v python3 &> /dev/null; then
    PYTHON="python3"
elif command -v python &> /dev/null; then
    PYTHON="python"
else
    echo "ERROR: Python is not installed (python3 or python)"
    echo "       Python is needed to parse configuration files"
    HAS_ERRORS=true
fi

if [ "$HAS_ERRORS" = "true" ]; then
    exit 1
fi

if [ ! -f "claude-settings/settings.json" ]; then
    echo "WARNING: claude-settings/settings.json not found"
    echo "         Claude Code IDE settings will not be configured automatically"
    echo ""
fi

echo "OK Prerequisites validated"

# Detect platform and architecture
echo
echo "Detecting platform and architecture..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "arm64" ]]; then
        echo "✓ Detected macOS ARM64 (Apple Silicon)"
        BINARY_SUFFIX="macos-arm64"
    else
        echo "✓ Detected macOS Intel"
        BINARY_SUFFIX="macos-intel"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]] || [[ "$ARCH" == "arm64" ]]; then
        echo "✓ Detected Linux ARM64"
        BINARY_SUFFIX="linux-arm64"
    else
        echo "✓ Detected Linux x64"
        BINARY_SUFFIX="linux-x64"
    fi
else
    echo "❌ Unsupported platform: $OSTYPE"
    echo "   This installer supports macOS and Linux only."
    exit 1
fi

# Check if binary for platform exists
CREDENTIAL_BINARY="credential-process-$BINARY_SUFFIX"
OTEL_BINARY="otel-helper-$BINARY_SUFFIX"

if [ ! -f "$CREDENTIAL_BINARY" ]; then
    echo "❌ Binary not found for your platform: $CREDENTIAL_BINARY"
    echo "   Please ensure you have the correct package for your architecture."
    exit 1
fi
"""

        installer_content += f"""
# Create directory
echo
echo "Installing authentication tools..."
mkdir -p ~/claude-code-with-bedrock

# Copy appropriate binary
cp "$CREDENTIAL_BINARY" ~/claude-code-with-bedrock/credential-process

# Copy config
cp config.json ~/claude-code-with-bedrock/
chmod +x ~/claude-code-with-bedrock/credential-process

# macOS Keychain Notice
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo
    echo "⚠️  macOS Keychain Access:"
    echo "   On first use, macOS will ask for permission to access the keychain."
    echo "   This is normal and required for secure credential storage."
    echo "   Click 'Always Allow' when prompted."
fi

# Copy Claude Code settings if present
if [ -d "claude-settings" ]; then
    echo
    echo "Installing Claude Code settings..."
    mkdir -p ~/.claude

    # Copy settings and replace placeholders
    if [ -f "claude-settings/settings.json" ]; then
        # Check if settings file already exists
        if [ -f ~/.claude/settings.json ]; then
            echo "Existing Claude Code settings found"
            # Backup existing settings
            BACKUP_NAME="settings.json.backup-$(date +%Y%m%d-%H%M%S)"
            cp ~/.claude/settings.json ~/.claude/$BACKUP_NAME
            echo "  Backed up to: ~/.claude/$BACKUP_NAME"
            read -p "Overwrite with new settings? (Y/n): " -n 1 -r
            echo
            # Default to Yes if user just presses enter (empty REPLY)
            if [[ -z "$REPLY" ]]; then
                REPLY="y"
            fi
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "Skipping Claude Code settings..."
                SKIP_SETTINGS=true
            fi
        fi

        if [ "$SKIP_SETTINGS" != "true" ]; then
            # Replace placeholders and write settings
            sed -e "s|__OTEL_HELPER_PATH__|$HOME/claude-code-with-bedrock/otel-helper|g" \
                -e "s|__CREDENTIAL_PROCESS_PATH__|$HOME/claude-code-with-bedrock/credential-process|g" \
                "claude-settings/settings.json" > ~/.claude/settings.json

            # Verify placeholders were replaced
            if grep -q '__CREDENTIAL_PROCESS_PATH__\\|__OTEL_HELPER_PATH__' ~/.claude/settings.json 2>/dev/null; then
                echo "WARNING: Some path placeholders were not replaced in settings.json"
                echo "         You may need to edit the file manually: ~/.claude/settings.json"
            else
                echo "OK Claude Code settings configured: ~/.claude/settings.json"
            fi
        fi
    fi
fi

# Copy OTEL helper executable if present
if [ -f "$OTEL_BINARY" ]; then
    echo
    echo "Installing OTEL helper..."
    cp "$OTEL_BINARY" ~/claude-code-with-bedrock/otel-helper
    chmod +x ~/claude-code-with-bedrock/otel-helper
    echo "✓ OTEL helper installed"
fi

# Add debug info if OTEL helper was installed
if [ -f ~/claude-code-with-bedrock/otel-helper ]; then
    echo "The OTEL helper will extract user attributes from authentication tokens"
    echo "and include them in metrics. To test the helper, run:"
    echo "  ~/claude-code-with-bedrock/otel-helper --test"
fi

# Update AWS config
echo
echo "Configuring AWS profiles..."
mkdir -p ~/.aws

# Read all profiles from config.json
PROFILES=$($PYTHON -c "import json; profiles = list(json.load(open('config.json')).keys()); print(' '.join(profiles))")

if [ -z "$PROFILES" ]; then
    echo "❌ No profiles found in config.json"
    exit 1
fi

echo "Found profiles: $PROFILES"
echo

# Get region from package settings (for Bedrock calls, not infrastructure)
if [ -f "claude-settings/settings.json" ]; then
    DEFAULT_REGION=$($PYTHON -c "
import json
print(json.load(open('claude-settings/settings.json'))['env']['AWS_REGION'])
" 2>/dev/null || echo "{profile.aws_region}")
else
    DEFAULT_REGION="{profile.aws_region}"
fi

# Configure each profile
for PROFILE_NAME in $PROFILES; do
    echo "Configuring AWS profile: $PROFILE_NAME"

    # Remove old profile if exists
    sed -i.bak "/\\[profile $PROFILE_NAME\\]/,/^$/d" ~/.aws/config 2>/dev/null || true

    # Get profile-specific region from config.json
    PROFILE_REGION=$($PYTHON -c "
import json
print(json.load(open('config.json')).get('$PROFILE_NAME', {{}}).get('aws_region', '$DEFAULT_REGION'))
")

    # Add new profile with --profile flag (cross-platform, no shell required)
    cat >> ~/.aws/config << EOF
[profile $PROFILE_NAME]
credential_process = $HOME/claude-code-with-bedrock/credential-process --profile $PROFILE_NAME
region = $PROFILE_REGION
EOF
    echo "  ✓ Created AWS profile '$PROFILE_NAME'"
done

# Post-install validation
echo
echo "Validating installation..."
if [ -f ~/claude-code-with-bedrock/credential-process ]; then
    echo "  OK credential-process: ~/claude-code-with-bedrock/credential-process"
else
    echo "  FAIL credential-process not found at: ~/claude-code-with-bedrock/credential-process"
fi
if [ -f ~/.claude/settings.json ]; then
    echo "  OK settings.json: ~/.claude/settings.json"
else
    echo "  WARN settings.json not found at: ~/.claude/settings.json"
fi

echo
echo "======================================"
echo "Installation complete!"
echo "======================================"
echo
echo "Available profiles:"
for PROFILE_NAME in $PROFILES; do
    echo "  - $PROFILE_NAME"
done
echo
echo "To use Claude Code authentication:"
echo "  export AWS_PROFILE=<profile-name>"
echo "  aws sts get-caller-identity"
echo
echo "Example:"
FIRST_PROFILE=$(echo $PROFILES | awk '{{print $1}}')
echo "  export AWS_PROFILE=$FIRST_PROFILE"
echo "  aws sts get-caller-identity"
echo
echo "Note: Authentication will automatically open your browser when needed."
echo
"""

        installer_path = output_dir / "install.sh"
        with open(installer_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(installer_content)
        installer_path.chmod(0o755)

        # Create Windows installer only if Windows builds are enabled (CodeBuild)
        if "windows" in platforms_built or (hasattr(profile, "enable_codebuild") and profile.enable_codebuild):
            self._create_windows_installer(output_dir, profile)

        return installer_path

    def _create_windows_installer(self, output_dir: Path, profile) -> Path:
        """Create Windows batch installer script and PowerShell helper."""

        # Create the PowerShell script that does the actual work
        ps1_content = f"""# Claude Code Authentication Installer for Windows
# Organization: {profile.provider_domain}
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
param(
    [string]$ScriptDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = 'Stop'
Set-Location $ScriptDir

Write-Host '======================================'
Write-Host 'Claude Code Authentication Installer'
Write-Host '======================================'
Write-Host ''
Write-Host 'Organization: {profile.provider_domain}'
Write-Host ''

# Check prerequisites
Write-Host 'Checking prerequisites...'
$hasErrors = $false

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {{
    Write-Host 'ERROR: AWS CLI is not installed'
    Write-Host '       Please install from https://aws.amazon.com/cli/'
    $hasErrors = $true
}}

if (-not (Test-Path 'config.json')) {{
    Write-Host 'ERROR: config.json not found in current directory'
    Write-Host '       Make sure you are running this from the extracted package folder'
    $hasErrors = $true
}}

if (-not (Test-Path 'credential-process-windows.exe')) {{
    Write-Host 'ERROR: credential-process-windows.exe not found'
    Write-Host '       The package may be incomplete or corrupted'
    $hasErrors = $true
}}

if ($hasErrors) {{
    Read-Host 'Press Enter to exit'
    exit 1
}}

if (-not (Test-Path 'claude-settings/settings.json')) {{
    Write-Host 'WARNING: claude-settings/settings.json not found'
    Write-Host '         Claude Code IDE settings will not be configured automatically'
    Write-Host '         You may need to create ~/.claude/settings.json manually'
    Write-Host ''
}}

Write-Host 'OK Prerequisites validated'
Write-Host ''

# Create directory
Write-Host 'Installing authentication tools...'
$installDir = Join-Path $env:USERPROFILE 'claude-code-with-bedrock'
if (-not (Test-Path $installDir)) {{ New-Item -ItemType Directory -Path $installDir -Force | Out-Null }}

# Copy credential process
Write-Host 'Copying credential process...'
Copy-Item -Force 'credential-process-windows.exe' (Join-Path $installDir 'credential-process.exe')

# Copy OTEL helper if it exists
if (Test-Path 'otel-helper-windows.exe') {{
    Write-Host 'Copying OTEL helper...'
    Copy-Item -Force 'otel-helper-windows.exe' (Join-Path $installDir 'otel-helper.exe')
}}

# Copy configuration
Write-Host 'Copying configuration...'
Copy-Item -Force 'config.json' $installDir

# Install Claude Code settings
$claudeDir = Join-Path $env:USERPROFILE '.claude'
if (Test-Path 'claude-settings/settings.json') {{
    Write-Host ''
    Write-Host 'Installing Claude Code settings...'
    if (-not (Test-Path $claudeDir)) {{ New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null }}

    $doWrite = $true
    $settingsTarget = Join-Path $claudeDir 'settings.json'
    if (Test-Path $settingsTarget) {{
        Write-Host 'Existing Claude Code settings found'
        # Backup existing settings
        $backupName = "settings.json.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        $backupPath = Join-Path $claudeDir $backupName
        Copy-Item $settingsTarget $backupPath
        Write-Host "  Backed up to: $backupPath"
        $answer = Read-Host 'Overwrite with new settings? (Y/n)'
        if ($answer -and $answer -ne 'y' -and $answer -ne 'Y') {{
            $doWrite = $false
            Write-Host 'Skipping Claude Code settings...'
        }}
    }}

    if ($doWrite) {{
        $otelPath = ((Join-Path $installDir 'otel-helper.exe') -replace '\\\\', '/')
        $credPath = ((Join-Path $installDir 'credential-process.exe') -replace '\\\\', '/')
        # Use JSON parsing to properly handle paths with spaces
        # ConvertTo-Json automatically escapes quotes inside string values
        $settings = Get-Content 'claude-settings/settings.json' -Raw | ConvertFrom-Json
        # Quote the executable paths to handle spaces in Windows usernames
        if ($settings.otelHeadersHelper) {{
            $settings.otelHeadersHelper = "`"$otelPath`""
        }}
        if ($settings.awsAuthRefresh) {{
            $settings.awsAuthRefresh = $settings.awsAuthRefresh -replace '__CREDENTIAL_PROCESS_PATH__', "`"$credPath`""
        }}
        $settings | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $settingsTarget

        # Verify placeholders were replaced
        $settingsContent = Get-Content $settingsTarget -Raw
        if ($settingsContent -match '__CREDENTIAL_PROCESS_PATH__|__OTEL_HELPER_PATH__') {{
            Write-Host 'WARNING: Some path placeholders were not replaced in settings.json'
            Write-Host '         You may need to edit the file manually:'
            Write-Host "         $settingsTarget"
        }} else {{
            Write-Host "OK Claude Code settings configured: $settingsTarget"
        }}
    }}
}} else {{
    Write-Host ''
    Write-Host 'WARNING: No claude-settings/settings.json found in package'
    Write-Host '         Skipping Claude Code IDE settings configuration'
}}

# Configure AWS profiles
Write-Host ''
Write-Host 'Configuring AWS profiles...'
$configJson = Get-Content 'config.json' | ConvertFrom-Json
$profiles = $configJson.PSObject.Properties.Name

foreach ($p in $profiles) {{
    Write-Host "Configuring AWS profile: $p"
    $region = $configJson.$p.aws_region
    if (-not $region) {{ $region = '{profile.aws_region}' }}
    $credExe = (Join-Path $installDir 'credential-process.exe') -replace '\\\\', '/'
    # Write AWS config directly to avoid quote-stripping by aws configure set
    $awsConfigDir = Join-Path $env:USERPROFILE '.aws'
    if (-not (Test-Path $awsConfigDir)) {{ New-Item -ItemType Directory -Path $awsConfigDir -Force | Out-Null }}
    $awsConfigFile = Join-Path $awsConfigDir 'config'
    $profileBlock = "[profile $p]`ncredential_process = `"$credExe`" --profile $p`nregion = $region`n"
    if (Test-Path $awsConfigFile) {{
        # Read existing content and remove old profile section if present
        $lines = Get-Content $awsConfigFile
        $newLines = @()
        $skipSection = $false
        foreach ($line in $lines) {{
            if ($line -match "^\[profile $p\]") {{
                $skipSection = $true
                continue
            }}
            if ($skipSection -and $line -match '^\[') {{
                $skipSection = $false
            }}
            if (-not $skipSection) {{
                $newLines += $line
            }}
        }}
        # Remove trailing empty lines
        while ($newLines.Count -gt 0 -and $newLines[-1] -eq '') {{ $newLines = $newLines[0..($newLines.Count-2)] }}
        if ($newLines.Count -gt 0) {{
            $newContent = ($newLines -join "`n") + "`n`n" + $profileBlock
        }} else {{
            $newContent = $profileBlock
        }}
    }} else {{
        $newContent = $profileBlock
    }}
    # Write without BOM (UTF8 BOM breaks AWS CLI config parser)
    [System.IO.File]::WriteAllText($awsConfigFile, $newContent)
    Write-Host "  OK Created AWS profile '$p'"
}}

# Post-install validation
Write-Host ''
Write-Host 'Validating installation...'
$credBinary = Join-Path $installDir 'credential-process.exe'
if (Test-Path $credBinary) {{
    Write-Host "  OK credential-process.exe: $credBinary"
}} else {{
    Write-Host "  FAIL credential-process.exe not found at: $credBinary"
}}
$settingsFile = Join-Path (Join-Path $env:USERPROFILE '.claude') 'settings.json'
if (Test-Path $settingsFile) {{
    Write-Host "  OK settings.json: $settingsFile"
}} else {{
    Write-Host "  WARN settings.json not found at: $settingsFile"
}}

# Summary
Write-Host ''
Write-Host '======================================'
Write-Host 'Installation complete!'
Write-Host '======================================'
Write-Host ''
Write-Host 'Available profiles:'
foreach ($p in $profiles) {{ Write-Host "  - $p" }}
Write-Host ''
Write-Host 'To use Claude Code authentication:'
Write-Host '  set AWS_PROFILE=<profile-name>'
Write-Host '  aws sts get-caller-identity'
Write-Host ''
Write-Host 'Example:'
$first = $profiles | Select-Object -First 1
Write-Host "  set AWS_PROFILE=$first"
Write-Host '  aws sts get-caller-identity'
Write-Host ''
Write-Host 'Note: Authentication will automatically open your browser when needed.'
"""

        ps1_path = output_dir / "ccwb-install.ps1"
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(ps1_content)

        # Create the batch launcher that calls the PowerShell script
        bat_content = f"""@echo off
REM Claude Code Authentication Installer for Windows
REM Organization: {profile.provider_domain}
REM Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ccwb-install.ps1"

pause
"""

        installer_path = output_dir / "install.bat"
        with open(installer_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        # Note: chmod not needed on Windows batch files
        return installer_path

    def _create_documentation(self, output_dir: Path, profile, timestamp: str):
        """Create user documentation."""
        readme_content = f"""# Claude Code Authentication Setup

## Quick Start

### macOS/Linux

1. Extract the package:
   ```bash
   unzip claude-code-package-*.zip
   cd claude-code-package
   ```

2. Run the installer:
   ```bash
   chmod +x install.sh && ./install.sh
   ```

3. Use the AWS profile:
   ```bash
   export AWS_PROFILE=ClaudeCode
   aws sts get-caller-identity
   ```

### Windows

#### Step 1: Download the Package
```powershell
# Use the Invoke-WebRequest command provided by your IT administrator
Invoke-WebRequest -Uri "URL_PROVIDED" -OutFile "claude-code-package.zip"
```

#### Step 2: Extract the Package

**Option A: Using Windows Explorer**
1. Right-click on `claude-code-package.zip`
2. Select "Extract All..."
3. Choose a destination folder
4. Click "Extract"

**Option B: Using PowerShell**
```powershell
# Extract to current directory
Expand-Archive -Path "claude-code-package.zip" -DestinationPath "claude-code-package"

# Navigate to the extracted folder
cd claude-code-package
```

**Option C: Using Command Prompt**
```cmd
# If you have tar available (Windows 10 1803+)
tar -xf claude-code-package.zip

# Or use PowerShell from Command Prompt
powershell -command "Expand-Archive -Path 'claude-code-package.zip' -DestinationPath 'claude-code-package'"

cd claude-code-package
```

#### Step 3: Run the Installer
```cmd
install.bat
```

The installer will:
- Check for AWS CLI installation
- Copy authentication tools to `%USERPROFILE%\\claude-code-with-bedrock`
- Configure the AWS profile "ClaudeCode"
- Test the authentication

#### Step 4: Use Claude Code
```cmd
# Set the AWS profile
set AWS_PROFILE=ClaudeCode

# Verify authentication works
aws sts get-caller-identity

# Your browser will open automatically for authentication if needed
```

For PowerShell users:
```powershell
$env:AWS_PROFILE = "ClaudeCode"
aws sts get-caller-identity
```

## What This Does

- Installs the Claude Code authentication tools
- Configures your AWS CLI to use {profile.provider_domain} for authentication
- Sets up automatic credential refresh via your browser

## Requirements

- Python 3.8 or later
- AWS CLI v2
- pip3

## Troubleshooting

### macOS Keychain Access Popup
On first use, macOS will ask for permission to access the keychain. This is normal and required for \
secure credential storage. Click "Always Allow" to avoid repeated prompts.

### Authentication Issues
If you encounter issues with authentication:
- Ensure you're assigned to the Claude Code application in your identity provider
- Check that port 8400 is available for the callback
- Contact your IT administrator for help

### Authentication Behavior

The system handles authentication automatically:
- Your browser will open when authentication is needed
- Credentials are cached securely to avoid repeated logins
- Bad credentials are automatically cleared and re-authenticated

To manually clear cached credentials (if needed):
```bash
~/claude-code-with-bedrock/credential-process --clear-cache
```

This will force re-authentication on your next AWS command.

### Browser doesn't open
Check that you're not in an SSH session. The browser needs to open on your local machine.

## Support

Contact your IT administrator for help.

Configuration Details:
- Organization: {profile.provider_domain}
- Region: {profile.aws_region}
- Package Version: {timestamp}"""

        # Add analytics information if enabled
        if profile.monitoring_enabled and getattr(profile, "analytics_enabled", True):
            analytics_section = f"""

## Analytics Dashboard

Your organization has enabled advanced analytics for Claude Code usage. You can access detailed metrics \
and reports through AWS Athena.

To view analytics:
1. Open the AWS Console in region {profile.aws_region}
2. Navigate to Athena
3. Select the analytics workgroup and database
4. Run pre-built queries or create custom reports

Available metrics include:
- Token usage by user
- Cost allocation
- Model usage patterns
- Activity trends
"""
            readme_content += analytics_section

        readme_content += "\n" ""

        with open(output_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(readme_content)

    def _create_claude_settings(
        self,
        output_dir: Path,
        profile: object,
        include_coauthored_by: bool = True,
        profile_name: str = "ClaudeCode",
        otel_resource_attributes: str | None = None,
    ) -> None:
        """Create Claude Code settings.json with Bedrock and optional monitoring configuration."""
        console = Console()

        try:
            # Create claude-settings directory (visible, not hidden)
            claude_dir = output_dir / "claude-settings"
            claude_dir.mkdir(exist_ok=True)

            # Start with basic settings required for Bedrock
            settings = {
                "env": {
                    # Set AWS_REGION based on cross-region profile for correct Bedrock endpoint
                    "AWS_REGION": self._get_bedrock_region_for_profile(profile),
                    "CLAUDE_CODE_USE_BEDROCK": "1",
                    # AWS_PROFILE is used by both AWS SDK and otel-helper
                    "AWS_PROFILE": profile_name,
                }
            }

            # Add includeCoAuthoredBy setting if user wants to disable it (Claude Code defaults to true)
            # Only add the field if the user wants it disabled
            if not include_coauthored_by:
                settings["includeCoAuthoredBy"] = False

            # Add awsAuthRefresh for session-based credential storage
            if profile.credential_storage == "session":
                settings["awsAuthRefresh"] = f"__CREDENTIAL_PROCESS_PATH__ --profile {profile_name}"

            # Add selected model as environment variable if available
            if hasattr(profile, "selected_model") and profile.selected_model:
                settings["env"]["ANTHROPIC_MODEL"] = profile.selected_model

                # Determine and set small/fast model based on selected model family
                if "opus" in profile.selected_model:
                    # For Opus, use Haiku as small/fast model
                    model_id = profile.selected_model
                    prefix = model_id.split(".anthropic")[0]  # Get us/eu/apac prefix
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = f"{prefix}.anthropic.claude-3-5-haiku-20241022-v1:0"
                else:
                    # For other models, use same model as small/fast (or could use Haiku)
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = profile.selected_model

            # If monitoring is enabled, add telemetry configuration
            if profile.monitoring_enabled:
                # Get monitoring stack outputs
                monitoring_stack = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
                cmd = [
                    "aws",
                    "cloudformation",
                    "describe-stacks",
                    "--stack-name",
                    monitoring_stack,
                    "--region",
                    profile.aws_region,
                    "--query",
                    "Stacks[0].Outputs",
                    "--output",
                    "json",
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
                        # Add monitoring configuration
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

                        # Add the helper executable for generating OTEL headers with user attributes
                        # Use a placeholder that will be replaced by the installer script based on platform
                        settings["otelHeadersHelper"] = "__OTEL_HELPER_PATH__"

                        is_https = endpoint.startswith("https://")
                        console.print(f"[dim]Added monitoring with {'HTTPS' if is_https else 'HTTP'} endpoint[/dim]")
                        if not is_https:
                            console.print(
                                "[dim]WARNING: Using HTTP endpoint - consider enabling HTTPS for production[/dim]"
                            )
                    else:
                        console.print("[yellow]Warning: No monitoring endpoint found in stack outputs[/yellow]")
                else:
                    console.print("[yellow]Warning: Could not fetch monitoring stack outputs[/yellow]")

            # Save settings.json
            settings_path = claude_dir / "settings.json"
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)

            console.print("[dim]Created Claude Code settings for Bedrock configuration[/dim]")

        except Exception as e:
            console.print(f"[yellow]Warning: Could not create Claude Code settings: {e}[/yellow]")
