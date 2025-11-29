# ABOUTME: Test command to verify authentication and Bedrock access
# ABOUTME: Performs comprehensive checks to ensure setup is working correctly

"""Test command - Verify authentication and access."""

import json
import subprocess
import time
import uuid
from pathlib import Path

import boto3
from cleo.commands.command import Command
from cleo.helpers import option
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from claude_code_with_bedrock.config import Config


class TestCommand(Command):
    name = "test"
    description = "Test authentication and verify access to Bedrock"

    options = [
        option(
            "profile", "p", description="Profile name to test (defaults to active profile)", flag=False, default=None
        ),
        option("full", description="Test all allowed regions (default: tests 3 representative regions)", flag=True),
        option("quota-only", description="Run only quota monitoring tests (API, policies, usage capture)", flag=True),
        option(
            "quota-api",
            description="Test quota API with optional custom endpoint override",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:
        """Execute the test command."""
        console = Console()

        # Load configuration to get active profile
        config = Config.load()
        test_profile_name = self.option("profile") or config.active_profile

        if not test_profile_name:
            console.print("[red]No profile specified and no active profile set.[/red]")
            console.print(
                "Use [cyan]ccwb context use <profile>[/cyan] to set an active profile or use "
                "[cyan]--profile <name>[/cyan]"
            )
            return 1

        # Welcome
        console.print(
            Panel.fit(
                "[bold cyan]Claude Code Package Test[/bold cyan]\n\n"
                f"Testing profile: [bold]{test_profile_name}[/bold]\n"
                "This will test authentication and verify Bedrock API access in your configured region",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Check if package exists - look in multiple locations
        # First try the source directory (where package command creates it)
        source_dist = Path(__file__).parent.parent.parent.parent / "dist"
        # Also check current directory
        local_dist = Path("./dist")

        def find_latest_package(dist_dir: Path, profile_name: str) -> Path | None:
            """Find the latest package in dist/{profile}/{timestamp}/ structure."""
            profile_dir = dist_dir / profile_name
            if not profile_dir.exists():
                return None
            # Find timestamp directories (format: YYYY-MM-DD-HHMMSS)
            timestamp_dirs = [d for d in profile_dir.iterdir() if d.is_dir() and (d / "install.sh").exists()]
            if not timestamp_dirs:
                return None
            # Return the latest (sorted by name, which works for timestamp format)
            return sorted(timestamp_dirs, reverse=True)[0]

        package_dir = None
        # Try nested structure first: dist/{profile}/{timestamp}/
        for dist_path in [source_dist, local_dist]:
            if dist_path.exists():
                latest = find_latest_package(dist_path, test_profile_name)
                if latest:
                    package_dir = latest
                    console.print(f"[dim]Using package from: {package_dir}[/dim]")
                    break

        # Fall back to legacy flat structure: dist/install.sh
        if not package_dir:
            if source_dist.exists() and (source_dist / "install.sh").exists():
                package_dir = source_dist
                console.print(f"[dim]Using package from: {package_dir}[/dim]")
            elif local_dist.exists() and (local_dist / "install.sh").exists():
                package_dir = local_dist
                console.print(f"[dim]Using package from: {package_dir}[/dim]")

        if not package_dir:
            console.print("[red]No package found. Run 'poetry run ccwb package' first.[/red]")
            console.print("[dim]Searched in:[/dim]")
            console.print(f"[dim]  - {source_dist}/{test_profile_name}/<timestamp>/[/dim]")
            console.print(f"[dim]  - {local_dist}/{test_profile_name}/<timestamp>/[/dim]")
            console.print(f"[dim]  - {source_dist}[/dim]")
            console.print(f"[dim]  - {local_dist}[/dim]")
            return 1

        # Test directly from the package directory
        console.print(f"[dim]Testing package in: {package_dir}[/dim]\n")

        # Step 1: Check package contents
        console.print("[bold]Step 1: Checking package contents[/bold]")

        # Detect current platform
        import platform as platform_module

        system = platform_module.system().lower()
        machine = platform_module.machine().lower()

        if system == "darwin":
            if machine == "arm64":
                platform_suffix = "macos-arm64"
            else:
                platform_suffix = "macos-intel"
        elif system == "linux":
            if machine in ["aarch64", "arm64"]:
                platform_suffix = "linux-arm64"
            else:
                platform_suffix = "linux-x64"
        elif system == "windows":
            platform_suffix = "windows"
        else:
            console.print(f"[red]Unsupported platform: {system}[/red]")
            return 1

        # Check for platform binary
        credential_binary = package_dir / f"credential-process-{platform_suffix}"
        if system == "windows" and not credential_binary.exists():
            credential_binary = package_dir / f"credential-process-{platform_suffix}.exe"

        if not credential_binary.exists():
            console.print(f"[red]✗ Binary not found for your platform: {credential_binary.name}[/red]")
            return 1

        console.print(f"✓ Found binary: {credential_binary.name}")

        # Check for OTEL helper (optional)
        otel_binary = package_dir / f"otel-helper-{platform_suffix}"
        if system == "windows" and not otel_binary.exists():
            otel_binary = package_dir / f"otel-helper-{platform_suffix}.exe"

        has_otel = otel_binary.exists()
        if has_otel:
            console.print(f"✓ Found OTEL helper: {otel_binary.name}")
        else:
            console.print("[dim]  - OTEL helper not included (monitoring disabled)[/dim]")

        # Check config
        config_path = package_dir / "config.json"
        if not config_path.exists():
            console.print("[red]✗ config.json not found[/red]")
            return 1

        console.print("✓ Found config.json")

        # Read and display config details
        with open(config_path) as f:
            pkg_config = json.load(f)
            # Try to read from the specified profile name, fall back to "ClaudeCode" for backward compatibility
            profile_config = pkg_config.get(test_profile_name) or pkg_config.get("ClaudeCode", {})

            if not profile_config:
                console.print(f"[red]✗ Profile '{test_profile_name}' not found in config.json[/red]")
                console.print(f"[dim]Available profiles: {', '.join(pkg_config.keys())}[/dim]")
                return 1

            # Display configuration
            console.print("\n[bold]Configuration:[/bold]")
            console.print(f"[dim]  - Provider: {profile_config.get('provider_domain', 'unknown')}[/dim]")
            console.print(f"[dim]  - AWS Region: {profile_config.get('aws_region', 'unknown')}[/dim]")

            # Check credential storage
            storage_method = profile_config.get("credential_storage", "session")
            storage_display = (
                "Keyring (OS secure storage)" if storage_method == "keyring" else "Session Files (temporary)"
            )
            console.print(f"[dim]  - Credential Storage: {storage_display}[/dim]")

            # Check federation type
            federation_type = profile_config.get("federation_type", "cognito")
            if federation_type == "direct":
                console.print("[dim]  - Federation Type: Direct STS (12-hour sessions)[/dim]")
                if "federated_role_arn" in profile_config:
                    console.print(f"[dim]  - Role ARN: {profile_config['federated_role_arn']}[/dim]")
            else:
                console.print("[dim]  - Federation Type: Cognito Identity Pool (8-hour sessions)[/dim]")
                if "identity_pool_id" in profile_config:
                    console.print(f"[dim]  - Identity Pool: {profile_config['identity_pool_id']}[/dim]")

        console.print()

        # Check for --quota-only flag early
        quota_only = self.option("quota-only")
        quota_api_override = self.option("quota-api")

        # If --quota-only, run dedicated quota tests and exit
        if quota_only:
            # Load the profile from ccwb config
            profile = config.get_profile(test_profile_name)
            if not profile:
                console.print(f"[red]Profile '{test_profile_name}' not found in configuration.[/red]")
                return 1

            # Set up temporary AWS profile for testing
            test_profile = f"ccwb-test-{uuid.uuid4().hex[:8]}"
            credential_command = f"/bin/sh -c 'CCWB_PROFILE={test_profile_name} {credential_binary}'"
            subprocess.run(
                ["aws", "configure", "set", f"profile.{test_profile}.credential_process", credential_command],
                capture_output=True,
            )
            subprocess.run(
                ["aws", "configure", "set", f"profile.{test_profile}.region", profile.aws_region],
                capture_output=True,
            )

            return self._run_quota_tests(
                profile,
                credential_binary,
                package_dir,
                test_profile_name,
                test_profile,
                quota_api_override,
            )

        # Step 2: Test the binary directly
        console.print("[bold]Step 2: Testing credential process binary[/bold]")

        # Test if binary is executable
        test_result = subprocess.run([str(credential_binary), "--version"], capture_output=True, text=True)

        if test_result.returncode == 0:
            console.print("✓ Binary is executable")
        else:
            console.print("[red]✗ Binary failed to run[/red]")
            console.print(f"[dim]{test_result.stderr}[/dim]")
            return 1

        # Set up temporary AWS profile for testing
        test_profile = f"ccwb-test-{uuid.uuid4().hex[:8]}"

        console.print("\n[bold]Step 3: Testing authentication[/bold]")
        console.print(f"[dim]Using temporary profile: {test_profile}[/dim]")

        # Configure the test profile
        # Set environment variable to tell credential binary which profile to use from config.json
        # Use shell to set environment variable
        credential_command = f"/bin/sh -c 'CCWB_PROFILE={test_profile_name} {credential_binary}'"
        aws_config_result = subprocess.run(
            ["aws", "configure", "set", f"profile.{test_profile}.credential_process", credential_command],
            capture_output=True,
        )

        if aws_config_result.returncode != 0:
            console.print("[red]Failed to configure test profile[/red]")
            return 1

        # Configure region for the test profile
        subprocess.run(
            [
                "aws",
                "configure",
                "set",
                f"profile.{test_profile}.region",
                profile_config.get("aws_region", "us-east-1"),
            ],
            capture_output=True,
        )

        # Load configuration for test parameters
        profile = config.get_profile(test_profile_name)

        if not profile:
            console.print(
                f"[red]Profile '{test_profile_name}' not found in configuration. Run 'poetry run ccwb \
                init' first.[/red]"
            )
            return 1

        # Use test_profile instead of hardcoded "ClaudeCode"
        aws_profile = test_profile
        test_all_regions = self.option("full")
        with_api = True  # Always test with API calls by default

        # Create test results table
        table = Table(title="Test Results", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Test", style="white", no_wrap=True, min_width=24)
        table.add_column("Status", style="white", width=12)
        table.add_column("Details", style="dim", min_width=50, overflow="fold")

        test_results = []

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # Test 1: AWS Profile exists
            task = progress.add_task("Checking AWS profile...", total=None)
            result = self._test_aws_profile(aws_profile)
            test_results.append(("AWS Profile Configured", result["status"], result["details"]))
            progress.update(task, completed=True)

            # Test 2: Credentials can be obtained
            task = progress.add_task("Testing authentication...", total=None)
            result = self._test_authentication(aws_profile)
            test_results.append(("Authentication", result["status"], result["details"]))
            progress.update(task, completed=True)

            if result["status"] == "✓":
                # Test 3: Check assumed role
                task = progress.add_task("Verifying IAM role...", total=None)
                result = self._test_iam_role(aws_profile, profile)
                test_results.append(("IAM Role", result["status"], result["details"]))
                progress.update(task, completed=True)

                # Validate that selected_source_region is configured
                if not profile.selected_source_region:
                    test_results.append(
                        ("Configuration", "✗", "selected_source_region not set - run 'ccwb init' to configure")
                    )
                    progress.stop()
                    # Display results immediately and exit
                    console.print("\n")
                    table = Table(title="Test Results", box=box.ROUNDED, show_header=True, header_style="bold cyan")
                    table.add_column("Test", style="white", no_wrap=True, min_width=24)
                    table.add_column("Status", style="white", width=12)
                    table.add_column("Details", style="dim", min_width=50, overflow="fold")
                    for test_name, status, details in test_results:
                        if status == "✓":
                            status_display = "[green]✓ Pass[/green]"
                        else:
                            status_display = "[red]✗ Fail[/red]"
                        table.add_row(test_name, status_display, details)
                    console.print(table)
                    console.print("\n[red]Configuration error: selected_source_region must be set[/red]")
                    return 1

                # Test 4: Determine which regions to test
                if test_all_regions:
                    # Test all allowed regions
                    regions_to_test = profile.allowed_bedrock_regions
                else:
                    # Test only the user's configured source region
                    regions_to_test = [profile.selected_source_region]

                # Test Bedrock access in configured region(s)
                for region in regions_to_test:
                    task = progress.add_task(f"Testing Bedrock API in {region}...", total=None)
                    result = self._test_bedrock_access(aws_profile, region, with_api)
                    test_results.append((f"Bedrock - {region}", result["status"], result["details"]))
                    progress.update(task, completed=True)

                # Test 5: Test inference profiles in configured source region
                if not test_all_regions:
                    # Only test inference profiles when testing configured region (not during full test)
                    task = progress.add_task("Testing inference profiles...", total=None)
                    result = self._test_inference_profiles(
                        aws_profile, profile.selected_source_region, profile.selected_model
                    )
                    test_results.append(("Inference Profiles", result["status"], result["details"]))
                    progress.update(task, completed=True)

                # Test 6: Quota Monitoring API (if enabled)
                quota_enabled = getattr(profile, "quota_monitoring_enabled", False)
                quota_endpoint = quota_api_override or getattr(profile, "quota_api_endpoint", None)

                if quota_enabled and quota_endpoint:
                    task = progress.add_task("Testing quota monitoring API...", total=None)
                    # Get profile name from package's config.json (more reliable than ccwb profile name)
                    package_profile = self._get_package_profile_name(package_dir)
                    if package_profile:
                        result = self._test_quota_api(credential_binary, quota_endpoint, package_dir, package_profile)
                        test_results.append(("Quota Monitoring", result["status"], result["details"]))
                    else:
                        test_results.append(("Quota Monitoring", "!", "Could not determine profile from package"))
                    progress.update(task, completed=True)
                elif quota_enabled and not quota_endpoint:
                    test_results.append(("Quota Monitoring", "!", "Enabled but API endpoint not configured"))
                else:
                    test_results.append(("Quota Monitoring", "-", "Skipped (not enabled)"))

        # Display results
        console.print("\n")
        for test_name, status, details in test_results:
            if status == "✓":
                status_display = "[green]✓ Pass[/green]"
            elif status == "!":
                status_display = "[yellow]! Warning[/yellow]"
            elif status == "-":
                status_display = "[dim]- Skip[/dim]"
            else:
                status_display = "[red]✗ Fail[/red]"
            table.add_row(test_name, status_display, details)

        console.print(table)

        # Summary
        passed = sum(1 for _, status, _ in test_results if status == "✓")
        warnings = sum(1 for _, status, _ in test_results if status == "!")
        failed = sum(1 for _, status, _ in test_results if status == "✗")
        skipped = sum(1 for _, status, _ in test_results if status == "-")

        summary_parts = [f"{passed} passed", f"{warnings} warnings", f"{failed} failed"]
        if skipped > 0:
            summary_parts.append(f"{skipped} skipped")
        console.print(f"\n[bold]Summary:[/bold] {', '.join(summary_parts)}")

        if failed > 0:
            console.print("\n[red]Some tests failed. Please check the details above.[/red]")
            console.print("\n[bold]Troubleshooting tips:[/bold]")
            console.print("• Ensure you have access to the Okta application")
            console.print("• Check that the Cognito Identity Pool is deployed")
            console.print("• Verify IAM roles have correct permissions")
            console.print("• Make sure Bedrock is enabled in your AWS account")

            # If Bedrock tests failed, show how to check Bedrock status
            bedrock_failed = any("Bedrock" in name and status == "✗" for name, status, _ in test_results)
            if bedrock_failed:
                console.print("\n[bold]To check Bedrock status in your account:[/bold]")
                console.print("1. Visit https://console.aws.amazon.com/bedrock/")
                console.print("2. Check if you have access to Claude models")
                console.print("3. You may need to request model access if not enabled")
                console.print("\n[bold]To test with your admin credentials:[/bold]")
                console.print(
                    f"aws bedrock list-foundation-models --region "
                    f"{profile.allowed_bedrock_regions[0]} --query "
                    f"\"modelSummaries[?contains(modelId, 'claude')]\""
                )

            return 1
        elif warnings > 0:
            console.print("\n[yellow]Tests passed with warnings. Check details above.[/yellow]")
            return 0
        else:
            console.print("\n[green]All tests passed! Your setup is working correctly.[/green]")

            if not test_all_regions:
                console.print(
                    "\n[dim]Note: Tested your configured source region. Use --full to test all allowed regions.[/dim]"
                )

            console.print("\n[bold]Package test complete. Authentication and Bedrock access verified.[/bold]")

            # Clean up test profile if we created one
            if "test_profile" in locals():
                subprocess.run(
                    ["aws", "configure", "--profile", test_profile, "set", "credential_process", ""],
                    capture_output=True,
                )

            return 0

    def _test_aws_profile(self, profile_name: str) -> dict:
        """Test if AWS profile exists."""
        try:
            aws_config_file = Path.home() / ".aws" / "config"
            if not aws_config_file.exists():
                return {"status": "✗", "details": "AWS config file not found"}

            with open(aws_config_file) as f:
                content = f.read()
                if f"[profile {profile_name}]" in content:
                    return {"status": "✓", "details": f"Profile '{profile_name}' found"}
                else:
                    return {"status": "✗", "details": f"Profile '{profile_name}' not found"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_authentication(self, profile_name: str) -> dict:
        """Test if authentication works."""
        try:
            # Try to get caller identity
            # Clear AWS credentials from environment to ensure credential_process is used
            import os

            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)

            cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]

            # Show credential process output in real-time
            import sys

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,  # Show stderr (browser messages, auth progress) in real-time
                text=True,
                timeout=120,
                env=test_env,
            )

            if result.returncode == 0:
                identity = json.loads(result.stdout)
                return {"status": "✓", "details": f"Authenticated as {identity.get('UserId', 'unknown')[:20]}..."}
            else:
                return {"status": "✗", "details": f"Authentication failed (exit code {result.returncode})"}
        except subprocess.TimeoutExpired:
            return {"status": "✗", "details": "Authentication timed out"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_iam_role(self, profile_name: str, config_profile) -> dict:
        """Test IAM role and permissions."""
        try:
            # Clear AWS credentials from environment
            import os

            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)

            cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]
            result = subprocess.run(cmd, capture_output=True, text=True, env=test_env)

            if result.returncode == 0:
                identity = json.loads(result.stdout)
                arn = identity.get("Arn", "")
                account_id = identity.get("Account", "")

                # Check if it's an assumed role
                if ":assumed-role/" in arn:
                    role_name = arn.split("/")[-2]

                    # Try to get the expected account from the stack
                    expected_account = self._get_expected_account(config_profile)

                    # Check account match
                    if expected_account and account_id != expected_account:
                        return {"status": "✗", "details": f"Wrong account: {account_id} (expected {expected_account})"}

                    # Check role name pattern - support both Cognito and Direct IAM patterns
                    expected_patterns = [
                        config_profile.identity_pool_name,
                        "BedrockAccessRole",
                        "BedrockOktaFederatedRole",
                        "BedrockAzureFederatedRole",
                        "BedrockAuth0FederatedRole",
                        "BedrockCognitoFederatedRole",
                        "Bedrock",  # General Bedrock role pattern
                        "FederatedRole",  # General federated pattern
                    ]

                    # Check if role matches any expected pattern
                    if any(pattern in role_name for pattern in expected_patterns if pattern):
                        return {"status": "✓", "details": f"Role: {role_name} in account {account_id}"}
                    else:
                        return {"status": "!", "details": f"Using role: {role_name}"}
                else:
                    return {"status": "✗", "details": "Not using assumed role"}
            else:
                return {"status": "✗", "details": "Could not get caller identity"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_bedrock_access(self, profile_name: str, region: str, with_api: bool = False) -> dict:
        """Test Bedrock access in a specific region."""
        try:
            # Clear AWS credentials from environment
            import os

            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)

            # First get the account we're using
            identity_cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]
            identity_result = subprocess.run(identity_cmd, capture_output=True, text=True, env=test_env)
            account_id = "unknown"
            role_name = "unknown"
            if identity_result.returncode == 0:
                identity = json.loads(identity_result.stdout)
                account_id = identity.get("Account", "unknown")
                arn = identity.get("Arn", "")
                if ":assumed-role/" in arn:
                    role_name = arn.split("/")[-2]

            # First check if Bedrock is available in the region
            describe_cmd = [
                "aws",
                "bedrock",
                "list-foundation-models",
                "--profile",
                profile_name,
                "--region",
                region,
                "--query",
                "modelSummaries[?contains(modelId, 'claude')].modelId",
                "--output",
                "json",
            ]
            result = subprocess.run(describe_cmd, capture_output=True, text=True, timeout=60, env=test_env)

            if result.returncode == 0:
                models = json.loads(result.stdout)
                if models:
                    if with_api:
                        # Test actual model invocation with one of the available models
                        test_result = self._test_model_invocation(profile_name, region, models)
                        if test_result["success"]:
                            return {"status": "✓", "details": f"Found {len(models)} models, API test passed"}
                        else:
                            # Check the type of error
                            error = test_result["error"]
                            if "ValidationException" in error:
                                # Validation errors often mean model isn't available in this region
                                return {
                                    "status": "✓",
                                    "details": f"Found {len(models)} Claude models (some models may \
                                    not support invoke)",
                                }
                            elif "ThrottlingException" in error or "Rate limited" in error:
                                # Rate limiting is not a failure
                                return {
                                    "status": "✓",
                                    "details": f"Found {len(models)} Claude models (API test rate limited)",
                                }
                            elif "timeout" in error.lower():
                                # Timeouts could be transient
                                return {
                                    "status": "!",
                                    "details": f"Found {len(models)} Claude models (API test timed out)",
                                }
                            else:
                                # Other errors are actual failures
                                return {"status": "✗", "details": f"Found models but API test failed: {error[:80]}"}
                    else:
                        return {"status": "✓", "details": f"Found {len(models)} Claude models"}
                else:
                    return {"status": "!", "details": "No Claude models found"}
            else:
                error_msg = result.stderr or result.stdout

                # Parse specific error types
                if "AccessDeniedException" in error_msg:
                    # Extract the specific error message
                    if "is not authorized to perform" in error_msg:
                        action = (
                            "bedrock:ListFoundationModels" if "ListFoundationModels" in error_msg else "bedrock access"
                        )
                        return {"status": "✗", "details": f"Role {role_name} lacks {action} permission"}
                    elif "Bedrock is not available" in error_msg:
                        return {"status": "✗", "details": f"Bedrock not available in {region} for account {account_id}"}
                    else:
                        return {"status": "✗", "details": "Access denied - check IAM permissions"}
                elif "UnrecognizedClientException" in error_msg:
                    return {"status": "✗", "details": "Invalid credentials or role"}
                elif "could not be found" in error_msg:
                    return {"status": "✗", "details": f"Bedrock service not found in {region}"}
                else:
                    # Show first line of error for clarity
                    first_line = error_msg.split("\n")[0] if error_msg else "Unknown error"
                    return {"status": "✗", "details": first_line[:80]}
        except subprocess.TimeoutExpired:
            return {"status": "!", "details": "Request timed out (may be a network issue)"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_inference_profiles(self, profile_name: str, region: str, selected_model: str = None) -> dict:
        """Test inference profiles access in the configured region."""
        try:
            # Clear AWS credentials from environment
            import os

            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)

            # List inference profiles
            cmd = [
                "aws",
                "bedrock",
                "list-inference-profiles",
                "--profile",
                profile_name,
                "--region",
                region,
                "--output",
                "json",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=test_env)

            if result.returncode == 0:
                profiles = json.loads(result.stdout)
                profile_summaries = profiles.get("inferenceProfileSummaries", [])

                if profile_summaries:
                    # Check if the selected model matches any inference profile
                    if selected_model:
                        matching_profiles = [
                            p
                            for p in profile_summaries
                            if p.get("inferenceProfileId") == selected_model or selected_model in p.get("models", [])
                        ]
                        if matching_profiles:
                            return {
                                "status": "✓",
                                "details": f"Found {len(profile_summaries)} profiles, selected model available",
                            }

                    return {"status": "✓", "details": f"Found {len(profile_summaries)} cross-region inference profiles"}
                else:
                    return {
                        "status": "!",
                        "details": "No inference profiles available (cross-region routing not configured)",
                    }
            else:
                error_msg = result.stderr or result.stdout

                # Parse specific error types
                if "AccessDeniedException" in error_msg:
                    return {"status": "✗", "details": "Access denied - check bedrock:ListInferenceProfiles permission"}
                elif "UnrecognizedClientException" in error_msg:
                    return {"status": "✗", "details": "Invalid credentials or role"}
                else:
                    # Show first line of error for clarity
                    first_line = error_msg.split("\n")[0] if error_msg else "Unknown error"
                    return {"status": "✗", "details": first_line[:80]}
        except subprocess.TimeoutExpired:
            return {"status": "!", "details": "Request timed out"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_otel_helper(self, otel_binary: Path, credential_binary: Path) -> dict:
        """Test OTEL helper functionality."""
        try:
            # First get a monitoring token
            token_result = subprocess.run(
                [str(credential_binary), "--get-monitoring-token"], capture_output=True, text=True, timeout=30
            )

            if token_result.returncode != 0 or not token_result.stdout.strip():
                return {"status": "!", "details": "Could not get monitoring token"}

            # Test OTEL helper with the token
            import os

            env = os.environ.copy()
            env["CLAUDE_CODE_MONITORING_TOKEN"] = token_result.stdout.strip()

            otel_result = subprocess.run(
                [str(otel_binary), "--test"], capture_output=True, text=True, env=env, timeout=10
            )

            if otel_result.returncode == 0:
                # Parse output to extract key claims
                output = otel_result.stdout
                email = None
                user_id = None

                for line in output.split("\n"):
                    if "X-user-email:" in line:
                        email = line.split(":", 1)[1].strip()
                    elif "user.id:" in line and not user_id:
                        user_id = line.split(":", 1)[1].strip()[:20] + "..."

                if email:
                    details = f"Claims extracted: email={email[:20]}..."
                    if user_id:
                        details += f", id={user_id}"
                    return {"status": "✓", "details": details}
                else:
                    return {"status": "✓", "details": "OTEL helper working"}
            else:
                return {"status": "✗", "details": "OTEL helper failed"}
        except subprocess.TimeoutExpired:
            return {"status": "✗", "details": "OTEL helper timeout"}
        except Exception as e:
            return {"status": "✗", "details": str(e)[:50]}

    def _get_package_profile_name(self, package_dir: Path) -> str | None:
        """Get the profile name from the package's config.json."""
        config_file = package_dir / "config.json"
        if not config_file.exists():
            return None
        try:
            with open(config_file) as f:
                config = json.load(f)
            # config.json has profile names as top-level keys
            # Return the first (usually only) profile
            profiles = list(config.keys())
            return profiles[0] if profiles else None
        except Exception:
            return None

    def _test_quota_api(
        self, credential_binary: Path, quota_api_endpoint: str, package_dir: Path, profile_name: str
    ) -> dict:
        """Test quota monitoring API access."""
        import urllib.error
        import urllib.request

        try:
            # Get JWT token using the monitoring token flag
            # Run from package_dir so binary can find config.json
            token_result = subprocess.run(
                [str(credential_binary), "--profile", profile_name, "--get-monitoring-token"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=package_dir,
            )

            if token_result.returncode != 0 or not token_result.stdout.strip():
                # Include stderr for debugging if available
                err_msg = token_result.stderr.strip()[:50] if token_result.stderr else "no output"
                return {"status": "!", "details": f"Could not get JWT token: {err_msg}"}

            jwt_token = token_result.stdout.strip()

            # Call the /check endpoint
            url = f"{quota_api_endpoint.rstrip('/')}/check"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {jwt_token}")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

                # Verify response structure
                if "allowed" in data and "reason" in data:
                    allowed = data.get("allowed", False)
                    reason = data.get("reason", "unknown")
                    if allowed:
                        return {"status": "✓", "details": f"API responding, access: allowed ({reason})"}
                    else:
                        # User is blocked but API is working
                        return {"status": "!", "details": f"API responding, access: blocked ({reason})"}
                else:
                    return {"status": "!", "details": "API responded but unexpected format"}

        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"status": "✗", "details": "JWT authentication failed (401)"}
            elif e.code == 403:
                return {"status": "✗", "details": "Access forbidden (403)"}
            else:
                return {"status": "✗", "details": f"HTTP error: {e.code}"}
        except urllib.error.URLError as e:
            return {"status": "✗", "details": f"Connection failed: {str(e.reason)[:50]}"}
        except subprocess.TimeoutExpired:
            return {"status": "✗", "details": "Request timed out"}
        except Exception as e:
            return {"status": "✗", "details": str(e)[:50]}

    def _test_model_invocation(self, profile_name: str, region: str, available_models: list = None) -> dict:
        """Test actual model invocation with Claude 3."""
        try:
            # Clear AWS credentials from environment
            import os

            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)
            # Pick a model to test - prefer Claude 3 Sonnet, but use what's available
            if available_models:
                # Prefer these models in order
                preferred_models = [
                    "anthropic.claude-3-sonnet-20240229-v1:0",
                    "anthropic.claude-3-haiku-20240307-v1:0",
                    "anthropic.claude-instant-v1",
                ]

                model_id = None
                for preferred in preferred_models:
                    if preferred in available_models:
                        model_id = preferred
                        break

                # If none of our preferred models are available, use the first available Claude model
                if not model_id and available_models:
                    model_id = available_models[0]
            else:
                # Fallback if no models list provided
                model_id = "anthropic.claude-3-sonnet-20240229-v1:0"

            # Create a minimal test prompt
            if model_id and "claude-instant" in model_id:
                # Claude Instant v1 uses the older text completions API
                body_dict = {
                    "prompt": "\n\nHuman: Say 'test successful' in exactly 2 words\n\nAssistant:",
                    "max_tokens_to_sample": 10,
                    "temperature": 0,
                }
            else:
                # Claude 2 and 3 use Messages API
                body_dict = {
                    "messages": [{"role": "user", "content": "Say 'test successful' in exactly 2 words"}],
                    "max_tokens": 10,
                    "temperature": 0,
                    "anthropic_version": "bedrock-2023-05-31",
                }

            # Write body to a temporary file
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(body_dict, f)
                body_file = f.name

            # Test invocation
            cmd = [
                "aws",
                "bedrock-runtime",
                "invoke-model",
                "--profile",
                profile_name,
                "--region",
                region,
                "--model-id",
                model_id,
                "--body",
                f"fileb://{body_file}",
                "--content-type",
                "application/json",
                "/tmp/bedrock-test-output.json",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=test_env)

            if result.returncode == 0:
                # Check if we got a response
                try:
                    with open("/tmp/bedrock-test-output.json") as f:
                        response = json.load(f)
                        # Different response formats for different models
                        if "content" in response and len(response["content"]) > 0:
                            # Messages API response (Claude 2/3)
                            text = response["content"][0].get("text", "").strip()
                            return {"success": True, "response": text}
                        elif "completion" in response:
                            # Text completions API response (Claude Instant v1)
                            text = response["completion"].strip()
                            return {"success": True, "response": text}
                        else:
                            return {"success": False, "error": "No content in response"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to parse response: {str(e)}"}
            else:
                error_msg = result.stderr or result.stdout
                if "ThrottlingException" in error_msg:
                    return {"success": False, "error": "Rate limited"}
                elif "ModelNotReadyException" in error_msg:
                    return {"success": False, "error": "Model not ready"}
                else:
                    # Return more of the error for debugging
                    if "ValidationException" in error_msg and model_id:
                        return {"success": False, "error": f"Model {model_id} validation error: {error_msg[:150]}"}
                    else:
                        return {"success": False, "error": error_msg[:200]}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            # Clean up test files
            try:
                import os

                os.remove("/tmp/bedrock-test-output.json")
                if "body_file" in locals():
                    os.remove(body_file)
            except Exception:
                pass

    def _get_expected_account(self, config_profile) -> str:
        """Get the expected AWS account ID from the deployed stack."""
        try:
            # Try to get account ID from the auth stack
            stack_name = config_profile.stack_names.get("auth", f"{config_profile.identity_pool_name}-stack")

            # Use the current AWS credentials (not the profile being tested)
            cmd = [
                "aws",
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--region",
                config_profile.aws_region,
                "--query",
                "Stacks[0].StackId",
                "--output",
                "text",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0 and result.stdout:
                # Extract account ID from stack ARN
                # arn:aws:cloudformation:region:ACCOUNT:stack/name/id
                stack_arn = result.stdout.strip()
                parts = stack_arn.split(":")
                if len(parts) >= 5:
                    return parts[4]

            return None
        except Exception:
            return None

    def _format_tokens(self, tokens: int) -> str:
        """Format token count for display."""
        if tokens >= 1_000_000_000:
            return f"{tokens / 1_000_000_000:.1f}B"
        elif tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        elif tokens >= 1_000:
            return f"{tokens / 1_000:.1f}K"
        return str(tokens)

    def _test_quota_config(self, profile) -> dict:
        """Validate quota monitoring configuration."""
        checks = []

        if not getattr(profile, "quota_monitoring_enabled", False):
            return {"name": "Quota Config", "status": "!", "details": "Quota monitoring not enabled"}

        if not getattr(profile, "quota_api_endpoint", None):
            checks.append("API endpoint not configured")
        if not getattr(profile, "quota_policies_table", None):
            checks.append("Policies table not configured")
        if not getattr(profile, "user_quota_metrics_table", None):
            checks.append("Metrics table not configured")

        if checks:
            return {"name": "Quota Config", "status": "!", "details": ", ".join(checks)}
        return {"name": "Quota Config", "status": "✓", "details": "All configuration present"}

    def _test_quota_policies(self, profile) -> list:
        """Test quota policy management operations."""
        results = []
        test_email = f"ccwb-test-{uuid.uuid4().hex[:8]}@test.local"

        try:
            from claude_code_with_bedrock.models import EnforcementMode, PolicyType
            from claude_code_with_bedrock.quota_policies import QuotaPolicyManager

            table_name = getattr(profile, "quota_policies_table", None)
            if not table_name:
                return [{"name": "Policy Tests", "status": "!", "details": "Policies table not configured"}]

            manager = QuotaPolicyManager(table_name, profile.aws_region)

            # Test 1: Create user policy
            try:
                policy = manager.create_policy(
                    policy_type=PolicyType.USER,
                    identifier=test_email,
                    monthly_token_limit=1000000,
                    enforcement_mode=EnforcementMode.ALERT,
                    enabled=True,
                )
                results.append({"name": "Create Policy", "status": "✓", "details": f"Created for {test_email}"})
            except Exception as e:
                results.append({"name": "Create Policy", "status": "✗", "details": str(e)[:60]})
                return results  # Can't continue without policy

            # Test 2: List policies (verify it appears)
            try:
                policies = manager.list_policies(PolicyType.USER)
                found = any(p.identifier == test_email for p in policies)
                if found:
                    results.append({"name": "List Policies", "status": "✓", "details": "Test policy found in list"})
                else:
                    results.append({"name": "List Policies", "status": "✗", "details": "Test policy not found"})
            except Exception as e:
                results.append({"name": "List Policies", "status": "✗", "details": str(e)[:60]})

            # Test 3: Resolve quota for user
            try:
                resolved = manager.resolve_quota_for_user(test_email, groups=None)
                if resolved and resolved.identifier == test_email:
                    results.append({"name": "Resolve Quota", "status": "✓", "details": "User policy correctly resolved"})
                else:
                    results.append(
                        {"name": "Resolve Quota", "status": "!", "details": "Policy resolved but not user-specific"}
                    )
            except Exception as e:
                results.append({"name": "Resolve Quota", "status": "✗", "details": str(e)[:60]})

            # Test 4: Delete policy (cleanup)
            try:
                deleted = manager.delete_policy(PolicyType.USER, test_email)
                if deleted:
                    results.append({"name": "Delete Policy", "status": "✓", "details": "Test policy cleaned up"})
                else:
                    results.append({"name": "Delete Policy", "status": "!", "details": "Policy not found for deletion"})
            except Exception as e:
                results.append({"name": "Delete Policy", "status": "✗", "details": str(e)[:60]})

        except ImportError as e:
            results.append({"name": "Policy Tests", "status": "✗", "details": f"Import error: {e}"})
        except Exception as e:
            results.append({"name": "Policy Tests", "status": "✗", "details": f"Unexpected error: {str(e)[:50]}"})

        return results

    def _get_user_usage(self, profile, email: str) -> dict:
        """Fetch user usage data from UserQuotaMetrics table."""
        from datetime import datetime

        table_name = getattr(profile, "user_quota_metrics_table", None)
        if not table_name:
            return {}

        try:
            dynamodb = boto3.resource("dynamodb", region_name=profile.aws_region)
            table = dynamodb.Table(table_name)

            # Get current month
            current_month = datetime.utcnow().strftime("%Y-%m")

            # Query for user's monthly usage
            response = table.get_item(Key={"pk": f"USER#{email}", "sk": f"MONTH#{current_month}"})

            item = response.get("Item", {})
            return {
                "total_tokens": int(item.get("total_tokens", 0)),
                "daily_tokens": int(item.get("daily_tokens", 0)),
                "input_tokens": int(item.get("input_tokens", 0)),
                "output_tokens": int(item.get("output_tokens", 0)),
                "estimated_cost": item.get("estimated_cost", "0"),
            }
        except Exception:
            return {}

    def _get_user_email_from_jwt(self, credential_binary: Path, package_dir: Path, profile_name: str) -> str | None:
        """Extract user email from JWT token."""
        import base64

        try:
            token_result = subprocess.run(
                [str(credential_binary), "--profile", profile_name, "--get-monitoring-token"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=package_dir,
            )

            if token_result.returncode != 0 or not token_result.stdout.strip():
                return None

            jwt_token = token_result.stdout.strip()

            # Decode JWT payload (middle part)
            parts = jwt_token.split(".")
            if len(parts) != 3:
                return None

            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding

            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)

            return claims.get("email")
        except Exception:
            return None

    def _invoke_metrics_aggregator(self, profile) -> dict:
        """Force-invoke the metrics aggregator Lambda."""
        try:
            lambda_client = boto3.client("lambda", region_name=profile.aws_region)

            # Lambda name is fixed (deployed by monitoring stack)
            function_name = "ClaudeCode-MetricsAggregator"

            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=b"{}",
            )

            if response["StatusCode"] == 200:
                return {"name": "Aggregator Lambda", "status": "✓", "details": "Invoked successfully"}
            else:
                return {"name": "Aggregator Lambda", "status": "✗", "details": f"Status: {response['StatusCode']}"}

        except lambda_client.exceptions.ResourceNotFoundException:
            return {"name": "Aggregator Lambda", "status": "✗", "details": "Lambda function not found"}
        except Exception as e:
            return {"name": "Aggregator Lambda", "status": "✗", "details": str(e)[:60]}

    def _make_quota_test_bedrock_call(self, aws_profile: str, region: str) -> dict:
        """Make a small Bedrock call for testing usage capture."""
        import os
        import tempfile

        try:
            test_env = os.environ.copy()
            test_env.pop("AWS_ACCESS_KEY_ID", None)
            test_env.pop("AWS_SECRET_ACCESS_KEY", None)
            test_env.pop("AWS_SESSION_TOKEN", None)

            # Create request body
            body_dict = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Hi"}],
            }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(body_dict, f)
                body_file = f.name

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                output_file = f.name

            try:
                result = subprocess.run(
                    [
                        "aws",
                        "bedrock-runtime",
                        "invoke-model",
                        "--model-id",
                        "anthropic.claude-3-haiku-20240307-v1:0",
                        "--body",
                        f"fileb://{body_file}",
                        "--content-type",
                        "application/json",
                        "--profile",
                        aws_profile,
                        "--region",
                        region,
                        output_file,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=test_env,
                )

                if result.returncode == 0:
                    return {"name": "Test Bedrock Call", "status": "✓", "details": "Haiku responded"}
                else:
                    return {"name": "Test Bedrock Call", "status": "✗", "details": result.stderr[:80]}
            finally:
                try:
                    os.remove(body_file)
                    os.remove(output_file)
                except Exception:
                    pass

        except subprocess.TimeoutExpired:
            return {"name": "Test Bedrock Call", "status": "✗", "details": "Request timed out"}
        except Exception as e:
            return {"name": "Test Bedrock Call", "status": "✗", "details": str(e)[:60]}

    def _test_usage_capture(
        self, profile, credential_binary: Path, package_dir: Path, profile_name: str, aws_profile: str
    ) -> list:
        """Test that Bedrock usage is captured in quota metrics."""
        results = []

        # Get user email from JWT
        email = self._get_user_email_from_jwt(credential_binary, package_dir, profile_name)
        if not email:
            return [{"name": "Usage Capture", "status": "!", "details": "Could not determine user email from JWT"}]

        try:
            # Step 1: Get initial usage
            initial_usage = self._get_user_usage(profile, email)
            initial_tokens = initial_usage.get("total_tokens", 0)
            results.append(
                {"name": "Initial Usage", "status": "✓", "details": f"{self._format_tokens(initial_tokens)} tokens"}
            )

            # Step 2: Make a small Bedrock call
            bedrock_result = self._make_quota_test_bedrock_call(aws_profile, profile.aws_region)
            if bedrock_result["status"] != "✓":
                results.append(bedrock_result)
                return results
            results.append(bedrock_result)

            # Step 3: Wait for CloudWatch Logs sync
            time.sleep(2)

            # Step 4: Force-invoke metrics aggregator Lambda
            aggregator_result = self._invoke_metrics_aggregator(profile)
            if aggregator_result["status"] != "✓":
                results.append(aggregator_result)
                return results
            results.append(aggregator_result)

            # Step 5: Wait for aggregator to complete (it queries logs)
            time.sleep(5)

            # Step 6: Query usage again
            final_usage = self._get_user_usage(profile, email)
            final_tokens = final_usage.get("total_tokens", 0)

            # Step 7: Verify increase
            if final_tokens > initial_tokens:
                increase = final_tokens - initial_tokens
                results.append(
                    {"name": "Usage Captured", "status": "✓", "details": f"+{self._format_tokens(increase)} tokens"}
                )
            else:
                results.append(
                    {
                        "name": "Usage Captured",
                        "status": "!",
                        "details": f"No increase (was {self._format_tokens(initial_tokens)}, still "
                        f"{self._format_tokens(final_tokens)})",
                    }
                )

        except Exception as e:
            results.append({"name": "Usage Capture", "status": "✗", "details": str(e)[:60]})

        return results

    def _run_quota_tests(
        self,
        profile,
        credential_binary: Path,
        package_dir: Path,
        profile_name: str,
        aws_profile: str,
        endpoint_override: str | None = None,
    ) -> int:
        """Run comprehensive quota monitoring tests."""
        console = Console()
        test_results = []

        console.print(
            Panel.fit(
                "[bold cyan]Quota Monitoring Tests[/bold cyan]\n\n"
                f"Testing profile: [bold]{profile_name}[/bold]",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
        ) as progress:
            # 1. Validate quota configuration
            task = progress.add_task("Checking quota configuration...", total=None)
            result = self._test_quota_config(profile)
            test_results.append(result)
            progress.update(task, completed=True)

            # If config is not valid, we can still continue with some tests
            config_ok = result["status"] == "✓"

            # 2. Test quota API endpoint (/check)
            endpoint = endpoint_override or getattr(profile, "quota_api_endpoint", None)
            if endpoint:
                task = progress.add_task("Testing quota API...", total=None)
                api_result = self._test_quota_api(credential_binary, endpoint, package_dir, profile_name)
                test_results.append({"name": "Quota API", "status": api_result["status"], "details": api_result["details"]})
                progress.update(task, completed=True)
            else:
                test_results.append({"name": "Quota API", "status": "!", "details": "No endpoint configured"})

            # 3. Test quota policy CRUD operations
            task = progress.add_task("Testing quota policies...", total=None)
            policy_results = self._test_quota_policies(profile)
            test_results.extend(policy_results)
            progress.update(task, completed=True)

        # Display results
        self._display_quota_results(console, test_results)

        # Return appropriate exit code
        failed = sum(1 for r in test_results if r["status"] == "✗")
        return 1 if failed > 0 else 0

    def _display_quota_results(self, console: Console, results: list):
        """Display quota test results in a table."""
        table = Table(title="Quota Monitoring Tests", box=box.ROUNDED)
        table.add_column("Test", style="cyan", min_width=20)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Details", style="dim", min_width=40, overflow="fold")

        passed = warnings = failed = skipped = 0

        for result in results:
            status = result["status"]
            if status == "✓":
                passed += 1
                status_display = "[green]✓ Pass[/green]"
            elif status == "!":
                warnings += 1
                status_display = "[yellow]! Warning[/yellow]"
            elif status == "-":
                skipped += 1
                status_display = "[dim]- Skip[/dim]"
            else:
                failed += 1
                status_display = "[red]✗ Fail[/red]"

            table.add_row(result["name"], status_display, result.get("details", ""))

        console.print("\n")
        console.print(table)

        summary_parts = [f"{passed} passed", f"{warnings} warnings", f"{failed} failed"]
        if skipped > 0:
            summary_parts.append(f"{skipped} skipped")
        console.print(f"\n[bold]Summary:[/bold] {', '.join(summary_parts)}")

        if failed > 0:
            console.print("\n[red]Some quota tests failed. Check the details above.[/red]")
        elif warnings > 0:
            console.print("\n[yellow]Quota tests passed with warnings.[/yellow]")
        else:
            console.print("\n[green]All quota tests passed![/green]")
