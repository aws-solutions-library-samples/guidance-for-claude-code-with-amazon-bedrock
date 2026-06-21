# ABOUTME: Contract tests for the agentcore-websearch mcpServers block in settings.json
# ABOUTME: T6 (AC5 emit/omit, AC8 URL read-half: profile-first with CFN-output fallback)

"""Contract tests: `ccwb package` emits an mcpServers.agentcore-websearch block.

AC5: when `web_search_enabled`, settings.json gains an `mcpServers` block with
`agentcore-websearch = {type:http, url:<GatewayUrl>, headersHelper:"…credential-process
--get-mcp-auth-header --profile <name>"}`; the block is omitted entirely when disabled.

AC8 (read-half): the gateway URL is resolved profile-first (`agentcore_gateway_url`),
falling back to the websearch stack's `GatewayUrl` CloudFormation output (us-east-1) —
mirroring the OTel-endpoint discovery precedent. The headersHelper path uses the
`__CREDENTIAL_PROCESS_PATH__` placeholder the installer substitutes.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _base_profile(**overrides) -> Profile:
    kwargs = {
        "name": "test",
        "provider_domain": "test.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "keyring",
        "aws_region": "us-east-1",
        "identity_pool_name": "test-pool",
        "allowed_bedrock_regions": ["us-east-1", "us-west-2"],
        "cross_region_profile": "us",
        "monitoring_enabled": False,
    }
    kwargs.update(overrides)
    return Profile(**kwargs)


def _read_settings(output_dir: Path) -> dict:
    settings_path = output_dir / "claude-settings" / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        return json.load(f)


class TestMcpServersOmittedWhenDisabled:
    def test_no_mcpservers_when_web_search_disabled(self):
        command = PackageCommand()
        profile = _base_profile(web_search_enabled=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="ClaudeCode")
            settings = _read_settings(output_dir)

        assert "mcpServers" not in settings


class TestMcpServersEmittedWhenEnabled:
    def test_block_present_and_wellformed_from_profile_url(self):
        command = PackageCommand()
        profile = _base_profile(
            web_search_enabled=True,
            agentcore_gateway_url="https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="MyProfile")
            settings = _read_settings(output_dir)

        assert "mcpServers" in settings
        block = settings["mcpServers"]["agentcore-websearch"]
        assert block["type"] == "http"
        assert block["url"] == "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
        # headersHelper uses the installer-substituted placeholder + the mode flag + profile.
        assert block["headersHelper"] == ("__CREDENTIAL_PROCESS_PATH__ --get-mcp-auth-header --profile MyProfile")

    def test_profile_url_takes_precedence_over_cfn(self):
        """Profile-first: when agentcore_gateway_url is set, CFN is never queried."""
        command = PackageCommand()
        profile = _base_profile(
            web_search_enabled=True,
            agentcore_gateway_url="https://profile-url.example.com/mcp",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch("claude_code_with_bedrock.cli.commands.package.get_stack_outputs") as mock_outputs:
                command._create_claude_settings(output_dir, profile, profile_name="ClaudeCode")
                settings = _read_settings(output_dir)
            mock_outputs.assert_not_called()

        assert settings["mcpServers"]["agentcore-websearch"]["url"] == "https://profile-url.example.com/mcp"


class TestUrlCfnFallback:
    def test_falls_back_to_cfn_output_when_profile_empty(self):
        command = PackageCommand()
        profile = _base_profile(
            web_search_enabled=True,
            agentcore_gateway_url="",
            stack_names={"websearch": "test-pool-websearch"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch(
                "claude_code_with_bedrock.cli.commands.package.get_stack_outputs",
                return_value={"GatewayUrl": "https://cfn-fallback.example.com/mcp"},
            ) as mock_outputs:
                command._create_claude_settings(output_dir, profile, profile_name="ClaudeCode")
                settings = _read_settings(output_dir)

            # Fallback must query the websearch stack in us-east-1 (region-pinned).
            assert mock_outputs.called
            _args, kwargs = mock_outputs.call_args
            call = list(_args) + list(kwargs.values())
            assert "us-east-1" in call

        assert settings["mcpServers"]["agentcore-websearch"]["url"] == "https://cfn-fallback.example.com/mcp"

    def test_no_block_when_enabled_but_no_url_resolvable(self):
        """Enabled but neither profile nor CFN yields a URL → omit the block (no broken entry)."""
        command = PackageCommand()
        profile = _base_profile(
            web_search_enabled=True,
            agentcore_gateway_url="",
            stack_names={"websearch": "test-pool-websearch"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch(
                "claude_code_with_bedrock.cli.commands.package.get_stack_outputs",
                return_value={},
            ):
                command._create_claude_settings(output_dir, profile, profile_name="ClaudeCode")
                settings = _read_settings(output_dir)

        assert "mcpServers" not in settings
