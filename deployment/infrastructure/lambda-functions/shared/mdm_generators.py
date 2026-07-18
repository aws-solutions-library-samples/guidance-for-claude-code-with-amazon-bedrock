# ABOUTME: Shared MDM file generators for macOS mobileconfig and Windows registry
# ABOUTME: Used by idc-landing-page, bootstrap-server, and ccwb cowork generate

"""MDM File Generators.

This module provides functions to generate platform-specific MDM configuration
files (macOS mobileconfig, Windows registry) from a common MDM config dict.
"""

import json
import uuid
from typing import Any

# =============================================================================
# macOS Mobileconfig Generator
# =============================================================================


def generate_mobileconfig(
    config: dict[str, Any],
    profile_identifier: str = "default",
    profile_display_name: str = "Claude Desktop",
) -> str:
    """Generate a macOS mobileconfig XML file from MDM config.

    Args:
        config: MDM configuration dict
        profile_identifier: Unique identifier for the profile (used in bundle ID)
        profile_display_name: Human-readable profile name

    Returns:
        XML string for the mobileconfig file
    """
    payload_uuid = str(uuid.uuid4()).upper()
    deployment_uuid = config.get("deploymentOrganizationUuid", str(uuid.uuid4()).upper())

    # Build policy keys
    policy_keys = []

    # Bootstrap configuration
    if config.get("bootstrapEnabled"):
        policy_keys.append("				<key>bootstrapEnabled</key>\n				<true/>")
        if config.get("bootstrapUrl"):
            policy_keys.append(f'				<key>bootstrapUrl</key>\n				<string>{config["bootstrapUrl"]}</string>')
        if config.get("bootstrapOidc"):
            oidc_json = json.dumps(config["bootstrapOidc"]) if isinstance(config["bootstrapOidc"], dict) else config["bootstrapOidc"]
            policy_keys.append(f'				<key>bootstrapOidc</key>\n				<string>{oidc_json}</string>')

    # Disabled tools
    if config.get("disabledBuiltinTools"):
        policy_keys.append(f'				<key>disabledBuiltinTools</key>\n				<string>{json.dumps(config["disabledBuiltinTools"])}</string>')

    # Tool policies
    if config.get("builtinToolPolicy"):
        policy_keys.append(f'				<key>builtinToolPolicy</key>\n				<string>{json.dumps(config["builtinToolPolicy"])}</string>')

    # Feature toggles (only add non-default values)
    if "isLocalDevMcpEnabled" in config and not config["isLocalDevMcpEnabled"]:
        policy_keys.append("				<key>isLocalDevMcpEnabled</key>\n				<false/>")

    if "isDesktopExtensionEnabled" in config and not config["isDesktopExtensionEnabled"]:
        policy_keys.append("				<key>isDesktopExtensionEnabled</key>\n				<false/>")

    if config.get("isDesktopExtensionSignatureRequired"):
        policy_keys.append("				<key>isDesktopExtensionSignatureRequired</key>\n				<true/>")

    if "coworkTabEnabled" in config and not config["coworkTabEnabled"]:
        policy_keys.append("				<key>coworkTabEnabled</key>\n				<false/>")

    if config.get("disableBundledSkills"):
        policy_keys.append("				<key>disableBundledSkills</key>\n				<true/>")

    if config.get("disableDeploymentModeChooser"):
        policy_keys.append("				<key>disableDeploymentModeChooser</key>\n				<true/>")

    # Workspace and network restrictions
    if config.get("allowedWorkspaceFolders"):
        policy_keys.append(f'				<key>allowedWorkspaceFolders</key>\n				<string>{json.dumps(config["allowedWorkspaceFolders"])}</string>')

    if config.get("coworkEgressAllowedHosts"):
        policy_keys.append(f'				<key>coworkEgressAllowedHosts</key>\n				<string>{json.dumps(config["coworkEgressAllowedHosts"])}</string>')

    # MCP servers
    if config.get("managedMcpServers"):
        policy_keys.append(f'				<key>managedMcpServers</key>\n				<string>{json.dumps(config["managedMcpServers"])}</string>')

    # OTEL
    if config.get("otlpEndpoint"):
        policy_keys.append(f'				<key>otlpEndpoint</key>\n				<string>{config["otlpEndpoint"]}</string>')
        if config.get("otlpProtocol"):
            policy_keys.append(f'				<key>otlpProtocol</key>\n				<string>{config["otlpProtocol"]}</string>')
        if config.get("otlpHeaders"):
            headers_json = json.dumps(config["otlpHeaders"]) if isinstance(config["otlpHeaders"], dict) else config["otlpHeaders"]
            policy_keys.append(f'				<key>otlpHeaders</key>\n				<string>{headers_json}</string>')

    policy_keys_str = "\n".join(policy_keys)

    # Build inference models JSON
    inference_models_json = json.dumps(config.get("inferenceModels", []))

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
	<dict>
		<key>PayloadContent</key>
		<array>
			<dict>
				<key>PayloadType</key>
				<string>com.anthropic.claudefordesktop</string>
				<key>PayloadIdentifier</key>
				<string>com.anthropic.claudefordesktop.settings</string>
				<key>PayloadUUID</key>
				<string>{payload_uuid}</string>
				<key>PayloadVersion</key>
				<integer>1</integer>
				<key>PayloadDisplayName</key>
				<string>Claude Desktop</string>
				<key>inferenceProvider</key>
				<string>{config.get("inferenceProvider", "bedrock")}</string>
				<key>inferenceCredentialKind</key>
				<string>{config.get("inferenceCredentialKind", "interactive")}</string>
				<key>inferenceBedrockRegion</key>
				<string>{config.get("inferenceBedrockRegion", "us-east-1")}</string>
				<key>inferenceBedrockSsoStartUrl</key>
				<string>{config.get("inferenceBedrockSsoStartUrl", "")}</string>
				<key>inferenceBedrockSsoRegion</key>
				<string>{config.get("inferenceBedrockSsoRegion", "us-east-1")}</string>
				<key>inferenceBedrockSsoAccountId</key>
				<string>{config.get("inferenceBedrockSsoAccountId", "")}</string>
				<key>inferenceBedrockSsoRoleName</key>
				<string>{config.get("inferenceBedrockSsoRoleName", "")}</string>
				<key>inferenceModels</key>
				<string>{inference_models_json}</string>
				<key>deploymentOrganizationUuid</key>
				<string>{deployment_uuid}</string>
{policy_keys_str}
			</dict>
		</array>
		<key>PayloadDisplayName</key>
		<string>{profile_display_name}</string>
		<key>PayloadIdentifier</key>
		<string>com.anthropic.claudefordesktop.{profile_identifier}</string>
		<key>PayloadType</key>
		<string>Configuration</string>
		<key>PayloadUUID</key>
		<string>{deployment_uuid}</string>
		<key>PayloadVersion</key>
		<integer>1</integer>
		<key>PayloadScope</key>
		<string>User</string>
	</dict>
</plist>'''


# =============================================================================
# Windows Registry Generator
# =============================================================================


def generate_reg_file(
    config: dict[str, Any],
    profile_identifier: str = "default",
) -> str:
    """Generate a Windows registry file from MDM config.

    The output is UTF-16 LE encoded with BOM as required by Windows regedit.

    Args:
        config: MDM configuration dict
        profile_identifier: Used in comments only

    Returns:
        Registry file content string (encode with UTF-16 LE before writing)
    """
    # Escape quotes for registry string values
    def escape_reg(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    inference_models_json = escape_reg(json.dumps(config.get("inferenceModels", [])))

    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"; Claude Desktop MDM Configuration - {profile_identifier}",
        "",
        "[HKEY_CURRENT_USER\\Software\\Policies\\Anthropic\\Claude]",
        f'"inferenceProvider"="{config.get("inferenceProvider", "bedrock")}"',
        f'"inferenceCredentialKind"="{config.get("inferenceCredentialKind", "interactive")}"',
        f'"inferenceBedrockRegion"="{config.get("inferenceBedrockRegion", "us-east-1")}"',
        f'"inferenceBedrockSsoStartUrl"="{config.get("inferenceBedrockSsoStartUrl", "")}"',
        f'"inferenceBedrockSsoRegion"="{config.get("inferenceBedrockSsoRegion", "us-east-1")}"',
        f'"inferenceBedrockSsoAccountId"="{config.get("inferenceBedrockSsoAccountId", "")}"',
        f'"inferenceBedrockSsoRoleName"="{config.get("inferenceBedrockSsoRoleName", "")}"',
        f'"inferenceModels"="{inference_models_json}"',
        f'"deploymentOrganizationUuid"="{config.get("deploymentOrganizationUuid", "")}"',
    ]

    # Bootstrap configuration
    if config.get("bootstrapEnabled"):
        lines.append('"bootstrapEnabled"=dword:00000001')
        if config.get("bootstrapUrl"):
            lines.append(f'"bootstrapUrl"="{config["bootstrapUrl"]}"')
        if config.get("bootstrapOidc"):
            oidc_json = json.dumps(config["bootstrapOidc"]) if isinstance(config["bootstrapOidc"], dict) else config["bootstrapOidc"]
            lines.append(f'"bootstrapOidc"="{escape_reg(oidc_json)}"')

    # Disabled tools
    if config.get("disabledBuiltinTools"):
        lines.append(f'"disabledBuiltinTools"="{escape_reg(json.dumps(config["disabledBuiltinTools"]))}"')

    # Tool policies
    if config.get("builtinToolPolicy"):
        lines.append(f'"builtinToolPolicy"="{escape_reg(json.dumps(config["builtinToolPolicy"]))}"')

    # Feature toggles
    if "isLocalDevMcpEnabled" in config:
        val = "1" if config["isLocalDevMcpEnabled"] else "0"
        lines.append(f'"isLocalDevMcpEnabled"=dword:0000000{val}')

    if "isDesktopExtensionEnabled" in config:
        val = "1" if config["isDesktopExtensionEnabled"] else "0"
        lines.append(f'"isDesktopExtensionEnabled"=dword:0000000{val}')

    if config.get("isDesktopExtensionSignatureRequired"):
        lines.append('"isDesktopExtensionSignatureRequired"=dword:00000001')

    if "coworkTabEnabled" in config:
        val = "1" if config["coworkTabEnabled"] else "0"
        lines.append(f'"coworkTabEnabled"=dword:0000000{val}')

    if config.get("disableBundledSkills"):
        lines.append('"disableBundledSkills"=dword:00000001')

    if config.get("disableDeploymentModeChooser"):
        lines.append('"disableDeploymentModeChooser"=dword:00000001')

    # Workspace and network restrictions
    if config.get("allowedWorkspaceFolders"):
        lines.append(f'"allowedWorkspaceFolders"="{escape_reg(json.dumps(config["allowedWorkspaceFolders"]))}"')

    if config.get("coworkEgressAllowedHosts"):
        lines.append(f'"coworkEgressAllowedHosts"="{escape_reg(json.dumps(config["coworkEgressAllowedHosts"]))}"')

    # MCP servers
    if config.get("managedMcpServers"):
        lines.append(f'"managedMcpServers"="{escape_reg(json.dumps(config["managedMcpServers"]))}"')

    # OTEL
    if config.get("otlpEndpoint"):
        lines.append(f'"otlpEndpoint"="{config["otlpEndpoint"]}"')
        if config.get("otlpProtocol"):
            lines.append(f'"otlpProtocol"="{config["otlpProtocol"]}"')
        if config.get("otlpHeaders"):
            headers_json = json.dumps(config["otlpHeaders"]) if isinstance(config["otlpHeaders"], dict) else config["otlpHeaders"]
            lines.append(f'"otlpHeaders"="{escape_reg(headers_json)}"')

    lines.append("")  # Trailing newline
    return "\r\n".join(lines)


# =============================================================================
# JSON Config Generator
# =============================================================================


def generate_json_config(config: dict[str, Any]) -> str:
    """Generate a JSON configuration file from MDM config.

    This is the raw config that can be used for manual setup or
    served by the bootstrap API.

    Args:
        config: MDM configuration dict

    Returns:
        Pretty-printed JSON string
    """
    return json.dumps(config, indent=2)
