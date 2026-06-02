"""Shared CoWork 3P (Claude Desktop) MDM configuration generation utilities.

Generates the three MDM artifact files that point Claude Desktop at the same
credential_process pipeline that Claude Code CLI uses:

    cowork-3p-config.json    — raw MDM key/value (audit/debug)
    cowork-3p.mobileconfig   — macOS configuration profile (XML plist)
    cowork-3p.reg            — Windows registry file under HKCU\\SOFTWARE\\Policies\\Claude

The MDM payload sets ``inferenceBedrockProfile = ClaudeCode`` (not
``inferenceCredentialHelper``). That makes Claude Desktop go through boto3's
named-profile resolution; the installer wires ``credential_process`` into
``~/.aws/config`` for that named profile, so Desktop reuses the existing auth
binary with no extra artifacts.

Ported from upstream PR #336 (commit cd9510e).
"""

import json
import uuid
from pathlib import Path
from html import escape as xml_escape


# CoWork 3P model aliases — defined by Claude Desktop, resolved client-side.
# These are NOT the CRIS model IDs Claude Code uses via ANTHROPIC_MODEL.
COWORK_DEFAULT_ALIASES = ["opus", "sonnet", "haiku"]


def derive_model_aliases() -> list:
    """Return the default CoWork 3P model aliases."""
    return list(COWORK_DEFAULT_ALIASES)


def build_mdm_config(
    bedrock_region: str,
    model_aliases: list,
    profile_name: str = "ClaudeCode",
) -> dict:
    """Build the base CoWork 3P MDM configuration dictionary.

    Uses ``inferenceBedrockProfile``, which points Claude Desktop at an AWS
    named profile in ``~/.aws/config``. The installer configures that profile
    with ``credential_process = credential-process --profile <name>``, so CoWork
    reuses the same auth pipeline as Claude Code with zero extra artifacts to
    ship.
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


def _mdm_keys(config: dict) -> dict:
    """Return config without internal underscore-prefixed keys."""
    return {k: v for k, v in config.items() if not k.startswith("_")}


def generate_json(output_dir: Path, mdm_config: dict) -> Path:
    """Generate raw MDM configuration JSON file."""
    json_path = output_dir / "cowork-3p-config.json"
    with open(json_path, "w") as f:
        json.dump(_mdm_keys(mdm_config), f, indent=2)
    return json_path


def generate_mobileconfig(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a macOS .mobileconfig XML plist for Claude Cowork 3P."""
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
\t<string>com.smartnews.claude-cowork-bedrock</string>
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


def generate_all(output_dir: Path, mdm_config: dict, console=None) -> list:
    """Generate all three CoWork 3P MDM configuration files.

    Returns the list of generated filenames.
    """
    generated = []

    generate_json(output_dir, mdm_config)
    generated.append("cowork-3p-config.json")
    if console is not None:
        console.print("[green]✓[/green] Generated cowork-3p-config.json")

    generate_mobileconfig(output_dir, mdm_config)
    generated.append("cowork-3p.mobileconfig")
    if console is not None:
        console.print("[green]✓[/green] Generated cowork-3p.mobileconfig (macOS)")

    generate_reg_file(output_dir, mdm_config)
    generated.append("cowork-3p.reg")
    if console is not None:
        console.print("[green]✓[/green] Generated cowork-3p.reg (Windows)")

    return generated
