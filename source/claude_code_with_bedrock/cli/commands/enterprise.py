# ABOUTME: Enterprise governance and policy management commands
# ABOUTME: Provides enterprise-specific functionality for Claude Code deployments

"""Enterprise command - governance and policy management for enterprise deployments."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

import boto3
from cleo.commands.command import Command
from cleo.helpers import option, argument
import questionary
from questionary import Choice
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.cli.utils.aws import check_aws_credentials, get_current_region
from claude_code_with_bedrock.cli.utils.progress import WizardProgress


class EnterpriseCommand(Command):
    name = "enterprise"
    description = "Enterprise governance and policy management"
    
    arguments = [
        argument(
            "action",
            description="Action to perform: configure, deploy-policies, status, audit",
            optional=True
        )
    ]
    
    options = [
        option(
            "profile",
            "p", 
            description="Configuration profile name",
            flag=False,
            default="default"
        ),
        option(
            "security-profile",
            "s",
            description="Enterprise security profile (plan-only, restricted, standard, elevated)",
            flag=False
        ),
        option(
            "dry-run",
            None,
            description="Show what would be deployed without making changes",
            flag=True
        ),
        option(
            "force",
            "f",
            description="Force deployment without confirmation prompts",
            flag=True
        )
    ]
    
    def handle(self) -> int:
        """Execute the enterprise command."""
        console = Console()
        
        # Check AWS credentials
        if not check_aws_credentials():
            console.print("[red]❌ AWS credentials not configured[/red]")
            console.print("Please run: aws configure")
            return 1
            
        action = self.argument("action")
        if not action:
            return self._show_help(console)
            
        # Route to appropriate handler
        if action == "configure":
            return self._configure_enterprise(console)
        elif action == "deploy-policies":
            return self._deploy_policies(console)
        elif action == "status":
            return self._show_status(console)
        elif action == "audit":
            return self._show_audit(console)
        else:
            console.print(f"[red]❌ Unknown action: {action}[/red]")
            return self._show_help(console)
    
    def _show_help(self, console: Console) -> int:
        """Show help information."""
        console.print("\n[bold blue]Claude Code Enterprise Management[/bold blue]\n")
        
        table = Table(box=box.ROUNDED)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        
        table.add_row(
            "ccwb enterprise configure", 
            "Interactive configuration of enterprise policies"
        )
        table.add_row(
            "ccwb enterprise deploy-policies",
            "Deploy enhanced security policies to existing infrastructure"
        )
        table.add_row(
            "ccwb enterprise status",
            "Show current enterprise configuration and policy status"
        )
        table.add_row(
            "ccwb enterprise audit",
            "Generate audit report of Claude Code usage and compliance"
        )
        
        console.print(table)
        
        console.print("\n[bold]Security Profiles:[/bold]")
        profiles_table = Table(box=box.ROUNDED)
        profiles_table.add_column("Profile", style="cyan", no_wrap=True) 
        profiles_table.add_column("Description", style="white")
        profiles_table.add_column("Use Cases", style="green")
        
        profiles_table.add_row(
            "plan-only",
            "Most restrictive - Claude operates in plan mode only",
            "Compliance-heavy orgs, initial rollouts"
        )
        profiles_table.add_row(
            "restricted", 
            "Safe development tools only, no network access",
            "General development teams"
        )
        profiles_table.add_row(
            "standard",
            "Balanced security and functionality",
            "Most enterprise teams"
        )
        profiles_table.add_row(
            "elevated",
            "Advanced permissions for senior engineers",
            "Platform teams, senior developers"
        )
        
        console.print(profiles_table)
        console.print()
        return 0
        
    def _configure_enterprise(self, console: Console) -> int:
        """Interactive configuration of enterprise policies."""
        console.print("\n[bold blue]🏢 Enterprise Policy Configuration[/bold blue]\n")
        
        try:
            # Load existing config
            config = Config.load(self.option("profile"))
            console.print(f"[green]✓[/green] Loaded profile: {config.profile_name}")
            
        except Exception as e:
            console.print(f"[red]❌ Could not load configuration: {e}[/red]")
            console.print("Please run 'ccwb init' first to set up base infrastructure.")
            return 1
        
        # Check if base infrastructure exists
        if not self._check_base_infrastructure(console, config):
            return 1
            
        # Security profile selection
        security_profile = self.option("security-profile")
        if not security_profile:
            security_profile = questionary.select(
                "Select enterprise security profile:",
                choices=[
                    Choice("plan-only", "Plan-Only: Most restrictive, plan mode only"),
                    Choice("restricted", "Restricted: Safe development tools only"),  
                    Choice("standard", "Standard: Balanced security and functionality"),
                    Choice("elevated", "Elevated: Advanced permissions for senior engineers")
                ]
            ).ask()
            
        console.print(f"[cyan]Selected security profile:[/cyan] {security_profile}")
        
        # Cost tracking configuration
        enable_cost_tracking = questionary.confirm(
            "Enable detailed cost tracking and budgets?",
            default=True
        ).ask()
        
        # User attribute mapping
        enable_user_mapping = questionary.confirm(
            "Enable user/team attribute mapping for chargeback?",
            default=True
        ).ask()
        
        # Budget configuration if cost tracking enabled
        budget_amount = 1000
        budget_email = "admin@company.com"
        if enable_cost_tracking:
            budget_amount = questionary.text(
                "Monthly budget amount (USD):",
                default="1000",
                validate=lambda x: x.isdigit() and int(x) > 0
            ).ask()
            budget_amount = int(budget_amount)
            
            budget_email = questionary.text(
                "Budget alert email address:",
                default="admin@company.com",
                validate=lambda x: "@" in x and "." in x
            ).ask()
        
        # Save enterprise configuration
        enterprise_config = {
            "security_profile": security_profile,
            "cost_tracking_enabled": enable_cost_tracking,
            "user_attribute_mapping_enabled": enable_user_mapping,
            "budget_amount": budget_amount,
            "budget_email": budget_email,
            "existing_identity_pool_id": getattr(config, 'identity_pool_id', ''),
            "existing_bedrock_role_arn": getattr(config, 'bedrock_role_arn', ''),
            "allowed_bedrock_regions": getattr(config, 'allowed_bedrock_regions', ['us-east-1', 'us-west-2'])
        }
        
        # Save to enterprise config file
        enterprise_config_path = Path.cwd() / "enterprise-config.json"
        with open(enterprise_config_path, 'w') as f:
            json.dump(enterprise_config, f, indent=2)
            
        console.print(f"\n[green]✓[/green] Enterprise configuration saved to: {enterprise_config_path}")
        console.print("\nNext steps:")
        console.print("1. Review the configuration file")
        console.print("2. Run 'ccwb enterprise deploy-policies' to apply policies")
        
        return 0
    
    def _check_base_infrastructure(self, console: Console, config: Config) -> bool:
        """Check if base infrastructure exists."""
        try:
            # Check for Cognito Identity Pool
            cognito_client = boto3.client('cognito-identity', region_name=config.aws_region)
            identity_pool_id = getattr(config, 'identity_pool_id', None)
            
            if not identity_pool_id:
                console.print("[red]❌ No Identity Pool found in configuration[/red]")
                return False
                
            # Verify identity pool exists
            try:
                cognito_client.describe_identity_pool(IdentityPoolId=identity_pool_id)
                console.print(f"[green]✓[/green] Found Identity Pool: {identity_pool_id}")
            except cognito_client.exceptions.ResourceNotFoundException:
                console.print(f"[red]❌ Identity Pool not found: {identity_pool_id}[/red]")
                return False
                
            return True
            
        except Exception as e:
            console.print(f"[red]❌ Error checking base infrastructure: {e}[/red]")
            return False
    
    def _deploy_policies(self, console: Console) -> int:
        """Deploy enhanced security policies."""
        console.print("\n[bold blue]🚀 Deploying Enterprise Policies[/bold blue]\n")
        
        # Load enterprise configuration
        enterprise_config_path = Path.cwd() / "enterprise-config.json"
        if not enterprise_config_path.exists():
            console.print("[red]❌ Enterprise configuration not found[/red]")
            console.print("Please run 'ccwb enterprise configure' first")
            return 1
            
        with open(enterprise_config_path, 'r') as f:
            enterprise_config = json.load(f)
            
        console.print(f"[cyan]Security Profile:[/cyan] {enterprise_config['security_profile']}")
        console.print(f"[cyan]Cost Tracking:[/cyan] {'Enabled' if enterprise_config['cost_tracking_enabled'] else 'Disabled'}")
        
        if self.option("dry-run"):
            console.print("\n[yellow]🔍 DRY RUN - No changes will be made[/yellow]")
            return self._show_deployment_plan(console, enterprise_config)
            
        # Confirm deployment
        if not self.option("force"):
            if not questionary.confirm("Deploy enterprise policies?").ask():
                console.print("Deployment cancelled.")
                return 0
                
        # Deploy CloudFormation stack
        return self._deploy_cloudformation_stack(console, enterprise_config)
    
    def _show_deployment_plan(self, console: Console, enterprise_config: Dict[str, Any]) -> int:
        """Show what would be deployed in dry run mode."""
        console.print("\n[bold]Deployment Plan:[/bold]\n")
        
        table = Table(box=box.ROUNDED)
        table.add_column("Resource", style="cyan")
        table.add_column("Action", style="green")
        table.add_column("Description", style="white")
        
        # Policy resources
        security_profile = enterprise_config['security_profile']
        table.add_row(
            f"IAM Policy", 
            "CREATE",
            f"Enhanced {security_profile} security policy"
        )
        
        # Cost tracking resources
        if enterprise_config['cost_tracking_enabled']:
            table.add_row(
                "AWS Budget",
                "CREATE", 
                f"Monthly budget: ${enterprise_config['budget_amount']}"
            )
            table.add_row(
                "CloudWatch Dashboard",
                "CREATE",
                "Enterprise monitoring dashboard"
            )
            
        # User attribute mapping
        if enterprise_config['user_attribute_mapping_enabled']:
            table.add_row(
                "Principal Tag Mapping",
                "UPDATE",
                "Enhanced user/team attribute mapping"
            )
            
        console.print(table)
        console.print(f"\n[green]✓[/green] Dry run completed - {table.row_count} resources would be deployed")
        return 0
        
    def _deploy_cloudformation_stack(self, console: Console, enterprise_config: Dict[str, Any]) -> int:
        """Deploy the CloudFormation stack with enterprise policies."""
        try:
            cloudformation = boto3.client('cloudformation', region_name=get_current_region())
            
            # Load template
            template_path = Path(__file__).parent.parent.parent.parent.parent / "enterprise-addons" / "governance" / "templates" / "enhanced-cognito-policies.yaml"
            
            if not template_path.exists():
                console.print(f"[red]❌ Template not found: {template_path}[/red]")
                return 1
                
            with open(template_path, 'r') as f:
                template_body = f.read()
                
            # Prepare parameters
            parameters = [
                {
                    'ParameterKey': 'ExistingIdentityPoolId',
                    'ParameterValue': enterprise_config['existing_identity_pool_id']
                },
                {
                    'ParameterKey': 'ExistingBedrockRoleArn', 
                    'ParameterValue': enterprise_config['existing_bedrock_role_arn']
                },
                {
                    'ParameterKey': 'EnterpriseSecurityProfile',
                    'ParameterValue': enterprise_config['security_profile']
                },
                {
                    'ParameterKey': 'AllowedBedrockRegions',
                    'ParameterValue': ','.join(enterprise_config['allowed_bedrock_regions'])
                },
                {
                    'ParameterKey': 'EnableCostTracking',
                    'ParameterValue': str(enterprise_config['cost_tracking_enabled']).lower()
                },
                {
                    'ParameterKey': 'EnableUserAttributeMapping',
                    'ParameterValue': str(enterprise_config['user_attribute_mapping_enabled']).lower()
                }
            ]
            
            stack_name = f"claude-code-enterprise-{enterprise_config['security_profile']}"
            
            console.print(f"[cyan]Deploying stack:[/cyan] {stack_name}")
            
            # Deploy or update stack
            try:
                cloudformation.create_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_IAM'],
                    Tags=[
                        {'Key': 'Purpose', 'Value': 'Claude Code Enterprise Policies'},
                        {'Key': 'SecurityProfile', 'Value': enterprise_config['security_profile']}
                    ]
                )
                console.print("[green]✓[/green] Stack deployment initiated")
                
            except cloudformation.exceptions.AlreadyExistsException:
                # Update existing stack
                cloudformation.update_stack(
                    StackName=stack_name,
                    TemplateBody=template_body,
                    Parameters=parameters,
                    Capabilities=['CAPABILITY_IAM']
                )
                console.print("[green]✓[/green] Stack update initiated")
                
            console.print(f"\n[cyan]Monitor deployment:[/cyan]")
            console.print(f"aws cloudformation describe-stacks --stack-name {stack_name}")
            
            return 0
            
        except Exception as e:
            console.print(f"[red]❌ Deployment failed: {e}[/red]")
            return 1
    
    def _show_status(self, console: Console) -> int:
        """Show current enterprise configuration and policy status."""
        console.print("\n[bold blue]📊 Enterprise Status[/bold blue]\n")
        
        # Load enterprise configuration
        enterprise_config_path = Path.cwd() / "enterprise-config.json"
        if not enterprise_config_path.exists():
            console.print("[yellow]⚠️  No enterprise configuration found[/yellow]")
            console.print("Run 'ccwb enterprise configure' to get started")
            return 0
            
        with open(enterprise_config_path, 'r') as f:
            enterprise_config = json.load(f)
            
        # Show configuration
        config_table = Table(title="Configuration", box=box.ROUNDED)
        config_table.add_column("Setting", style="cyan")
        config_table.add_column("Value", style="white")
        
        config_table.add_row("Security Profile", enterprise_config['security_profile'])
        config_table.add_row("Cost Tracking", "✓" if enterprise_config['cost_tracking_enabled'] else "✗")
        config_table.add_row("User Mapping", "✓" if enterprise_config['user_attribute_mapping_enabled'] else "✗")
        config_table.add_row("Budget Amount", f"${enterprise_config.get('budget_amount', 'N/A')}")
        
        console.print(config_table)
        
        # Check CloudFormation stack status
        try:
            cloudformation = boto3.client('cloudformation', region_name=get_current_region())
            stack_name = f"claude-code-enterprise-{enterprise_config['security_profile']}"
            
            response = cloudformation.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]
            stack_status = stack['StackStatus']
            
            status_table = Table(title="Deployment Status", box=box.ROUNDED)
            status_table.add_column("Resource", style="cyan")
            status_table.add_column("Status", style="green" if "COMPLETE" in stack_status else "yellow")
            
            status_table.add_row("CloudFormation Stack", stack_status)
            status_table.add_row("Last Updated", stack.get('LastUpdatedTime', stack['CreationTime']).strftime('%Y-%m-%d %H:%M:%S'))
            
            console.print(status_table)
            
        except cloudformation.exceptions.ClientError:
            console.print("[yellow]⚠️  Enterprise policies not yet deployed[/yellow]")
            console.print("Run 'ccwb enterprise deploy-policies' to deploy")
            
        return 0
        
    def _show_audit(self, console: Console) -> int:
        """Generate audit report of Claude Code usage and compliance."""
        console.print("\n[bold blue]🔍 Enterprise Audit Report[/bold blue]\n")
        
        # This would integrate with CloudTrail and CloudWatch to generate reports
        console.print("[yellow]⚠️  Audit report generation not yet implemented[/yellow]")
        console.print("\nPlanned features:")
        console.print("• User access patterns and compliance violations")
        console.print("• Cost breakdown by user/team/project") 
        console.print("• Policy effectiveness metrics")
        console.print("• Security incident reporting")
        
        return 0