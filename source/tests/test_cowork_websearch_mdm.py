# ABOUTME: Tests for injecting the AgentCore web search gateway into the CoWork MDM config (PR4)
# ABOUTME: Covers add_websearch_mcp_config: opt-in gating, headersHelper entry shape, IDC skip, merge/dedup

"""Unit tests for add_websearch_mcp_config (CoWork managedMcpServers injection).

Uses the remote-MCP ``managedMcpServers`` entry authenticated with a
``headersHelper`` script (Metodo 1): ``{name, url, headersHelper,
headersHelperTtlSec}``. The built-in ``server:"websearch"``/``provider:"custom"``
shape is intentionally NOT used — the AgentCore Gateway cannot parse the body
that connector sends.
"""

import json

from rich.console import Console

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    WEBSEARCH_HEADERS_HELPER_PLACEHOLDER,
    WEBSEARCH_HEADERS_HELPER_POSIX,
    WEBSEARCH_HEADERS_HELPER_WINDOWS,
    WEBSEARCH_HEADERS_TTL_SEC,
    WEBSEARCH_MCP_SERVER_NAME,
    add_websearch_mcp_config,
    generate_mobileconfig,
    generate_reg_file,
)
from claude_code_with_bedrock.config import Profile

_CONSOLE = Console()


def _profile(**overrides) -> Profile:
    data = {
        "name": "test",
        "provider_domain": "us-east-1abc.auth.eu-central-1.amazoncognito.com",
        "client_id": "client123",
        "credential_storage": "keyring",
        "aws_region": "eu-central-1",
        "identity_pool_name": "ccwb",
        "provider_type": "cognito",
        "cognito_user_pool_id": "eu-central-1_AbCdEf",
        "web_search_enabled": True,
        "websearch_gateway_url": "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
    }
    data.update(overrides)
    return Profile.from_dict(data)


def _servers(mdm_config: dict) -> list:
    raw = mdm_config.get("managedMcpServers")
    return json.loads(raw) if raw else []


def test_disabled_is_noop():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(web_search_enabled=False), _CONSOLE)
    assert "managedMcpServers" not in mdm


def test_enabled_adds_headers_helper_entry():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    servers = _servers(mdm)
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == WEBSEARCH_MCP_SERVER_NAME
    assert entry["url"] == "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
    # Without an override, the entry carries the OS placeholder; generators resolve it.
    assert entry["headersHelper"] == WEBSEARCH_HEADERS_HELPER_PLACEHOLDER
    assert entry["headersHelperTtlSec"] == WEBSEARCH_HEADERS_TTL_SEC
    # Remote MCP entry → not the built-in websearch connector, no oauth block.
    assert "server" not in entry
    assert "provider" not in entry
    assert "customUrl" not in entry
    assert "oauth" not in entry


def test_mobileconfig_resolves_posix_helper_path(tmp_path):
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    generate_mobileconfig(tmp_path, mdm)
    content = (tmp_path / "cowork-3p.mobileconfig").read_text()
    assert WEBSEARCH_HEADERS_HELPER_POSIX in content
    assert WEBSEARCH_HEADERS_HELPER_PLACEHOLDER not in content


def test_reg_resolves_windows_helper_path(tmp_path):
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    generate_reg_file(tmp_path, mdm)
    content = (tmp_path / "cowork-3p.reg").read_text()
    # .reg JSON-escapes backslashes; check on the unescaped form.
    assert WEBSEARCH_HEADERS_HELPER_WINDOWS.replace("\\", "\\\\") in content
    assert WEBSEARCH_HEADERS_HELPER_PLACEHOLDER not in content


def test_override_skips_placeholder_in_all_formats(tmp_path):
    mdm = {}
    custom = "/opt/org/bin/websearch-headers"
    add_websearch_mcp_config(mdm, _profile(websearch_headers_helper_path=custom), _CONSOLE)
    # Entry carries the literal override (no placeholder), so generators emit it verbatim.
    assert _servers(mdm)[0]["headersHelper"] == custom
    generate_mobileconfig(tmp_path, mdm)
    assert custom in (tmp_path / "cowork-3p.mobileconfig").read_text()


def test_managed_mcp_servers_is_json_encoded_string():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    assert isinstance(mdm["managedMcpServers"], str)


def test_appends_mcp_suffix_when_missing():
    mdm = {}
    add_websearch_mcp_config(
        mdm,
        _profile(websearch_gateway_url="https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com"),
        _CONSOLE,
    )
    url = _servers(mdm)[0]["url"]
    assert url.endswith("/mcp")
    assert not url.endswith("/mcp/mcp")


def test_does_not_double_mcp_suffix():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    assert _servers(mdm)[0]["url"].count("/mcp") == 1


def test_entry_is_provider_agnostic_for_azure():
    """The entry shape is identical regardless of IdP (id_token aud=client_id is universal)."""
    profile = _profile(
        provider_type="azure",
        provider_domain="login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        oidc_issuer_url="https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        cognito_user_pool_id=None,
    )
    mdm = {}
    add_websearch_mcp_config(mdm, profile, _CONSOLE)
    entry = _servers(mdm)[0]
    assert entry["url"].endswith("/mcp")
    assert "headersHelper" in entry
    assert "oauth" not in entry


def test_idc_auth_is_skipped():
    """IDC uses IAM/SigV4 — not supported for Claude Desktop managed MCP; skip."""
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(auth_type="idc"), _CONSOLE)
    assert "managedMcpServers" not in mdm


def test_preserves_admin_defined_servers_and_dedupes():
    admin_entry = {"name": "github", "transport": "http", "url": "https://example/mcp"}
    mdm = {"managedMcpServers": json.dumps([admin_entry])}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    servers = _servers(mdm)
    names = [s["name"] for s in servers]
    assert "github" in names
    assert names.count(WEBSEARCH_MCP_SERVER_NAME) == 1
    assert len(servers) == 2


def test_rerun_does_not_duplicate_websearch_entry():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    servers = _servers(mdm)
    assert [s["name"] for s in servers].count(WEBSEARCH_MCP_SERVER_NAME) == 1


def test_unresolved_endpoint_warns_and_skips():
    mdm = {}
    # No profile URL and no websearch stack → cannot resolve, must skip cleanly.
    add_websearch_mcp_config(mdm, _profile(websearch_gateway_url="", stack_names={}), _CONSOLE)
    assert "managedMcpServers" not in mdm
