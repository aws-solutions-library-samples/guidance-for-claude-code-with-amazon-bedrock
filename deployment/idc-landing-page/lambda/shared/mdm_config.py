# ABOUTME: Shared MDM configuration schema and constants for Claude Desktop
# ABOUTME: Used by idc-landing-page, bootstrap-server, and ccwb cowork generate

"""MDM Configuration Schema and Utilities.

This module defines the canonical MDM key names, default values, and helper
functions for generating Claude Desktop configuration. It is the single source
of truth for both Lambda functions and the ccwb CLI.

References:
- Claude Desktop MDM docs: https://support.claude.com/en/articles/14680741
"""

import json
import uuid
from typing import Any

# =============================================================================
# MDM Key Definitions
# =============================================================================

# Core inference provider settings
MDM_KEYS_INFERENCE = {
    "inferenceProvider",           # "bedrock" | "anthropic"
    "inferenceBedrockRegion",      # AWS region for Bedrock API
    "inferenceBedrockProfile",     # AWS profile name (for credential_process)
    "inferenceCredentialKind",     # "interactive" for IDC SSO
    "inferenceCredentialHelper",   # Path to credential helper binary
    "inferenceCredentialHelperTtlSec",  # TTL for credential helper cache
    "inferenceCredentialHelperSilentRefreshEnabled",  # Enable silent refresh
    "inferenceModels",             # List of allowed models
    "inferenceSessionLifetimeSec", # Session lifetime before re-auth
}

# IAM Identity Center SSO settings
MDM_KEYS_IDC_SSO = {
    "inferenceBedrockSsoStartUrl",   # IDC portal URL
    "inferenceBedrockSsoRegion",     # IDC region
    "inferenceBedrockSsoAccountId",  # AWS account ID
    "inferenceBedrockSsoRoleName",   # Permission set / role name
}

# Bootstrap dynamic configuration
MDM_KEYS_BOOTSTRAP = {
    "bootstrapEnabled",    # Enable dynamic config
    "bootstrapUrl",        # URL to fetch config from
    "bootstrapOidc",       # OIDC config for bootstrap auth (JSON string)
}

# Tool and feature controls
MDM_KEYS_POLICIES = {
    "disabledBuiltinTools",        # List of disabled tools
    "builtinToolPolicy",           # Per-tool policy overrides
    "isLocalDevMcpEnabled",        # Allow user MCP servers
    "isDesktopExtensionEnabled",   # Allow desktop extensions
    "isDesktopExtensionSignatureRequired",  # Require signed extensions
    "isDesktopExtensionDirectoryEnabled",   # Allow extension directory
    "coworkTabEnabled",            # Enable Cowork tab
    "disableBundledSkills",        # Disable built-in skills
    "disableDeploymentModeChooser", # Lock to configured provider
}

# Workspace and network restrictions
MDM_KEYS_RESTRICTIONS = {
    "allowedWorkspaceFolders",     # List of allowed folders
    "coworkEgressAllowedHosts",    # Network egress allowlist
}

# MCP server configuration
MDM_KEYS_MCP = {
    "managedMcpServers",           # Remote MCP servers (JSON string)
    "mcpServers",                  # Local MCP server templates
}

# Telemetry / OTEL settings
MDM_KEYS_TELEMETRY = {
    "otlpEndpoint",                # OTEL collector endpoint
    "otlpProtocol",                # "http/protobuf" | "grpc"
    "otlpHeaders",                 # Additional headers (JSON string)
}

# Organization settings
MDM_KEYS_ORG = {
    "deploymentOrganizationUuid",  # Org identifier for MDM
    "isClaudeCodeForDesktopEnabled",  # Enable Claude Code features
}

# All MDM keys combined
ALL_MDM_KEYS = (
    MDM_KEYS_INFERENCE |
    MDM_KEYS_IDC_SSO |
    MDM_KEYS_BOOTSTRAP |
    MDM_KEYS_POLICIES |
    MDM_KEYS_RESTRICTIONS |
    MDM_KEYS_MCP |
    MDM_KEYS_TELEMETRY |
    MDM_KEYS_ORG
)

# =============================================================================
# Default Values
# =============================================================================

DEFAULT_INFERENCE_REGION = "us-east-1"
DEFAULT_SESSION_LIFETIME_SEC = 28800  # 8 hours
DEFAULT_CREDENTIAL_HELPER_TTL_SEC = 3500  # Just under 1 hour STS token lifetime

# Default feature toggles (most permissive)
DEFAULT_POLICIES = {
    "isLocalDevMcpEnabled": True,
    "isDesktopExtensionEnabled": True,
    "isDesktopExtensionSignatureRequired": True,
    "isDesktopExtensionDirectoryEnabled": True,
    "coworkTabEnabled": True,
    "disableBundledSkills": False,
    "disableDeploymentModeChooser": True,  # Lock to Bedrock by default
    "isClaudeCodeForDesktopEnabled": True,
}

# =============================================================================
# Model ID Utilities
# =============================================================================


def normalize_model_id(model_id: str) -> str:
    """Normalize a model ID to the full Bedrock inference profile format.

    Ensures model_id has proper prefix for Bedrock (us. or global.).

    Args:
        model_id: Raw model ID (e.g., "anthropic.claude-sonnet-4")

    Returns:
        Normalized model ID (e.g., "us.anthropic.claude-sonnet-4")
    """
    if not model_id:
        return model_id

    # Already has proper prefix
    if model_id.startswith(("us.", "global.")):
        return model_id

    # Add us. prefix for anthropic models
    if model_id.startswith("anthropic."):
        return f"us.{model_id}"

    # Default to us.anthropic. prefix
    return f"us.anthropic.{model_id}"


def infer_model_tier(model_id: str) -> str | None:
    """Infer the Claude model tier from a model ID.

    Args:
        model_id: Bedrock/CRIS model ID

    Returns:
        Tier name ("opus", "sonnet", "haiku", "fable") or None if unknown
    """
    model_lower = model_id.lower()
    if "opus" in model_lower:
        return "opus"
    if "sonnet" in model_lower:
        return "sonnet"
    if "haiku" in model_lower:
        return "haiku"
    if "fable" in model_lower:
        return "fable"
    return None


def build_inference_models(
    models: list[dict | str],
    include_tier_info: bool = False
) -> list[dict | str]:
    """Build the inferenceModels array for MDM config.

    Args:
        models: List of model specs. Each can be:
            - str: Simple model ID or alias
            - dict: {"modelId": "...", "modelName": "..."} or
                   {"name": "...", "labelOverride": "..."}
        include_tier_info: If True, add anthropicFamilyTier/isFamilyDefault

    Returns:
        List suitable for the inferenceModels MDM key
    """
    result = []
    tier_seen: dict[str, bool] = {}

    for model in models:
        if isinstance(model, str):
            # Simple alias (opus, sonnet, haiku) - keep as-is for client resolution
            if model in ("opus", "sonnet", "haiku", "fable"):
                result.append(model)
            else:
                # Full model ID
                normalized = normalize_model_id(model)
                if include_tier_info:
                    entry: dict[str, Any] = {"name": normalized}
                    tier = infer_model_tier(normalized)
                    if tier:
                        entry["anthropicFamilyTier"] = tier
                        if tier not in tier_seen:
                            entry["isFamilyDefault"] = True
                            tier_seen[tier] = True
                    result.append(entry)
                else:
                    result.append({"name": normalized})
        else:
            # Dict format - normalize and pass through
            model_id = model.get("modelId") or model.get("name", "")
            model_name = model.get("modelName") or model.get("labelOverride", "")

            normalized = normalize_model_id(model_id)
            entry = {"name": normalized}
            if model_name:
                entry["labelOverride"] = model_name

            if include_tier_info:
                tier = infer_model_tier(normalized)
                if tier:
                    entry["anthropicFamilyTier"] = tier
                    if tier not in tier_seen:
                        entry["isFamilyDefault"] = True
                        tier_seen[tier] = True

            result.append(entry)

    return result


# =============================================================================
# Config Builder
# =============================================================================


def build_base_config(
    bedrock_region: str = DEFAULT_INFERENCE_REGION,
    models: list[dict | str] | None = None,
    deployment_uuid: str | None = None,
) -> dict[str, Any]:
    """Build the base MDM configuration with common settings.

    Args:
        bedrock_region: AWS region for Bedrock API
        models: List of model specs
        deployment_uuid: Organization deployment UUID (generated if not provided)

    Returns:
        Base MDM config dict
    """
    config: dict[str, Any] = {
        "inferenceProvider": "bedrock",
        "inferenceBedrockRegion": bedrock_region,
    }

    # Add default policies
    config.update(DEFAULT_POLICIES)

    # Add models if provided
    if models:
        config["inferenceModels"] = build_inference_models(models)

    # Add deployment UUID
    config["deploymentOrganizationUuid"] = deployment_uuid or str(uuid.uuid4()).upper()

    return config


def add_idc_sso_config(
    config: dict[str, Any],
    start_url: str,
    region: str,
    account_id: str,
    role_name: str,
) -> None:
    """Add IAM Identity Center SSO configuration to MDM config.

    Args:
        config: MDM config dict to modify
        start_url: IDC portal start URL
        region: IDC region
        account_id: AWS account ID
        role_name: Permission set / role name
    """
    config["inferenceCredentialKind"] = "interactive"
    config["inferenceBedrockSsoStartUrl"] = start_url
    config["inferenceBedrockSsoRegion"] = region
    config["inferenceBedrockSsoAccountId"] = account_id
    config["inferenceBedrockSsoRoleName"] = role_name


def add_bootstrap_config(
    config: dict[str, Any],
    bootstrap_url: str,
    oidc_config: dict[str, str] | None = None,
) -> None:
    """Add bootstrap dynamic configuration settings.

    Args:
        config: MDM config dict to modify
        bootstrap_url: URL to fetch dynamic config from
        oidc_config: OIDC config for bootstrap auth:
            {"clientId": "...", "issuer": "...", "scopes": "...", "redirectPort": 8080}
    """
    config["bootstrapEnabled"] = True
    config["bootstrapUrl"] = bootstrap_url

    if oidc_config:
        # bootstrapOidc is stored as a JSON string in MDM
        config["bootstrapOidc"] = oidc_config  # Will be serialized by generators


def add_policies(
    config: dict[str, Any],
    disabled_tools: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
    allowed_folders: list[dict | str] | None = None,
    egress_hosts: list[str] | None = None,
    feature_toggles: dict[str, bool] | None = None,
) -> None:
    """Add policy settings to MDM config.

    Args:
        config: MDM config dict to modify
        disabled_tools: List of tool names to disable completely
        tool_policies: Per-tool policy overrides (tool -> "allow"|"ask"|"blocked")
        allowed_folders: List of allowed workspace folders
        egress_hosts: Network egress allowlist
        feature_toggles: Feature toggle overrides
    """
    if disabled_tools:
        config["disabledBuiltinTools"] = disabled_tools

    if tool_policies:
        config["builtinToolPolicy"] = tool_policies

    if allowed_folders:
        # Normalize to list of dicts with 'path' key
        normalized = []
        for folder in allowed_folders:
            if isinstance(folder, str):
                normalized.append({"path": folder})
            else:
                normalized.append(folder)
        config["allowedWorkspaceFolders"] = normalized

    if egress_hosts:
        config["coworkEgressAllowedHosts"] = egress_hosts

    if feature_toggles:
        for key, value in feature_toggles.items():
            if key in MDM_KEYS_POLICIES:
                config[key] = value


def add_mcp_servers(
    config: dict[str, Any],
    managed_servers: list[dict] | None = None,
    local_templates: list[dict] | None = None,
) -> None:
    """Add MCP server configuration.

    Args:
        config: MDM config dict to modify
        managed_servers: Remote HTTPS MCP servers
        local_templates: Local MCP server templates
    """
    if managed_servers:
        config["managedMcpServers"] = managed_servers

    if local_templates:
        config["mcpServers"] = local_templates


def add_telemetry_config(
    config: dict[str, Any],
    otlp_endpoint: str,
    otlp_protocol: str = "http/protobuf",
    otlp_headers: dict[str, str] | None = None,
) -> None:
    """Add telemetry/OTEL configuration.

    Args:
        config: MDM config dict to modify
        otlp_endpoint: OTEL collector endpoint URL
        otlp_protocol: Protocol ("http/protobuf" or "grpc")
        otlp_headers: Additional headers to send
    """
    config["otlpEndpoint"] = otlp_endpoint
    config["otlpProtocol"] = otlp_protocol

    if otlp_headers:
        config["otlpHeaders"] = otlp_headers
