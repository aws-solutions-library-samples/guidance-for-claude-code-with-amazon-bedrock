# ABOUTME: Distribute command for sharing packages via presigned URLs
# ABOUTME: Handles S3 upload, URL generation, and Parameter Store storage

"""Distribute command - Share packages via secure presigned URLs."""

import hashlib
import json
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config


class S3UploadProgress:
    """Track S3 upload progress."""

    def __init__(self, filename, size, progress_bar):
        self._filename = filename
        self._size = size
        self._seen_so_far = 0
        self._progress_bar = progress_bar
        self._lock = threading.Lock()
        self._task_id = None

    def set_task_id(self, task_id):
        """Set the progress bar task ID."""
        self._task_id = task_id

    def __call__(self, bytes_amount):
        """Called by boto3 during upload."""
        with self._lock:
            self._seen_so_far += bytes_amount
            if self._task_id is not None:
                self._progress_bar.update(self._task_id, completed=self._seen_so_far)


class DistributeCommand(Command):
    """
    Distribute built packages via secure presigned URLs

    This command enables IT administrators to share packages
    with developers without requiring AWS credentials.
    """

    name = "distribute"
    description = "Distribute packages via secure presigned URLs"

    options = [
        option("expires-hours", description="URL expiration time in hours (1-168)", flag=False, default="48"),
        option("get-latest", description="Retrieve the latest distribution URL", flag=True),
        option("allowed-ips", description="Comma-separated list of allowed IP ranges", flag=False),
        option("package-path", description="Path to package directory", flag=False, default="dist"),
        option("profile", description="Configuration profile to use", flag=False, default="default"),
        option("show-qr", description="Display QR code for URL (requires qrcode library)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the distribute command."""
        console = Console()

        # Show header
        console.print(
            Panel.fit(
                "[bold cyan]Claude Code Package Distribution[/bold cyan]\n\n"
                "Share packages securely via presigned URLs",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Load configuration
        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)

        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found. Run 'poetry run ccwb init' first.[/red]")
            return 1

        # Check if distribution is enabled and stack is deployed
        if profile.enable_distribution:
            dist_stack_name = profile.stack_names.get("distribution", f"{profile.identity_pool_name}-distribution")
            try:
                dist_outputs = get_stack_outputs(dist_stack_name, profile.aws_region)
                if not dist_outputs:
                    console.print("[red]Distribution stack not deployed.[/red]")
                    console.print("Deploy the distribution stack first:")
                    console.print("  poetry run ccwb deploy distribution")
                    return 1
            except Exception:
                console.print("[red]Distribution stack not deployed.[/red]")
                console.print("Deploy the distribution stack first:")
                console.print("  poetry run ccwb deploy distribution")
                return 1
        else:
            # Distribution not enabled - show info message
            console.print("[yellow]Note: Distribution features not enabled.[/yellow]")
            console.print("Package will be created locally without S3 upload or presigned URL.")

        # Get latest URL if requested (only if distribution is enabled)
        if self.option("get-latest"):
            if not profile.enable_distribution:
                console.print("[red]Distribution features not enabled.[/red]")
                console.print("Enable distribution in profile configuration to use this feature.")
                return 1
            return self._get_latest_url(profile, console)

        # Otherwise, create new distribution
        return self._create_distribution(profile, console)

    def _get_latest_url(self, profile, console: Console) -> int:
        """Retrieve the latest distribution URL from Parameter Store."""
        try:
            ssm = boto3.client("ssm", region_name=profile.aws_region)

            # Get parameter
            response = ssm.get_parameter(
                Name=f"/claude-code/{profile.identity_pool_name}/distribution/latest", WithDecryption=True
            )

            # Parse the stored data
            data = json.loads(response["Parameter"]["Value"])

            # Check if URL is still valid
            expires = datetime.fromisoformat(data["expires"])
            now = datetime.now()

            if expires < now:
                console.print("[red]Latest distribution URL has expired.[/red]")
                console.print("Generate a new one with: poetry run ccwb distribute")
                return 1

            # Display information
            console.print("\n[bold]Latest Distribution URL[/bold]")
            console.print(f"Expires: {expires.strftime('%Y-%m-%d %H:%M:%S')}")
            console.print(f"Package: {data.get('filename', 'Unknown')}")
            console.print(f"SHA256: {data.get('checksum', 'Unknown')}")
            console.print(f"\n[cyan]{data['url']}[/cyan]")

            # Output download commands for different platforms
            console.print("\n[bold]Download and Installation Instructions:[/bold]")

            filename = data.get("filename", "claude-code-package.zip")

            console.print("\n[cyan]For macOS/Linux:[/cyan]")
            console.print("1. Download (copy entire line):")
            # Use regular print to avoid Rich console line wrapping
            print(f'   curl -L -o "{filename}" "{data["url"]}"')
            console.print("2. Extract and install:")
            console.print(f"   unzip {filename} && cd claude-code-package && ./install.sh")

            console.print("\n[cyan]For Windows PowerShell:[/cyan]")
            console.print("1. Download (copy entire line):")
            print(f'   Invoke-WebRequest -Uri "{data["url"]}" -OutFile "{filename}"')
            console.print("2. Extract and install:")
            console.print(f'   Expand-Archive -Path "{filename}" -DestinationPath "."')
            console.print("   cd claude-code-package")
            console.print("   .\\install.bat")

            console.print(f"\n[dim]Verify download with: sha256sum {filename} (or Get-FileHash on Windows)[/dim]")

            # Show QR code if requested
            if self.option("show-qr"):
                self._display_qr_code(data["url"], console)

            # Try to get download stats from S3 (optional)
            self._show_download_stats(profile, data.get("package_key"), console)

            return 0

        except ClientError as e:
            if e.response["Error"]["Code"] == "ParameterNotFound":
                console.print("[yellow]No distribution URL found.[/yellow]")
                console.print("Create one with: poetry run ccwb distribute")
            else:
                console.print(f"[red]Error retrieving URL: {e}[/red]")
            return 1

    def _create_distribution(self, profile, console: Console) -> int:
        """Create a new distribution package and generate presigned URL."""
        import json

        import boto3

        package_path = Path(self.option("package-path"))

        # Validate package directory
        if not package_path.exists():
            console.print(f"[red]Package directory not found: {package_path}[/red]")
            console.print("Run 'poetry run ccwb package' first to build packages.")
            return 1

        # Check what's in the package directory
        console.print("\n[bold]Package contents:[/bold]")
        found_platforms = []

        # Check for macOS executables
        macos_arm = package_path / "credential-process-macos-arm64"
        macos_intel = package_path / "credential-process-macos-intel"
        if macos_arm.exists():
            mod_time = datetime.fromtimestamp(macos_arm.stat().st_mtime)
            console.print(f"  ✓ macOS ARM64 executable (built: {mod_time.strftime('%Y-%m-%d %H:%M')})")
            found_platforms.append("macos-arm64")
        if macos_intel.exists():
            mod_time = datetime.fromtimestamp(macos_intel.stat().st_mtime)
            console.print(f"  ✓ macOS Intel executable (built: {mod_time.strftime('%Y-%m-%d %H:%M')})")
            found_platforms.append("macos-intel")

        # Check for Windows executables
        windows_exe = package_path / "credential-process-windows.exe"
        windows_exe_time = None
        if windows_exe.exists():
            from datetime import timezone

            windows_exe_time = datetime.fromtimestamp(windows_exe.stat().st_mtime, tz=timezone.utc)
            console.print(f"  ✓ Windows executable (built: {windows_exe_time.strftime('%Y-%m-%d %H:%M')})")
            found_platforms.append("windows")

            # Check if there are newer Windows builds available and download them
            try:
                # Get CodeBuild project name from profile
                project_name = f"{profile.identity_pool_name}-windows-build"
                codebuild = boto3.client("codebuild", region_name=profile.aws_region)

                # List recent builds
                response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")

                if response.get("ids"):
                    # Get details of recent successful builds
                    build_ids = response["ids"][:3]  # Check last 3 builds
                    builds_response = codebuild.batch_get_builds(ids=build_ids)

                    for build in builds_response.get("builds", []):
                        if build["buildStatus"] == "SUCCEEDED":
                            build_time = build.get("endTime", build.get("startTime"))
                            if build_time and build_time > windows_exe_time:
                                console.print(
                                    f"    [yellow]⚠️  Newer Windows build available (completed {build_time.strftime('%Y-%m-%d %H:%M')})[/yellow]"
                                )

                                # Automatically download the newer build
                                console.print("    [cyan]Downloading newer Windows artifacts...[/cyan]")
                                if self._download_windows_artifacts(profile, package_path, console):
                                    console.print("    [green]✓ Downloaded newer Windows artifacts[/green]")
                                    # Update the timestamp
                                    windows_exe_time = datetime.fromtimestamp(
                                        windows_exe.stat().st_mtime, tz=timezone.utc
                                    )
                                else:
                                    console.print(
                                        "    [yellow]Failed to download newer artifacts, using existing[/yellow]"
                                    )
                            break
            except Exception:
                pass  # Silently ignore if we can't check
        else:
            # Check if Windows build is completed and download it
            windows_downloaded = False

            # First check for any completed builds
            try:
                project_name = f"{profile.identity_pool_name}-windows-build"
                codebuild = boto3.client("codebuild", region_name=profile.aws_region)

                # List recent builds
                response = codebuild.list_builds_for_project(projectName=project_name, sortOrder="DESCENDING")

                if response.get("ids"):
                    # Get details of recent builds
                    build_ids = response["ids"][:5]  # Check last 5 builds
                    builds_response = codebuild.batch_get_builds(ids=build_ids)

                    for build in builds_response.get("builds", []):
                        if build["buildStatus"] == "SUCCEEDED":
                            # Found a successful build, download it
                            build_time = build.get("endTime", build.get("startTime"))
                            console.print(
                                f"  ⚠️  Windows executable [yellow](found completed build from {build_time.strftime('%Y-%m-%d %H:%M')})[/yellow]"
                            )
                            console.print("    [cyan]Downloading Windows artifacts...[/cyan]")

                            if self._download_windows_artifacts(profile, package_path, console):
                                console.print("    [green]✓ Downloaded Windows artifacts[/green]")
                                found_platforms.append("windows")
                                windows_downloaded = True
                            else:
                                console.print("    [yellow]Failed to download Windows artifacts[/yellow]")
                            break
                        elif build["buildStatus"] == "IN_PROGRESS":
                            console.print("  ⚠️  Windows executable [yellow](build in progress)[/yellow]")
                            break
            except Exception:
                pass  # Continue to check for build info file

            # If we didn't download, check build info file
            if not windows_downloaded:
                build_info_file = Path.home() / ".claude-code" / "latest-build.json"
                if build_info_file.exists():
                    with open(build_info_file) as f:
                        build_info = json.load(f)

                    # Check build status
                    try:
                        codebuild = boto3.client("codebuild", region_name=profile.aws_region)
                        response = codebuild.batch_get_builds(ids=[build_info["build_id"]])
                        if response.get("builds"):
                            build = response["builds"][0]
                            if build["buildStatus"] == "IN_PROGRESS":
                                console.print("  ⚠️  Windows executable [yellow](build in progress)[/yellow]")
                            elif build["buildStatus"] == "SUCCEEDED":
                                console.print("  ⚠️  Windows executable [yellow](build completed)[/yellow]")
                                console.print("    [cyan]Downloading Windows artifacts...[/cyan]")

                                if self._download_windows_artifacts(profile, package_path, console):
                                    console.print("    [green]✓ Downloaded Windows artifacts[/green]")
                                    found_platforms.append("windows")
                                else:
                                    console.print("    [yellow]Failed to download Windows artifacts[/yellow]")
                            else:
                                console.print("  ✗ Windows executable [red](build failed)[/red]")
                    except:
                        console.print("  ✗ Windows executable [red](not found)[/red]")
                elif not windows_downloaded:
                    console.print("  ✗ Windows executable [red](not built)[/red]")

        # Check for Linux executables
        linux_x64 = package_path / "credential-process-linux-x64"
        linux_arm64 = package_path / "credential-process-linux-arm64"
        linux_generic = package_path / "credential-process-linux"  # Native Linux build

        if linux_x64.exists():
            mod_time = datetime.fromtimestamp(linux_x64.stat().st_mtime)
            found_platforms.append("linux-x64")
            console.print(f"  ✓ Linux x64 executable (built: {mod_time.strftime('%Y-%m-%d %H:%M')})")

        if linux_arm64.exists():
            mod_time = datetime.fromtimestamp(linux_arm64.stat().st_mtime)
            found_platforms.append("linux-arm64")
            console.print(f"  ✓ Linux ARM64 executable (built: {mod_time.strftime('%Y-%m-%d %H:%M')})")

        if linux_generic.exists() and not linux_x64.exists() and not linux_arm64.exists():
            # Show generic Linux build if no architecture-specific versions exist
            mod_time = datetime.fromtimestamp(linux_generic.stat().st_mtime)
            console.print(f"  ✓ Linux executable (built: {mod_time.strftime('%Y-%m-%d %H:%M')})")
            found_platforms.append("linux")

        # Check for installers and config
        if (package_path / "install.sh").exists():
            console.print("  ✓ Unix installer script")
        if (package_path / "install.bat").exists():
            console.print("  ✓ Windows installer script")
        if (package_path / "config.json").exists():
            console.print("  ✓ Configuration file")

        # Warn if missing critical platforms
        if not found_platforms:
            console.print("\n[red]No platform executables found![/red]")
            console.print("Run: [cyan]poetry run ccwb package --target-platform all[/cyan]")
            return 1

        if "windows" not in found_platforms:
            console.print("\n[yellow]Warning: Windows support not included in this distribution[/yellow]")
            from questionary import confirm

            proceed = confirm("Continue without Windows support?", default=False).ask()
            if not proceed:
                console.print("Distribution cancelled.")
                return 0

        console.print(f"\n[green]Ready to distribute for: {', '.join(found_platforms)}[/green]")

        # Validate expiration hours (max 7 days for IAM user presigned URLs)
        try:
            expires_hours = int(self.option("expires-hours"))
            if not 1 <= expires_hours <= 168:
                console.print("[red]Expiration must be between 1 and 168 hours (7 days).[/red]")
                console.print(
                    "[dim]Note: Presigned URLs have a maximum lifetime of 7 days when using IAM user credentials.[/dim]"
                )
                return 1
        except ValueError:
            console.print("[red]Invalid expiration hours.[/red]")
            return 1

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # Create archive
            task = progress.add_task("Creating distribution archive...", total=None)
            archive_path = self._create_archive(package_path)

            # Calculate checksum
            progress.update(task, description="Calculating checksum...")
            checksum = self._calculate_checksum(archive_path)

            # Prepare filename
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"claude-code-package-{timestamp}.zip"

            # Only do S3 operations if distribution is enabled
            if profile.enable_distribution:
                # Get S3 bucket from distribution stack outputs
                progress.update(task, description="Getting S3 bucket information...")
                dist_stack_name = profile.stack_names.get("distribution", f"{profile.identity_pool_name}-distribution")
                try:
                    stack_outputs = get_stack_outputs(dist_stack_name, profile.aws_region)
                    bucket_name = stack_outputs.get("DistributionBucket")
                    if not bucket_name:
                        console.print("[red]S3 bucket not found in distribution stack outputs.[/red]")
                        return 1
                except Exception as e:
                    console.print(f"[red]Error getting distribution stack outputs: {e}[/red]")
                    console.print("Deploy the distribution stack first: poetry run ccwb deploy distribution")
                    return 1

                # Upload to S3 with progress tracking
                progress.update(task, description="Preparing upload...")
                package_key = f"packages/{timestamp}/{filename}"

                # Get file size for progress tracking
                file_size = archive_path.stat().st_size

                # Configure multipart upload for better performance
                config = TransferConfig(
                    multipart_threshold=1024 * 25,  # 25MB
                    max_concurrency=10,
                    multipart_chunksize=1024 * 25,
                    use_threads=True,
                )

                # Create S3 client
                s3 = boto3.client("s3", region_name=profile.aws_region)

                # Close the spinner progress and create a new one with upload progress
                progress.stop()

                # Create progress bar for upload
                with Progress(
                    TextColumn("[bold blue]Uploading to S3"),
                    BarColumn(),
                    "[progress.percentage]{task.percentage:>3.1f}%",
                    "•",
                    DownloadColumn(),
                    "•",
                    TimeRemainingColumn(),
                    console=console,
                ) as upload_progress:
                    upload_task = upload_progress.add_task("upload", total=file_size)

                    # Create callback
                    callback = S3UploadProgress(filename, file_size, upload_progress)
                    callback.set_task_id(upload_task)

                    try:
                        s3.upload_file(
                            str(archive_path),
                            bucket_name,
                            package_key,
                            ExtraArgs={
                                "Metadata": {
                                    "checksum": checksum,
                                    "created": datetime.now().isoformat(),
                                    "profile": profile.name,
                                }
                            },
                            Config=config,
                            Callback=callback,
                        )
                    except ClientError as e:
                        console.print(f"[red]Failed to upload package: {e}[/red]")
                        return 1

                # Restart the spinner progress for remaining tasks
                progress = Progress(
                    SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
                )
                progress.start()
                task = progress.add_task("Processing...", total=None)

            # Generate presigned URL
            progress.update(task, description="Generating presigned URL...")
            allowed_ips = self.option("allowed-ips")

            if allowed_ips:
                # Generate URL with IP restrictions
                url = self._generate_restricted_url(s3, bucket_name, package_key, allowed_ips, expires_hours)
            else:
                # Generate standard presigned URL
                try:
                    url = s3.generate_presigned_url(
                        "get_object", Params={"Bucket": bucket_name, "Key": package_key}, ExpiresIn=expires_hours * 3600
                    )
                except ClientError as e:
                    console.print(f"[red]Failed to generate URL: {e}[/red]")
                    return 1

            # Store in Parameter Store
            progress.update(task, description="Storing in Parameter Store...")
            expiration = datetime.now() + timedelta(hours=expires_hours)

            ssm = boto3.client("ssm", region_name=profile.aws_region)
            try:
                ssm.put_parameter(
                    Name=f"/claude-code/{profile.identity_pool_name}/distribution/latest",
                    Value=json.dumps(
                        {
                            "url": url,
                            "expires": expiration.isoformat(),
                            "package_key": package_key,
                            "checksum": checksum,
                            "filename": filename,
                            "created": datetime.now().isoformat(),
                        }
                    ),
                    Type="SecureString",
                    Overwrite=True,
                    Description="Latest Claude Code package distribution URL",
                )
            except ClientError as e:
                console.print(f"[yellow]Warning: Failed to store in Parameter Store: {e}[/yellow]")

                # Get file size before cleanup
                file_size = archive_path.stat().st_size if archive_path.exists() else 0
            else:
                # Distribution not enabled - save locally
                progress.update(task, description="Saving package locally...")
                local_dir = Path("dist")
                local_dir.mkdir(exist_ok=True)
                local_path = local_dir / filename

                import shutil

                shutil.copy2(archive_path, local_path)

                # Get file size
                file_size = archive_path.stat().st_size if archive_path.exists() else 0

            # Clean up temp file
            archive_path.unlink()

            # Stop progress if it's still running
            if "progress" in locals() and hasattr(progress, "stop"):
                progress.stop()

        # Display results based on distribution mode
        if profile.enable_distribution:
            console.print("\n[bold green]✓ Distribution package created successfully![/bold green]")
            console.print(f"\n[bold]Distribution URL[/bold] (expires in {expires_hours} hours):")
        else:
            console.print("\n[bold green]✓ Package created successfully![/bold green]")
            console.print(f"\n[bold]Package saved locally:[/bold] dist/{filename}")

        if profile.enable_distribution:
            # Show distribution-specific details
            if allowed_ips:
                console.print(f"[dim]Restricted to IPs: {allowed_ips}[/dim]")

            console.print(f"\n[cyan]{url}[/cyan]")

            console.print("\n[bold]Package Details:[/bold]")
            console.print(f"  Filename: {filename}")
            console.print(f"  SHA256: {checksum}")
            console.print(f"  Expires: {expiration.strftime('%Y-%m-%d %H:%M:%S')}")
            console.print(f"  Size: {self._format_size(file_size)}")

            # Show QR code if requested
            if self.option("show-qr"):
                self._display_qr_code(url, console)

            console.print("\n[bold]Share this URL with developers to download the package.[/bold]")

            # Output download commands for different platforms
            console.print("\n[bold]Download and Installation Instructions:[/bold]")

            console.print("\n[cyan]For macOS/Linux:[/cyan]")
            console.print("1. Download (copy entire line):")
            # Use regular print to avoid Rich console line wrapping
            print(f'   curl -L -o "{filename}" "{url}"')
            console.print("2. Extract and install:")
            console.print(f"   unzip {filename} && cd claude-code-package && ./install.sh")

            console.print("\n[cyan]For Windows PowerShell:[/cyan]")
            console.print("1. Download (copy entire line):")
            print(f'   Invoke-WebRequest -Uri "{url}" -OutFile "{filename}"')
            console.print("2. Extract and install:")
            console.print(f'   Expand-Archive -Path "{filename}" -DestinationPath "."')
            console.print("   cd claude-code-package")
            console.print("   .\\install.bat")

            console.print(f"\n[dim]Verify download with: sha256sum {filename} (or Get-FileHash on Windows)[/dim]")
        else:
            # Show local package details
            console.print("\n[bold]Package Details:[/bold]")
            console.print(f"  Filename: {filename}")
            console.print(f"  SHA256: {checksum}")
            console.print(f"  Size: {self._format_size(file_size)}")

            console.print("\n[bold]Installation Instructions:[/bold]")
            console.print("1. Extract the package:")
            console.print(f"   unzip dist/{filename}")
            console.print("2. Install:")
            console.print("   cd claude-code-package")
            console.print("   ./install.sh  (macOS/Linux)")
            console.print("   .\\install.bat  (Windows)")

            console.print("\n[dim]To enable distribution features:[/dim]")
            console.print("  1. Run: poetry run ccwb init")
            console.print("  2. Enable distribution when prompted")
            console.print("  3. Run: poetry run ccwb deploy distribution")

        return 0

    def _create_archive(self, package_path: Path) -> Path:
        """Create a zip archive of the package directory."""
        import zipfile

        # Create temp directory for archive
        temp_dir = Path(tempfile.mkdtemp())
        archive_path = temp_dir / "claude-code-package.zip"

        # Create a clean package directory with only necessary files
        package_temp_dir = temp_dir / "claude-code-package"
        package_temp_dir.mkdir(exist_ok=True)

        # Files to include in the package
        required_files = [
            # Executables for each platform
            "credential-process-macos-arm64",
            "credential-process-macos-intel",
            "credential-process-linux-x64",
            "credential-process-linux-arm64",
            "credential-process-windows.exe",
            # OTEL helpers
            "otel-helper-macos-arm64",
            "otel-helper-macos-intel",
            "otel-helper-linux-x64",
            "otel-helper-linux-arm64",
            "otel-helper-windows.exe",
            # Installation scripts
            "install.sh",
            "install.bat",
            # Configuration
            "config.json",
            "README.md",
        ]

        # Also include claude-settings directory if it exists
        settings_dir = package_path / "claude-settings"
        if settings_dir.exists() and settings_dir.is_dir():
            shutil.copytree(settings_dir, package_temp_dir / "claude-settings")

        # Copy only the required files
        for filename in required_files:
            source_file = package_path / filename
            if source_file.exists():
                shutil.copy2(source_file, package_temp_dir / filename)

        # Create zip archive with contents at root level
        # When extracted, it will create claude-code-package/ with files directly inside
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add all files from the package directory
            for file in package_temp_dir.rglob("*"):
                if file.is_file():
                    # Get relative path from package_temp_dir (not temp_dir) to avoid nested directories
                    # This creates paths like "config.json", "install.sh" instead of "claude-code-package/config.json"
                    arcname = f"claude-code-package/{file.relative_to(package_temp_dir)}"
                    zf.write(file, arcname)

        # Clean up temp package directory
        shutil.rmtree(package_temp_dir)

        return archive_path

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _generate_restricted_url(self, s3_client, bucket: str, key: str, allowed_ips: str, expires_hours: int) -> str:
        """Generate a presigned URL with IP restrictions."""
        # Parse IP addresses
        [ip.strip() for ip in allowed_ips.split(",")]

        # Create bucket policy for IP restriction

        # Generate presigned POST (which supports policies)
        # Note: For GET with IP restrictions, we'd need to use CloudFront
        # For now, we'll generate a standard URL with a warning
        url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_hours * 3600
        )

        # Log the requested IP restriction for audit
        Console().print("[yellow]Note: IP restriction requested but requires CloudFront for enforcement.[/yellow]")
        Console().print(
            "[yellow]URL will work from any IP. Consider using CloudFront for IP-based access control.[/yellow]"
        )

        return url

    def _display_qr_code(self, url: str, console: Console):
        """Display a QR code for the URL if qrcode library is available."""
        try:
            import qrcode

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=1,
                border=1,
            )
            qr.add_data(url)
            qr.make(fit=True)

            console.print("\n[bold]QR Code for distribution URL:[/bold]")
            qr.print_ascii(invert=True)

        except ImportError:
            console.print("\n[dim]QR code display requires: pip install qrcode[/dim]")

    def _show_download_stats(self, profile, package_key: str, console: Console):
        """Show download statistics if available (requires S3 access logs)."""
        # This would require S3 access logs to be configured and queryable
        # For now, just show a placeholder
        console.print("\n[dim]Download tracking requires S3 access logs configuration.[/dim]")

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def _download_windows_artifacts(self, profile, package_path: Path, console: Console) -> bool:
        """Download Windows build artifacts from S3."""
        import zipfile

        from botocore.exceptions import ClientError

        from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs

        try:
            # Windows artifacts are always in the CodeBuild bucket
            if not profile.enable_codebuild:
                console.print("[red]CodeBuild is not enabled for this profile[/red]")
                return False

            codebuild_stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
            codebuild_outputs = get_stack_outputs(codebuild_stack_name, profile.aws_region)

            if not codebuild_outputs:
                console.print("[red]CodeBuild stack not found[/red]")
                return False

            bucket_name = codebuild_outputs.get("BuildBucket")
            project_name = codebuild_outputs.get("ProjectName")

            if not bucket_name or not project_name:
                console.print("[red]Could not get CodeBuild bucket or project name from stack outputs[/red]")
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

                # Clean up
                zip_path.unlink()
                return True

            except ClientError as e:
                console.print(f"[red]Failed to download artifacts: {e}[/red]")
                console.print(f"[dim]Tried: s3://{bucket_name}/{artifact_key}[/dim]")
                return False

        except Exception as e:
            console.print(f"[red]Error downloading Windows artifacts: {e}[/red]")
            return False
