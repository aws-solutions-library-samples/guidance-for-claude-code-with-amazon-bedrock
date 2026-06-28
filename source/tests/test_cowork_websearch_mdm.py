# ABOUTME: Tests for injecting the AgentCore web search gateway into the CoWork MDM config
# ABOUTME: Covers add_websearch_mcp_config: opt-in gating, entry shape, merge/dedup, URL resolution

"""Unit tests for add_websearch_mcp_config (CoWork managedMcpServers injection)."""

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
        "redirect_port": 8400,
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


def test_enabled_adds_entry_with_expected_shape():
    """v1.15962.0+ native managedMcpServers format with server=websearch, provider=custom."""
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    servers = _servers(mdm)
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == WEBSEARCH_MCP_SERVER_NAME
    assert entry["server"] == "websearch"
    assert entry["provider"] == "custom"
    assert entry["customUrl"] == "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"


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
    assert _servers(mdm)[0]["customUrl"].endswith("/mcp")
    assert not _servers(mdm)[0]["customUrl"].endswith("/mcp/mcp")


def test_does_not_double_mcp_suffix():
    mdm = {}
    add_websearch_mcp_config(mdm, _profile(), _CONSOLE)
    assert _servers(mdm)[0]["customUrl"].count("/mcp") == 1


def test_preserves_admin_defined_servers_and_dedupes():
    admin_entry = {"name": "github", "server": "websearch", "provider": "brave"}
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
    add_websearch_mcp_config(mdm, _profile(websearch_gateway_url="", stack_names={}), _CONSOLE)
    assert "managedMcpServers" not in mdm
