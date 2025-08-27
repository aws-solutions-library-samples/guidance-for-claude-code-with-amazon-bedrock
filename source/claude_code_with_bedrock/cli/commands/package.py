# ABOUTME: Package command for building distribution packages
# ABOUTME: Creates ready-to-distribute packages with embedded configuration

"""Package command - Build distribution packages."""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

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
            "distribute", description="Upload package and generate distribution URL", flag=True
        ),
        option(
            "expires-hours", description="Distribution URL expiration in hours (with --distribute)", flag=False, default="48"
        ),
        option(
            "profile", description="Configuration profile to use", flag=False, default="default"
        ),
        option(
            "status", description="Check status of a build by ID", flag=False
        ),
    ]

    def handle(self) -> int:
        """Execute the package command."""
        import platform
        import subprocess
        console = Console()

        # Check if this is a status check (deprecated - moved to builds command)
        if self.option("status"):
            console.print("[yellow]Status check has moved to the builds command[/yellow]")
            console.print("Use: [cyan]poetry run ccwb builds --status <build-id>[/cyan]")
            return self._check_build_status(self.option("status"), console)

        # Get target platform
        target_platform = self.option("target-platform")
        valid_platforms = ["macos", "macos-arm64", "macos-intel", "linux", "linux-x64", "linux-arm64", "windows", "all"]
        if target_platform not in valid_platforms:
            console.print(
                f"[red]Invalid platform: {target_platform}. Valid options: {', '.join(valid_platforms)}[/red]"
            )
            return 1

        # Load configuration
        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print("[red]No deployment found. Run 'poetry run ccwb init' first.[/red]")
            return 1

        # Get actual Identity Pool ID from stack outputs
        console.print("[yellow]Fetching deployment information...[/yellow]")
        stack_outputs = get_stack_outputs(
            profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack"), profile.aws_region
        )

        if not stack_outputs:
            console.print("[red]Could not fetch stack outputs. Is the stack deployed?[/red]")
            return 1

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

        # Use default values
        output_dir = Path("./dist")
        package_format = "both"

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create embedded configuration
        embedded_config = {
            "provider_domain": profile.provider_domain,
            "client_id": profile.client_id,
            "identity_pool_id": identity_pool_id,
            "region": profile.aws_region,
            "allowed_bedrock_regions": profile.allowed_bedrock_regions,
            "package_timestamp": timestamp,
            "package_version": "1.0.0",
        }

        # Show what will be packaged using shared display utility
        display_configuration_info(profile, identity_pool_id, format_type="simple")

        # Build package
        console.print("\n[bold]Building package...[/bold]")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:

            # Build executable(s) using Nuitka
            if target_platform == "all":
                # For "all", try to build what's possible on current platform
                platforms_to_build = []
                current_os = platform.system().lower()
                current_machine = platform.machine().lower()
                
                if current_os == "darwin":
                    # On macOS, build for current architecture
                    if current_machine == "arm64":
                        platforms_to_build.append("macos-arm64")
                        # Also try Intel build via Rosetta if available
                        rosetta_check = subprocess.run(["arch", "-x86_64", "true"], capture_output=True)
                        if rosetta_check.returncode == 0:
                            platforms_to_build.append("macos-intel")
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
                platforms_to_build = [target_platform]

            built_executables = []
            built_otel_helpers = []
            for platform in platforms_to_build:
                # Build credential process
                task = progress.add_task(f"Building credential process for {platform}...", total=None)
                try:
                    executable_path = self._build_executable(output_dir, platform)
                    # Check if this was an async Windows build that returned early
                    if executable_path == 0:
                        # Async build started, exit early
                        return 0
                    built_executables.append((platform, executable_path))
                    progress.update(task, completed=True)
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not build credential process for {platform}: {e}[/yellow]")
                    progress.update(task, completed=True)

                # Build OTEL helper if monitoring is enabled
                if profile.monitoring_enabled:
                    task = progress.add_task(f"Building OTEL helper for {platform}...", total=None)
                    try:
                        otel_helper_path = self._build_otel_helper(output_dir, platform)
                        built_otel_helpers.append((platform, otel_helper_path))
                        progress.update(task, completed=True)
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not build OTEL helper for {platform}: {e}[/yellow]")
                        progress.update(task, completed=True)

            # Check if any binaries were built
            if not built_executables:
                console.print("\n[red]Error: No binaries were successfully built.[/red]")
                console.print("Please check the error messages above.")
                return 1

            # Create configuration
            task = progress.add_task("Creating configuration...", total=None)
            config_path = self._create_config(output_dir, profile, identity_pool_id)
            progress.update(task, completed=True)

            # Create installer
            task = progress.add_task("Creating installer script...", total=None)
            installer_path = self._create_installer(output_dir, profile, built_executables, built_otel_helpers)
            progress.update(task, completed=True)

            # Create documentation
            task = progress.add_task("Creating documentation...", total=None)
            self._create_documentation(output_dir, profile, timestamp)
            progress.update(task, completed=True)

            # Create Claude Code settings if monitoring is enabled
            if profile.monitoring_enabled:
                task = progress.add_task("Creating Claude Code settings...", total=None)
                self._create_claude_settings(output_dir, profile)
                progress.update(task, completed=True)

        # Summary
        console.print("\n[green]✓ Package created successfully![/green]")
        console.print(f"\nOutput directory: [cyan]{output_dir}[/cyan]")
        console.print("\nPackage contents:")

        # Show which binaries were built
        for platform, executable_path in built_executables:
            binary_name = executable_path.name
            console.print(f"  • {binary_name} - Authentication executable for {platform}")

        console.print("  • config.json - Configuration")
        console.print("  • install.sh - Installation script for macOS/Linux")
        # Check if Windows installer exists (created when Windows binaries are present)
        if (output_dir / "install.bat").exists():
            console.print("  • install.bat - Installation script for Windows")
        console.print("  • README.md - Installation instructions")
        if profile.monitoring_enabled and (output_dir / ".claude" / "settings.json").exists():
            console.print("  • .claude/settings.json - Claude Code telemetry settings")
            for platform, otel_helper_path in built_otel_helpers:
                console.print(f"  • {otel_helper_path.name} - OTEL helper executable for {platform}")

        # Next steps
        console.print("\n[bold]Distribution steps:[/bold]")
        console.print("1. Send users the entire dist folder")
        console.print("2. Users run: ./install.sh")
        console.print("3. Authentication is configured automatically")

        console.print("\n[bold]To test locally:[/bold]")
        console.print(f"cd {output_dir}")
        console.print("./install.sh")

        # Handle distribution if requested
        if self.option("distribute"):
            console.print("\n[bold]Creating distribution...[/bold]")
            
            # Import and use subprocess to call distribute command
            import subprocess
            import sys
            
            # Build the command
            dist_cmd = [
                "poetry", "run", "ccwb", "distribute",
                "--package-path", str(output_dir),
                "--expires-hours", self.option("expires-hours"),
                "--profile", self.option("profile")
            ]
            
            # Execute distribution command
            try:
                result = subprocess.run(dist_cmd, capture_output=False, text=True, cwd=Path(__file__).parents[4] / "source")
                if result.returncode != 0:
                    console.print("[red]Distribution failed. Package was built but not distributed.[/red]")
                    return 0  # Don't fail the whole command if distribution fails
            except Exception as e:
                console.print(f"[red]Distribution error: {e}[/red]")
                console.print("[yellow]Package was built successfully but distribution failed.[/yellow]")
                return 0  # Don't fail the whole command if distribution fails

        return 0

    def _check_build_status(self, build_id: str, console: Console) -> int:
        """Check the status of a CodeBuild build."""
        import boto3
        import json
        from pathlib import Path
        
        try:
            # If no build ID provided, check for latest
            if not build_id or build_id == "latest":
                build_info_file = Path.home() / '.claude-code' / 'latest-build.json'
                if not build_info_file.exists():
                    console.print("[red]No recent builds found. Start a build with 'poetry run ccwb package'[/red]")
                    return 1
                
                with open(build_info_file) as f:
                    build_info = json.load(f)
                    build_id = build_info['build_id']
                    console.print(f"[dim]Checking latest build: {build_id}[/dim]")
            
            # Get build status from CodeBuild
            codebuild = boto3.client('codebuild', region_name='us-east-1')  # Windows builds are in us-east-1
            response = codebuild.batch_get_builds(ids=[build_id])
            
            if not response.get('builds'):
                console.print(f"[red]Build not found: {build_id}[/red]")
                return 1
            
            build = response['builds'][0]
            status = build['buildStatus']
            
            # Display status
            if status == 'IN_PROGRESS':
                console.print(f"[yellow]⏳ Build in progress[/yellow]")
                console.print(f"Phase: {build.get('currentPhase', 'Unknown')}")
                if 'startTime' in build:
                    from datetime import datetime
                    start_time = build['startTime']
                    elapsed = datetime.now(start_time.tzinfo) - start_time
                    console.print(f"Elapsed: {int(elapsed.total_seconds() / 60)} minutes")
            elif status == 'SUCCEEDED':
                console.print(f"[green]✓ Build succeeded![/green]")
                console.print(f"Duration: {build.get('buildDurationInMinutes', 'Unknown')} minutes")
                console.print("\n[bold]Windows build artifacts are ready![/bold]")
                console.print("Next steps:")
                console.print("  1. Run: [cyan]poetry run ccwb package --target-platform all[/cyan]")
                console.print("     (This will download the Windows artifacts)")
                console.print("  2. Run: [cyan]poetry run ccwb distribute[/cyan]")
                console.print("     (This will create the distribution URL)")
            else:
                console.print(f"[red]✗ Build {status.lower()}[/red]")
                if 'phases' in build:
                    for phase in build['phases']:
                        if phase.get('phaseStatus') == 'FAILED':
                            console.print(f"[red]Failed in phase: {phase.get('phaseType')}[/red]")
            
            # Show console link
            project_name = build_id.split(':')[0]
            build_uuid = build_id.split(':')[1]
            console.print(f"\n[dim]View logs: https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_uuid}[/dim]")
            
            return 0
            
        except Exception as e:
            console.print(f"[red]Error checking build status: {e}[/red]")
            return 1

    def _build_executable(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable using Nuitka compiler for target platform."""
        import platform

        current_system = platform.system().lower()
        current_machine = platform.machine().lower()
        
        # Handle special platform variants
        if target_platform == "macos-arm64":
            # Build ARM64 binary on ARM Mac
            os.environ.pop("CCWB_MACOS_VARIANT", None)  # Ensure we build for ARM64
            return self._build_native_executable(output_dir, "macos")
        elif target_platform == "macos-intel":
            # Build Intel binary - use Docker on ARM Macs, native on Intel Macs
            import platform
            current_machine = platform.machine().lower()
            current_system = platform.system().lower()
            
            if current_system == "darwin" and current_machine == "arm64":
                # On ARM Mac, use Docker with x86_64 emulation
                console = Console()
                console.print("[yellow]Building Intel Mac binary via Docker (x86_64 emulation)...[/yellow]")
                return self._build_macos_intel_via_docker(output_dir)
            else:
                # Native Intel Mac build
                os.environ["CCWB_MACOS_VARIANT"] = "intel"
                return self._build_native_executable(output_dir, "macos")
        elif target_platform == "linux-x64":
            # Build Linux x64 binary via Docker
            return self._build_linux_via_docker(output_dir, "x64")
        elif target_platform == "linux-arm64":
            # Build Linux ARM64 binary via Docker
            return self._build_linux_via_docker(output_dir, "arm64")
        
        # Handle Windows builds via CodeBuild
        if target_platform == "windows":
            if current_system == "windows":
                # Native Windows build
                binary_name = "credential-process-windows.exe"
            else:
                # Use CodeBuild for Windows builds on non-Windows platforms
                return self._build_windows_via_codebuild(output_dir)
        
        # For regular platform names, use the native build method
        return self._build_native_executable(output_dir, target_platform)
    
    def _build_native_executable(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable using native Nuitka compiler."""
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
            }
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
        if (target_platform == "macos" and platform_variant == "intel" and 
            current_system == "darwin" and current_machine == "arm64"):
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
        nuitka_check = subprocess.run(["poetry", "run", "which", "nuitka"], capture_output=True, text=True, cwd=source_dir)
        if nuitka_check.returncode != 0:
            raise RuntimeError(
                "Nuitka not found. Please install it:\n"
                "  poetry add --group dev nuitka ordered-set zstandard\n\n"
                "Note: Nuitka requires Python 3.10-3.12."
            )

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent.parent / "source" / "cognito_auth" / "__main__.py"

        if not src_file.exists():
            raise FileNotFoundError(f"Source file not found: {src_file}")

        # Build Nuitka command (use poetry run to ensure correct Python version)
        # If building Intel binary on ARM Mac, use Rosetta
        if (target_platform == "macos" and platform_variant == "intel" and 
            current_system == "darwin" and current_machine == "arm64"):
            cmd = [
                "arch", "-x86_64",  # Run under Rosetta
                "poetry", "run", "nuitka",
            ]
        else:
            cmd = [
                "poetry", "run", "nuitka",
            ]
        
        # Add common Nuitka flags
        cmd.extend([
            "--standalone",
            "--onefile",
            "--assume-yes-for-downloads",
            f"--output-filename={binary_name}",
            f"--output-dir={str(output_dir)}",
            "--quiet",
            "--remove-output",  # Clean up build artifacts
            "--python-flag=no_site",  # Don't include site packages
        ])

        # Add platform-specific flags
        if target_platform == "macos":
            cmd.extend([
                "--macos-create-app-bundle",
                "--macos-app-name=Claude Code Credential Process",
                "--disable-console",  # GUI app on macOS
            ])
        elif target_platform == "linux":
            cmd.extend([
                "--linux-onefile-icon=NONE",  # No icon for Linux
            ])

        # Add the source file
        cmd.append(str(src_file))

        # Run Nuitka (from source directory where pyproject.toml is located)
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=source_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Nuitka build failed: {result.stderr}")

        return output_dir / binary_name

    def _build_macos_intel_via_docker(self, output_dir: Path) -> Path:
        """Build Intel Mac binary using Docker with x86_64 Python and host Nuitka.
        
        This approach uses Docker to get x86_64 Python, then runs Nuitka on the host
        to build a proper macOS binary with the x86_64 architecture.
        """
        import tempfile
        import shutil
        
        console = Console()
        
        # Check if Docker is available
        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
        if docker_check.returncode != 0:
            raise RuntimeError(
                "Docker is not available. Please install Docker Desktop to build Intel Mac binaries on ARM Mac.\n"
                "Visit: https://docs.docker.com/get-docker/"
            )
        
        # Check if Nuitka is available on host
        nuitka_check = subprocess.run(["which", "nuitka"], capture_output=True)
        if nuitka_check.returncode != 0:
            # Try with poetry
            nuitka_check = subprocess.run(["poetry", "run", "which", "nuitka"], capture_output=True, cwd=Path(__file__).parent.parent.parent.parent)
            if nuitka_check.returncode != 0:
                console.print("[yellow]Nuitka not found on host, installing...[/yellow]")
                install_result = subprocess.run(
                    ["pip3", "install", "nuitka==2.7.12", "ordered-set", "zstandard"],
                    capture_output=True
                )
                if install_result.returncode != 0:
                    raise RuntimeError("Failed to install Nuitka on host")
        
        console.print("[yellow]Building Intel Mac binary using Docker + host Nuitka...[/yellow]")
        console.print("[dim]Step 1: Creating x86_64 Python environment in Docker[/dim]")
        
        # Create a temporary directory for the build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = Path(__file__).parent.parent.parent.parent
            
            # Copy source to temp directory
            shutil.copytree(source_dir / "cognito_auth", temp_path / "cognito_auth")
            
            # Create a script to prepare the Python environment
            prep_script = """#!/bin/bash
set -e

# Install dependencies in x86_64 Python
pip install --target /deps \
    boto3 \
    requests \
    PyJWT \
    cryptography \
    keyring \
    questionary \
    rich \
    cleo \
    pydantic \
    pyyaml

echo "Dependencies installed to /deps"
"""
            (temp_path / "prep.sh").write_text(prep_script)
            (temp_path / "prep.sh").chmod(0o755)
            
            # Run Docker to prepare x86_64 Python dependencies
            docker_cmd = [
                "docker", "run",
                "--rm",
                "--platform", "linux/amd64",
                "-v", f"{str(temp_path)}:/work ",
                "-w", "/work",
                "python:3.12-slim",
                "/work/prep.sh"
            ]
            
            prep_result = subprocess.run(docker_cmd, capture_output=True, text=True)
            
            if prep_result.returncode != 0:
                console.print(f"[yellow]Docker prep failed: {prep_result.stderr}[/yellow]")
                console.print("[yellow]Falling back to native build with arch command[/yellow]")
                
                # Fallback: Try to use arch command directly
                os.environ["CCWB_MACOS_VARIANT"] = "intel"
                
                # Try building with arch -x86_64 directly (not through poetry)
                src_file = source_dir / "cognito_auth" / "__main__.py"
                binary_name = "credential-process-macos-intel"
                
                # Build command using arch to force x86_64
                cmd = [
                    "arch", "-x86_64",
                    "python3", "-m", "nuitka",
                    "--standalone",
                    "--onefile",
                    "--assume-yes-for-downloads",
                    f"--output-filename={binary_name}",
                    f"--output-dir={str(output_dir)}",
                    "--quiet",
                    "--remove-output",
                    "--python-flag=no_site",
                    "--macos-create-app-bundle",
                    "--macos-app-name=Claude Code Credential Process",
                    "--disable-console",
                    str(src_file)
                ]
                
                console.print("[dim]Step 2: Building macOS Intel binary with arch -x86_64[/dim]")
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    console.print(f"[red]Build failed: {result.stderr}[/red]")
                    console.print("[yellow]Intel Mac builds on ARM Macs require additional setup[/yellow]")
                    console.print("[yellow]Options:[/yellow]")
                    console.print("  1. Install x86_64 Python via Rosetta")
                    console.print("  2. Use an Intel Mac for building")
                    console.print("  3. Use the Windows-style CodeBuild approach")
                    raise RuntimeError("Cannot build Intel Mac binary on ARM Mac with current setup")
                
                binary_path = output_dir / binary_name
                if binary_path.exists():
                    console.print("[green]✓ Intel Mac binary built successfully[/green]")
                    return binary_path
                else:
                    raise RuntimeError("Intel Mac binary was not created")
            
            # If Docker prep succeeded, use host Nuitka with the prepared environment
            console.print("[dim]Step 2: Building macOS binary with host Nuitka[/dim]")
            
            # This won't work as intended because the deps are Linux x86_64, not macOS
            # The real solution requires x86_64 Python installed on the Mac itself
            console.print("[yellow]Note: Cross-architecture builds require x86_64 Python on host[/yellow]")
            raise RuntimeError(
                "Building Intel Mac binaries on ARM Mac requires:\n"
                "1. x86_64 Python installed via Rosetta (/usr/local/bin/python3)\n"
                "2. Or use an Intel Mac for building\n"
                "3. Or set up CodeBuild for macOS (like Windows builds)"
            )

    def _build_linux_via_docker(self, output_dir: Path, arch: str = "x64") -> Path:
        """Build Linux binaries using Docker."""
        import tempfile
        import shutil
        
        console = Console()
        
        # Determine platform and binary name
        if arch == "arm64":
            docker_platform = "linux/arm64"
            binary_name = "credential-process-linux-arm64"
        else:
            docker_platform = "linux/amd64"
            binary_name = "credential-process-linux-x64"
        
        # Check if Docker is available
        docker_check = subprocess.run(["docker", "--version"], capture_output=True)
        if docker_check.returncode != 0:
            raise RuntimeError(
                "Docker is not available. Please install Docker to build Linux binaries.\n"
                "Visit: https://docs.docker.com/get-docker/"
            )
        
        # Create a temporary directory for the Docker build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Copy source files to temp directory
            source_dir = Path(__file__).parent.parent.parent.parent
            shutil.copytree(source_dir / "cognito_auth", temp_path / "cognito_auth")
            
            # Create Dockerfile
            dockerfile_content = f"""FROM --platform={docker_platform} python:3.12-slim

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    nuitka==2.7.12 \
    ordered-set \
    zstandard \
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
    pyyaml

# Set working directory
WORKDIR /build

# Copy source code
COPY cognito_auth /build/cognito_auth

# Build the binary
RUN python -m nuitka \
    --standalone \
    --onefile \
    --assume-yes-for-downloads \
    --output-filename={binary_name} \
    --output-dir=/output \
    --remove-output \
    --python-flag=no_site \
    cognito_auth/__main__.py

# The binary will be in /output/{binary_name}
"""
            
            (temp_path / "Dockerfile").write_text(dockerfile_content)
            
            # Build Docker image
            console.print(f"[yellow]Building Linux {arch} binary via Docker (this may take a few minutes)...[/yellow]")
            build_result = subprocess.run(
                ["docker", "buildx", "build", "--platform", docker_platform, "-t", f"ccwb-linux-{arch}-builder", "."],
                cwd=temp_path,
                capture_output=True,
                text=True
            )
            
            if build_result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {build_result.stderr}")
            
            # Run container and copy binary out
            container_name = f"ccwb-extract-{os.getpid()}"
            
            # Create container
            run_result = subprocess.run(
                ["docker", "create", "--name", container_name, f"ccwb-linux-{arch}-builder"],
                capture_output=True,
                text=True
            )
            
            if run_result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {run_result.stderr}")
            
            try:
                # Copy binary from container
                copy_result = subprocess.run(
                    ["docker", "cp", f"{container_name}:/output/{binary_name}", str(output_dir)],
                    capture_output=True,
                    text=True
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
                # Clean up container
                subprocess.run(["docker", "rm", container_name], capture_output=True)
    
    def _build_linux_otel_helper_via_docker(self, output_dir: Path, arch: str = "x64") -> Path:
        """Build Linux OTEL helper binary using Docker."""
        import tempfile
        import shutil
        
        console = Console()
        
        # Determine platform and binary name
        if arch == "arm64":
            docker_platform = "linux/arm64"
            binary_name = "otel-helper-linux-arm64"
        else:
            docker_platform = "linux/amd64"
            binary_name = "otel-helper-linux-x64"
        
        # Create a temporary directory for the Docker build
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Copy source files to temp directory
            source_dir = Path(__file__).parent.parent.parent.parent
            shutil.copytree(source_dir / "otel_helper", temp_path / "otel_helper")
            
            # Create Dockerfile for OTEL helper
            dockerfile_content = f"""FROM --platform={docker_platform} python:3.12-slim

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    nuitka==2.7.12 \
    ordered-set \
    zstandard \
    PyJWT \
    cryptography

# Set working directory
WORKDIR /build

# Copy source code
COPY otel_helper /build/otel_helper

# Build the binary
RUN python -m nuitka \
    --standalone \
    --onefile \
    --assume-yes-for-downloads \
    --output-filename={binary_name} \
    --output-dir=/output \
    --remove-output \
    --python-flag=no_site \
    otel_helper/__main__.py

# The binary will be in /output/{binary_name}
"""
            
            (temp_path / "Dockerfile").write_text(dockerfile_content)
            
            # Build Docker image
            console.print(f"[yellow]Building Linux {arch} OTEL helper via Docker...[/yellow]")
            build_result = subprocess.run(
                ["docker", "buildx", "build", "--platform", docker_platform, "-t", f"ccwb-otel-{arch}-builder", "."],
                cwd=temp_path,
                capture_output=True,
                text=True
            )
            
            if build_result.returncode != 0:
                raise RuntimeError(f"Docker build failed for OTEL helper: {build_result.stderr}")
            
            # Run container and copy binary out
            container_name = f"ccwb-otel-extract-{os.getpid()}"
            
            # Create container
            run_result = subprocess.run(
                ["docker", "create", "--name", container_name, f"ccwb-otel-{arch}-builder"],
                capture_output=True,
                text=True
            )
            
            if run_result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {run_result.stderr}")
            
            try:
                # Copy binary from container
                copy_result = subprocess.run(
                    ["docker", "cp", f"{container_name}:/output/{binary_name}", str(output_dir)],
                    capture_output=True,
                    text=True
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
                # Clean up container
                subprocess.run(["docker", "rm", container_name], capture_output=True)

    def _build_windows_via_codebuild(self, output_dir: Path) -> Path:
        """Build Windows binaries using AWS CodeBuild."""
        import json
        import tempfile
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
                codebuild = boto3.client('codebuild', region_name='us-east-1')
                
                # List recent builds
                response = codebuild.list_builds_for_project(
                    projectName=project_name,
                    sortOrder='DESCENDING'
                )
                
                if response.get('ids'):
                    # Check only the most recent builds
                    build_ids = response['ids'][:3]
                    builds_response = codebuild.batch_get_builds(ids=build_ids)
                    
                    for build in builds_response.get('builds', []):
                        if build['buildStatus'] == 'IN_PROGRESS':
                            console.print(f"[yellow]Windows build already in progress (started {build['startTime'].strftime('%Y-%m-%d %H:%M')})[/yellow]")
                            console.print(f"Check status: [cyan]poetry run ccwb builds[/cyan]")
                            console.print(f"Create distribution when ready: [cyan]poetry run ccwb distribute[/cyan]")
                            return 0  # Return early, build in progress
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
            raise RuntimeError("CodeBuild stack not deployed")
        
        bucket_name = stack_outputs.get('BuildBucket')
        project_name = stack_outputs.get('ProjectName')
        
        if not bucket_name or not project_name:
            console.print("[red]CodeBuild stack outputs not found[/red]")
            raise RuntimeError("Invalid CodeBuild stack")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            # Package source code
            task = progress.add_task("Packaging source code for CodeBuild...", total=None)
            source_zip = self._package_source_for_codebuild()
            
            # Upload to S3
            progress.update(task, description="Uploading source to S3...")
            s3 = boto3.client('s3', region_name=profile.aws_region)
            try:
                s3.upload_file(str(source_zip), bucket_name, 'source.zip')
            except ClientError as e:
                console.print(f"[red]Failed to upload source: {e}[/red]")
                raise
            
            # Start build
            progress.update(task, description="Starting CodeBuild project...")
            codebuild = boto3.client('codebuild', region_name=profile.aws_region)
            try:
                response = codebuild.start_build(projectName=project_name)
                build_id = response['build']['id']
            except ClientError as e:
                console.print(f"[red]Failed to start build: {e}[/red]")
                raise
            
            # Monitor build
            progress.update(task, description="Building Windows binaries (5-10 minutes)...")
            console.print(f"[dim]Build ID: {build_id}[/dim]")
            console.print("[dim]Estimated cost: ~$0.10[/dim]")
            
            # Store build ID for later retrieval
            import json
            from pathlib import Path
            build_info_file = Path.home() / '.claude-code' / 'latest-build.json'
            build_info_file.parent.mkdir(exist_ok=True)
            with open(build_info_file, 'w') as f:
                json.dump({
                    'build_id': build_id,
                    'started_at': datetime.now().isoformat(),
                    'project': project_name,
                    'bucket': bucket_name
                }, f)
            
            # Clean up source zip
            source_zip.unlink()
            progress.update(task, completed=True)
        
        # Don't wait - return build info immediately
        console.print("\n[bold yellow]Windows build started![/bold yellow]")
        console.print(f"[dim]Build ID: {build_id}[/dim]")
        console.print(f"Build will take approximately 12-15 minutes to complete.")
        console.print(f"\nTo check status:")
        console.print(f"  [cyan]poetry run ccwb builds[/cyan]")
        console.print(f"\nWhen ready, create distribution:")
        console.print(f"  [cyan]poetry run ccwb distribute[/cyan]")
        console.print(f"\n[dim]View logs in AWS Console:[/dim]")
        console.print(f"  [dim]https://console.aws.amazon.com/codesuite/codebuild/projects/{project_name}/build/{build_id.split(':')[1]}[/dim]")
        
        return 0  # Exit early for async builds
    
    def _package_source_for_codebuild(self) -> Path:
        """Package source code for CodeBuild."""
        import tempfile
        import zipfile
        
        # Create a temporary zip file
        temp_dir = Path(tempfile.mkdtemp())
        source_zip = temp_dir / "source.zip"
        
        # Get the source directory (parent of package.py)
        source_dir = Path(__file__).parents[3]  # Go up to source/ directory
        
        with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add all Python files from source directory
            for py_file in source_dir.rglob('*.py'):
                arcname = str(py_file.relative_to(source_dir.parent))
                zf.write(py_file, arcname)
            
            # Add pyproject.toml for dependencies
            pyproject_file = source_dir / 'pyproject.toml'
            if pyproject_file.exists():
                zf.write(pyproject_file, 'pyproject.toml')
        
        return source_zip

    def _build_otel_helper(self, output_dir: Path, target_platform: str) -> Path:
        """Build executable for OTEL helper script using Nuitka."""
        import platform

        current_system = platform.system().lower()
        current_machine = platform.machine().lower()
        
        # Handle special platform variants
        if target_platform == "macos-arm64":
            # Build ARM64 binary on ARM Mac
            os.environ.pop("CCWB_MACOS_VARIANT", None)  # Ensure we build for ARM64
            return self._build_native_otel_helper(output_dir, "macos")
        elif target_platform == "macos-intel":
            # Build Intel binary using Rosetta on ARM Mac
            os.environ["CCWB_MACOS_VARIANT"] = "intel"
            return self._build_native_otel_helper(output_dir, "macos")
        elif target_platform == "linux-x64":
            # Build Linux x64 binary via Docker
            return self._build_linux_otel_helper_via_docker(output_dir, "x64")
        elif target_platform == "linux-arm64":
            # Build Linux ARM64 binary via Docker
            return self._build_linux_otel_helper_via_docker(output_dir, "arm64")
        
        # For Windows, the otel-helper is built together with credential-process by CodeBuild
        if target_platform == "windows":
            # Check if the Windows binary already exists (built by _build_executable)
            windows_binary = output_dir / "otel-helper-windows.exe"
            if windows_binary.exists():
                return windows_binary
            else:
                # If not, we need to build via CodeBuild (but this should have been done already)
                raise RuntimeError("Windows otel-helper should have been built with credential-process")
        
        # For regular platform names, use the native build method
        return self._build_native_otel_helper(output_dir, target_platform)
    
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
        current_platform_str = f"{current_system}-{current_machine}"
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
        if (target_platform == "macos" and platform_variant == "intel" and 
            current_system == "darwin" and current_machine == "arm64"):
            cmd = [
                "arch", "-x86_64",  # Run under Rosetta
                "poetry", "run", "nuitka",
            ]
        else:
            cmd = [
                "poetry", "run", "nuitka",
            ]
        
        # Add common Nuitka flags
        cmd.extend([
            "--standalone",
            "--onefile",
            "--assume-yes-for-downloads",
            f"--output-filename={binary_name}",
            f"--output-dir={str(output_dir)}",
            "--quiet",
            "--remove-output",
            "--python-flag=no_site",
        ])

        # Add platform-specific flags
        if target_platform == "macos":
            cmd.extend([
                "--macos-create-app-bundle",
                "--macos-app-name=Claude Code OTEL Helper",
                "--disable-console",
            ])
        elif target_platform == "linux":
            cmd.extend([
                "--linux-onefile-icon=NONE",
            ])

        # Add the source file
        cmd.append(str(src_file))

        # Run Nuitka (from source directory where pyproject.toml is located)
        source_dir = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=source_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Nuitka build failed for OTEL helper: {result.stderr}")

        return output_dir / binary_name

    def _create_config(self, output_dir: Path, profile, identity_pool_id: str) -> Path:
        """Create the configuration file."""
        config = {
            "ClaudeCode": {
                "provider_domain": profile.provider_domain,
                "client_id": profile.client_id,
                "identity_pool_id": identity_pool_id,
                "aws_region": profile.aws_region,
                "provider_type": profile.provider_type or self._detect_provider_type(profile.provider_domain),
                "credential_storage": profile.credential_storage,
                "cross_region_profile": profile.cross_region_profile or "us",
            }
        }

        # Add cognito_user_pool_id if it's a Cognito provider
        if profile.provider_type == "cognito" and profile.cognito_user_pool_id:
            config["ClaudeCode"]["cognito_user_pool_id"] = profile.cognito_user_pool_id

        # Add selected_model if available
        if hasattr(profile, "selected_model") and profile.selected_model:
            config["ClaudeCode"]["selected_model"] = profile.selected_model

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
        url_to_parse = domain if domain.startswith(('http://', 'https://')) else f"https://{domain}"
        
        try:
            parsed = urlparse(url_to_parse)
            hostname = parsed.hostname
            
            if not hostname:
                return "oidc"
            
            hostname_lower = hostname.lower()
            
            # Check for exact domain match or subdomain match
            # Using endswith with leading dot prevents bypass attacks
            if hostname_lower.endswith('.okta.com') or hostname_lower == 'okta.com':
                return "okta"
            elif hostname_lower.endswith('.auth0.com') or hostname_lower == 'auth0.com':
                return "auth0"
            elif hostname_lower.endswith('.microsoftonline.com') or hostname_lower == 'microsoftonline.com':
                return "azure"
            elif hostname_lower.endswith('.windows.net') or hostname_lower == 'windows.net':
                return "azure"
            elif hostname_lower.endswith('.amazoncognito.com') or hostname_lower == 'amazoncognito.com':
                return "cognito"
            else:
                return "oidc"  # Default to generic OIDC
        except Exception:
            return "oidc"  # Default to generic OIDC on parsing error

    def _create_installer(self, output_dir: Path, profile, built_executables, built_otel_helpers=None) -> Path:
        """Create simple installer script."""

        # Determine which binaries were built
        platforms_built = [platform for platform, _ in built_executables]
        otel_platforms_built = [platform for platform, _ in built_otel_helpers] if built_otel_helpers else []

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

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    echo "   Please install from https://aws.amazon.com/cli/"
    exit 1
fi

echo "✓ Prerequisites found"

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
if [ -d ".claude" ]; then
    echo
    echo "Installing Claude Code settings..."
    mkdir -p ~/.claude
    cp -f .claude/settings.json ~/.claude/settings.json 2>/dev/null || true
    echo "✓ Claude Code telemetry configured"
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
echo "Configuring AWS profile..."
mkdir -p ~/.aws

# Remove old profile if exists
sed -i.bak '/\\[profile ClaudeCode\\]/,/^$/d' ~/.aws/config 2>/dev/null || true

# Get region from settings (for Bedrock calls, not infrastructure)
REGION=$(python3 -c "import json; print(json.load(open('.claude/settings.json'))['env']['AWS_REGION'])" 2>/dev/null || echo "{profile.aws_region}")

# Add new profile
cat >> ~/.aws/config << EOF
[profile ClaudeCode]
credential_process = $HOME/claude-code-with-bedrock/credential-process
region = $REGION
EOF

echo
echo "======================================"
echo "✓ Installation complete!"
echo "======================================"
echo
echo "To use Claude Code authentication:"
echo "  export AWS_PROFILE=ClaudeCode"
echo "  aws sts get-caller-identity"
echo
echo "Note: Authentication will automatically open your browser when needed."
echo
"""

        installer_path = output_dir / "install.sh"
        with open(installer_path, "w") as f:
            f.write(installer_content)
        installer_path.chmod(0o755)

        # Also create Windows installer if Windows binaries exist
        # Check if Windows executables are present (either just built or from previous build)
        windows_exe = output_dir / "credential-process-windows.exe"
        if "windows" in platforms_built or windows_exe.exists():
            self._create_windows_installer(output_dir, profile)

        return installer_path
    
    def _create_windows_installer(self, output_dir: Path, profile) -> Path:
        """Create Windows batch installer script."""
        
        installer_content = f"""@echo off
REM Claude Code Authentication Installer for Windows
REM Organization: {profile.provider_domain}
REM Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

echo ======================================
echo Claude Code Authentication Installer
echo ======================================
echo.
echo Organization: {profile.provider_domain}
echo.

REM Check prerequisites
echo Checking prerequisites...

where aws >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: AWS CLI is not installed
    echo        Please install from https://aws.amazon.com/cli/
    pause
    exit /b 1
)

echo OK Prerequisites found
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

REM Copy Claude Code settings if they exist
if exist ".claude" (
    echo Copying Claude Code telemetry settings...
    if not exist "%USERPROFILE%\\claude-code-with-bedrock\\.claude" mkdir "%USERPROFILE%\\claude-code-with-bedrock\\.claude"
    xcopy /Y /E ".claude" "%USERPROFILE%\\claude-code-with-bedrock\\.claude\\" >nul
)

REM Configure AWS profile
echo.
echo Configuring AWS profile...

REM Remove existing profile if it exists
aws configure set credential_process "" --profile ClaudeCode 2>nul

REM Set new credential process
aws configure set credential_process "\"%USERPROFILE%\\claude-code-with-bedrock\\credential-process.exe\"" --profile ClaudeCode

REM Set region
aws configure set region {profile.selected_source_region or profile.aws_region} --profile ClaudeCode

echo OK AWS profile configured
echo.

REM Test authentication
echo Testing authentication...
echo.

aws sts get-caller-identity --profile ClaudeCode >nul 2>&1
if %errorlevel% equ 0 (
    echo OK Authentication successful!
    aws sts get-caller-identity --profile ClaudeCode
) else (
    echo WARNING: Authentication test failed. You may need to authenticate when first using the profile.
)

echo.
echo ======================================
echo Installation complete!
echo ======================================
echo.
echo To use Claude Code authentication:
echo   set AWS_PROFILE=ClaudeCode
echo   aws sts get-caller-identity
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
On first use, macOS will ask for permission to access the keychain. This is normal and required for secure credential storage. Click "Always Allow" to avoid repeated prompts.

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

Your organization has enabled advanced analytics for Claude Code usage. You can access detailed metrics and reports through AWS Athena.

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

    def _create_claude_settings(self, output_dir: Path, profile):
        """Create Claude Code settings.json with monitoring configuration."""
        console = Console()

        try:
            # Get monitoring stack outputs directly
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
            if result.returncode != 0:
                console.print("[yellow]Warning: Could not fetch monitoring stack outputs[/yellow]")
                return

            outputs = json.loads(result.stdout)
            endpoint = None

            for output in outputs:
                if output["OutputKey"] == "CollectorEndpoint":
                    endpoint = output["OutputValue"]
                    break

            if not endpoint:
                console.print("[yellow]Warning: No monitoring endpoint found in stack outputs[/yellow]")
                return

            # Create .claude directory
            claude_dir = output_dir / ".claude"
            claude_dir.mkdir(exist_ok=True)

            # Determine if we're using HTTPS
            is_https = endpoint.startswith("https://")

            # Check if token authentication is required
            is_secured = is_https

            # Create settings.json
            settings = {
                "env": {
                    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
                    "OTEL_METRICS_EXPORTER": "otlp",
                    "OTEL_LOGS_EXPORTER": "otlp",
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
                    # Set AWS_REGION based on cross-region profile for correct Bedrock endpoint
                    "AWS_REGION": self._get_bedrock_region_for_profile(profile),
                    "CLAUDE_CODE_USE_BEDROCK": "1",
                    "AWS_PROFILE": "ClaudeCode",
                    # Add basic OTEL resource attributes for multi-team support
                    # These can be overridden by environment variables
                    "OTEL_RESOURCE_ATTRIBUTES": "department=engineering,team.id=default,cost_center=default,organization=default",
                }
            }

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

            # Add the helper executable for generating OTEL headers with user attributes
            # The helper extracts user info from JWT and sends as HTTP headers
            # The OTEL collector will extract these headers to resource attributes
            # Use platform-appropriate path format (don't expand on build machine)
            # Check if Windows executables exist in the package to determine target platform
            if (output_dir / "credential-process-windows.exe").exists():
                # Windows package - use Windows path format with .exe
                settings["otelHeadersHelper"] = "%USERPROFILE%\\claude-code-with-bedrock\\otel-helper.exe"
            else:
                # Unix package - use Unix path format
                settings["otelHeadersHelper"] = "~/claude-code-with-bedrock/otel-helper"

            settings_path = claude_dir / "settings.json"
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)

            console.print(
                f"[dim]Created Claude Code settings with {'HTTPS' if is_https else 'HTTP'} monitoring endpoint[/dim]"
            )
            if not is_https:
                console.print("[dim]WARNING: Using HTTP endpoint - consider enabling HTTPS for production[/dim]")

        except Exception as e:
            console.print(f"[yellow]Warning: Could not create Claude Code settings: {e}[/yellow]")
