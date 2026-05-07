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

# Runtime packages bundled into the credential provider binary.
_CREDENTIAL_PROVIDER_RUNTIME_DEPS = ["boto3", "requests", "PyJWT", "keyring", "cryptography"]
_OTEL_HELPER_RUNTIME_DEPS: list[str] = []  # otel_helper uses only stdlib
_PYINSTALLER_PIN = "pyinstaller==6.*"


def _find_universal2_python() -> Path | None:
    """Return the first universal2 Python ≥3.10 found in the standard python.org install location, or None."""
    import glob

    candidates = sorted(
        glob.glob("/Library/Frameworks/Python.framework/Versions/*/bin/python3*"),
        reverse=True,  # prefer higher versions
    )
    for candidate in candidates:
        p = Path(candidate)
        if not p.is_file() or not p.stat().st_size:
            continue
        result = subprocess.run(["/usr/bin/lipo", "-info", str(p)], capture_output=True, text=True)  # nosec B603 B607
        if result.returncode != 0:
            continue
        out = result.stdout.strip()
        # universal2 shows "are: x86_64 arm64" or "are: arm64 x86_64"
        if "are:" in out and "x86_64" in out and "arm64" in out:
            # Verify version ≥3.10
            ver = subprocess.run([str(p), "--version"], capture_output=True, text=True)  # nosec B603 B607
            if ver.returncode == 0:
                try:
                    parts = ver.stdout.strip().split()[1].split(".")
                    if int(parts[0]) >= 3 and int(parts[1]) >= 10:
                        return p
                except (IndexError, ValueError):
                    continue
    return None


def _ensure_cross_arch_venv(arch: str, universal2_python: Path, runtime_packages: list[str], console: Console) -> Path:
    """Create (or reuse) ~/.ccwb/build-venvs/<arch>/ seeded from a universal2 Python.

    The venv is created under `arch -<arch>` so pip pulls arch-matched wheels for every
    native extension (cffi, cryptography, etc.). Reused on subsequent runs unless stale.
    """
    venv_dir = Path.home() / ".ccwb" / "build-venvs" / arch
    pyinstaller_bin = venv_dir / "bin" / "pyinstaller"
    python_bin = venv_dir / "bin" / "python3"

    if pyinstaller_bin.exists() and python_bin.exists():
        # Validate the venv's Python is actually the right arch
        result = subprocess.run(["/usr/bin/lipo", "-info", str(python_bin)], capture_output=True, text=True)  # nosec B603 B607
        if result.returncode == 0 and arch in result.stdout:
            return venv_dir
        # Wrong arch — rebuild
        import shutil
        console.print(f"[yellow]Rebuilding {arch} build venv (wrong architecture detected)[/yellow]")
        shutil.rmtree(venv_dir, ignore_errors=True)

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]Preparing {arch} build venv at {venv_dir} (first run, ~30s)...[/cyan]")

    create = subprocess.run(  # nosec B603 B607
        ["/usr/bin/arch", f"-{arch}", str(universal2_python), "-m", "venv", str(venv_dir)],
        capture_output=True, text=True,
    )
    if create.returncode != 0:
        raise RuntimeError(f"Failed to create {arch} build venv: {create.stderr}")

    pip = venv_dir / "bin" / "pip"
    install = subprocess.run(  # nosec B603 B607
        ["/usr/bin/arch", f"-{arch}", str(pip), "install", "--quiet", _PYINSTALLER_PIN, *runtime_packages],
        capture_output=True, text=True,
    )
    if install.returncode != 0:
        raise RuntimeError(f"Failed to install deps into {arch} build venv: {install.stderr or install.stdout}")

    console.print(f"[green]✓ {arch} build venv ready[/green]")
    return venv_dir


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
        option("build-verbose", description="Enable verbose logging for build processes", flag=True),
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

            # Only include Windows if CodeBuild is enabled
            if hasattr(profile, "enable_codebuild") and profile.enable_codebuild:
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

        # Cross-arch macOS builds auto-create per-arch venvs from a universal2 Python.
        # Detect once here so both the platforms_to_build assembly and _build_macos_pyinstaller share the same result.
        _universal2_python = _find_universal2_python() if platform.system().lower() == "darwin" else None

        # Build executable(s) using PyInstaller/Docker
        # Handle both list and single platform selection
        if isinstance(target_platform, list):
            # User selected multiple platforms via checkbox
            platforms_to_build = []
            for platform_choice in target_platform:
                if platform_choice == "all":
                    # If "all" is in the list, expand it based on current OS
                    current_os = platform.system().lower()
                    current_machine = platform.machine().lower()

                    if current_os == "darwin":
                        host_arch = current_machine  # arm64 or x86_64
                        platforms_to_build.append(f"macos-{'arm64' if host_arch == 'arm64' else 'intel'}")
                        cross_arch = "x86_64" if host_arch == "arm64" else "arm64"
                        cross_platform = "macos-intel" if host_arch == "arm64" else "macos-arm64"
                        if _universal2_python:
                            platforms_to_build.append(cross_platform)
                        else:
                            console.print(
                                f"[dim]Note: {cross_platform} skipped — install Python universal2 from python.org to enable.[/dim]"
                            )

                        try:
                            docker_check = subprocess.run(["docker", "--version"], capture_output=True)
                            docker_available = docker_check.returncode == 0
                        except FileNotFoundError:
                            docker_available = False
                        if docker_available:
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
                host_arch = current_machine  # arm64 or x86_64
                platforms_to_build.append(f"macos-{'arm64' if host_arch == 'arm64' else 'intel'}")
                cross_platform = "macos-intel" if host_arch == "arm64" else "macos-arm64"
                if _universal2_python:
                    platforms_to_build.append(cross_platform)
                else:
                    console.print(
                        f"[dim]Note: {cross_platform} skipped — install Python universal2 from python.org to enable.[/dim]"
                    )

                # Check if Docker is available for Linux builds
                try:
                    docker_check = subprocess.run(["docker", "--version"], capture_output=True)
                    docker_available = docker_check.returncode == 0
                except FileNotFoundError:
                    docker_available = False
                if docker_available:
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
        self._create_config(output_dir, profile, federation_identifier, federation_type, profile_name, console)

        # Create installer
        console.print("[cyan]Creating installer script...[/cyan]")
        self._create_installer(output_dir, profile, built_executables, built_otel_helpers)

        # Copy shell wrapper for OTEL helper (Layer 2 caching - avoids PyInstaller startup)
        if built_otel_helpers:
            import shutil as _shutil

            shell_wrapper_src = Path(__file__).parent.parent.parent.parent / "otel_helper" / "otel-helper.sh"
            if shell_wrapper_src.exists():
                shell_wrapper_dst = output_dir / "otel-helper.sh"
                _shutil.copy2(shell_wrapper_src, shell_wrapper_dst)
                shell_wrapper_dst.chmod(0o755)
                console.print("[green]✓ OTEL helper shell wrapper included[/green]")

        # Create documentation
        console.print("[cyan]Creating documentation...[/cyan]")
        self._create_documentation(output_dir, profile, timestamp)

        # Always create Claude Code settings (required for Bedrock configuration)
        console.print("[cyan]Creating Claude Code settings...[/cyan]")
        self._create_claude_settings(output_dir, profile, include_coauthored_by, profile_name)

        # Generate CoWork 3P MDM configuration if enabled
        if profile.cowork_3p_enabled:
            console.print("\n[cyan]Generating CoWork 3P MDM configuration...[/cyan]")
            self._generate_cowork_3p_mdm_config(output_dir, profile, profile_name)

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
        console.print("  • README.md - Installation instructions")
        if profile.monitoring_enabled and (output_dir / "claude-settings" / "settings.json").exists():
            console.print("  • claude-settings/settings.json - Claude Code telemetry settings")
            for platform_name, otel_helper_path in built_otel_helpers:
                console.print(f"  • {otel_helper_path.name} - OTEL helper executable for {platform_name}")
        if profile.cowork_3p_enabled:
            if (output_dir / "cowork-3p-config.json").exists():
                console.print("  • cowork-3p-config.json - CoWork 3P MDM configuration (JSON)")
            if (output_dir / "cowork-3p.mobileconfig").exists():
                console.print("  • cowork-3p.mobileconfig - CoWork 3P MDM profile (macOS)")
            if (output_dir / "cowork-3p.reg").exists():
                console.print("  • cowork-3p.reg - CoWork 3P registry file (Windows)")

        # Next steps
        console.print("\n[bold]Distribution steps:[/bold]")
        console.print("1. Send users the entire dist folder")
        console.print("2. Users run: ./install.sh")
        console.print("3. Authentication is configured automatically")

        console.print("\n[bold]To test locally:[/bold]")
        console.print(f"cd {output_dir}")
        console.print("./install.sh")

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
            # binary_name already set above
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
            ["poetry", "run", "which", "nuitka"], capture_output=True, text=True, cwd=source_dir
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

        host_arch = platform.machine().lower()
        cross_arch = arch != host_arch and arch != "universal2"

        # Determine log level based on verbose flag
        log_level = "INFO" if verbose else "WARN"

        if cross_arch:
            # Cross-arch build: need a per-arch venv seeded from a universal2 Python
            universal2_python = _find_universal2_python()
            if universal2_python is None:
                raise RuntimeError(
                    f"Cross-arch macOS build requires a universal2 Python but none was found.\n\n"
                    f"Install Python universal2 from python.org:\n"
                    f"  https://www.python.org/downloads/macos/\n\n"
                    f"Download the 'macOS 64-bit universal2 installer' for Python 3.12, then re-run.\n\n"
                    f"To build only the host arch ({host_arch}), omit the cross-arch target."
                )
            venv_dir = _ensure_cross_arch_venv(arch, universal2_python, _CREDENTIAL_PROVIDER_RUNTIME_DEPS, console)
            work_root = Path.home() / ".ccwb" / "build-work"
            work_root.mkdir(parents=True, exist_ok=True)
            cmd = [
                "/usr/bin/arch", f"-{arch}",
                str(venv_dir / "bin" / "pyinstaller"),
                "--onefile", "--clean", "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                f"--workpath={str(work_root / arch)}",
                f"--specpath={str(work_root / arch)}",
                f"--log-level={log_level}",
                "--hidden-import=keyring.backends.macOS",
                "--hidden-import=keyring.backends.SecretService",
                "--hidden-import=keyring.backends.Windows",
                "--hidden-import=keyring.backends.chainer",
                str(src_file),
            ]
        else:
            # Native build: use Poetry environment directly
            cmd = [
                "poetry", "run", "pyinstaller",
                "--onefile", "--clean", "--noconfirm",
                f"--target-arch={arch}",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller",
                "--specpath=/tmp/pyinstaller",
                f"--log-level={log_level}",
                "--hidden-import=keyring.backends.macOS",
                "--hidden-import=keyring.backends.SecretService",
                "--hidden-import=keyring.backends.Windows",
                "--hidden-import=keyring.backends.chainer",
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
        try:
            docker_check = subprocess.run(["docker", "--version"], capture_output=True)
            docker_installed = docker_check.returncode == 0
        except FileNotFoundError:
            docker_installed = False
        if not docker_installed:
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
        try:
            docker_check = subprocess.run(["docker", "--version"], capture_output=True)
            docker_installed = docker_check.returncode == 0
        except FileNotFoundError:
            docker_installed = False
        if not docker_installed:
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
                arcname = str(py_file.relative_to(source_dir.parent))
                zf.write(py_file, arcname)

            # Add pyproject.toml for dependencies
            pyproject_file = source_dir / "pyproject.toml"
            if pyproject_file.exists():
                zf.write(pyproject_file, "pyproject.toml")

        return source_zip

    def _build_otel_helper(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable for OTEL helper script."""
        # Windows uses Nuitka via CodeBuild
        if target_platform == "windows":
            # Check if the Windows binary already exists (built by _build_executable)
            windows_binary = output_dir / "otel-helper-windows.exe"
            if windows_binary.exists():
                return windows_binary
            else:
                # If not, we need to build via CodeBuild (but this should have been done already)
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

        # Determine log level based on verbose flag
        log_level = "INFO" if verbose else "WARN"

        host_arch = platform_module.machine().lower()
        cross_arch = platform_name == "macos" and arch is not None and arch != host_arch and arch != "universal2"

        # Build PyInstaller command
        if cross_arch:
            # Cross-arch build: need a per-arch venv seeded from a universal2 Python
            universal2_python = _find_universal2_python()
            if universal2_python is None:
                console.print(f"[yellow]Warning: Skipping {binary_name} — cross-arch build requires universal2 Python (not found)[/yellow]")
                return output_dir / binary_name
            venv_dir = _ensure_cross_arch_venv(arch, universal2_python, _OTEL_HELPER_RUNTIME_DEPS, console)
            work_root = Path.home() / ".ccwb" / "build-work"
            work_root.mkdir(parents=True, exist_ok=True)
            cmd = [
                "/usr/bin/arch", f"-{arch}",
                str(venv_dir / "bin" / "pyinstaller"),
                "--onefile", "--clean", "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                f"--workpath={str(work_root / arch)}",
                f"--specpath={str(work_root / arch)}",
                f"--log-level={log_level}",
                str(src_file),
            ]
        else:
            cmd = [
                "poetry", "run", "pyinstaller",
                "--onefile", "--clean", "--noconfirm",
                f"--name={binary_name}",
                f"--distpath={str(output_dir)}",
                "--workpath=/tmp/pyinstaller",
                "--specpath=/tmp/pyinstaller",
                f"--log-level={log_level}",
                str(src_file),
            ]

        # Add target architecture for macOS (only for native Poetry build)
        if not cross_arch and platform_name == "macos" and arch:
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
        else:
            raise ValueError(f"Unsupported target platform: {target_platform}")

        # Check platform compatibility (same as credential-process)
        if target_platform == "macos" and current_system != "darwin":
            raise RuntimeError(f"Cannot build macOS binary on {current_system}. Nuitka requires native builds.")
        elif target_platform == "linux" and current_system != "linux":
            raise RuntimeError(f"Cannot build Linux binary on {current_system}. Nuitka requires native builds.")

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

    def _create_config(
        self,
        output_dir: Path,
        profile,
        federation_identifier: str,
        federation_type: str = "cognito",
        profile_name: str = "ClaudeCode",
        console=None,
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

        # Add confidential client fields for Azure AD if present.
        # client_secret is never written to config.json — it lives in the OS keyring.
        # End users set it with: credential-process --set-client-secret --profile <profile>
        if getattr(profile, "azure_auth_mode", None):
            config[profile_name]["azure_auth_mode"] = profile.azure_auth_mode
        if getattr(profile, "client_certificate_path", None):
            config[profile_name]["client_certificate_path"] = profile.client_certificate_path
            config[profile_name]["client_certificate_key_path"] = profile.client_certificate_key_path
            # Warn if the paths are absolute — they are machine-specific and will not
            # resolve on end-user machines with different install layouts.
            cert_is_absolute = Path(profile.client_certificate_path).is_absolute()
            key_is_absolute = Path(profile.client_certificate_key_path).is_absolute()
            if (cert_is_absolute or key_is_absolute) and console:
                console.print(
                    "\n[yellow]Warning: certificate paths in config.json are absolute and will not "
                    "resolve on machines where the files are stored elsewhere.[/yellow]"
                )
                console.print(
                    "[yellow]Instruct end users to set the following environment variables:[/yellow]"
                )
                console.print("[dim]  AZURE_CLIENT_CERTIFICATE_PATH=<path/to/cert.pem>[/dim]")
                console.print("[dim]  AZURE_CLIENT_CERTIFICATE_KEY_PATH=<path/to/key.pem>[/dim]\n")

        # Add quota settings so the credential provider can enforce limits
        if getattr(profile, "quota_api_endpoint", None):
            config[profile_name]["quota_api_endpoint"] = profile.quota_api_endpoint
            config[profile_name]["quota_fail_mode"] = getattr(profile, "quota_fail_mode", "open")
            config[profile_name]["quota_check_interval"] = getattr(profile, "quota_check_interval", 30)

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
            if hostname_lower.endswith(".okta.com") or hostname_lower == "okta.com":
                return "okta"
            elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                return "auth0"
            elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                return "azure"
            elif hostname_lower.endswith(".windows.net") or hostname_lower == "windows.net":
                return "azure"
            elif hostname_lower.endswith(".amazoncognito.com") or hostname_lower == "amazoncognito.com":
                return "cognito"
            else:
                return "oidc"  # Default to generic OIDC
        except Exception:
            return "oidc"  # Default to generic OIDC on parsing error

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

# macOS Gatekeeper + Keychain notices
if [[ "$OSTYPE" == "darwin"* ]]; then
    # Remove quarantine flag added by macOS when downloading unsigned binaries.
    # Without this, Gatekeeper blocks execution with "Apple could not verify..." dialog.
    xattr -d com.apple.quarantine ~/claude-code-with-bedrock/credential-process 2>/dev/null || true
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
            echo "✓ Claude Code settings configured"
        fi
    fi
fi

# Copy OTEL helper executable and shell wrapper if present
if [ -f "$OTEL_BINARY" ]; then
    echo
    echo "Installing OTEL helper..."
    # Install PyInstaller binary as otel-helper-bin (fallback for cache miss)
    cp "$OTEL_BINARY" ~/claude-code-with-bedrock/otel-helper-bin
    chmod +x ~/claude-code-with-bedrock/otel-helper-bin
    xattr -d com.apple.quarantine ~/claude-code-with-bedrock/otel-helper-bin 2>/dev/null || true
    # Install shell wrapper as otel-helper (fast cache check, avoids PyInstaller startup)
    if [ -f "otel-helper.sh" ]; then
        cp "otel-helper.sh" ~/claude-code-with-bedrock/otel-helper
        chmod +x ~/claude-code-with-bedrock/otel-helper
    else
        # Fallback: if shell wrapper not in package, point directly to binary
        cp "$OTEL_BINARY" ~/claude-code-with-bedrock/otel-helper
        chmod +x ~/claude-code-with-bedrock/otel-helper
    fi
    echo "✓ OTEL helper installed"
fi

# Add debug info if OTEL helper was installed
if [ -f ~/claude-code-with-bedrock/otel-helper ]; then
    echo "The OTEL helper will extract user attributes from authentication tokens"
    echo "and include them in metrics. To test the helper, run:"
    echo "  ~/claude-code-with-bedrock/otel-helper-bin --test"
fi

# Update AWS config
echo
echo "Configuring AWS profiles..."
mkdir -p ~/.aws

# Read all profiles from config.json
PROFILES=$(python3 -c "import json; profiles = list(json.load(open('config.json')).keys()); print(' '.join(profiles))")

if [ -z "$PROFILES" ]; then
    echo "❌ No profiles found in config.json"
    exit 1
fi

echo "Found profiles: $PROFILES"
echo

# Get region from package settings (for Bedrock calls, not infrastructure)
if [ -f "claude-settings/settings.json" ]; then
    DEFAULT_REGION=$(python3 -c "import json; print(json.load(open('claude-settings/settings.json'))[
    'env']['AWS_REGION'])" 2>/dev/null || echo "{profile.aws_region}")
else
    DEFAULT_REGION="{profile.aws_region}"
fi

# Configure each profile
for PROFILE_NAME in $PROFILES; do
    echo "Configuring AWS profile: $PROFILE_NAME"

    # Remove old profile if exists
    sed -i.bak "/\\[profile $PROFILE_NAME\\]/,/^$/d" ~/.aws/config 2>/dev/null || true

    # Purge any stale stanza from ~/.aws/credentials. The credential chain
    # resolves that file before credential_process in ~/.aws/config, so a
    # leftover [PROFILE_NAME] block (e.g. EXPIRED placeholder written by an
    # older ccwb auth logout) would shadow credential_process and break
    # Cowork Desktop with a 403 InvalidClientTokenId.
    sed -i.bak "/\\[$PROFILE_NAME\\]/,/^$/d" ~/.aws/credentials 2>/dev/null || true

    # Get profile-specific region from config.json
    PROFILE_REGION=$(python3 -c "import json; print(json.load(open('config.json')).get('$PROFILE_NAME', \
    {{}}).get('aws_region', '$DEFAULT_REGION'))")

    # Add new profile with --profile flag (cross-platform, no shell required)
    cat >> ~/.aws/config << EOF
[profile $PROFILE_NAME]
credential_process = $HOME/claude-code-with-bedrock/credential-process --profile $PROFILE_NAME
region = $PROFILE_REGION
EOF
    echo "  ✓ Created AWS profile '$PROFILE_NAME'"
done

# Apply CoWork configuration profile on macOS if present
if [[ "$OSTYPE" == "darwin"* ]] && [ -f "cowork-3p.mobileconfig" ]; then
    echo
    echo "Applying CoWork configuration profile..."
    # `open` launches System Settings > Profiles so the user can review and
    # click Install. macOS does not allow silent installation of unsigned
    # configuration profiles without MDM enrollment.
    if open "cowork-3p.mobileconfig" 2>/dev/null; then
        echo "✓ CoWork configuration profile opened in System Settings"
        echo "  → Click 'Install' to complete CoWork 3P setup"
    else
        echo "⚠️  Could not open cowork-3p.mobileconfig automatically"
        echo "   Double-click the file to install it manually"
    fi
fi

echo
echo "======================================"
echo "✓ Installation complete!"
echo "======================================"
echo
echo "Available profiles:"
for PROFILE_NAME in $PROFILES; do
    echo "  - $PROFILE_NAME"
done
echo
echo "To use Claude Code authentication:"
echo "  export AWS_PROFILE=<profile-name>"
echo "  claude"
echo
echo "Example:"
FIRST_PROFILE=$(echo $PROFILES | awk '{{print $1}}')
echo "  export AWS_PROFILE=$FIRST_PROFILE"
echo "  claude"
echo
echo "Note: Authentication will automatically open your browser when needed."
echo
"""

        installer_path = output_dir / "install.sh"
        with open(installer_path, "w") as f:
            f.write(installer_content)
        installer_path.chmod(0o755)

        # Create Windows installer only if Windows builds are enabled (CodeBuild)
        if "windows" in platforms_built or (hasattr(profile, "enable_codebuild") and profile.enable_codebuild):
            self._create_windows_installer(output_dir, profile)

        return installer_path

    def _create_windows_installer(self, output_dir: Path, profile) -> Path:
        """Create Windows batch installer script."""

        installer_content = f"""@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
REM Claude Code Authentication Installer for Windows
REM Organization: {profile.provider_domain}
REM Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

echo ======================================
echo Claude Code Authentication Installer
echo ======================================
echo.
echo Organization: {profile.provider_domain}
echo.

REM Create directory
echo Installing authentication tools...
if not exist "%USERPROFILE%\\claude-code-with-bedrock" mkdir "%USERPROFILE%\\claude-code-with-bedrock"

REM Copy credential process executable with renamed target
echo Copying credential process...
copy /Y "credential-process-windows.exe" "%USERPROFILE%\\claude-code-with-bedrock\\credential-process.exe" >nul
if %errorlevel% neq 0 (
    echo ERROR: Failed to copy credential-process-windows.exe
    pause
    exit /b 1
)

REM Copy OTEL helper if it exists with renamed target
if exist "otel-helper-windows.exe" (
    echo Copying OTEL helper...
    copy /Y "otel-helper-windows.exe" "%USERPROFILE%\\claude-code-with-bedrock\\otel-helper.exe" >nul
)

REM Copy configuration
echo Copying configuration...
copy /Y "config.json" "%USERPROFILE%\\claude-code-with-bedrock\\" >nul

REM Apply CoWork registry settings if present
if exist "cowork-3p.reg" (
    echo Applying CoWork registry settings...
    REM Remove the policy key first so stale values (e.g. old inferenceCredentialHelper)
    REM don't linger alongside the new config — regedit /s only adds/updates, never deletes.
    reg delete "HKCU\\SOFTWARE\\Policies\\Claude" /f >nul 2>&1
    regedit /s "cowork-3p.reg"
    if %errorlevel% neq 0 (
        echo WARNING: Failed to apply CoWork registry settings
    ) else (
        echo OK CoWork registry settings applied
    )
)

REM Copy Claude Code settings if they exist
if exist "claude-settings" (
    echo Copying Claude Code telemetry settings...
    if not exist "%USERPROFILE%\\.claude" mkdir "%USERPROFILE%\\.claude"

    REM Copy settings and replace placeholders
    if exist "claude-settings\\settings.json" (
        set SKIP_SETTINGS=false
        if exist "%USERPROFILE%\\.claude\\settings.json" (
            echo Existing Claude Code settings found
            set /p OVERWRITE="Overwrite with new settings? (y/n): "
            if /i not "%OVERWRITE%"=="y" (
                echo Skipping Claude Code settings...
                set SKIP_SETTINGS=true
            )
        )

        if not "%SKIP_SETTINGS%"=="true" (
            REM Use PowerShell to replace placeholders
            powershell -Command "$otelPath = $env:USERPROFILE + '\\claude-code-with-bedrock\\otel-helper.exe' -replace '\\\\', '/'; $credPath = $env:USERPROFILE + '\\claude-code-with-bedrock\\credential-process.exe' -replace '\\\\', '/'; (Get-Content 'claude-settings\\settings.json') -replace '__OTEL_HELPER_PATH__', $otelPath -replace '__CREDENTIAL_PROCESS_PATH__', $credPath | Set-Content (Join-Path $env:USERPROFILE '.claude\\settings.json')"
            echo OK Claude Code settings configured
        )
    )
)

REM Configure AWS profiles by writing ~/.aws/config directly (no AWS CLI dependency)
echo.
echo Configuring AWS profiles...

if not exist "%USERPROFILE%\\.aws" mkdir "%USERPROFILE%\\.aws"

REM Purge any stale stanza from %USERPROFILE%\.aws\credentials. The credential
REM chain resolves that file before credential_process in %USERPROFILE%\.aws\config,
REM so a leftover [profile-name] block (e.g. EXPIRED placeholder written by an
REM older ccwb auth logout) would shadow credential_process and break Cowork
REM Desktop with a 403 InvalidClientTokenId.
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $awsCreds = Join-Path $env:USERPROFILE '.aws\credentials'; if (Test-Path $awsCreds) {{ $cfg = Get-Content config.json | ConvertFrom-Json; $existing = Get-Content $awsCreds -Raw; foreach ($p in $cfg.PSObject.Properties.Name) {{ $pattern = '(?ms)^\[' + [regex]::Escape($p) + '\].*?(?=^\[|\Z)'; $existing = [regex]::Replace($existing, $pattern, '') }}; Set-Content -Path $awsCreds -Value $existing.TrimStart() -NoNewline -Encoding ASCII }}"

powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $nl = [char]13 + [char]10; $cfg = Get-Content config.json | ConvertFrom-Json; $awsConfig = Join-Path $env:USERPROFILE '.aws\config'; $credProcess = Join-Path $env:USERPROFILE 'claude-code-with-bedrock\credential-process.exe'; $existing = if (Test-Path $awsConfig) {{ Get-Content $awsConfig -Raw }} else {{ '' }}; foreach ($p in $cfg.PSObject.Properties.Name) {{ $region = $cfg.$p.aws_region; if (-not $region) {{ $region = '{profile.aws_region}' }}; $pattern = '(?ms)^\[profile ' + [regex]::Escape($p) + '\].*?(?=^\[|\Z)'; $existing = [regex]::Replace($existing, $pattern, ''); $stanza = '[profile ' + $p + ']' + $nl + 'credential_process = ' + $credProcess + ' --profile ' + $p + $nl + 'region = ' + $region + $nl; $existing = $existing.TrimEnd() + $nl + $nl + $stanza; Write-Host ('  OK Configured AWS profile ' + $p) }}; Set-Content -Path $awsConfig -Value $existing.TrimStart() -NoNewline -Encoding ASCII"
if %errorlevel% neq 0 (
    echo ERROR: Failed to configure AWS profiles
    pause
    exit /b 1
)

echo.
echo ======================================
echo Installation complete!
echo ======================================
echo.
echo Available profiles:
for /f %%p in ('powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).PSObject.Properties.Name"') do (
    echo   - %%p
)
echo.
echo To use Claude Code authentication:
echo   set AWS_PROFILE=^<profile-name^>
echo   claude
echo.
echo Example:
for /f %%p in ('powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).PSObject.Properties.Name | Select-Object -First 1"') do (
    echo   set AWS_PROFILE=%%p
    echo   claude
)
echo.
echo Note: Authentication will automatically open your browser when needed.
echo.
pause
"""

        installer_path = output_dir / "install.bat"
        with open(installer_path, "w", encoding="utf-8") as f:
            f.write(installer_content)

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
   ./install.sh
   ```

3. Use the AWS profile:
   ```bash
   export AWS_PROFILE=ClaudeCode
   claude
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
- Copy authentication tools to `%USERPROFILE%\\claude-code-with-bedrock`
- Configure the AWS profile "ClaudeCode" in `%USERPROFILE%\\.aws\\config`
- Apply CoWork registry settings (if included)

#### Step 4: Use Claude Code
```cmd
# Set the AWS profile
set AWS_PROFILE=ClaudeCode

# Run Claude Code (authentication opens your browser on first use)
claude
```

For PowerShell users:
```powershell
$env:AWS_PROFILE = "ClaudeCode"
claude
```

## What This Does

- Installs the Claude Code authentication tools
- Configures an AWS named profile in `~/.aws/config` (or `%USERPROFILE%\\.aws\\config`) that points at the bundled `credential-process` binary
- Sets up automatic credential refresh via your browser

## Requirements

- Claude Code CLI (`claude`)

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

        with open(output_dir / "README.md", "w") as f:
            f.write(readme_content)

    def _create_claude_settings(
        self, output_dir: Path, profile, include_coauthored_by: bool = True, profile_name: str = "ClaudeCode"
    ):
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
                    # AWS_CREDENTIAL_PROCESS allows the AWS SDK to obtain credentials
                    # directly without requiring the AWS CLI or ~/.aws/config.
                    # The __CREDENTIAL_PROCESS_PATH__ placeholder is replaced by
                    # install.sh/install.bat with the actual binary path at install time.
                    "AWS_CREDENTIAL_PROCESS": f"__CREDENTIAL_PROCESS_PATH__ --profile {profile_name}",
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

                # Set all model tier env vars using the CRIS prefix from init.
                # Claude Code uses these to resolve the correct CRIS-prefixed
                # models for each tier (small/fast, default sonnet/opus/haiku).
                # This ensures all tiers respect the admin's routing geography
                # choice and works correctly with model aliases like 'opus', 'sonnet', 'haiku'.
                from claude_code_with_bedrock.models import resolve_model_for_tier
                cris_prefix = getattr(profile, "cross_region_profile", None) or "us"

                haiku_model = resolve_model_for_tier("haiku", cris_prefix)
                sonnet_model = resolve_model_for_tier("sonnet", cris_prefix)
                opus_model = resolve_model_for_tier("opus", cris_prefix)

                if haiku_model:
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = haiku_model
                    settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku_model
                if sonnet_model:
                    settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet_model
                if opus_model:
                    settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus_model

                # Override with Application Inference Profile ARNs when configured
                opus_arn = getattr(profile, "inference_profile_opus_arn", None)
                sonnet_arn = getattr(profile, "inference_profile_sonnet_arn", None)
                haiku_arn = getattr(profile, "inference_profile_haiku_arn", None)

                if opus_arn:
                    settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus_arn
                if sonnet_arn:
                    settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet_arn
                if haiku_arn:
                    settings["env"]["ANTHROPIC_SMALL_FAST_MODEL"] = haiku_arn
                    settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku_arn

                # Override ANTHROPIC_MODEL with the primary inference profile ARN
                # so Claude Code uses the inference profile for all code paths.
                # Only override if the matching tier has an ARN configured —
                # otherwise ANTHROPIC_MODEL stays on the CRIS model ID.
                model_id = profile.selected_model
                if "opus" in model_id and opus_arn:
                    settings["env"]["ANTHROPIC_MODEL"] = opus_arn
                elif "sonnet" in model_id and sonnet_arn:
                    settings["env"]["ANTHROPIC_MODEL"] = sonnet_arn
                elif "haiku" in model_id and haiku_arn:
                    settings["env"]["ANTHROPIC_MODEL"] = haiku_arn

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
                        settings["env"].update(
                            {
                                "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
                                "OTEL_METRICS_EXPORTER": "otlp",
                                "OTEL_LOGS_EXPORTER": "otlp",
                                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                                "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
                                # Add basic OTEL resource attributes for multi-team support
                                "OTEL_RESOURCE_ATTRIBUTES": "department=engineering,team.id=default, \
                                cost_center=default,organization=default",
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


    def _generate_cowork_3p_mdm_config(
        self,
        output_dir: Path,
        profile,
        profile_name: str = "ClaudeCode",
    ) -> None:
        """Generate Claude Cowork 3P MDM configuration files.

        Delegates to shared utilities in cli/utils/cowork_3p.py to ensure
        consistency with the standalone 'ccwb cowork generate' command.
        """
        from claude_code_with_bedrock.cli.utils.cowork_3p import (
            add_monitoring_config,
            build_mdm_config,
            derive_model_aliases,
            generate_all,
        )

        console = Console()

        try:
            bedrock_region = self._get_bedrock_region_for_profile(profile)
            model_aliases = derive_model_aliases()

            mdm_config = build_mdm_config(
                bedrock_region=bedrock_region,
                model_aliases=model_aliases,
                profile_name=profile_name,
            )

            add_monitoring_config(mdm_config, profile, console)
            generate_all(output_dir, mdm_config, console)

        except Exception as e:
            console.print(f"[yellow]Warning: Could not generate CoWork 3P config: {e}[/yellow]")
