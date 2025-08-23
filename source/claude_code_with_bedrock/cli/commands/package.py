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
        )
    ]

    def handle(self) -> int:
        """Execute the package command."""
        console = Console()

        # Get target platform
        target_platform = self.option("target-platform")
        valid_platforms = ["macos", "linux", "all"]
        if target_platform not in valid_platforms:
            console.print(
                f"[red]Invalid platform: {target_platform}. Valid options: {', '.join(valid_platforms)}[/red]"
            )
            return 1

        # Load configuration
        config = Config.load()
        profile = config.get_profile()

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

            # Build PyInstaller executable(s)
            if target_platform == "all":
                platforms_to_build = ["macos", "linux"]
            else:
                platforms_to_build = [target_platform]

            built_executables = []
            built_otel_helpers = []
            for platform in platforms_to_build:
                # Build credential process
                task = progress.add_task(f"Building credential process for {platform}...", total=None)
                try:
                    executable_path = self._build_executable(output_dir, platform)
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
        console.print("  • install.sh - Installation script (auto-detects platform)")
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

        return 0

    def _build_executable(self, output_dir: Path, target_platform: str) -> Path:
        """Build PyInstaller executable for target platform."""
        import platform

        current_platform = platform.system().lower()

        # Check if we can build for the target platform
        if target_platform == "linux" and current_platform == "darwin":
            # Check if Docker is available
            docker_check = subprocess.run(["which", "docker"], capture_output=True, text=True)
            if docker_check.returncode == 0:
                # Docker is available, check if it's running
                docker_running = subprocess.run(["docker", "ps"], capture_output=True, text=True)
                if docker_running.returncode == 0:
                    # Try to use Docker for cross-platform build
                    try:
                        return self._build_linux_with_docker(output_dir)
                    except Exception as e:
                        # Docker failed, provide helpful message
                        console = Console()
                        console.print(f"\n[yellow]Docker build failed: {e}[/yellow]")
                        console.print("[yellow]To build Linux binaries, either:[/yellow]")
                        console.print("[yellow]  1. Fix the Docker issues above, or[/yellow]")
                        console.print("[yellow]  2. Run this command on a Linux machine[/yellow]\n")
                        raise RuntimeError("Cannot build Linux binary on macOS without working Docker")
                else:
                    # Docker installed but not running
                    raise RuntimeError(
                        "Docker is installed but not running.\n"
                        "To build Linux binaries on macOS:\n"
                        "  1. Start Docker Desktop, or\n"
                        "  2. Run this command on a Linux machine"
                    )
            else:
                # Docker not available
                raise RuntimeError(
                    "Docker not found. To build Linux binaries on macOS:\n"
                    "  1. Install Docker Desktop from https://docker.com, or\n"
                    "  2. Run this command on a Linux machine"
                )
        elif target_platform == "linux" and current_platform != "linux":
            raise RuntimeError("Cannot build Linux binary on this platform. Use Docker or build on Linux.")
        elif target_platform == "macos" and current_platform != "darwin":
            raise RuntimeError("Cannot build macOS binary on this platform. Build on macOS.")

        # Check if PyInstaller is available
        pyinstaller_check = subprocess.run(["which", "pyinstaller"], capture_output=True, text=True)
        if pyinstaller_check.returncode != 0:
            raise RuntimeError(
                "PyInstaller not found. Please install it:\n"
                "  pip install pyinstaller\n"
                "  or\n"
                "  poetry add --group dev pyinstaller\n\n"
                "Note: PyInstaller doesn't support Python 3.13+ yet.\n"
                "You may need to use Python 3.12 or earlier."
            )

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent.parent / "source" / "cognito_auth" / "__main__.py"

        if not src_file.exists():
            raise FileNotFoundError(f"Source file not found: {src_file}")

        # Determine output name
        output_name = f"credential-process-{target_platform}"

        # Run PyInstaller
        cmd = [
            "pyinstaller",
            "--onefile",
            "--name",
            output_name,
            "--distpath",
            str(output_dir),
            "--workpath",
            str(output_dir / "build"),
            "--specpath",
            str(output_dir / "build"),
            "--noconfirm",
            "--clean",
            "--strip",  # Strip debug symbols for smaller size
            "--noupx",  # Don't use UPX compression (can cause issues on macOS)
            str(src_file),
        ]

        # Add platform-specific flags
        if target_platform == "macos" and current_platform == "darwin":
            cmd.extend(["--osx-bundle-identifier", "com.claudecode.credential-process"])
            # For ARM64 Macs, explicitly set native architecture to avoid universal2 issues
            # Homebrew Python on ARM64 doesn't support universal2 builds
            if platform.machine() == "arm64":
                cmd.extend(["--target-arch", "arm64"])
            elif platform.machine() == "x86_64":
                # On Intel Macs, we can try universal2
                cmd.extend(["--target-arch", "universal2"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"PyInstaller failed: {result.stderr}")

        # Clean up build artifacts
        shutil.rmtree(output_dir / "build", ignore_errors=True)

        return output_dir / output_name

    def _build_linux_with_docker(self, output_dir: Path) -> Path:
        """Build Linux binary using Docker."""
        console = Console()
        console.print("[yellow]Building Linux binary with Docker...[/yellow]")

        # Prepare source directory
        src_dir = Path(__file__).parent.parent.parent.parent.parent / "source"

        # Create Dockerfile content
        dockerfile_content = """
FROM python:3.12-slim

WORKDIR /build

# Install dependencies
RUN apt-get update && apt-get install -y \\
    binutils \\
    && rm -rf /var/lib/apt/lists/*

# Copy source files
COPY cognito_auth /build/cognito_auth
COPY pyproject.toml poetry.lock* /build/

# Install PyInstaller
RUN pip install pyinstaller

# Build the binary
RUN pyinstaller \\
    --onefile \\
    --name credential-process-linux \\
    --strip \\
    --noupx \\
    /build/cognito_auth/__main__.py

# The output will be in /build/dist/
"""

        # Write temporary Dockerfile
        dockerfile_path = output_dir / "Dockerfile.linux"
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        try:
            # Build Docker image
            build_cmd = [
                "docker",
                "build",
                "-t",
                "credential-process-builder",
                "-f",
                str(dockerfile_path),
                str(src_dir),
            ]
            result = subprocess.run(build_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {result.stderr}")

            # Extract the binary from the container
            container_cmd = ["docker", "create", "credential-process-builder"]
            result = subprocess.run(container_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {result.stderr}")

            container_id = result.stdout.strip()

            # Copy the binary out
            copy_cmd = ["docker", "cp", f"{container_id}:/build/dist/credential-process-linux", str(output_dir)]
            result = subprocess.run(copy_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to copy binary: {result.stderr}")

            # Clean up
            subprocess.run(["docker", "rm", container_id], capture_output=True)

            console.print("[green]Linux binary built successfully with Docker[/green]")

        finally:
            # Clean up Dockerfile
            dockerfile_path.unlink(missing_ok=True)

        return output_dir / "credential-process-linux"

    def _build_otel_helper(self, output_dir: Path, target_platform: str) -> Path:
        """Build PyInstaller executable for OTEL helper script."""
        import platform

        current_platform = platform.system().lower()

        # Platform compatibility checks (similar to credential process)
        if target_platform == "linux" and current_platform == "darwin":
            # Use Docker for cross-platform build
            docker_check = subprocess.run(["which", "docker"], capture_output=True, text=True)
            if docker_check.returncode == 0:
                docker_running = subprocess.run(["docker", "ps"], capture_output=True, text=True)
                if docker_running.returncode == 0:
                    try:
                        return self._build_otel_helper_linux_with_docker(output_dir)
                    except Exception as e:
                        console = Console()
                        console.print(f"\n[yellow]Docker build failed for OTEL helper: {e}[/yellow]")
                        raise RuntimeError("Cannot build Linux OTEL helper on macOS without working Docker")

        # Find the source file
        src_file = Path(__file__).parent.parent.parent.parent / "otel_helper" / "__main__.py"

        if not src_file.exists():
            raise FileNotFoundError(f"OTEL helper script not found: {src_file}")

        # Determine output name
        output_name = f"otel-helper-{target_platform}"

        # Run PyInstaller
        cmd = [
            "pyinstaller",
            "--onefile",
            "--name",
            output_name,
            "--distpath",
            str(output_dir),
            "--workpath",
            str(output_dir / "build"),
            "--specpath",
            str(output_dir / "build"),
            "--noconfirm",
            "--clean",
            "--strip",
            "--noupx",
            str(src_file),
        ]

        # Add platform-specific flags
        if target_platform == "macos" and current_platform == "darwin":
            cmd.extend(["--osx-bundle-identifier", "com.claudecode.otel-helper"])
            if platform.machine() == "arm64":
                cmd.extend(["--target-arch", "arm64"])
            elif platform.machine() == "x86_64":
                cmd.extend(["--target-arch", "universal2"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"PyInstaller failed for OTEL helper: {result.stderr}")

        # Clean up build artifacts
        shutil.rmtree(output_dir / "build", ignore_errors=True)

        return output_dir / output_name

    def _build_otel_helper_linux_with_docker(self, output_dir: Path) -> Path:
        """Build Linux OTEL helper binary using Docker."""
        console = Console()
        console.print("[yellow]Building Linux OTEL helper binary with Docker...[/yellow]")

        # Create temporary Dockerfile
        dockerfile_content = """FROM python:3.11-slim

WORKDIR /build

# Install dependencies
RUN apt-get update && apt-get install -y \\
    binutils \\
    && rm -rf /var/lib/apt/lists/*

# Copy source files
COPY otel_helper /build/otel_helper/
COPY pyproject.toml poetry.lock* /build/

# Install PyInstaller and dependencies
RUN pip install pyinstaller keyring

# Build the binary
RUN pyinstaller \\
    --onefile \\
    --name otel-helper-linux \\
    --strip \\
    --noupx \\
    /build/otel_helper/__main__.py
"""

        # Write temporary Dockerfile
        src_dir = Path(__file__).parent.parent.parent.parent
        dockerfile_path = src_dir / "Dockerfile.otel-helper"
        dockerfile_path.write_text(dockerfile_content)

        try:
            # Build Docker image
            build_cmd = ["docker", "build", "-t", "otel-helper-builder", "-f", str(dockerfile_path), str(src_dir)]
            result = subprocess.run(build_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {result.stderr}")

            # Extract the binary
            container_cmd = ["docker", "create", "otel-helper-builder"]
            result = subprocess.run(container_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create container: {result.stderr}")

            container_id = result.stdout.strip()

            # Copy the binary out
            copy_cmd = ["docker", "cp", f"{container_id}:/build/dist/otel-helper-linux", str(output_dir)]
            result = subprocess.run(copy_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to copy binary: {result.stderr}")

            # Clean up container
            subprocess.run(["docker", "rm", container_id], capture_output=True)

        finally:
            # Clean up Dockerfile
            dockerfile_path.unlink(missing_ok=True)

        return output_dir / "otel-helper-linux"

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

# Detect platform
echo
echo "Detecting platform..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macos"
    echo "✓ Detected macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PLATFORM="linux"
    echo "✓ Detected Linux"
else
    echo "❌ Unsupported platform: $OSTYPE"
    echo "   This installer supports macOS and Linux only."
    exit 1
fi

# Check if binary for platform exists
"""

        # Add platform availability checks
        if "macos" in platforms_built:
            installer_content += """
if [ "$PLATFORM" = "macos" ] && [ ! -f "credential-process-macos" ]; then
    echo "❌ macOS binary not found in package"
    exit 1
fi
"""

        if "linux" in platforms_built:
            installer_content += """
if [ "$PLATFORM" = "linux" ] && [ ! -f "credential-process-linux" ]; then
    echo "❌ Linux binary not found in package"
    exit 1
fi
"""

        installer_content += f"""
# Create directory
echo
echo "Installing authentication tools..."
mkdir -p ~/claude-code-with-bedrock

# Copy appropriate binary
if [ "$PLATFORM" = "macos" ]; then
    cp credential-process-macos ~/claude-code-with-bedrock/credential-process
elif [ "$PLATFORM" = "linux" ]; then
    cp credential-process-linux ~/claude-code-with-bedrock/credential-process
fi

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
if [ "$PLATFORM" = "macos" ] && [ -f "otel-helper-macos" ]; then
    echo
    echo "Installing OTEL helper..."
    cp otel-helper-macos ~/claude-code-with-bedrock/otel-helper
    chmod +x ~/claude-code-with-bedrock/otel-helper
    echo "✓ OTEL helper installed"
elif [ "$PLATFORM" = "linux" ] && [ -f "otel-helper-linux" ]; then
    echo
    echo "Installing OTEL helper..."
    cp otel-helper-linux ~/claude-code-with-bedrock/otel-helper
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

        return installer_path

    def _create_documentation(self, output_dir: Path, profile, timestamp: str):
        """Create user documentation."""
        readme_content = f"""# Claude Code Authentication Setup

## Quick Start

1. Run the installer:
   ```bash
   ./install.sh
   ```

2. Use the AWS profile:
   ```bash
   export AWS_PROFILE=ClaudeCode
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
            helper_executable_path = "~/claude-code-with-bedrock/otel-helper"
            settings["otelHeadersHelper"] = os.path.expanduser(helper_executable_path)

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
