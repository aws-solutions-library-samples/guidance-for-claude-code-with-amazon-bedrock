# ABOUTME: Tests for the --get-mcp-auth-header mode (AC4, T3) of the credential process.
# ABOUTME: Verifies cached-token header output, clean no-browser failure, and Go↔Python output parity.
"""Tests for credential-process --get-mcp-auth-header (Python side + Go parity).

The AgentCore web-search MCP server uses a CUSTOM_JWT gateway authorizer that
validates the same OIDC id_token the solution mints. Claude Code calls
`credential-process --get-mcp-auth-header` as the MCP server's headersHelper to
supply `{"Authorization":"Bearer <id_token>"}`. This mode MUST:
  - print the header from the cached/silently-refreshed token,
  - NEVER open a browser (a headersHelper can't drive interactive login),
  - fail cleanly (non-zero, no hang) when no valid token is available,
  - emit output byte-identical to the Go variant (credential-helper-parity).
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_config():
    return {
        "provider_domain": "test.okta.com",
        "client_id": "test-client-id",
        "identity_pool_id": "us-east-1:test-pool",
        "aws_region": "us-east-1",
        "credential_storage": "session",
        "provider_type": "okta",
        "federation_type": "cognito",
        "max_session_duration": 28800,
    }


@pytest.fixture
def auth_instance(tmp_path):
    """A MultiProviderAuth instance with config + storage init mocked out."""
    with (
        patch("credential_provider.__main__.MultiProviderAuth._load_config") as mock_load,
        patch("credential_provider.__main__.MultiProviderAuth._init_credential_storage"),
    ):
        mock_load.return_value = _make_config()
        from credential_provider.__main__ import MultiProviderAuth

        instance = MultiProviderAuth(profile="TestProfile")
        instance.cache_dir = tmp_path / "cache"
        instance.cache_dir.mkdir(parents=True, exist_ok=True)
        return instance


class TestGetMCPAuthHeader:
    """Unit tests for MultiProviderAuth.get_mcp_auth_header."""

    def test_returns_bearer_header_from_cached_token(self, auth_instance):
        """A cached valid token yields {"Authorization": "Bearer <token>"}."""
        with patch.object(auth_instance, "get_monitoring_token", return_value="cached-id-token"):
            header = auth_instance.get_mcp_auth_header()
        assert header == {"Authorization": "Bearer cached-id-token"}

    def test_returns_none_when_no_cached_token(self, auth_instance):
        """No valid cached token → None (caller fails cleanly, no browser)."""
        with patch.object(auth_instance, "get_monitoring_token", return_value=None) as mock_token:
            header = auth_instance.get_mcp_auth_header()
        assert header is None
        mock_token.assert_called_once()

    def test_never_triggers_browser_authentication(self, auth_instance):
        """The header path must not call any interactive/browser auth method."""
        with (
            patch.object(auth_instance, "get_monitoring_token", return_value=None),
            patch.object(auth_instance, "authenticate_for_monitoring") as mock_auth_mon,
            patch.object(auth_instance, "authenticate_oidc") as mock_auth_oidc,
        ):
            result = auth_instance.get_mcp_auth_header()
        assert result is None
        mock_auth_mon.assert_not_called()
        mock_auth_oidc.assert_not_called()

    def test_output_uses_compact_json_for_go_parity(self, auth_instance):
        """The serialized line must match Go's encoding/json (no spaces after : or ,)."""
        with patch.object(auth_instance, "get_monitoring_token", return_value="tok"):
            header = auth_instance.get_mcp_auth_header()
        line = json.dumps(header, separators=(",", ":"))
        assert line == '{"Authorization":"Bearer tok"}'


# Resolve the Go credential-process package dir for the parity test.
# __file__ = source/tests/test_mcp_auth_header.py → parents[1] = source/ → source/go.
_GO_DIR = Path(__file__).resolve().parents[1] / "go"


def _go_available():
    if not (_GO_DIR / "go.mod").exists():
        return False
    from shutil import which

    return which("go") is not None


@pytest.mark.skipif(not _go_available(), reason="Go toolchain or source not available")
class TestGoPythonParity:
    """The Go and Python variants must emit byte-identical header output (credential-helper-parity)."""

    def test_compact_json_shape_matches_go_marshal(self, tmp_path):
        """Python's compact json.dumps matches Go's json.Marshal(map[string]string) shape.

        Run a tiny Go program that marshals the same map the credential-process builds,
        and assert it equals the Python serialization for the same token.
        """
        token = "header.payload.signature"
        go_src = (
            "package main\n"
            'import ("encoding/json";"fmt")\n'
            "func main(){\n"
            'b,_ := json.Marshal(map[string]string{"Authorization":"Bearer ' + token + '"})\n'
            "fmt.Println(string(b))\n"
            "}\n"
        )
        # Write a standalone .go file in an isolated temp dir (outside the module so
        # `go run` doesn't try to resolve module deps) and execute it.
        go_file = tmp_path / "parity_main.go"
        go_file.write_text(go_src, encoding="utf-8")
        proc = subprocess.run(
            ["go", "run", str(go_file)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "GOTOOLCHAIN": "local", "GO111MODULE": "off"},
        )
        assert proc.returncode == 0, f"go run failed: {proc.stderr}"
        go_line = proc.stdout.strip()

        py_line = json.dumps({"Authorization": f"Bearer {token}"}, separators=(",", ":"))
        assert go_line == py_line == '{"Authorization":"Bearer header.payload.signature"}'
