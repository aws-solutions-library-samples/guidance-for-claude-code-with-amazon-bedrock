# ABOUTME: Shared display utilities for consistent output formatting
# ABOUTME: Provides common functions for displaying configuration information

"""Shared display utilities for consistent output formatting across commands."""

from typing import Any

from rich import box
from rich.console import Console
from rich.table import Table

from claude_code_with_bedrock.models import get_all_model_display_names


def display_configuration_info(profile, identity_pool_id: str | None = None, format_type: str = "table") -> None:
    """
    Display configuration information in a consistent format.

    Args:
        profile: The configuration profile object
        identity_pool_id: Optional actual identity pool ID (from stack outputs)
        format_type: Display format - "table" for rich table, "simple" for simple text
    """
    console = Console()

    if format_type == "table":
        _display_table_format(console, profile, identity_pool_id)
    else:
        _display_simple_format(console, profile, identity_pool_id)


def _display_table_format(console: Console, profile, identity_pool_id: str | None) -> None:
    """Display configuration in rich table format."""
    config_table = Table(box=box.SIMPLE)
    config_table.add_column("Setting", style="dim")
    config_table.add_column("Value")

    # Configuration and AWS profile names
    config_table.add_row("Configuration Profile", profile.name)
    config_table.add_row("AWS Profile", "ClaudeCode")

    # Provider information
    config_table.add_row("OIDC Provider", profile.provider_domain)
    config_table.add_row("Client ID", profile.client_id)

    # Federation configuration
    federation_type = getattr(profile, "federation_type", "cognito")
    if federation_type == "direct":
        config_table.add_row("Federation Type", "Direct STS (12-hour sessions)")
        federated_role_arn = getattr(profile, "federated_role_arn", None)
        if federated_role_arn:
            config_table.add_row("Federated Role", federated_role_arn.split("/")[-1])  # Show just role name
    else:
        config_table.add_row("Federation Type", "Cognito Identity Pool (8-hour sessions)")

    # AWS configuration
    config_table.add_row("AWS Region", profile.aws_region)

    # Identity Pool - show both name and ID if available
    if identity_pool_id:
        config_table.add_row("Identity Pool", f"{profile.identity_pool_name} ({identity_pool_id})")
    else:
        config_table.add_row("Identity Pool", profile.identity_pool_name)

    # Model configuration
    selected_model = getattr(profile, "selected_model", None)
    if selected_model:
        model_names = get_all_model_display_names()
        config_table.add_row("Claude Model", model_names.get(selected_model, selected_model))

    # Source region
    source_region = getattr(profile, "selected_source_region", None)
    if source_region:
        config_table.add_row("Source Region", source_region)

    # Cross-region profile
    cross_region_names = {
        "us": "US Cross-Region (us-east-1, us-east-2, us-west-2)",
        "europe": "Europe Cross-Region (eu-west-1, eu-west-3, eu-central-1, eu-north-1)",
        "apac": "APAC Cross-Region (ap-northeast-1, ap-southeast-1/2, ap-south-1)",
    }
    cross_region = getattr(profile, "cross_region_profile", None) or "us"
    config_table.add_row("Bedrock Regions", cross_region_names.get(cross_region, cross_region))

    # Monitoring and Analytics
    config_table.add_row("Monitoring", "✓ Enabled" if profile.monitoring_enabled else "✗ Disabled")

    if profile.monitoring_enabled and getattr(profile, "analytics_enabled", True):
        config_table.add_row("Analytics", "✓ Enabled (Athena + Kinesis Firehose)")
    elif profile.monitoring_enabled:
        config_table.add_row("Analytics", "✗ Disabled")

    console.print(config_table)


def _display_simple_format(console: Console, profile, identity_pool_id: str | None) -> None:
    """Display configuration in simple text format."""
    console.print("\n[bold]Package Configuration:[/bold]")

    # Configuration and AWS profile names
    console.print(f"  Configuration Profile: [cyan]{profile.name}[/cyan]")
    console.print("  AWS Profile: [cyan]ClaudeCode[/cyan]")

    # Provider information
    console.print(f"  OIDC Provider: [cyan]{profile.provider_domain}[/cyan]")
    console.print(f"  Client ID: [cyan]{profile.client_id}[/cyan]")

    # Federation configuration
    federation_type = getattr(profile, "federation_type", "cognito")
    if federation_type == "direct":
        console.print("  Federation Type: [cyan]Direct STS (12-hour sessions)[/cyan]")
        federated_role_arn = getattr(profile, "federated_role_arn", None)
        if federated_role_arn:
            console.print(f"  Federated Role: [cyan]{federated_role_arn.split('/')[-1]}[/cyan]")
    else:
        console.print("  Federation Type: [cyan]Cognito Identity Pool (8-hour sessions)[/cyan]")

    # AWS configuration
    console.print(f"  AWS Region: [cyan]{profile.aws_region}[/cyan]")

    # Identity Pool - show actual ID if available
    if identity_pool_id:
        console.print(f"  Identity Pool: [cyan]{identity_pool_id}[/cyan]")
    else:
        console.print(f"  Identity Pool: [cyan]{profile.identity_pool_name}[/cyan]")

    # Model configuration
    selected_model = getattr(profile, "selected_model", None)
    if selected_model:
        model_names = get_all_model_display_names()
        model_display = model_names.get(selected_model, selected_model)
        console.print(f"  Claude Model: [cyan]{model_display}[/cyan]")

    # Source region
    source_region = getattr(profile, "selected_source_region", None)
    if source_region:
        console.print(f"  Source Region: [cyan]{source_region}[/cyan]")

    # Cross-region profile
    cross_region_names = {
        "us": "US Cross-Region (us-east-1, us-east-2, us-west-2)",
        "europe": "Europe Cross-Region (eu-west-1, eu-west-3, eu-central-1, eu-north-1)",
        "apac": "APAC Cross-Region (ap-northeast-1, ap-southeast-1/2, ap-south-1)",
    }
    cross_region = getattr(profile, "cross_region_profile", None) or "us"
    console.print(f"  Bedrock Regions: [cyan]{cross_region_names.get(cross_region, cross_region)}[/cyan]")

    # Analytics
    if profile.monitoring_enabled and getattr(profile, "analytics_enabled", True):
        console.print("  Analytics: [cyan]Enabled (Athena + Kinesis Firehose)[/cyan]")


def get_configuration_dict(profile, identity_pool_id: str | None = None) -> dict[str, Any]:
    """
    Get configuration information as a dictionary for JSON output.

    Args:
        profile: The configuration profile object
        identity_pool_id: Optional actual identity pool ID (from stack outputs)

    Returns:
        Dictionary containing all configuration information
    """
    config_dict = {
        "configuration_profile": profile.name,
        "aws_profile": "ClaudeCode",
        "oidc_provider": profile.provider_domain,
        "client_id": profile.client_id,
        "aws_region": profile.aws_region,
        "identity_pool_name": profile.identity_pool_name,
        "monitoring_enabled": profile.monitoring_enabled,
        "bedrock_regions": profile.allowed_bedrock_regions,
        "selected_model": getattr(profile, "selected_model", None),
        "cross_region_profile": getattr(profile, "cross_region_profile", None),
        "source_region": getattr(profile, "selected_source_region", None),
        "analytics_enabled": getattr(profile, "analytics_enabled", None),
    }

    if identity_pool_id:
        config_dict["identity_pool_id"] = identity_pool_id

    return config_dict
