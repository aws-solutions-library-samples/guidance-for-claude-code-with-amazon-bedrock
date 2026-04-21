# ABOUTME: Shared utilities for generating Claude Cowork 3P MDM configurations
# ABOUTME: Used by both 'ccwb package' and 'ccwb cowork generate' commands

"""Shared CoWork 3P MDM configuration generation utilities."""

import json
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from rich.console import Console

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs

# CoWork 3P model aliases — defined by Anthropic's Claude Desktop client.
# These may differ from the model IDs used by Claude Code (ANTHROPIC_MODEL env var).
# The ccwb cowork generate --models flag allows admins to override if needed.
COWORK_DEFAULT_ALIASES = ["opus", "sonnet", "haiku", "opusplan"]


def derive_model_aliases(profile) -> list[str]:
    """Return the default CoWork 3P model aliases.

    Returns the standard alias list. Admins can override via the --models CLI flag.

    Note: CoWork model aliases (opus, sonnet, haiku, opusplan) are resolved by
    Claude Desktop internally and may differ from the CRIS model IDs configured
    for Claude Code via ANTHROPIC_MODEL.
    """
    return list(COWORK_DEFAULT_ALIASES)


def build_mdm_config(
    bedrock_region: str,
    model_aliases: list[str],
    profile_name: str = "ClaudeCode",
    credential_helper_ttl: int = 3600,
) -> dict:
    """Build the base CoWork 3P MDM configuration dictionary.

    Args:
        bedrock_region: AWS region for Bedrock API calls.
        model_aliases: List of model aliases (e.g., ["opus", "sonnet", "opusplan"]).
        profile_name: Credential process profile name.
        credential_helper_ttl: Cache TTL in seconds for the credential helper.

    Returns:
        Dictionary of MDM configuration key-value pairs.
    """
    return {
        "inferenceProvider": "bedrock",
        "inferenceBedrockRegion": bedrock_region,
        "inferenceModels": model_aliases,
        "inferenceCredentialHelper": (
            f"~/claude-code-with-bedrock/credential-process --profile {profile_name}"
        ),
        "inferenceCredentialHelperTtlSec": credential_helper_ttl,
        "isClaudeCodeForDesktopEnabled": True,
        "isDesktopExtensionEnabled": True,
        "isDesktopExtensionDirectoryEnabled": True,
        "isDesktopExtensionSignatureRequired": True,
        "isLocalDevMcpEnabled": True,
    }


def add_monitoring_config(mdm_config: dict, profile, console: Console) -> None:
    """Add OTLP monitoring endpoint to MDM config if monitoring stack is deployed.

    Modifies mdm_config in place by adding otlpEndpoint and otlpProtocol keys
    if the monitoring CloudFormation stack is found and has a CollectorEndpoint output.

    Uses the boto3-based get_stack_outputs utility to avoid subprocess calls.
    """
    if not profile.monitoring_enabled:
        return

    monitoring_stack = profile.stack_names.get(
        "monitoring", f"{profile.identity_pool_name}-otel-collector"
    )

    try:
        outputs = get_stack_outputs(monitoring_stack, profile.aws_region)
        endpoint = outputs.get("CollectorEndpoint")

        if endpoint:
            mdm_config["otlpEndpoint"] = endpoint
            mdm_config["otlpProtocol"] = "http/protobuf"
            console.print("[dim]Added OTLP endpoint to CoWork 3P config[/dim]")
        else:
            console.print("[dim]Monitoring stack not found — skipping OTLP in CoWork 3P config[/dim]")
    except Exception:
        console.print("[dim]Could not query monitoring stack — skipping OTLP config[/dim]")


def generate_json(output_dir: Path, mdm_config: dict) -> Path:
    """Generate raw MDM configuration JSON file.

    Returns the path to the generated file.
    """
    json_path = output_dir / "cowork-3p-config.json"
    with open(json_path, "w") as f:
        json.dump(mdm_config, f, indent=2)
    return json_path


def generate_mobileconfig(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a macOS .mobileconfig XML plist for Claude Cowork 3P.

    Returns the path to the generated file.
    """
    payload_uuid = str(uuid.uuid4()).upper()
    profile_uuid = str(uuid.uuid4()).upper()

    # Build payload key-value pairs
    payload_items = []
    for key, value in mdm_config.items():
        payload_items.append(f"\t\t\t<key>{key}</key>")
        if isinstance(value, bool):
            payload_items.append(f"\t\t\t<{'true' if value else 'false'}/>")
        elif isinstance(value, int):
            payload_items.append(f"\t\t\t<integer>{value}</integer>")
        elif isinstance(value, list):
            payload_items.append("\t\t\t<array>")
            for item in value:
                payload_items.append(f"\t\t\t\t<string>{xml_escape(str(item))}</string>")
            payload_items.append("\t\t\t</array>")
        else:
            payload_items.append(f"\t\t\t<string>{xml_escape(str(value))}</string>")

    payload_content = "\n".join(payload_items)

    mobileconfig = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>PayloadContent</key>
\t<array>
\t\t<dict>
\t\t\t<key>PayloadType</key>
\t\t\t<string>com.anthropic.claudedesktop</string>
\t\t\t<key>PayloadUUID</key>
\t\t\t<string>{payload_uuid}</string>
\t\t\t<key>PayloadIdentifier</key>
\t\t\t<string>com.anthropic.claudedesktop.config</string>
\t\t\t<key>PayloadDisplayName</key>
\t\t\t<string>Claude Cowork - Bedrock Configuration</string>
\t\t\t<key>PayloadVersion</key>
\t\t\t<integer>1</integer>
{payload_content}
\t\t</dict>
\t</array>
\t<key>PayloadDisplayName</key>
\t<string>Claude Cowork with Amazon Bedrock</string>
\t<key>PayloadIdentifier</key>
\t<string>com.company.claude-cowork-bedrock</string>
\t<key>PayloadType</key>
\t<string>Configuration</string>
\t<key>PayloadUUID</key>
\t<string>{profile_uuid}</string>
\t<key>PayloadVersion</key>
\t<integer>1</integer>
</dict>
</plist>
"""

    mobileconfig_path = output_dir / "cowork-3p.mobileconfig"
    with open(mobileconfig_path, "w") as f:
        f.write(mobileconfig)
    return mobileconfig_path


def generate_reg_file(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a Windows .reg file for Claude Cowork 3P.

    Returns the path to the generated file.
    """
    reg_key = r"HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Anthropic\Claude Desktop"

    lines = ["Windows Registry Editor Version 5.00", "", f"[{reg_key}]"]

    for key, value in mdm_config.items():
        if isinstance(value, bool):
            dword_val = 1 if value else 0
            lines.append(f'"{key}"=dword:{dword_val:08x}')
        elif isinstance(value, int):
            lines.append(f'"{key}"=dword:{value:08x}')
        elif isinstance(value, list):
            # Store arrays as JSON-encoded string with escaped inner quotes
            json_str = json.dumps(value).replace('"', '\\"')
            lines.append(f'"{key}"="{json_str}"')
        else:
            # Escape backslashes for .reg format
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{key}"="{escaped}"')

    lines.append("")  # Trailing newline

    reg_path = output_dir / "cowork-3p.reg"
    with open(reg_path, "w", newline="\r\n") as f:
        f.write("\n".join(lines))
    return reg_path


def generate_all(output_dir: Path, mdm_config: dict, console: Console) -> list[str]:
    """Generate all three CoWork 3P MDM configuration files.

    Args:
        output_dir: Directory to write files to.
        mdm_config: MDM configuration dictionary.
        console: Rich console for status output.

    Returns:
        List of generated filenames.
    """
    generated = []

    generate_json(output_dir, mdm_config)
    generated.append("cowork-3p-config.json")
    console.print("[green]✓[/green] Generated cowork-3p-config.json")

    generate_mobileconfig(output_dir, mdm_config)
    generated.append("cowork-3p.mobileconfig")
    console.print("[green]✓[/green] Generated cowork-3p.mobileconfig (macOS)")

    generate_reg_file(output_dir, mdm_config)
    generated.append("cowork-3p.reg")
    console.print("[green]✓[/green] Generated cowork-3p.reg (Windows)")

    return generated
