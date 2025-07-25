# ABOUTME: Interactive setup wizard for first-time users
# ABOUTME: Guides through complete Claude Code with Bedrock deployment

"""Init command - Interactive setup wizard."""

from cleo.commands.command import Command
from cleo.helpers import option, argument
import boto3
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Dict, Any, List
import questionary
from questionary import Choice
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from claude_code_with_bedrock.config import Config, Profile
from claude_code_with_bedrock.cli.utils.validators import validate_okta_domain, validate_aws_region, validate_oidc_provider_domain
from claude_code_with_bedrock.cli.utils.aws import check_bedrock_access, get_current_region, get_vpcs, get_subnets
from claude_code_with_bedrock.cli.utils.progress import WizardProgress


class InitCommand(Command):
    name = "init"
    description = "Interactive setup wizard for first-time deployment"
    
    options = [
        option(
            "profile",
            "p",
            description="Configuration profile name",
            flag=False,
            default="default"
        )
    ]
    
    def handle(self) -> int:
        """Execute the init command."""
        console = Console()
        progress = WizardProgress("init")
        
        try:
            return self._handle_with_progress(console, progress)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Setup interrupted. Your progress has been saved.[/yellow]")
            console.print("Run [bold cyan]poetry run ccwb init[/bold cyan] to resume where you left off.")
            return 1
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            return 1
    
    def _handle_with_progress(self, console: Console, progress: WizardProgress) -> int:
        """Handle the command with progress tracking."""
        
        # Check for existing deployment first
        existing_config = self._check_existing_deployment()
        if existing_config:
            # Check if we found stacks or just configuration
            stacks_exist = existing_config.get("_stacks_found", True)
            
            console.print("\n[green]Found existing configuration![/green]")
            self._show_existing_deployment(existing_config)
            
            if not stacks_exist:
                console.print("\n[yellow]Note: Stacks are not deployed in the current AWS account[/yellow]")
            
            action = questionary.select(
                "\nWhat would you like to do?",
                choices=[
                    "View current configuration",
                    "Update configuration", 
                    "Start fresh"
                ]
            ).ask()
            
            if action is None:  # User cancelled (Ctrl+C)
                console.print("\n[yellow]Setup cancelled.[/yellow]")
                return 1
            
            if action == "View current configuration":
                self._review_configuration(existing_config)
                return 0
            elif action == "Update configuration":
                config = self._gather_configuration(progress, existing_config)
                if not config:
                    return 1
                if not self._review_configuration(config):
                    return 1
                self._save_configuration(config)
                console.print("\n[green]✓ Configuration updated successfully![/green]")
                console.print("\nNext steps:")
                console.print("• Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]")
                console.print("• Create package: [cyan]poetry run ccwb package[/cyan]")
                console.print("• Test authentication: [cyan]poetry run ccwb test[/cyan]")
                return 0
            elif action == "Start fresh":
                confirm = questionary.confirm("This will replace your existing configuration. Continue?", default=False).ask()
                if confirm is None:  # User cancelled
                    console.print("\n[yellow]Setup cancelled.[/yellow]")
                    return 1
                if not confirm:
                    return 0
                # Clear saved progress to start fresh
                progress.clear()
                # Continue to normal flow
        
        # Check for saved progress
        elif progress.has_saved_progress():
            console.print("\n[yellow]Found saved progress from previous session:[/yellow]")
            console.print(progress.get_summary())
            
            resume = questionary.confirm(
                "\nWould you like to resume where you left off?",
                default=True
            ).ask()
            
            if not resume:
                progress.clear()
        
        # Welcome message
        welcome = Panel.fit(
            "[bold cyan]Welcome to Claude Code with Bedrock Setup![/bold cyan]\n\n"
            "This wizard will help you deploy Claude Code using Amazon Bedrock with:\n"
            "  • Secure authentication via your identity provider\n"
            "  • Usage monitoring and dashboards\n"
            "  • Cost tracking and controls",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(welcome)
        
        # Prerequisites check
        if not self._check_prerequisites():
            return 1
            
        # Gather configuration
        config = self._gather_configuration(progress)
        if not config:
            return 1
            
        # Review and confirm
        if not self._review_configuration(config):
            return 1
            
        # Save configuration
        self._save_configuration(config)
        progress.clear()  # Clear progress since we're done
        
        # Success message
        success_panel = Panel.fit(
            "[bold green]✓ Configuration complete![/bold green]\n\n"
            "Your configuration has been saved.\n\n"
            "Next steps:\n"
            "1. Deploy infrastructure: [cyan]poetry run ccwb deploy[/cyan]\n"
            "2. Create package: [cyan]poetry run ccwb package[/cyan]\n"
            "3. Test authentication: [cyan]poetry run ccwb test[/cyan]",
            border_style="green",
            padding=(1, 2)
        )
        console.print("\n", success_panel)
        
        return 0
    
    def _check_prerequisites(self) -> bool:
        """Check system prerequisites."""
        console = Console()
        
        console.print("[bold cyan]Prerequisites Check:[/bold cyan]")
        
        checks = {
            "AWS CLI installed": self._check_aws_cli(),
            "AWS credentials configured": self._check_aws_credentials(),
            "Python 3.8+ available": self._check_python_version(),
        }
        
        # Check current region and Bedrock access
        region = get_current_region()
        if region:
            checks[f"Current region: {region}"] = True
            checks[f"Bedrock access enabled in {region}"] = check_bedrock_access(region)
        
        # Display results
        all_passed = True
        for check, passed in checks.items():
            if passed:
                console.print(f"  [green]✓[/green] {check}")
            else:
                console.print(f"  [red]✗[/red] {check}")
                all_passed = False
                
        if not all_passed:
            console.print("\n[red]Prerequisites not met. Please fix the issues above.[/red]")
            return False
            
        console.print("")
        return True
    
    def _gather_configuration(self, progress: WizardProgress, existing_config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Gather configuration from user."""
        console = Console()
        # Use existing config as base if provided, otherwise use saved progress
        if existing_config:
            config = existing_config.copy()
        else:
            config = progress.get_saved_data() or {}
        last_step = progress.get_last_step()
        
        # Skip completed steps only if we're not updating existing config
        if existing_config:
            # When updating existing config, don't skip any steps
            skip_okta = False
            skip_aws = False
            skip_monitoring = False
            skip_bedrock = False
        else:
            # Normal progress-based skipping for new installations
            skip_okta = last_step in ['okta_complete', 'aws_complete', 'monitoring_complete', 'bedrock_complete']
            skip_aws = last_step in ['aws_complete', 'monitoring_complete', 'bedrock_complete']
            skip_monitoring = last_step in ['monitoring_complete', 'bedrock_complete']
            skip_bedrock = last_step in ['bedrock_complete']
        
        # OIDC Provider Configuration
        if not skip_okta:
            console.print("\n[bold blue]Step 1: OIDC Provider Configuration[/bold blue]")
            console.print("─" * 30)
            
            provider_domain = questionary.text(
                "Enter your OIDC provider domain:",
                validate=lambda x: validate_oidc_provider_domain(x) or "Invalid provider domain format (e.g., company.okta.com)",
                instruction="(e.g., company.okta.com, company.auth0.com, login.microsoftonline.com/{tenant-id}/v2.0, or my-app.auth.us-east-1.amazoncognito.com)",
                default=config.get('okta', {}).get('domain', '')
            ).ask()
            
            if not provider_domain:
                return None
            
            # Strip https:// or http:// if provided
            provider_domain = provider_domain.replace('https://', '').replace('http://', '').strip('/')
                
            # Auto-detect provider type
            provider_type = None
            cognito_user_pool_id = None
            domain_lower = provider_domain.lower()
            
            if 'okta.com' in domain_lower:
                provider_type = 'okta'
            elif 'auth0.com' in domain_lower:
                provider_type = 'auth0'
            elif 'microsoftonline.com' in domain_lower or 'windows.net' in domain_lower:
                provider_type = 'azure'
            elif 'amazoncognito.com' in domain_lower or questionary.confirm(
                "Is this a custom domain for AWS Cognito User Pool?",
                default=False
            ).ask():
                provider_type = 'cognito'
                # For Cognito, we must ask for the User Pool ID
                # Cannot reliably extract from domain due to case sensitivity
                import re
                
                # Try to detect region from domain
                region_match = re.search(r'\.auth\.([^.]+)\.amazoncognito\.com', provider_domain)
                if not region_match:
                    region_match = re.search(r'\.([a-z]{2}-[a-z]+-\d+)\.', provider_domain)
                
                region_hint = f" for {region_match.group(1)}" if region_match else ""
                
                # Always ask for User Pool ID to ensure correct case
                cognito_user_pool_id = questionary.text(
                    f"Enter your Cognito User Pool ID{region_hint}:",
                    validate=lambda x: bool(re.match(r'^[\w-]+_[0-9a-zA-Z]+$', x)) or "Invalid User Pool ID format",
                    instruction="(case-sensitive)"
                ).ask()
                
                if not cognito_user_pool_id:
                    return None
            
            client_id = questionary.text(
                "Enter your OIDC Client ID:",
                validate=lambda x: bool(x and len(x) >= 10) or "Client ID must be at least 10 characters",
                default=config.get('okta', {}).get('client_id', '')
            ).ask()
            
            if not client_id:
                return None
            
            # Credential Storage Method
            console.print("\n[bold]Credential Storage Method[/bold]")
            console.print("Choose how to store AWS credentials locally:")
            console.print("  • [cyan]Keyring[/cyan]: Uses OS secure storage (may prompt for password)")
            console.print("  • [cyan]Session Files[/cyan]: Temporary files (deleted on logout)\n")
            
            credential_storage = questionary.select(
                "Select credential storage method:",
                choices=[
                    questionary.Choice("Keyring (Secure OS storage)", value="keyring"),
                    questionary.Choice("Session Files (Temporary storage)", value="session")
                ],
                default=config.get('credential_storage', 'session')
            ).ask()
            
            if not credential_storage:
                return None
                
            config["okta"] = {
                "domain": provider_domain,
                "client_id": client_id
            }
            config["credential_storage"] = credential_storage
            config["provider_type"] = provider_type
            if cognito_user_pool_id:
                config["cognito_user_pool_id"] = cognito_user_pool_id
            
            # Save progress
            progress.save_step('oidc_complete', config)
        
        # AWS Configuration
        if not skip_aws:
            console.print("\n[bold blue]Step 2: AWS Infrastructure Configuration[/bold blue]")
            console.print("─" * 40)
            
            current_region = get_current_region()
            
            # Get list of common AWS regions
            common_regions = [
                "us-east-1", "us-east-2", "us-west-1", "us-west-2",
                "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", 
                "ap-northeast-1", "ap-northeast-2", "ap-southeast-1", "ap-southeast-2",
                "ap-south-1", "ca-central-1", "sa-east-1"
            ]
            
            # Check for saved region
            saved_region = config.get('aws', {}).get('region', current_region)
            
            region = questionary.select(
                "Select AWS Region for infrastructure deployment (Cognito, IAM, monitoring):",
                choices=common_regions,
                default=saved_region if saved_region in common_regions else "us-east-1",
                instruction="(This is where your authentication and monitoring resources will be created)"
            ).ask()
            
            if not region:
                return None
                
            pool_name = questionary.text(
                "Identity Pool Name:",
                default=config.get('aws', {}).get('identity_pool_name', 'claude-code-auth'),
                validate=lambda x: bool(x and re.match(r'^[a-zA-Z0-9_-]+$', x)) or "Invalid pool name (alphanumeric, underscore, hyphen only)"
            ).ask()
            
            if not pool_name:
                return None
            
            config["aws"] = {
                "region": region,
                "identity_pool_name": pool_name,
                "stacks": {
                    "auth": f"{pool_name}-stack",
                    "monitoring": f"{pool_name}-monitoring",
                    "dashboard": f"{pool_name}-dashboard",
                    "analytics": f"{pool_name}-analytics"
                }
            }
            
            # Save progress
            progress.save_step('aws_complete', config)
        
        # Monitoring
        if not skip_monitoring:
            enable_monitoring = questionary.confirm(
                "Enable monitoring and usage dashboards?",
                default=config.get('monitoring', {}).get('enabled', True)
            ).ask()
            
            config["monitoring"] = {"enabled": enable_monitoring}
            
            # If monitoring is enabled, configure VPC
            if enable_monitoring:
                vpc_config = self._configure_vpc(config.get('aws', {}).get('region', get_current_region()))
                if not vpc_config:
                    return None
                config["monitoring"]["vpc_config"] = vpc_config
                
                # Optional: Configure HTTPS with custom domain
                console.print("\n[yellow]Optional: Configure HTTPS for secure telemetry[/yellow]")
                enable_https = questionary.confirm(
                    "Enable HTTPS with custom domain?",
                    default=False
                ).ask()
                
                if enable_https:
                    custom_domain = questionary.text(
                        "Enter custom domain name (e.g., telemetry.company.com):",
                        validate=lambda x: len(x) > 0 and '.' in x
                    ).ask()
                    
                    # Get Route53 hosted zones
                    hosted_zones = self._get_hosted_zones()
                    if hosted_zones:
                        zone_choices = [
                            f"{zone['Name'].rstrip('.')} ({zone['Id'].split('/')[-1]})"
                            for zone in hosted_zones
                        ]
                        selected_zone = questionary.select(
                            "Select Route53 hosted zone for the domain:",
                            choices=zone_choices
                        ).ask()
                        
                        # Extract zone ID
                        zone_id = selected_zone.split('(')[-1].rstrip(')')
                        
                        config["monitoring"]["custom_domain"] = custom_domain
                        config["monitoring"]["hosted_zone_id"] = zone_id
                        console.print(f"[green]✓[/green] HTTPS will be enabled with domain: {custom_domain}")
                    else:
                        console.print("[yellow]No Route53 hosted zones found. HTTPS requires a hosted zone.[/yellow]")
                        console.print("[dim]You can add these parameters manually during deployment.[/dim]")
                
                # Analytics configuration (only if monitoring is enabled)
                console.print("\n[bold]Analytics Pipeline[/bold]")
                console.print("The analytics pipeline enables advanced user metrics and reporting through AWS Athena.")
                console.print("This allows you to track user-specific token usage without hard-coding user IDs.")
                
                enable_analytics = questionary.confirm(
                    "Enable analytics pipeline (Kinesis Firehose + Athena)?",
                    default=config.get('analytics', {}).get('enabled', True)
                ).ask()
                
                config["analytics"] = {"enabled": enable_analytics}
                
                if enable_analytics:
                    console.print("[green]✓[/green] Analytics pipeline will be deployed with your monitoring stack")
            
            # Save progress
            progress.save_step('monitoring_complete', config)
        
        # Bedrock regions - get available regions
        if not skip_bedrock:
            console.print("\n[bold blue]Step 3: Bedrock Access Configuration[/bold blue]")
            console.print("─" * 40)
            
            # Region names for better UX
            region_names = {
                "us-east-1": "US East (N. Virginia)",
                "us-east-2": "US East (Ohio)",
                "us-west-2": "US West (Oregon)",
                "eu-west-1": "Europe (Ireland)",
                "eu-west-3": "Europe (Paris)",
                "eu-central-1": "Europe (Frankfurt)",
                "ap-northeast-1": "Asia Pacific (Tokyo)",
                "ap-southeast-1": "Asia Pacific (Singapore)",
                "ap-southeast-2": "Asia Pacific (Sydney)",
                "ap-south-1": "Asia Pacific (Mumbai)",
                "ca-central-1": "Canada (Central)",
            }
            
            available_regions = self._get_bedrock_regions()
            
            # Get saved selections or default to current region
            saved_bedrock_regions = config.get('aws', {}).get('allowed_bedrock_regions', [])
            region = config.get('aws', {}).get('region', get_current_region())
            
            # Pre-select saved regions or current region
            default_selections = saved_bedrock_regions if saved_bedrock_regions else ([region] if region in available_regions else [])
            
            bedrock_regions = questionary.checkbox(
                "Select AWS regions where users can access Bedrock models:",
                choices=[
                    questionary.Choice(
                        title=f"{r} - {region_names.get(r, r)}", 
                        value=r, 
                        checked=(r in default_selections)
                    )
                    for r in available_regions
                ],
                instruction="(Users will be able to use Claude in these regions. Use space to select/deselect, Enter to confirm)"
            ).ask()
            
            if bedrock_regions is None:  # User cancelled
                return None
            
            if not bedrock_regions:
                bedrock_regions = [region]
                
            config["aws"]["allowed_bedrock_regions"] = bedrock_regions
            
            # Save progress
            progress.save_step('bedrock_complete', config)
        
        return config
    
    def _review_configuration(self, config: Dict[str, Any]) -> bool:
        """Review configuration with user."""
        console = Console()
        
        console.print("\n[bold blue]Step 4: Review Configuration[/bold blue]")
        console.print("─" * 30)
        
        # Create a nice table using Rich
        table = Table(
            title="Configuration Summary",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("Setting", style="white", no_wrap=True)
        table.add_column("Value", style="green")
        
        table.add_row("OIDC Provider", config["okta"]["domain"])
        table.add_row("OIDC Client ID", config["okta"]["client_id"][:20] + "..." if len(config["okta"]["client_id"]) > 20 else config["okta"]["client_id"])
        table.add_row("Credential Storage", "Keyring (OS secure storage)" if config.get("credential_storage") == "keyring" else "Session Files (temporary)")
        table.add_row("Infrastructure Region", f"{config['aws']['region']} (Cognito, IAM, Monitoring)")
        table.add_row("Identity Pool", config["aws"]["identity_pool_name"])
        table.add_row("Monitoring", "✓ Enabled" if config["monitoring"]["enabled"] else "✗ Disabled")
        if config.get("monitoring", {}).get("enabled"):
            table.add_row("Analytics Pipeline", "✓ Enabled" if config.get("analytics", {}).get("enabled", True) else "✗ Disabled")
        
        # Show VPC config if monitoring is enabled
        if config.get("monitoring", {}).get("enabled"):
            vpc_config = config.get("monitoring", {}).get("vpc_config", {})
            if vpc_config.get("create_vpc"):
                table.add_row("Monitoring VPC", "New VPC will be created")
            else:
                vpc_info = f"Existing: {vpc_config.get('vpc_id', 'Unknown')}"
                if vpc_config.get('subnet_ids'):
                    vpc_info += f"\n{len(vpc_config['subnet_ids'])} subnets selected"
                table.add_row("Monitoring VPC", vpc_info)
        
        table.add_row("Bedrock Access Regions", "\n".join(config["aws"]["allowed_bedrock_regions"]))
        
        console.print(table)
        
        # Show what will be created
        console.print("\n[bold yellow]Resources to be created:[/bold yellow]")
        console.print("• Cognito Identity Pool for authentication")
        console.print("• IAM roles and policies for Bedrock access")
        if config["monitoring"]["enabled"]:
            console.print("• CloudWatch dashboards for usage monitoring")
            console.print("• OpenTelemetry collector for metrics")
        
        return True
    
    def _deploy(self, config: Dict[str, Any]) -> int:
        """Deploy the infrastructure."""
        console = Console()
        
        # Save configuration first
        self._save_configuration(config)
        
        # Create a progress display
        console.print("\n[bold]Deploying infrastructure...[/bold]")
        
        # Deploy authentication stack
        auth_success = False
        with console.status("[yellow]Deploying authentication stack...[/yellow]") as status:
            try:
                # Get the parameters file path
                params_file = Path(__file__).parent.parent.parent.parent.parent.parent / "deployment" / "infrastructure" / "parameters.json"
                
                # Update parameters with our configuration
                self._update_parameters_file(params_file, config)
                
                # Deploy the stack
                stack_name = config["aws"]["stacks"]["auth"]
                template_file = Path(__file__).parent.parent.parent.parent.parent.parent / "deployment" / "infrastructure" / "cognito-identity-pool.yaml"
                
                if self._deploy_stack(stack_name, template_file, params_file, config["aws"]["region"]):
                    console.print("  [green]✓[/green] Authentication stack deployed")
                    auth_success = True
                else:
                    console.print("  [red]✗[/red] Authentication stack deployment failed")
                    return 1
            except Exception as e:
                console.print(f"  [red]✗[/red] Authentication stack deployment failed: {e}")
                return 1
        
        # Deploy monitoring stack if enabled
        if config["monitoring"]["enabled"]:
            with console.status("[yellow]Deploying monitoring stack...[/yellow]") as status:
                try:
                    # Deploy OTel collector
                    collector_stack = config["aws"]["stacks"]["monitoring"]
                    collector_template = Path(__file__).parent.parent.parent.parent.parent.parent / "deployment" / "infrastructure" / "otel-collector.yaml"
                    
                    if self._deploy_stack(collector_stack, collector_template, params_file, config["aws"]["region"]):
                        console.print("  [green]✓[/green] Monitoring collector deployed")
                    else:
                        console.print("  [yellow]![/yellow] Monitoring deployment skipped or failed")
                    
                    # Deploy dashboard
                    dashboard_stack = config["aws"]["stacks"]["dashboard"]
                    dashboard_template = Path(__file__).parent.parent.parent.parent.parent.parent / "deployment" / "infrastructure" / "monitoring-dashboard.yaml"
                    
                    if self._deploy_stack(dashboard_stack, dashboard_template, params_file, config["aws"]["region"]):
                        console.print("  [green]✓[/green] Monitoring dashboard deployed")
                    else:
                        console.print("  [yellow]![/yellow] Dashboard deployment skipped or failed")
                        
                except Exception as e:
                    console.print(f"  [yellow]![/yellow] Monitoring deployment partially failed: {e}")
        
        console.print("  [green]✓[/green] Configuration saved")
        
        # Success message
        success_panel = Panel.fit(
            "[bold green]✓ Setup complete![/bold green]\n\n"
            "Next steps:\n"
            "1. Create package: [cyan]poetry run ccwb package[/cyan]\n"
            "2. Test authentication: [cyan]poetry run ccwb test[/cyan]\n"
            "3. Distribute to users (see dist/ folder)",
            border_style="green",
            padding=(1, 2)
        )
        console.print("\n", success_panel)
        
        return 0
    
    def _save_configuration(self, config_data: Dict[str, Any]) -> None:
        """Save configuration to file."""
        # Get profile name from option
        profile_name = self.option("profile")
            
        config = Config.load()
        
        profile = Profile(
            name=profile_name,
            provider_domain=config_data["okta"]["domain"],
            client_id=config_data["okta"]["client_id"],
            credential_storage=config_data.get("credential_storage", "session"),
            aws_region=config_data["aws"]["region"],
            identity_pool_name=config_data["aws"]["identity_pool_name"],
            stack_names=config_data["aws"]["stacks"],
            monitoring_enabled=config_data["monitoring"]["enabled"],
            monitoring_config=config_data.get("monitoring", {}).get("vpc_config", {}),
            analytics_enabled=config_data.get("analytics", {}).get("enabled", True) if config_data.get("monitoring", {}).get("enabled") else False,
            allowed_bedrock_regions=config_data["aws"]["allowed_bedrock_regions"],
            provider_type=config_data.get("provider_type"),
            cognito_user_pool_id=config_data.get("cognito_user_pool_id")
        )
        
        config.add_profile(profile)
        config.save()
    
    def _check_aws_cli(self) -> bool:
        """Check if AWS CLI is installed."""
        try:
            import subprocess
            result = subprocess.run(["aws", "--version"], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def _check_aws_credentials(self) -> bool:
        """Check if AWS credentials are configured."""
        try:
            boto3.client("sts").get_caller_identity()
            return True
        except:
            return False
    
    def _check_python_version(self) -> bool:
        """Check Python version."""
        import sys
        return sys.version_info >= (3, 8)
    
    def _get_bedrock_regions(self) -> List[str]:
        """Get list of regions where Bedrock is available."""
        try:
            # These are the regions where Bedrock is currently available
            # This list should be updated as AWS expands Bedrock availability
            bedrock_regions = [
                "us-east-1",      # N. Virginia
                "us-east-2",      # Ohio
                "us-west-2",      # Oregon
                "ap-northeast-1", # Tokyo
                "ap-southeast-1", # Singapore
                "ap-southeast-2", # Sydney
                "eu-central-1",   # Frankfurt
                "eu-west-1",      # Ireland
                "eu-west-3",      # Paris
                "ap-south-1",     # Mumbai
                "ca-central-1",   # Canada
            ]
            
            # For now, return the known list without checking each one
            # (checking each region takes time and requires permissions)
            return bedrock_regions
        except:
            # Return default list if we can't check
            return [
                "us-east-1", "us-west-2", "eu-west-1", "eu-central-1",
                "ap-northeast-1", "ap-southeast-1", "ap-southeast-2"
            ]
    
    def _update_parameters_file(self, params_file: Path, config: Dict[str, Any]) -> None:
        """Update the CloudFormation parameters file with our configuration."""
        # Load existing parameters
        if params_file.exists():
            with open(params_file, 'r') as f:
                params = json.load(f)
        else:
            params = []
        
        # Update with our values
        param_map = {
            "OktaDomain": config["okta"]["domain"],
            "OktaClientId": config["okta"]["client_id"],
            "IdentityPoolName": config["aws"]["identity_pool_name"],
            "AllowedBedrockRegions": ",".join(config["aws"]["allowed_bedrock_regions"]),
            "EnableMonitoring": "true" if config["monitoring"]["enabled"] else "false",
            "MaxSessionDuration": "28800",  # 8 hours
        }
        
        # Add VPC configuration if monitoring is enabled
        if config.get("monitoring", {}).get("enabled"):
            vpc_config = config.get("monitoring", {}).get("vpc_config", {})
            if vpc_config.get("create_vpc", True):
                param_map["CreateVPC"] = "true"
            else:
                param_map["CreateVPC"] = "false"
                param_map["VpcId"] = vpc_config.get("vpc_id", "")
                param_map["SubnetIds"] = ",".join(vpc_config.get("subnet_ids", []))
        
        # Update or add parameters
        for key, value in param_map.items():
            found = False
            for param in params:
                if param["ParameterKey"] == key:
                    param["ParameterValue"] = value
                    found = True
                    break
            if not found:
                params.append({
                    "ParameterKey": key,
                    "ParameterValue": value
                })
        
        # Save updated parameters
        params_file.parent.mkdir(parents=True, exist_ok=True)
        with open(params_file, 'w') as f:
            json.dump(params, f, indent=2)
    
    def _deploy_stack(self, stack_name: str, template_file: Path, params_file: Path, region: str) -> bool:
        """Deploy a CloudFormation stack."""
        try:
            console = Console()
            
            # Check if template exists
            if not template_file.exists():
                console.print(f"[yellow]Template not found: {template_file.name}[/yellow]")
                return False
            
            # Build the AWS CLI command
            cmd = [
                "aws", "cloudformation", "deploy",
                "--template-file", str(template_file),
                "--stack-name", stack_name,
                "--parameter-overrides", f"file://{params_file}",
                "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
                "--region", region,
                "--no-fail-on-empty-changeset"
            ]
            
            # Show command in verbose mode
            if self.io.is_verbose():
                console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
            
            # Run the deployment
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                return True
            else:
                console = Console()
                # Check for common issues
                if "No changes to deploy" in result.stderr:
                    return True  # Stack already up to date
                elif "does not exist" in result.stderr and "CREATE_IN_PROGRESS" not in result.stderr:
                    # Stack doesn't exist, but we're trying to update
                    console.print(f"[yellow]Creating new stack: {stack_name}[/yellow]")
                    # Try create instead of deploy
                    create_cmd = cmd.copy()
                    create_cmd[2] = "create-stack"
                    create_result = subprocess.run(create_cmd, capture_output=True, text=True)
                    if create_result.returncode == 0:
                        # Wait for stack to complete
                        wait_cmd = [
                            "aws", "cloudformation", "wait", "stack-create-complete",
                            "--stack-name", stack_name,
                            "--region", region
                        ]
                        subprocess.run(wait_cmd)
                        return True
                
                # Show the actual error
                error_msg = result.stderr if result.stderr else result.stdout
                console.print(f"[red]Deployment error:[/red]")
                console.print(f"[dim]{error_msg}[/dim]")
                return False
                
        except Exception as e:
            console = Console()
            console.print(f"[red]Deployment error: {e}[/red]")
            return False
    
    def _check_existing_deployment(self) -> Dict[str, Any]:
        """Check if there's an existing deployment and return its configuration."""
        try:
            # First check if we have a saved configuration
            config = Config.load()
            profile = config.get_profile("default")
            
            if not profile:
                return None
            
            # Try to check if the auth stack exists, but don't fail if AWS creds are missing
            region = profile.aws_region
            auth_stack = profile.stack_names.get("auth", f"{profile.identity_pool_name}-stack")
            
            # Only check stack if we have AWS credentials
            console = Console()
            stacks_found = False
            try:
                console.print("\n[dim]Checking deployment status in current AWS account...[/dim]")
                if self._stack_exists(auth_stack, region):
                    # Get stack outputs to verify it's our stack
                    outputs = self._get_stack_outputs(auth_stack, region)
                    console.print(f"[dim]  ✓ Found auth stack: {auth_stack}[/dim]")
                    stacks_found = True
                else:
                    # Stack doesn't exist, but we have config
                    console.print(f"[dim]  ✗ Auth stack not found: {auth_stack}[/dim]")
            except Exception as e:
                # Can't check AWS - maybe no credentials
                console.print(f"[dim]  ! Could not verify stack status[/dim]")
                # Assume stacks exist if we can't check
                stacks_found = True
            
            # Build config from saved profile and stack outputs
            existing_config = {
                "_stacks_found": stacks_found,
                "okta": {
                    "domain": profile.provider_domain,
                    "client_id": profile.client_id
                },
                "credential_storage": getattr(profile, 'credential_storage', 'session'),
                "aws": {
                    "region": region,
                    "identity_pool_name": profile.identity_pool_name,
                    "stacks": profile.stack_names,
                    "allowed_bedrock_regions": profile.allowed_bedrock_regions
                },
                "monitoring": {
                    "enabled": profile.monitoring_enabled
                }
            }
            
            return existing_config
            
        except Exception:
            return None
    
    def _show_existing_deployment(self, config: Dict[str, Any]) -> None:
        """Show summary of existing deployment."""
        console = Console()
        
        console.print(f"• OIDC Provider: [cyan]{config['okta']['domain']}[/cyan]")
        console.print(f"• Credential Storage: [cyan]{'Keyring' if config.get('credential_storage') == 'keyring' else 'Session Files'}[/cyan]")
        console.print(f"• AWS Region: [cyan]{config['aws']['region']}[/cyan]") 
        console.print(f"• Identity Pool: [cyan]{config['aws']['identity_pool_name']}[/cyan]")
        console.print(f"• Bedrock Regions: [cyan]{', '.join(config['aws']['allowed_bedrock_regions'])}[/cyan]")
        console.print(f"• Monitoring: [cyan]{'Enabled' if config['monitoring']['enabled'] else 'Disabled'}[/cyan]")
    
    def _stack_exists(self, stack_name: str, region: str) -> bool:
        """Check if a CloudFormation stack exists."""
        try:
            cmd = [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                status = result.stdout.strip()
                # Stack exists if it's in any valid state
                valid_statuses = [
                    "CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"
                ]
                return status in valid_statuses
            return False
        except:
            return False
    
    def _get_stack_outputs(self, stack_name: str, region: str) -> Dict[str, str]:
        """Get outputs from a CloudFormation stack."""
        try:
            cmd = [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].Outputs",
                "--output", "json"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                outputs_list = json.loads(result.stdout)
                outputs = {}
                for output in outputs_list:
                    outputs[output["OutputKey"]] = output["OutputValue"]
                return outputs
            return {}
        except:
            return {}
    
    def _get_hosted_zones(self) -> List[Dict[str, Any]]:
        """Get available Route53 hosted zones."""
        try:
            import boto3
            client = boto3.client('route53')
            response = client.list_hosted_zones()
            return response.get('HostedZones', [])
        except Exception:
            return []
    
    def _configure_vpc(self, region: str) -> Dict[str, Any]:
        """Configure VPC for monitoring stack."""
        console = Console()
        
        console.print("\n[bold]VPC Configuration for Monitoring[/bold]")
        console.print("The monitoring stack requires a VPC for the OpenTelemetry collector.")
        
        # Check if monitoring stack already exists with a VPC
        monitoring_stack = None
        stack_vpc_info = None
        try:
            # Check for existing monitoring stack
            config = Config.load()
            profile = config.get_profile()
            if profile and profile.stack_names:
                monitoring_stack = profile.stack_names.get("monitoring")
                if monitoring_stack:
                    from claude_code_with_bedrock.cli.utils.aws import check_stack_exists, get_stack_outputs
                    if check_stack_exists(monitoring_stack, region):
                        outputs = get_stack_outputs(monitoring_stack, region)
                        if outputs.get("VpcSource") == "stack-created":
                            stack_vpc_info = {
                                "vpc_id": outputs.get("VpcId"),
                                "subnet_ids": outputs.get("SubnetIds", "").split(",") if outputs.get("SubnetIds") else []
                            }
                            console.print(f"\n[green]Found existing monitoring stack with VPC: {stack_vpc_info['vpc_id']}[/green]")
        except Exception:
            # If we can't check, continue with normal flow
            pass
        
        # If we found a stack-created VPC, offer to keep using it
        if stack_vpc_info and stack_vpc_info["vpc_id"]:
            use_stack_vpc = questionary.confirm(
                "The monitoring stack already has a VPC. Continue using it?",
                default=True
            ).ask()
            
            if use_stack_vpc:
                return {"create_vpc": True}  # Keep CreateVPC=true to maintain the stack-created VPC
        
        # Check for existing VPCs
        console.print("\n[yellow]Searching for existing VPCs...[/yellow]")
        vpcs = get_vpcs(region)
        
        if vpcs:
            # Found existing VPCs
            vpc_choices = []
            vpc_choices.append(questionary.Choice("Create new VPC", value="create_new"))
            
            for vpc in vpcs:
                label = f"{vpc['id']} - {vpc['cidr']}"
                if vpc['name']:
                    label = f"{vpc['name']} ({label})"
                if vpc['is_default']:
                    label = f"{label} [DEFAULT]"
                vpc_choices.append(questionary.Choice(label, value=vpc['id']))
            
            vpc_choice = questionary.select(
                "Select VPC for monitoring infrastructure:",
                choices=vpc_choices
            ).ask()
            
            if vpc_choice == "create_new":
                return {"create_vpc": True}
            else:
                # User selected an existing VPC
                selected_vpc = next(v for v in vpcs if v['id'] == vpc_choice)
                console.print(f"\n[green]Selected VPC: {vpc_choice}[/green]")
                
                # Get subnets
                console.print("\n[yellow]Searching for subnets...[/yellow]")
                subnets = get_subnets(region, vpc_choice)
                
                if len(subnets) < 2:
                    console.print("[red]Error: ALB requires at least 2 subnets in different availability zones[/red]")
                    create_new = questionary.confirm(
                        "Would you like to create a new VPC instead?",
                        default=True
                    ).ask()
                    if create_new:
                        return {"create_vpc": True}
                    else:
                        return None
                
                # Let user select subnets
                subnet_choices = []
                for subnet in subnets:
                    label = f"{subnet['id']} - {subnet['cidr']} ({subnet['availability_zone']})"
                    if subnet['name']:
                        label = f"{subnet['name']} - {label}"
                    if subnet['is_public']:
                        label = f"{label} [PUBLIC]"
                    subnet_choices.append(
                        questionary.Choice(label, value=subnet['id'], checked=subnet['is_public'])
                    )
                
                selected_subnets = questionary.checkbox(
                    "Select at least 2 subnets for the ALB (in different AZs):",
                    choices=subnet_choices,
                    validate=lambda x: len(x) >= 2 or "Please select at least 2 subnets"
                ).ask()
                
                if not selected_subnets:
                    return None
                
                # Validate subnets are in different AZs
                selected_subnet_details = [s for s in subnets if s['id'] in selected_subnets]
                azs = set(s['availability_zone'] for s in selected_subnet_details)
                
                if len(azs) < 2:
                    console.print("[red]Error: Selected subnets must be in different availability zones[/red]")
                    return None
                
                return {
                    "create_vpc": False,
                    "vpc_id": vpc_choice,
                    "subnet_ids": selected_subnets
                }
        else:
            # No VPCs found or can't list them
            console.print("[yellow]No existing VPCs found or unable to list VPCs.[/yellow]")
            create_new = questionary.confirm(
                "Create a new VPC for monitoring?",
                default=True
            ).ask()
            
            if create_new:
                return {"create_vpc": True}
            else:
                # Manual entry
                vpc_id = questionary.text(
                    "Enter existing VPC ID:",
                    validate=lambda x: x.startswith('vpc-') or "Invalid VPC ID format"
                ).ask()
                
                if not vpc_id:
                    return None
                
                subnet_ids_str = questionary.text(
                    "Enter at least 2 subnet IDs (comma-separated):",
                    validate=lambda x: len(x.split(',')) >= 2 or "Please provide at least 2 subnet IDs"
                ).ask()
                
                if not subnet_ids_str:
                    return None
                
                subnet_ids = [s.strip() for s in subnet_ids_str.split(',')]
                
                return {
                    "create_vpc": False,
                    "vpc_id": vpc_id,
                    "subnet_ids": subnet_ids
                }