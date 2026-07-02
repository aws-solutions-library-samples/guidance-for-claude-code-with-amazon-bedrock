# ABOUTME: Shared utilities for generating Claude Cowork 3P MDM configurations
# ABOUTME: Used by both 'ccwb package' and 'ccwb cowork generate' commands

"""Shared CoWork 3P MDM configuration generation utilities."""

import json
import uuid
from html import escape as xml_escape
from pathlib import Path

from rich.console import Console

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs

# CoWork 3P model aliases — defined by Anthropic's Claude Desktop client.
# These may differ from the model IDs used by Claude Code (ANTHROPIC_MODEL env var).
# The ccwb cowork generate --models flag allows admins to override if needed.
COWORK_DEFAULT_ALIASES = ["opus", "sonnet", "haiku"]

# Mapping from tier alias to anthropicFamilyTier value used by Claude Desktop
# for tier shortcut resolution (e.g., "opus" shortcut resolves to your configured opus model)
FAMILY_TIER_MAP = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
    "fable": "fable",
}


def derive_model_aliases() -> list[str]:
    """Return the default CoWork 3P model aliases.

    Returns the standard alias list. Admins can override via the --models CLI flag.

    Note: CoWork model aliases (opus, sonnet, haiku) are resolved by Claude Desktop
    internally and may differ from the CRIS model IDs configured for Claude Code via
    ANTHROPIC_MODEL.
    """
    return list(COWORK_DEFAULT_ALIASES)


def build_inference_models(model_aliases: list[str]) -> list[dict[str, str | bool]]:
    """Build inferenceModels entries with anthropicFamilyTier and isFamilyDefault.

    Claude Desktop v1.13576+ supports object entries in inferenceModels with:
    - name: The model ID (e.g., CRIS inference profile ID for Bedrock)
    - anthropicFamilyTier: The Claude tier this model stands in for (opus/sonnet/haiku)
    - isFamilyDefault: Whether this is the default model for the tier
    - labelOverride: Optional display name override

    When using simple string aliases ("opus", "sonnet", "haiku"), Claude Desktop
    resolves them internally. The object format gives administrators explicit
    control over which model IDs map to which tier shortcuts.

    For backward compatibility, if aliases are simple tier names (opus/sonnet/haiku),
    we still use the string format since Claude Desktop handles resolution. Use
    build_inference_models_explicit() for full CRIS model IDs with tier tagging.

    Args:
        model_aliases: List of model aliases or CRIS model IDs.

    Returns:
        List suitable for the inferenceModels MDM key. Returns simple strings
        for tier aliases, or object entries for explicit model IDs.
    """
    # If all entries are simple tier aliases, return as-is for backward compat
    all_simple = all(alias in FAMILY_TIER_MAP for alias in model_aliases)
    if all_simple:
        return model_aliases

    # Otherwise, build object entries with anthropicFamilyTier
    models = []
    tier_seen: dict[str, bool] = {}  # Track which tiers have a default set
    for alias in model_aliases:
        if alias in FAMILY_TIER_MAP:
            # Simple alias — keep as string
            models.append(alias)
        else:
            # Looks like a full model ID — try to infer tier from name
            entry: dict[str, str | bool] = {"name": alias}
            tier = _infer_tier_from_model_id(alias)
            if tier:
                entry["anthropicFamilyTier"] = tier
                if tier not in tier_seen:
                    entry["isFamilyDefault"] = True
                    tier_seen[tier] = True
            models.append(entry)
    return models


def _infer_tier_from_model_id(model_id: str) -> str | None:
    """Infer the anthropicFamilyTier from a Bedrock/CRIS model ID.

    Matches patterns like:
    - global.anthropic.claude-opus-4-8 → opus
    - us.anthropic.claude-sonnet-4-6-v1:0 → sonnet
    - anthropic.claude-haiku-4-5-20251001-v1:0 → haiku
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


def _credential_process_path(profile_name: str) -> dict[str, str]:
    """Return platform-specific credential-process paths for inferenceCredentialHelper.

    The installer places the binary at a predictable location per-platform:
    - macOS/Linux: ~/claude-code-with-bedrock/credential-process
    - Windows: %USERPROFILE%\\claude-code-with-bedrock\\credential-process.exe

    For MDM deployment we use the tilde (~) shorthand which Claude Desktop
    resolves to the user's home directory on all platforms.
    """
    return {
        "unix": f"~/claude-code-with-bedrock/credential-process --desktop --profile {profile_name}",
        "windows": f"%USERPROFILE%\\claude-code-with-bedrock\\credential-process.exe --desktop --profile {profile_name}",
    }


def build_mdm_config(
    bedrock_region: str,
    model_aliases: list[str],
    profile_name: str = "ClaudeCode",
    extra_keys: dict[str, str] | None = None,
    credential_mode: str = "helper",
    credential_helper_ttl_sec: int = 3500,
) -> dict:
    """Build the base CoWork 3P MDM configuration dictionary.

    Supports two credential modes:

    - "helper" (default, recommended): Uses inferenceCredentialHelper, which gives
      Claude Desktop direct control over the credential lifecycle. The app caches
      the helper's output for `credential_helper_ttl_sec` seconds and automatically
      re-runs it on expiry — including mid-session silent refresh. This eliminates
      the stale-credential bug where CoWork requires a restart after token expiry.

    - "profile" (legacy): Uses inferenceBedrockProfile, which delegates credential
      resolution to the AWS SDK via ~/.aws/config. This works but credential refresh
      depends on boto3's internal session caching, which doesn't reliably trigger
      re-authentication in the CoWork process lifecycle.

    Ref: https://claude.com/docs/third-party/claude-desktop/credential-helper

    Args:
        bedrock_region: AWS region for Bedrock API calls.
        model_aliases: List of model aliases (e.g., ["opus", "sonnet", "haiku"]).
        profile_name: AWS named profile (matches ~/.aws/config stanza).
        extra_keys: Optional dictionary of additional MDM keys to merge into the
            configuration. Values should be strings (JSON-encoded for complex types).
        credential_mode: "helper" or "profile" (default: "helper").
        credential_helper_ttl_sec: Cache TTL for the credential helper output in
            seconds (default: 3500, slightly under the 1h STS token lifetime to
            ensure refresh happens before expiry).

    Returns:
        Dictionary of MDM configuration key-value pairs.
    """
    config = {
        "inferenceProvider": "bedrock",
        "inferenceBedrockRegion": bedrock_region,
        "inferenceModels": build_inference_models(model_aliases),
        "isClaudeCodeForDesktopEnabled": True,
        "isDesktopExtensionEnabled": True,
        "isDesktopExtensionDirectoryEnabled": True,
        "isDesktopExtensionSignatureRequired": True,
        "isLocalDevMcpEnabled": True,
    }

    if credential_mode == "helper":
        # Direct credential helper — Claude Desktop manages the credential lifecycle.
        # Uses the same credential-process binary but invoked directly by the app
        # instead of indirectly via the AWS SDK's credential_process chain.
        paths = _credential_process_path(profile_name)
        # Use the Unix path by default; installers for Windows will substitute.
        # MDM platforms (Jamf, Intune) typically deploy platform-specific configs.
        config["inferenceCredentialHelper"] = paths["unix"]
        config["inferenceCredentialHelperTtlSec"] = str(credential_helper_ttl_sec)
        config["inferenceCredentialHelperSilentRefreshEnabled"] = "true"
        # Keep the AWS profile as fallback for SDK-level operations (region, etc.)
        config["inferenceBedrockProfile"] = profile_name
    else:
        # Legacy profile mode — rely on AWS SDK credential_process chain.
        config["inferenceBedrockProfile"] = profile_name

    if extra_keys:
        config.update(extra_keys)

    return config


def add_monitoring_config(mdm_config: dict, profile, console: Console) -> None:
    """Add OTLP endpoint to MDM config if monitoring stack is deployed."""
    if not profile.monitoring_enabled:
        return

    monitoring_mode = getattr(profile, "monitoring_mode", "central")

    if monitoring_mode == "sidecar":
        # Sidecar mode: CoWork sends OTLP logs to the local otel-helper proxy,
        # which SigV4-signs and forwards to CloudWatch OTLP.
        # IMPORTANT: otel-helper must be running in proxy mode (otel-helper --proxy)
        # for CoWork telemetry to work. Without it, events are silently dropped
        # (connection refused on localhost:4318).
        mdm_config["otlpEndpoint"] = "http://localhost:4318"
        mdm_config["otlpProtocol"] = "http/protobuf"
        console.print("[dim]Sidecar mode \u2014 CoWork telemetry via local otel-helper proxy (localhost:4318)[/dim]")
        console.print("[dim]  \u2514\u2500 Requires: otel-helper --proxy running on this device[/dim]")

        # Add attribution headers if available (static, per-MDM-group)
        cowork_token = getattr(profile, "cowork_service_token", None)
        if cowork_token:
            mdm_config["otlpHeaders"] = json.dumps({"X-Cowork-Token": cowork_token})
        return

    # Try to resolve collector endpoint from stack outputs first,
    # fall back to profile.otel_collector_endpoint if stack query fails.
    endpoint = None
    monitoring_stack = profile.stack_names.get("monitoring", f"{profile.identity_pool_name}-otel-collector")
    try:
        outputs = get_stack_outputs(monitoring_stack, profile.aws_region)
        endpoint = outputs.get("CollectorEndpoint")
    except Exception:
        pass

    if not endpoint:
        # Fallback: use profile-level endpoint if configured
        endpoint = getattr(profile, "otel_collector_endpoint", None)

    if endpoint:
        mdm_config["otlpEndpoint"] = endpoint
        mdm_config["otlpProtocol"] = "http/protobuf"
        console.print(f"[dim]OTLP endpoint: {endpoint}[/dim]")

        # Add CoWork service token for ALB auth bypass (if configured).
        # CoWork cannot do OIDC — this static token header bypasses JWT validation.
        cowork_token = getattr(profile, "cowork_service_token", None)
        if cowork_token:
            mdm_config["otlpHeaders"] = json.dumps({"X-Cowork-Token": cowork_token})
            console.print("[dim]CoWork auth token configured for ALB bypass[/dim]")
    else:
        console.print(
            "[yellow]⚠ Could not resolve monitoring endpoint for CoWork telemetry.[/yellow]\n"
            "[dim]  Set otel_collector_endpoint in your profile, or deploy the monitoring stack first.[/dim]"
        )


def _mdm_keys(config: dict) -> dict:
    """Return config without internal underscore-prefixed keys."""
    return {k: v for k, v in config.items() if not k.startswith("_")}


def generate_json(output_dir: Path, mdm_config: dict) -> Path:
    """Generate raw MDM configuration JSON file.

    Returns the path to the generated file.
    """
    json_path = output_dir / "cowork-3p-config.json"
    with open(json_path, "w", encoding="utf-8") as f:
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
    with open(mobileconfig_path, "w", encoding="utf-8") as f:
        f.write(mobileconfig)
    return mobileconfig_path


def generate_reg_file(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a Windows .reg file for Claude Cowork 3P.

    All values are stored as REG_SZ strings — booleans, integers, and arrays
    included — matching what Claude Desktop reads from the registry.

    If inferenceCredentialHelper is present and uses a Unix-style path (~/ prefix),
    it is rewritten to the Windows equivalent (%USERPROFILE%\\ + .exe suffix).

    Returns the path to the generated file.
    """
    reg_key = r"HKEY_CURRENT_USER\SOFTWARE\Policies\Claude"

    # Create a copy with Windows-specific credential helper path
    config = dict(mdm_config)
    helper_key = "inferenceCredentialHelper"
    if helper_key in config and isinstance(config[helper_key], str) and config[helper_key].startswith("~/"):
        # Convert ~/claude-code-with-bedrock/credential-process --profile X
        # to %USERPROFILE%\claude-code-with-bedrock\credential-process.exe --profile X
        unix_path = config[helper_key]
        parts = unix_path.split(" ", 1)
        binary_part = parts[0].replace("~/", "%USERPROFILE%\\").replace("/", "\\")
        if not binary_part.endswith(".exe"):
            binary_part += ".exe"
        config[helper_key] = f"{binary_part} {parts[1]}" if len(parts) > 1 else binary_part

    lines = ["Windows Registry Editor Version 5.00", "", f"[{reg_key}]"]

    for key, value in _mdm_keys(config).items():
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
    with open(reg_path, "w", encoding="utf-8", newline="\r\n") as f:
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


def generate_admx(output_dir: Path, mdm_config: dict) -> Path:
    """Generate ADMX + ADML Group Policy templates for CoWork 3P.

    Creates Windows Group Policy Administrative Template files that can be
    imported into Intune (Import ADMX), Omnissa Workspace ONE, or Active
    Directory Group Policy. Values are pre-populated from the MDM config.

    The ADMX defines policies under HKCU\\SOFTWARE\\Policies\\Claude matching
    the same registry path used by the .reg generator.

    Returns the path to the generated .admx file.
    """
    import shutil

    # Copy the static ADMX/ADML templates from deployment/mdm/windows/
    mdm_source = Path(__file__).resolve().parent.parent.parent.parent.parent / "deployment" / "mdm" / "windows"

    admx_src = mdm_source / "ClaudeCowork3P.admx"
    adml_src = mdm_source / "en-US" / "ClaudeCowork3P.adml"

    if not admx_src.exists():
        raise FileNotFoundError(f"ADMX template not found: {admx_src}")

    # Copy ADMX
    admx_dst = output_dir / "ClaudeCowork3P.admx"
    shutil.copy2(admx_src, admx_dst)

    # Copy ADML (with en-US subdirectory)
    adml_dir = output_dir / "en-US"
    adml_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(adml_src, adml_dir / "ClaudeCowork3P.adml")

    return admx_dst


def generate_intune_script(output_dir: Path, mdm_config: dict) -> Path:
    """Generate an Intune-ready PowerShell script for CoWork 3P deployment.

    Creates a .ps1 file that writes CoWork 3P registry values to
    HKCU\\SOFTWARE\\Policies\\Claude. Pre-populated with values from the
    current deployment profile.

    Deploy via:
    - Intune: Devices > Scripts > Platform scripts (Run as user)
    - Omnissa: Devices > Profiles & Resources > Scripts (User context)

    Returns the path to the generated .ps1 file.
    """
    keys = _mdm_keys(mdm_config)

    lines = [
        "<#",
        ".SYNOPSIS",
        "    Deploy Claude Cowork 3P configuration via Intune platform script.",
        "",
        ".DESCRIPTION",
        "    Writes CoWork 3P registry values to HKCU\\SOFTWARE\\Policies\\Claude.",
        "    Claude Desktop reads these at launch as managed MDM policy.",
        "",
        "    Intune: Devices > Scripts and remediations > Platform scripts > Add",
        "      Run this script using the logged on credentials: YES",
        "      Run script in 64 bit PowerShell Host: Yes",
        "",
        ".NOTES",
        "    Auto-generated by: ccwb cowork generate --format ps1",
        "#>",
        "",
        "$ErrorActionPreference = 'Stop'",
        "",
        '$regPath = "HKCU:\\SOFTWARE\\Policies\\Claude"',
        "",
        "# Create registry key if it does not exist",
        "if (-not (Test-Path $regPath)) {",
        "    New-Item -Path $regPath -Force | Out-Null",
        "}",
        "",
        "# Write configuration values",
    ]

    for key, value in keys.items():
        if isinstance(value, bool):
            ps_value = "true" if value else "false"
        elif isinstance(value, (list, dict)):
            ps_value = json.dumps(value)
        else:
            ps_value = str(value)
        # Escape single quotes for PowerShell
        escaped = ps_value.replace("'", "''")
        lines.append(f"Set-ItemProperty -Path $regPath -Name '{key}' -Value '{escaped}' -Type String")

    lines.extend(
        [
            "",
            'Write-Output "Claude Cowork 3P policy deployed to $regPath"',
            'Write-Output "Restart Claude Desktop to apply changes."',
        ]
    )

    ps1_path = output_dir / "Set-CoworkPolicy.ps1"
    with open(ps1_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    return ps1_path
