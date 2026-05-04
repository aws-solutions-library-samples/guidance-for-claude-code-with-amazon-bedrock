# ABOUTME: Shared utilities for generating Claude Cowork 3P MDM configurations
# ABOUTME: Used by both 'ccwb package' and 'ccwb cowork generate' commands

"""Shared CoWork 3P MDM configuration generation utilities."""

import json
import uuid
from pathlib import Path
from html import escape as xml_escape

from rich.console import Console

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs

# CoWork 3P model aliases — defined by Anthropic's Claude Desktop client.
# These may differ from the model IDs used by Claude Code (ANTHROPIC_MODEL env var).
# The ccwb cowork generate --models flag allows admins to override if needed.
COWORK_DEFAULT_ALIASES = ["opus", "sonnet", "haiku", "opusplan"]


def derive_model_aliases() -> list[str]:
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
) -> dict:
    """Build the base CoWork 3P MDM configuration dictionary.

    Uses inferenceBedrockProfile, which points Claude Desktop at an AWS named
    profile in ~/.aws/config. The installer already configures that profile with
    credential_process = credential-process --profile <name>, so CoWork reuses
    the same auth pipeline as Claude Code with zero extra artifacts to ship.

    Ref: https://claude.com/docs/cowork/3p/bedrock

    Args:
        bedrock_region: AWS region for Bedrock API calls.
        model_aliases: List of model aliases (e.g., ["opus", "sonnet", "opusplan"]).
        profile_name: AWS named profile (matches ~/.aws/config stanza).

    Returns:
        Dictionary of MDM configuration key-value pairs.
    """
    return {
        "inferenceProvider": "bedrock",
        "inferenceBedrockRegion": bedrock_region,
        "inferenceBedrockProfile": profile_name,
        "inferenceModels": model_aliases,
        "isClaudeCodeForDesktopEnabled": True,
        "isDesktopExtensionEnabled": True,
        "isDesktopExtensionDirectoryEnabled": True,
        "isDesktopExtensionSignatureRequired": True,
        "isLocalDevMcpEnabled": True,
    }



def add_monitoring_config(mdm_config: dict, profile, console: Console) -> None:
    """Add OTLP endpoint to MDM config if monitoring stack is deployed."""
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
            console.print(f"[dim]OTLP endpoint: {endpoint}[/dim]")
        else:
            console.print("[dim]Monitoring stack not found — skipping OTLP config[/dim]")
    except Exception:
        console.print("[dim]Could not query monitoring stack — skipping OTLP config[/dim]")


def _mdm_keys(config: dict) -> dict:
    """Return config without internal underscore-prefixed keys."""
    return {k: v for k, v in config.items() if not k.startswith("_")}


def generate_json(output_dir: Path, mdm_config: dict) -> Path:
    """Generate raw MDM configuration JSON file.

    Returns the path to the generated file.
    """
    json_path = output_dir / "cowork-3p-config.json"
    with open(json_path, "w") as f:
        json.dump(_mdm_keys(mdm_config), f, indent=2)
    return json_path


def generate_mobileconfig(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a macOS .mobileconfig XML plist for Claude Cowork 3P.

    Returns the path to the generated file.
    """
    payload_uuid = str(uuid.uuid4()).upper()
    profile_uuid = str(uuid.uuid4()).upper()

    # Per Claude CoWork docs: all values are stored as strings in the OS preference
    # store, even booleans, integers, and arrays. Arrays must be JSON-encoded strings.
    payload_items = []
    for key, value in _mdm_keys(mdm_config).items():
        payload_items.append(f"\t\t\t<key>{xml_escape(key)}</key>")
        if isinstance(value, bool):
            string_value = "true" if value else "false"
        elif isinstance(value, (list, dict)):
            string_value = json.dumps(value)
        else:
            string_value = str(value)
        payload_items.append(f"\t\t\t<string>{xml_escape(string_value)}</string>")

    payload_content = "\n".join(payload_items)

    mobileconfig = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>PayloadContent</key>
\t<array>
\t\t<dict>
\t\t\t<key>PayloadType</key>
\t\t\t<string>com.anthropic.claudefordesktop</string>
\t\t\t<key>PayloadUUID</key>
\t\t\t<string>{payload_uuid}</string>
\t\t\t<key>PayloadIdentifier</key>
\t\t\t<string>com.anthropic.claudefordesktop.config</string>
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

    All values are stored as REG_SZ strings — booleans, integers, and arrays
    included — matching what Claude Desktop reads from the registry.

    Returns the path to the generated file.
    """
    reg_key = r"HKEY_CURRENT_USER\SOFTWARE\Policies\Claude"

    lines = ["Windows Registry Editor Version 5.00", "", f"[{reg_key}]"]

    for key, value in _mdm_keys(mdm_config).items():
        if isinstance(value, bool):
            string_value = "true" if value else "false"
        elif isinstance(value, (list, dict)):
            string_value = json.dumps(value)
        else:
            string_value = str(value)
        # Escape backslashes and quotes for .reg REG_SZ format
        escaped = string_value.replace("\\", "\\\\").replace('"', '\\"')
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
