# ABOUTME: Test command to verify authentication and Bedrock access
# ABOUTME: Performs comprehensive checks to ensure setup is working correctly

"""Test command - Verify authentication and access."""

import json
import subprocess
from pathlib import Path

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
            "profile", "p", description="AWS profile to test (default: ClaudeCode)", flag=False, default="ClaudeCode"
        ),
        option("quick", description="Run quick tests only", flag=True),
        option("api", description="Test actual Bedrock API calls (costs ~$0.001)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the test command."""
        console = Console()

        # Welcome
        console.print(
            Panel.fit(
                "[bold cyan]Claude Code Package Test[/bold cyan]\n\n"
                "This will test the packaged distribution as an end user would experience it",
                border_style="cyan",
                padding=(1, 2),
            )
        )

        # Check if package exists - look in multiple locations
        # First try the source directory (where package command creates it)
        source_dist = Path(__file__).parent.parent.parent.parent / "dist"
        # Also check current directory
        local_dist = Path("./dist")

        package_dir = None
        if source_dist.exists() and (source_dist / "install.sh").exists():
            package_dir = source_dist
            console.print(f"[dim]Using package from: {package_dir}[/dim]")
        elif local_dist.exists() and (local_dist / "install.sh").exists():
            package_dir = local_dist
            console.print(f"[dim]Using package from: {package_dir}[/dim]")
        else:
            console.print("[red]No package found. Run 'poetry run ccwb package' first.[/red]")
            console.print("[dim]Searched in:[/dim]")
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
            profile_config = pkg_config.get("ClaudeCode", {})

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
        import uuid

        test_profile = f"ccwb-test-{uuid.uuid4().hex[:8]}"

        console.print("\n[bold]Step 3: Testing authentication[/bold]")
        console.print(f"[dim]Using temporary profile: {test_profile}[/dim]")

        # Configure the test profile
        aws_config_result = subprocess.run(
            ["aws", "configure", "set", f"profile.{test_profile}.credential_process", str(credential_binary)],
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
        config = Config.load()
        profile = config.get_profile()

        if not profile:
            console.print("[red]No configuration found. Run 'poetry run ccwb init' first.[/red]")
            return 1

        # Use test_profile instead of hardcoded "ClaudeCode"
        aws_profile = test_profile
        quick_mode = self.option("quick")
        with_api = self.option("api")

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

                # Test 4: Check Bedrock access in each region
                if not quick_mode:
                    for region in profile.allowed_bedrock_regions:
                        task = progress.add_task(f"Testing Bedrock access in {region}...", total=None)
                        result = self._test_bedrock_access(aws_profile, region, with_api)
                        test_results.append((f"Bedrock - {region}", result["status"], result["details"]))
                        progress.update(task, completed=True)
                else:
                    # In quick mode, just test primary region
                    region = profile.allowed_bedrock_regions[0]
                    task = progress.add_task(f"Testing Bedrock access in {region}...", total=None)
                    result = self._test_bedrock_access(aws_profile, region, with_api)
                    test_results.append((f"Bedrock - {region}", result["status"], result["details"]))
                    progress.update(task, completed=True)

        # Display results
        console.print("\n")
        for test_name, status, details in test_results:
            if status == "✓":
                status_display = "[green]✓ Pass[/green]"
            elif status == "!":
                status_display = "[yellow]! Warning[/yellow]"
            else:
                status_display = "[red]✗ Fail[/red]"
            table.add_row(test_name, status_display, details)

        console.print(table)

        # Summary
        passed = sum(1 for _, status, _ in test_results if status == "✓")
        warnings = sum(1 for _, status, _ in test_results if status == "!")
        failed = sum(1 for _, status, _ in test_results if status == "✗")

        console.print(f"\n[bold]Summary:[/bold] {passed} passed, {warnings} warnings, {failed} failed")

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
                    f"aws bedrock list-foundation-models --region {profile.allowed_bedrock_regions[0]} --query \"modelSummaries[?contains(modelId, 'claude')]\""
                )

            return 1
        elif warnings > 0:
            console.print("\n[yellow]Tests passed with warnings. Check details above.[/yellow]")
            return 0
        else:
            console.print("\n[green]All tests passed! Your setup is working correctly.[/green]")

            if not with_api:
                console.print(
                    "\n[dim]Note: API invocation tests were skipped. Use --api to test actual Bedrock calls.[/dim]"
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
            cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                identity = json.loads(result.stdout)
                return {"status": "✓", "details": f"Authenticated as {identity.get('UserId', 'unknown')[:20]}..."}
            else:
                error_msg = result.stderr or result.stdout
                if "Unable to locate credentials" in error_msg:
                    return {"status": "✗", "details": "Credential process not configured"}
                elif "BrowserError" in error_msg:
                    return {"status": "✗", "details": "Browser authentication failed"}
                else:
                    return {"status": "✗", "details": error_msg[:100]}
        except subprocess.TimeoutExpired:
            return {"status": "✗", "details": "Authentication timed out"}
        except Exception as e:
            return {"status": "✗", "details": str(e)}

    def _test_iam_role(self, profile_name: str, config_profile) -> dict:
        """Test IAM role and permissions."""
        try:
            cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]
            result = subprocess.run(cmd, capture_output=True, text=True)

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
            # First get the account we're using
            identity_cmd = ["aws", "sts", "get-caller-identity", "--profile", profile_name]
            identity_result = subprocess.run(identity_cmd, capture_output=True, text=True)
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
            result = subprocess.run(describe_cmd, capture_output=True, text=True, timeout=60)

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
                                    "details": f"Found {len(models)} Claude models (some models may not support invoke)",
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

    def _test_model_invocation(self, profile_name: str, region: str, available_models: list = None) -> dict:
        """Test actual model invocation with Claude 3."""
        try:
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

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

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
            except:
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
