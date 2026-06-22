# ABOUTME: Tests for injecting the AgentCore web search gateway into the CoWork MDM config (PR4)
# ABOUTME: Covers add_websearch_mcp_config: opt-in gating, native entry shape, IDC skip, merge/dedup

"""Unit tests for add_websearch_mcp_config (CoWork managedMcpServers injection).

Uses the native Claude Desktop v1.15962.0+ ``managedMcpServers`` ``websearch``
server type (``server``/``provider``/``customUrl``); auth is handled natively by
Claude Desktop reusing the user's OIDC session, so there is no ``oauth`` block.
"""

import json

from rich.console import Console

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    WEBSEARCH_MCP_SERVER_NAME,
    add_websearch_mcp_config,
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


def test_enabled_adds_native_websearch_entry():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    servers = _servers(mdm)
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == WEBSEARCH_MCP_SERVER_NAME
    assert entry["server"] == "websearch"
    assert entry["provider"] == "custom"
    assert entry["customUrl"] == "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
    # Native auth → no oauth block / raw transport in the entry.
    assert "oauth" not in entry
    assert "transport" not in entry


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
    customurl = _servers(mdm)[0]["customUrl"]
    assert customurl.endswith("/mcp")
    assert not customurl.endswith("/mcp/mcp")


def test_does_not_double_mcp_suffix():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    assert _servers(mdm)[0]["customUrl"].count("/mcp") == 1


def test_native_entry_is_provider_agnostic_for_azure():
    """The native entry shape is identical regardless of IdP (no per-provider auth)."""
    profile = _profile(
        provider_type="azure",
        provider_domain="login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        oidc_issuer_url="https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        cognito_user_pool_id=None,
    )
    mdm = {}
    add_websearch_mcp_config(mdm, profile, _CONSOLE)
    entry = _servers(mdm)[0]
    assert entry["server"] == "websearch"
    assert entry["provider"] == "custom"
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
