# ABOUTME: Shared utilities for generating Claude Cowork 3P MDM configurations
# ABOUTME: Used by both 'ccwb package' and 'ccwb cowork generate' commands

"""Shared CoWork 3P MDM configuration generation utilities."""

import json
import uuid
from html import escape as xml_escape
from pathlib import Path

from rich.console import Console

from claude_code_with_bedrock.cli.utils.aws import get_stack_outputs

# Placeholder for the user's home directory in macOS MDM path values. Claude
# Desktop on macOS does NOT expand "~" (or env vars) in MDM string values, and
# the .mobileconfig is generated centrally (the packaging host's home may not be
# the user's). So macOS paths embed this token and `install.sh` substitutes it
# with the real $HOME on each user's machine at install time — mirroring the
# __CREDENTIAL_PROCESS_PATH__ pattern used for managed-settings.json. Windows
# paths use the native %USERPROFILE% env var instead.
CCWB_HOME_PLACEHOLDER = "__CCWB_HOME__"

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


# Wrapper scripts that Claude Desktop invokes as inferenceCredentialHelper.
# Per Anthropic's contract, Claude Desktop "runs the executable at the configured
# path with no arguments" — it does NOT parse a command line. So the helper value
# must be a bare path to a script, and the --desktop/--profile arguments are
# baked INSIDE the wrapper (which calls the co-located credential-process binary).
# Pointing inferenceCredentialHelper directly at "credential-process --desktop
# --profile X" makes Claude Desktop treat the whole string as one filename and
# fail to spawn it (ENOENT).
COWORK_HELPER_SCRIPT_UNIX = "cowork-credential-helper.sh"
COWORK_HELPER_SCRIPT_WINDOWS = "cowork-credential-helper.cmd"


def _credential_process_path(profile_name: str) -> dict[str, str]:
    """Return platform-specific, argument-free wrapper-script paths for
    inferenceCredentialHelper.

    The installer places the wrapper alongside the binary per-platform:
    - macOS/Linux: <home>/claude-code-with-bedrock/cowork-credential-helper.sh
    - Windows: <home>\\claude-code-with-bedrock\\cowork-credential-helper.cmd

    The wrapper hardcodes `--desktop --profile <name>` and execs the co-located
    credential-process binary. Claude Desktop does NOT expand "~"/env vars in MDM
    values, so both paths embed CCWB_HOME_PLACEHOLDER; `install.sh`/`install.bat`
    substitute it with the real home at install time.
    """
    return {
        "unix": f"{CCWB_HOME_PLACEHOLDER}/claude-code-with-bedrock/{COWORK_HELPER_SCRIPT_UNIX}",
        "windows": f"{CCWB_HOME_PLACEHOLDER}\\claude-code-with-bedrock\\{COWORK_HELPER_SCRIPT_WINDOWS}",
    }


def build_mdm_config(
    bedrock_region: str,
    model_aliases: list[str],
    profile_name: str = "ClaudeCode",
    auth_type: str = "profile",
    idc_start_url: str | None = None,
    idc_region: str | None = None,
    idc_account_id: str | None = None,
    idc_role_name: str | None = None,
    models_with_labels: list[dict] | None = None,
    deployment_org_uuid: str | None = None,
    extra_keys: dict[str, str] | None = None,
    credential_mode: str = "helper",
    credential_helper_ttl_sec: int = 3500,
) -> dict:
    """Build the base CoWork 3P MDM configuration dictionary.

    Supports two authentication modes:
    - "profile": Uses inferenceBedrockProfile pointing to ~/.aws/config with credential_process
    - "idc": Uses native IAM Identity Center SSO (no credential-process binary needed)

    For profile mode, supports two credential modes:
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
        profile_name: AWS named profile (for auth_type="profile").
        auth_type: Authentication type - "profile" or "idc".
        idc_start_url: IAM Identity Center start URL (for auth_type="idc").
        idc_region: IAM Identity Center region (for auth_type="idc").
        idc_account_id: AWS account ID (for auth_type="idc").
        idc_role_name: IAM Identity Center permission set/role name (for auth_type="idc").
        models_with_labels: Optional list of model dicts with name and labelOverride.
        deployment_org_uuid: Optional deployment organization UUID.
        extra_keys: Optional dictionary of additional MDM keys to merge into the
            configuration. Values should be strings (JSON-encoded for complex types).
        credential_mode: "helper" or "profile" (default: "helper"). Only used when auth_type="profile".
        credential_helper_ttl_sec: Cache TTL for the credential helper output in
            seconds (default: 3500, slightly under the 1h STS token lifetime to
            ensure refresh happens before expiry).

    Returns:
        Dictionary of MDM configuration key-value pairs.
    """
    config = {
        "inferenceProvider": "bedrock",
        "inferenceBedrockRegion": bedrock_region,
        "isClaudeCodeForDesktopEnabled": True,
        "isDesktopExtensionEnabled": True,
        "isDesktopExtensionDirectoryEnabled": True,
        "isDesktopExtensionSignatureRequired": True,
        "isLocalDevMcpEnabled": True,
    }

    if auth_type == "idc":
        # Native IAM Identity Center SSO - Claude Desktop handles auth directly
        config["inferenceCredentialKind"] = "interactive"
        if idc_start_url:
            config["inferenceBedrockSsoStartUrl"] = idc_start_url
        if idc_region:
            config["inferenceBedrockSsoRegion"] = idc_region
        if idc_account_id:
            config["inferenceBedrockSsoAccountId"] = idc_account_id
        if idc_role_name:
            config["inferenceBedrockSsoRoleName"] = idc_role_name
    elif credential_mode == "helper":
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
        # Disambiguate for Claude Desktop: shipping both inferenceCredentialHelper
        # and inferenceBedrockProfile together is intentional (the profile is a
        # region/metadata fallback, not the active auth path), but Desktop logs
        # "Multiple credential methods configured (vendor-profile, helper-script);
        # using vendor-profile" and silently prefers the WRONG one without this key
        # — causing repeated "Authentication Failed" since the SDK profile path was
        # never the supported one. Setting it explicitly removes the ambiguity.
        config["inferenceCredentialKind"] = "helper-script"
    else:
        # Legacy profile mode — rely on AWS SDK credential_process chain. Only
        # inferenceBedrockProfile is set here, so there is no ambiguity for
        # Claude Desktop to resolve — do not add inferenceCredentialKind, whose
        # name/values are inferred from a Desktop log string and unverified
        # against any published schema. Confine that unverified key to the one
        # mode (helper) that has the reported ambiguity bug.
        config["inferenceBedrockProfile"] = profile_name

    # Models - use models_with_labels if provided, otherwise build from aliases
    if models_with_labels:
        config["inferenceModels"] = models_with_labels
    else:
        config["inferenceModels"] = build_inference_models(model_aliases)

    # Optional deployment org UUID
    if deployment_org_uuid:
        config["deploymentOrganizationUuid"] = deployment_org_uuid

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


WEBSEARCH_MCP_SERVER_NAME = "agentcore-websearch"

# Filename of the headersHelper the installer drops next to the credential-process
# binary (in ~/claude-code-with-bedrock/). It prints
# {"Authorization": "Bearer <id_token>"} on stdout for Claude Desktop to attach
# to every MCP request to the gateway. On Windows it is a .cmd wrapper.
WEBSEARCH_HEADERS_HELPER_NAME = "websearch-headers"

# Per-OS default headersHelper paths. The MDM config is generated once but
# rendered into per-OS formats (.mobileconfig vs .reg/.ps1), so the entry stores
# a placeholder that each generator resolves to the right path. Admins can still
# override with an explicit absolute path via ``websearch_headers_helper_path``.
WEBSEARCH_HEADERS_HELPER_PLACEHOLDER = "__WEBSEARCH_HEADERS_HELPER__"
WEBSEARCH_HEADERS_HELPER_POSIX = f"{CCWB_HOME_PLACEHOLDER}/claude-code-with-bedrock/{WEBSEARCH_HEADERS_HELPER_NAME}"
# Windows path also embeds the home placeholder (NOT %USERPROFILE%): Claude
# Desktop does NOT expand env vars in registry MDM string values (same class of
# bug as "~" on macOS, confirmed by live Windows testing). install.bat
# substitutes __CCWB_HOME__ with the absolute home (the .reg-escaped
# %USERPROFILE%) before the .reg is imported; the Intune .ps1 resolves it via
# $env:USERPROFILE at deploy time.
WEBSEARCH_HEADERS_HELPER_WINDOWS = (
    rf"{CCWB_HOME_PLACEHOLDER}\claude-code-with-bedrock\{WEBSEARCH_HEADERS_HELPER_NAME}.cmd"
)

# Back-compat alias (POSIX default) for callers/tests that referenced the old name.
WEBSEARCH_HEADERS_HELPER_DEFAULT = WEBSEARCH_HEADERS_HELPER_POSIX

# How often (seconds) Claude Desktop re-invokes the headersHelper. Kept below the
# Cognito id_token lifetime (~1h) so a fresh bearer is fetched before expiry.
WEBSEARCH_HEADERS_TTL_SEC = 900


def _resolve_websearch_gateway_url(profile) -> str | None:
    """Resolve the gateway MCP endpoint, profile-first with a CloudFormation fallback.

    Prefers ``websearch_gateway_url`` saved on the profile by ``ccwb deploy``
    (mirrors the OTLP-endpoint discovery precedent), falling back to the
    ``websearch`` stack's ``GatewayMcpEndpoint`` output (the gateway is pinned to
    us-east-1). Ensures exactly one ``/mcp`` suffix. Returns None when unresolved.
    """
    url = (getattr(profile, "websearch_gateway_url", "") or "").strip()
    if not url:
        stack = (getattr(profile, "stack_names", None) or {}).get("websearch")
        region = getattr(profile, "websearch_region", None) or "us-east-1"
        if stack:
            try:
                url = (get_stack_outputs(stack, region).get("GatewayMcpEndpoint") or "").strip()
            except Exception:
                url = ""
    if not url:
        return None
    return url if url.rstrip("/").endswith("/mcp") else url.rstrip("/") + "/mcp"


def add_websearch_mcp_config(mdm_config: dict, profile, console: Console) -> None:
    """Inject the AgentCore web search gateway as a CoWork managed MCP server.

    No-op unless ``web_search_enabled``. Resolves the gateway endpoint at
    generation time (never a stale stored value beyond the profile cache) and
    emits a **remote MCP** ``managedMcpServers`` entry authenticated with a
    ``headersHelper`` script: ``{name, url, headersHelper, headersHelperTtlSec}``.

    Claude Desktop treats this as a generic remote MCP server and speaks standard
    MCP JSON-RPC that the AgentCore Gateway understands. The gateway's
    ``CUSTOM_JWT`` authorizer validates the OIDC id_token the ``headersHelper``
    emits (``Authorization: Bearer <id_token>``); the id_token's ``aud`` is the
    app client ID, so the gateway must be deployed with ``AllowedAudience``
    (the template default) — universal across Cognito/Entra/Okta.

    The built-in ``server:"websearch"``/``provider:"custom"`` shape is NOT used:
    that connector sends a request body the AgentCore Gateway cannot parse
    ("Invalid JSON format"), even though auth succeeds.

    The ``headersHelper`` path is OS-specific. Unless overridden, the entry
    carries a placeholder that each generator resolves to the per-OS default
    (``~/claude-code-with-bedrock/websearch-headers`` on macOS/Linux,
    ``%USERPROFILE%\\claude-code-with-bedrock\\websearch-headers.cmd`` on
    Windows) — the same path where ``ccwb package`` installs the wrapper. An
    explicit ``websearch_headers_helper_path`` override is used verbatim across
    all formats. Preserves any administrator-defined ``managedMcpServers`` and
    de-dupes by name.
    """
    if not getattr(profile, "web_search_enabled", False):
        return

    # IDC deployments authorize the gateway with IAM (SigV4), which Claude
    # Desktop does not yet support for managed MCP servers. Skip the CoWork
    # injection for IDC (Claude Code CLI handles IDC web search separately).
    auth_type = getattr(profile, "effective_auth_type", getattr(profile, "auth_type", "oidc"))
    if auth_type == "idc":
        console.print(
            "[dim]Web search: skipping CoWork config (IDC uses IAM/SigV4 auth, "
            "not yet supported for Claude Desktop managed MCP servers)[/dim]"
        )
        return

    url = _resolve_websearch_gateway_url(profile)
    if not url:
        console.print(
            "[yellow]⚠ Web search is enabled but the gateway endpoint could not be resolved; "
            "generating CoWork config without the web search MCP server.[/yellow]\n"
            "[dim]  Run 'ccwb deploy websearch' first.[/dim]"
        )
        return

    # Remote MCP entry authenticated via a headersHelper script. Claude Desktop
    # invokes the helper, attaches the returned {"Authorization": "Bearer
    # <id_token>"} header to each MCP request, and re-fetches every
    # headersHelperTtlSec so an expiring token is refreshed.
    #
    # The path is OS-specific, but this one MDM dict is rendered into both macOS
    # (.mobileconfig) and Windows (.reg/.ps1) formats. So unless the admin sets
    # an explicit override, store a placeholder that each generator resolves to
    # the right per-OS default. An override wins verbatim across all formats.
    override = (getattr(profile, "websearch_headers_helper_path", "") or "").strip()
    if override:
        headers_helper = override
        looks_absolute = (
            override.startswith("/")
            or override.startswith("~")
            or override.startswith("%")
            or (len(override) > 2 and override[1] == ":")  # Windows drive, e.g. C:\
        )
        if not looks_absolute:
            console.print(
                "[yellow]⚠ websearch_headers_helper_path is not an absolute path; "
                "Claude Desktop may not resolve it.[/yellow]"
            )
        console.print(
            "[dim]Web search: using a custom headersHelper path. The installer only creates the "
            "default path \u2014 ensure an executable helper exists at this path on every user's "
            "machine, and that it matches the target OS, especially with --target-platform all.[/dim]"
        )
    else:
        headers_helper = WEBSEARCH_HEADERS_HELPER_PLACEHOLDER
    entry = {
        "name": WEBSEARCH_MCP_SERVER_NAME,
        "url": url,
        "headersHelper": headers_helper,
        "headersHelperTtlSec": WEBSEARCH_HEADERS_TTL_SEC,
    }

    # managedMcpServers is a JSON-encoded string in the MDM config. Merge with any
    # admin-defined entries (e.g. from cowork_3p_extra_keys), keeping all and
    # de-duping by name so a re-run never creates a duplicate web search entry.
    existing_raw = mdm_config.get("managedMcpServers")
    servers: list = []
    if isinstance(existing_raw, str) and existing_raw.strip():
        try:
            parsed = json.loads(existing_raw)
            if isinstance(parsed, list):
                servers = parsed
        except (ValueError, TypeError):
            servers = []
    elif isinstance(existing_raw, list):
        servers = list(existing_raw)

    servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == WEBSEARCH_MCP_SERVER_NAME)]
    servers.append(entry)
    mdm_config["managedMcpServers"] = json.dumps(servers)
    console.print(f"[dim]Added {WEBSEARCH_MCP_SERVER_NAME} MCP server to CoWork config ({url})[/dim]")

    # Web Fetch egress: the Cowork sandbox blocks outbound egress by default, so
    # opening the URLs that web search returns fails with "failed to fetch".
    # Default to allowing all hosts so search results are usable out of the box.
    # Only set it when the admin hasn't already provided a value (e.g. a narrower
    # allowlist via cowork_3p_extra_keys), and warn loudly: "*" is broad.
    if "coworkEgressAllowedHosts" not in mdm_config:
        mdm_config["coworkEgressAllowedHosts"] = json.dumps(["*"])
        console.print(
            '[yellow]⚠ Web search: set coworkEgressAllowedHosts=["*"] so Web Fetch can open result '
            "pages. This allows sandbox egress to ALL hosts \u2014 narrow it to a targeted domain list "
            "for production (set coworkEgressAllowedHosts via cowork_3p_extra_keys).[/yellow]"
        )


def _mdm_keys(config: dict) -> dict:
    """Return config without internal underscore-prefixed keys."""
    return {k: v for k, v in config.items() if not k.startswith("_")}


def _mdm_keys_resolved(config: dict, helper_path: str) -> dict:
    """Like ``_mdm_keys`` but resolves the headersHelper placeholder for one OS.

    ``add_websearch_mcp_config`` stores ``WEBSEARCH_HEADERS_HELPER_PLACEHOLDER``
    in the ``managedMcpServers`` entry (unless the admin set an explicit path).
    Each generator calls this with its platform default so the macOS plist and
    the Windows .reg/.ps1 each get the correct path from the same MDM dict.
    No-op when the placeholder is absent (e.g. an explicit override).
    """
    keys = _mdm_keys(config)
    raw = keys.get("managedMcpServers")
    if isinstance(raw, str) and WEBSEARCH_HEADERS_HELPER_PLACEHOLDER in raw:
        keys = dict(keys)
        keys["managedMcpServers"] = raw.replace(WEBSEARCH_HEADERS_HELPER_PLACEHOLDER, helper_path)
    return keys


def generate_json(output_dir: Path, mdm_config: dict) -> Path:
    """Generate raw MDM configuration JSON file.

    Returns the path to the generated file.
    """
    json_path = output_dir / "cowork-3p-config.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_mdm_keys_resolved(mdm_config, WEBSEARCH_HEADERS_HELPER_POSIX), f, indent=2)
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
    for key, value in _mdm_keys_resolved(mdm_config, WEBSEARCH_HEADERS_HELPER_POSIX).items():
        payload_items.append(f"\t\t\t<key>{xml_escape(key)}</key>")
        if isinstance(value, bool):
            string_value = "true" if value else "false"
        elif isinstance(value, list | dict):
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


def _to_windows_credential_helper(value: str) -> str:
    """Convert the unix inferenceCredentialHelper wrapper path to the Windows form.

    ``__CCWB_HOME__/claude-code-with-bedrock/cowork-credential-helper.sh``
    becomes ``__CCWB_HOME__\\claude-code-with-bedrock\\cowork-credential-helper.cmd``.
    Keeps the ``__CCWB_HOME__`` placeholder (resolved at install/deploy time by
    install.bat / the Intune .ps1); rewrites slashes and swaps the .sh wrapper
    for its .cmd counterpart. The value is a bare, argument-free path (Claude
    Desktop runs it with no arguments). No-op when not a placeholder path.
    """
    if not (isinstance(value, str) and value.startswith(f"{CCWB_HOME_PLACEHOLDER}/")):
        return value
    windows = value.replace("/", "\\")
    if windows.endswith(COWORK_HELPER_SCRIPT_UNIX):
        windows = windows[: -len(COWORK_HELPER_SCRIPT_UNIX)] + COWORK_HELPER_SCRIPT_WINDOWS
    return windows


def generate_reg_file(output_dir: Path, mdm_config: dict) -> Path:
    """Generate a Windows .reg file for Claude Cowork 3P.

    All values are stored as REG_SZ strings — booleans, integers, and arrays
    included — matching what Claude Desktop reads from the registry.

    Paths embed the __CCWB_HOME__ home placeholder (NOT %USERPROFILE%): Claude
    Desktop does not expand env vars in registry MDM values. inferenceCredentialHelper's
    Unix path is converted to backslashes + .exe suffix (keeping the placeholder);
    install.bat substitutes __CCWB_HOME__ with the .reg-escaped absolute home
    before the file is imported.

    Returns the path to the generated file.
    """
    reg_key = r"HKEY_CURRENT_USER\SOFTWARE\Policies\Claude"

    # Create a copy with the Windows credential helper path (backslashes + .exe),
    # keeping the __CCWB_HOME__ placeholder for install.bat to resolve.
    config = dict(mdm_config)
    helper_key = "inferenceCredentialHelper"
    if helper_key in config:
        config[helper_key] = _to_windows_credential_helper(config[helper_key])

    lines = ["Windows Registry Editor Version 5.00", "", f"[{reg_key}]"]

    for key, value in _mdm_keys_resolved(config, WEBSEARCH_HEADERS_HELPER_WINDOWS).items():
        if isinstance(value, bool):
            string_value = "true" if value else "false"
        elif isinstance(value, list | dict):
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


def generate_helper_wrappers(output_dir: Path, profile_name: str) -> list[str]:
    """Write the argument-free credential-helper wrapper scripts.

    Claude Desktop runs inferenceCredentialHelper "at the configured path with no
    arguments", so the --desktop/--profile flags live inside these wrappers, which
    exec the co-located credential-process binary. The installer places them next
    to the binary; %~dp0 / $(dirname) resolves the binary relative to the wrapper.

    Returns the generated filenames.
    """
    sh = (
        "#!/bin/bash\n"
        "# ABOUTME: CoWork 3P credential helper — emits a Bedrock bearer token.\n"
        "# Invoked by Claude Desktop as inferenceCredentialHelper (no arguments).\n"
        "set -euo pipefail\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        f'exec "$SCRIPT_DIR/credential-process" --desktop --profile {profile_name}\n'
    )
    sh_path = output_dir / COWORK_HELPER_SCRIPT_UNIX
    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sh)
    try:
        sh_path.chmod(0o755)
    except OSError:
        pass  # no-op on Windows

    cmd = (
        "@echo off\r\n"
        "REM CoWork 3P credential helper - emits a Bedrock bearer token.\r\n"
        "REM Invoked by Claude Desktop as inferenceCredentialHelper (no arguments).\r\n"
        f'"%~dp0credential-process.exe" --desktop --profile {profile_name}\r\n'
        "exit /b %errorlevel%\r\n"
    )
    cmd_path = output_dir / COWORK_HELPER_SCRIPT_WINDOWS
    with open(cmd_path, "w", encoding="utf-8", newline="") as f:
        f.write(cmd)

    return [COWORK_HELPER_SCRIPT_UNIX, COWORK_HELPER_SCRIPT_WINDOWS]


def generate_all(output_dir: Path, mdm_config: dict, console: Console) -> list[str]:
    """Generate all CoWork 3P MDM configuration files (+ helper wrappers).

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

    # helper-script mode: ship the wrapper scripts Claude Desktop invokes.
    if "inferenceCredentialHelper" in mdm_config:
        profile_name = mdm_config.get("inferenceBedrockProfile", "ClaudeCode")
        generated += generate_helper_wrappers(output_dir, profile_name)
        console.print("[green]✓[/green] Generated cowork-credential-helper.sh / .cmd")

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
    keys = _mdm_keys_resolved(mdm_config, WEBSEARCH_HEADERS_HELPER_WINDOWS)
    # Convert the unix credential-helper path to the Windows form (keeps the
    # __CCWB_HOME__ placeholder, resolved at deploy time below).
    if "inferenceCredentialHelper" in keys:
        keys = dict(keys)
        keys["inferenceCredentialHelper"] = _to_windows_credential_helper(keys["inferenceCredentialHelper"])

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
        "# Resolve the home-directory placeholder to this user's absolute home.",
        "# Claude Desktop does NOT expand %USERPROFILE% (or other env vars) in",
        "# registry MDM values, so headersHelper / inferenceCredentialHelper paths",
        "# must be absolute. This script writes the literal (single-backslash) path.",
        "$ccwbHome = $env:USERPROFILE",
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
        elif isinstance(value, list | dict):
            ps_value = json.dumps(value)
        else:
            ps_value = str(value)
        # Escape single quotes for PowerShell
        escaped = ps_value.replace("'", "''")
        # Values carrying the home placeholder are resolved at deploy time to the
        # user's absolute home ($ccwbHome). %USERPROFILE% would NOT work — Claude
        # reads the registry string literally.
        if CCWB_HOME_PLACEHOLDER in ps_value:
            value_expr = f"'{escaped}'.Replace('{CCWB_HOME_PLACEHOLDER}', $ccwbHome)"
        else:
            value_expr = f"'{escaped}'"
        lines.append(f"Set-ItemProperty -Path $regPath -Name '{key}' -Value {value_expr} -Type String")

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
