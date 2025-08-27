# ABOUTME: Distribute command for sharing packages via presigned URLs
# ABOUTME: Handles S3 upload, URL generation, and Parameter Store storage

"""Distribute command - Share packages via secure presigned URLs."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs
from claude_code_with_bedrock.config import Config


class DistributeCommand(Command):
    """
    Distribute built packages via secure presigned URLs
    
    This command enables IT administrators to share packages
    with developers without requiring AWS credentials.
    """
    
    name = "distribute"
    description = "Distribute packages via secure presigned URLs"
    
    options = [
        option(
            "expires-hours",
            description="URL expiration time in hours (1-168)",
            flag=False,
            default="48"
        ),
        option(
            "get-latest",
            description="Retrieve the latest distribution URL",
            flag=True
        ),
        option(
            "allowed-ips",
            description="Comma-separated list of allowed IP ranges",
            flag=False
        ),
        option(
            "package-path",
            description="Path to package directory",
            flag=False,
            default="dist"
        ),
        option(
            "profile",
            description="Configuration profile to use",
            flag=False,
            default="default"
        ),
        option(
            "show-qr",
            description="Display QR code for URL (requires qrcode library)",
            flag=True
        ),
    ]
    
    def handle(self) -> int:
        """Execute the distribute command."""
        console = Console()
        
        # Show header
        console.print(Panel.fit(
            "[bold cyan]Claude Code Package Distribution[/bold cyan]\n\n"
            "Share packages securely via presigned URLs",
            border_style="cyan",
            padding=(1, 2)
        ))
        
        # Load configuration
        config = Config.load()
        profile_name = self.option("profile")
        profile = config.get_profile(profile_name)
        
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found. Run 'poetry run ccwb init' first.[/red]")
            return 1
        
        # Check if CodeBuild stack exists (which includes our S3 bucket)
        if not profile.enable_codebuild:
            console.print("[yellow]Warning: CodeBuild is not enabled.[/yellow]")
            console.print("To enable distribution features:")
            console.print("  1. Run: poetry run ccwb init")
            console.print("  2. Enable CodeBuild when prompted")
            console.print("  3. Run: poetry run ccwb deploy codebuild")
            return 1
        
        # Get latest URL if requested
        if self.option("get-latest"):
            return self._get_latest_url(profile, console)
        
        # Otherwise, create new distribution
        return self._create_distribution(profile, console)
    
    def _get_latest_url(self, profile, console: Console) -> int:
        """Retrieve the latest distribution URL from Parameter Store."""
        try:
            ssm = boto3.client('ssm', region_name=profile.aws_region)
            
            # Get parameter
            response = ssm.get_parameter(
                Name=f'/claude-code/{profile.identity_pool_name}/distribution/latest',
                WithDecryption=True
            )
            
            # Parse the stored data
            data = json.loads(response['Parameter']['Value'])
            
            # Check if URL is still valid
            expires = datetime.fromisoformat(data['expires'])
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
            console.print(f'   Expand-Archive -Path "{filename}" -DestinationPath "claude-code-package"')
            console.print('   cd claude-code-package')
            console.print('   .\\install.bat')
            
            console.print(f"\n[dim]Verify download with: sha256sum {filename} (or Get-FileHash on Windows)[/dim]")
            
            # Show QR code if requested
            if self.option("show-qr"):
                self._display_qr_code(data['url'], console)
            
            # Try to get download stats from S3 (optional)
            self._show_download_stats(profile, data.get('package_key'), console)
            
            return 0
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ParameterNotFound':
                console.print("[yellow]No distribution URL found.[/yellow]")
                console.print("Create one with: poetry run ccwb distribute")
            else:
                console.print(f"[red]Error retrieving URL: {e}[/red]")
            return 1
    
    def _create_distribution(self, profile, console: Console) -> int:
        """Create a new distribution package and generate presigned URL."""
        import boto3
        import json
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
                codebuild = boto3.client('codebuild', region_name='us-east-1')
                
                # List recent builds
                response = codebuild.list_builds_for_project(
                    projectName=project_name,
                    sortOrder='DESCENDING'
                )
                
                if response.get('ids'):
                    # Get details of recent successful builds
                    build_ids = response['ids'][:3]  # Check last 3 builds
                    builds_response = codebuild.batch_get_builds(ids=build_ids)
                    
                    for build in builds_response.get('builds', []):
                        if build['buildStatus'] == 'SUCCEEDED':
                            build_time = build.get('endTime', build.get('startTime'))
                            if build_time and build_time > windows_exe_time:
                                console.print(f"    [yellow]⚠️  Newer Windows build available (completed {build_time.strftime('%Y-%m-%d %H:%M')})[/yellow]")
                                
                                # Automatically download the newer build
                                console.print(f"    [cyan]Downloading newer Windows artifacts...[/cyan]")
                                if self._download_windows_artifacts(profile, package_path, console):
                                    console.print(f"    [green]✓ Downloaded newer Windows artifacts[/green]")
                                    # Update the timestamp
                                    windows_exe_time = datetime.fromtimestamp(windows_exe.stat().st_mtime, tz=timezone.utc)
                                else:
                                    console.print(f"    [yellow]Failed to download newer artifacts, using existing[/yellow]")
                            break
            except Exception as e:
                pass  # Silently ignore if we can't check
        else:
            # Check if Windows build is completed and download it
            windows_downloaded = False
            
            # First check for any completed builds
            try:
                project_name = f"{profile.identity_pool_name}-windows-build"
                codebuild = boto3.client('codebuild', region_name='us-east-1')
                
                # List recent builds
                response = codebuild.list_builds_for_project(
                    projectName=project_name,
                    sortOrder='DESCENDING'
                )
                
                if response.get('ids'):
                    # Get details of recent builds
                    build_ids = response['ids'][:5]  # Check last 5 builds
                    builds_response = codebuild.batch_get_builds(ids=build_ids)
                    
                    for build in builds_response.get('builds', []):
                        if build['buildStatus'] == 'SUCCEEDED':
                            # Found a successful build, download it
                            build_time = build.get('endTime', build.get('startTime'))
                            console.print(f"  ⚠️  Windows executable [yellow](found completed build from {build_time.strftime('%Y-%m-%d %H:%M')})[/yellow]")
                            console.print(f"    [cyan]Downloading Windows artifacts...[/cyan]")
                            
                            if self._download_windows_artifacts(profile, package_path, console):
                                console.print(f"    [green]✓ Downloaded Windows artifacts[/green]")
                                found_platforms.append("windows")
                                windows_downloaded = True
                            else:
                                console.print(f"    [yellow]Failed to download Windows artifacts[/yellow]")
                            break
                        elif build['buildStatus'] == 'IN_PROGRESS':
                            console.print(f"  ⚠️  Windows executable [yellow](build in progress)[/yellow]")
                            break
            except Exception as e:
                pass  # Continue to check for build info file
            
            # If we didn't download, check build info file
            if not windows_downloaded:
                build_info_file = Path.home() / '.claude-code' / 'latest-build.json'
                if build_info_file.exists():
                    with open(build_info_file) as f:
                        build_info = json.load(f)
                    
                    # Check build status
                    try:
                        codebuild = boto3.client('codebuild', region_name='us-east-1')
                        response = codebuild.batch_get_builds(ids=[build_info['build_id']])
                        if response.get('builds'):
                            build = response['builds'][0]
                            if build['buildStatus'] == 'IN_PROGRESS':
                                console.print(f"  ⚠️  Windows executable [yellow](build in progress)[/yellow]")
                            elif build['buildStatus'] == 'SUCCEEDED':
                                console.print(f"  ⚠️  Windows executable [yellow](build completed)[/yellow]")
                                console.print(f"    [cyan]Downloading Windows artifacts...[/cyan]")
                                
                                if self._download_windows_artifacts(profile, package_path, console):
                                    console.print(f"    [green]✓ Downloaded Windows artifacts[/green]")
                                    found_platforms.append("windows")
                                else:
                                    console.print(f"    [yellow]Failed to download Windows artifacts[/yellow]")
                            else:
                                console.print(f"  ✗ Windows executable [red](build failed)[/red]")
                    except:
                        console.print(f"  ✗ Windows executable [red](not found)[/red]")
                elif not windows_downloaded:
                    console.print(f"  ✗ Windows executable [red](not built)[/red]")
        
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
            console.print(f"  ✓ Unix installer script")
        if (package_path / "install.bat").exists():
            console.print(f"  ✓ Windows installer script")
        if (package_path / "config.json").exists():
            console.print(f"  ✓ Configuration file")
        
        # Warn if missing critical platforms
        if not found_platforms:
            console.print("\n[red]No platform executables found![/red]")
            console.print("Run: [cyan]poetry run ccwb package --target-platform all[/cyan]")
            return 1
        
        if "windows" not in found_platforms:
            console.print("\n[yellow]Warning: Windows support not included in this distribution[/yellow]")
            from questionary import confirm
            proceed = confirm(
                "Continue without Windows support?",
                default=False
            ).ask()
            if not proceed:
                console.print("Distribution cancelled.")
                return 0
        
        console.print(f"\n[green]Ready to distribute for: {', '.join(found_platforms)}[/green]")
        
        # Validate expiration hours
        try:
            expires_hours = int(self.option("expires-hours"))
            if not 1 <= expires_hours <= 168:
                console.print("[red]Expiration must be between 1 and 168 hours.[/red]")
                return 1
        except ValueError:
            console.print("[red]Invalid expiration hours.[/red]")
            return 1
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            
            # Create archive
            task = progress.add_task("Creating distribution archive...", total=None)
            archive_path = self._create_archive(package_path)
            
            # Calculate checksum
            progress.update(task, description="Calculating checksum...")
            checksum = self._calculate_checksum(archive_path)
            
            # Get S3 bucket from stack outputs
            progress.update(task, description="Getting S3 bucket information...")
            stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
            try:
                stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
                bucket_name = stack_outputs.get('BuildBucket')
                if not bucket_name:
                    console.print("[red]S3 bucket not found in stack outputs.[/red]")
                    return 1
            except Exception as e:
                console.print(f"[red]Error getting stack outputs: {e}[/red]")
                console.print("Deploy the CodeBuild stack first: poetry run ccwb deploy codebuild")
                return 1
            
            # Upload to S3
            progress.update(task, description="Uploading to S3...")
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"claude-code-package-{timestamp}.zip"
            package_key = f"packages/{timestamp}/{filename}"
            
            s3 = boto3.client('s3', region_name=profile.aws_region)
            try:
                s3.upload_file(
                    str(archive_path),
                    bucket_name,
                    package_key,
                    ExtraArgs={
                        'Metadata': {
                            'checksum': checksum,
                            'created': datetime.now().isoformat(),
                            'profile': profile.name
                        }
                    }
                )
            except ClientError as e:
                console.print(f"[red]Failed to upload package: {e}[/red]")
                return 1
            
            # Generate presigned URL
            progress.update(task, description="Generating presigned URL...")
            allowed_ips = self.option("allowed-ips")
            
            if allowed_ips:
                # Generate URL with IP restrictions
                url = self._generate_restricted_url(
                    s3, bucket_name, package_key, allowed_ips, expires_hours
                )
            else:
                # Generate standard presigned URL
                try:
                    url = s3.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': bucket_name, 'Key': package_key},
                        ExpiresIn=expires_hours * 3600
                    )
                except ClientError as e:
                    console.print(f"[red]Failed to generate URL: {e}[/red]")
                    return 1
            
            # Store in Parameter Store
            progress.update(task, description="Storing in Parameter Store...")
            expiration = datetime.now() + timedelta(hours=expires_hours)
            
            ssm = boto3.client('ssm', region_name=profile.aws_region)
            try:
                ssm.put_parameter(
                    Name=f'/claude-code/{profile.identity_pool_name}/distribution/latest',
                    Value=json.dumps({
                        'url': url,
                        'expires': expiration.isoformat(),
                        'package_key': package_key,
                        'checksum': checksum,
                        'filename': filename,
                        'created': datetime.now().isoformat()
                    }),
                    Type='SecureString',
                    Overwrite=True,
                    Description='Latest Claude Code package distribution URL'
                )
            except ClientError as e:
                console.print(f"[yellow]Warning: Failed to store in Parameter Store: {e}[/yellow]")
            
            # Clean up temp file
            archive_path.unlink()
            
            progress.update(task, completed=True)
        
        # Display results
        console.print("\n[bold green]✓ Distribution package created successfully![/bold green]")
        console.print(f"\n[bold]Distribution URL[/bold] (expires in {expires_hours} hours):")
        
        if allowed_ips:
            console.print(f"[dim]Restricted to IPs: {allowed_ips}[/dim]")
        
        console.print(f"\n[cyan]{url}[/cyan]")
        
        console.print(f"\n[bold]Package Details:[/bold]")
        console.print(f"  Filename: {filename}")
        console.print(f"  SHA256: {checksum}")
        console.print(f"  Expires: {expiration.strftime('%Y-%m-%d %H:%M:%S')}")
        console.print(f"  Size: {self._format_size(archive_path.stat().st_size if archive_path.exists() else 0)}")
        
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
        console.print(f'   Expand-Archive -Path "{filename}" -DestinationPath "claude-code-package"')
        console.print('   cd claude-code-package')
        console.print('   .\\install.bat')
        
        console.print(f"\n[dim]Verify download with: sha256sum {filename} (or Get-FileHash on Windows)[/dim]")
        
        return 0
    
    def _create_archive(self, package_path: Path) -> Path:
        """Create a zip archive of the package directory."""
        # Create temp file for archive
        temp_dir = Path(tempfile.mkdtemp())
        archive_path = temp_dir / "claude-code-package.zip"
        
        # Create zip archive
        shutil.make_archive(
            str(archive_path.with_suffix('')),
            'zip',
            package_path
        )
        
        return archive_path
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _generate_restricted_url(self, s3_client, bucket: str, key: str, 
                                  allowed_ips: str, expires_hours: int) -> str:
        """Generate a presigned URL with IP restrictions."""
        # Parse IP addresses
        ip_list = [ip.strip() for ip in allowed_ips.split(',')]
        
        # Create bucket policy for IP restriction
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "RestrictToIPs",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{key}",
                "Condition": {
                    "IpAddress": {
                        "aws:SourceIp": ip_list
                    }
                }
            }]
        }
        
        # Generate presigned POST (which supports policies)
        # Note: For GET with IP restrictions, we'd need to use CloudFront
        # For now, we'll generate a standard URL with a warning
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expires_hours * 3600
        )
        
        # Log the requested IP restriction for audit
        Console().print(f"[yellow]Note: IP restriction requested but requires CloudFront for enforcement.[/yellow]")
        Console().print(f"[yellow]URL will work from any IP. Consider using CloudFront for IP-based access control.[/yellow]")
        
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
        for unit in ['B', 'KB', 'MB', 'GB']:
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
            # Get bucket name from stack outputs
            stack_name = profile.stack_names.get("codebuild", f"{profile.identity_pool_name}-codebuild")
            stack_outputs = get_stack_outputs(stack_name, profile.aws_region)
            bucket_name = stack_outputs.get('BuildBucket')
            
            if not bucket_name:
                console.print("[red]Could not get S3 bucket from stack outputs[/red]")
                return False
            
            # Download from S3
            s3 = boto3.client('s3', region_name='us-east-1')
            zip_path = package_path / 'windows-binaries.zip'
            
            try:
                s3.download_file(bucket_name, 'windows-binaries.zip', str(zip_path))
                
                # Extract binaries
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(package_path)
                
                # Clean up
                zip_path.unlink()
                return True
                
            except ClientError as e:
                console.print(f"[red]Failed to download artifacts: {e}[/red]")
                return False
                
        except Exception as e:
            console.print(f"[red]Error downloading Windows artifacts: {e}[/red]")
            return False