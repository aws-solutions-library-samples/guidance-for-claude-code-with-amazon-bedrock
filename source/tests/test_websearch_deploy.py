# ABOUTME: Contract tests for T4 — deploy.py web-search gateway wiring.
# ABOUTME: Covers AC2 (us-east-1 region-pin), AC3 (per-provider discovery URL),
# AC8 (GatewayUrl→profile save), AC10/OIDC gating, and the target READY poll.

from unittest.mock import Mock, patch

import pytest

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


def _profile(**overrides):
    """Build a minimal valid OIDC profile, overridable per test."""
    base = {
        "name": "test-profile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client",
        "credential_storage": "session",
        "aws_region": "eu-west-1",
        "identity_pool_name": "test-pool",
        "auth_type": "oidc",
        "provider_type": "okta",
        "web_search_enabled": True,
    }
    base.update(overrides)
    return Profile(**base)


class TestWebSearchRegionPin:
    """AC2 — websearch stack pins to us-east-1 regardless of profile.aws_region."""

    def test_uses_us_east_1_manager_when_region_differs(self):
        profile = _profile(aws_region="eu-west-1")
        primary = Mock()
        primary.region = "eu-west-1"
        cmd = DeployCommand()
        mgr = cmd._websearch_cf_manager(profile, primary)
        assert mgr is not primary
        assert mgr.region == "us-east-1"

    def test_reuses_primary_manager_when_us_east_1(self):
        profile = _profile(aws_region="us-east-1")
        primary = Mock()
        primary.region = "us-east-1"
        cmd = DeployCommand()
        mgr = cmd._websearch_cf_manager(profile, primary)
        assert mgr is primary


class TestWebSearchDiscoveryUrl:
    """AC3 — CUSTOM_JWT discovery URL derived per-provider from the profile."""

    def setup_method(self):
        self.cmd = DeployCommand()

    def test_okta_uses_oauth2_default(self):
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(provider_type="okta", provider_domain="company.okta.com")
        )
        assert url == "https://company.okta.com/oauth2/default/.well-known/openid-configuration"

    def test_auth0_trailing_slash_issuer(self):
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(provider_type="auth0", provider_domain="company.auth0.com")
        )
        assert url == "https://company.auth0.com/.well-known/openid-configuration"

    def test_azure_v2_issuer(self):
        tenant = "12345678-1234-1234-1234-123456789012"
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(
                provider_type="azure",
                provider_domain=f"login.microsoftonline.com/{tenant}/v2.0",
            )
        )
        assert url == (f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration")

    def test_cognito_pool_issuer(self):
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(
                provider_type="cognito",
                provider_domain="mypool.auth.us-west-2.amazoncognito.com",
                cognito_user_pool_id="us-west-2_AbCdEfGhI",
            )
        )
        assert url == (
            "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_AbCdEfGhI/.well-known/openid-configuration"
        )

    def test_cognito_missing_pool_id_raises(self):
        with pytest.raises(ValueError):
            self.cmd._resolve_websearch_discovery_url(_profile(provider_type="cognito", cognito_user_pool_id=""))

    def test_google_fixed_issuer(self):
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(provider_type="google", provider_domain="accounts.google.com")
        )
        assert url == "https://accounts.google.com/.well-known/openid-configuration"

    def test_generic_uses_issuer_url(self):
        url = self.cmd._resolve_websearch_discovery_url(
            _profile(
                provider_type="generic",
                oidc_issuer_url="https://idp.example.com/oauth2",
            )
        )
        assert url == "https://idp.example.com/oauth2/.well-known/openid-configuration"

    def test_generic_missing_issuer_raises(self):
        with pytest.raises(ValueError):
            self.cmd._resolve_websearch_discovery_url(_profile(provider_type="generic", oidc_issuer_url=""))


class TestWebSearchGating:
    """AC10 + Story-A scope — websearch deploys only for OIDC + when enabled."""

    def setup_method(self):
        self.cmd = DeployCommand()

    def test_enabled_oidc_deploys(self):
        assert self.cmd._should_deploy_websearch(_profile(auth_type="oidc")) is True

    def test_disabled_does_not_deploy(self):
        assert self.cmd._should_deploy_websearch(_profile(web_search_enabled=False)) is False

    def test_idc_does_not_deploy(self):
        # Story B (AWS_IAM) handles idc/none; Story A's CUSTOM_JWT needs an id_token.
        p = _profile(auth_type="idc", web_search_enabled=True)
        assert self.cmd._should_deploy_websearch(p) is False

    def test_none_does_not_deploy(self):
        p = _profile(auth_type="none", web_search_enabled=True)
        assert self.cmd._should_deploy_websearch(p) is False


class TestWebSearchUrlSave:
    """AC8 — GatewayUrl output is persisted to profile.agentcore_gateway_url."""

    def test_saves_gateway_url_to_profile(self):
        profile = _profile()
        console = Mock()
        with patch("claude_code_with_bedrock.cli.commands.deploy.Config") as mock_config:
            saver = Mock()
            mock_config.load.return_value = saver
            url = DeployCommand()._persist_websearch_gateway_url(
                profile, {"GatewayUrl": "https://gw-abc.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"}, console
            )
        assert url.endswith("/mcp")
        assert profile.agentcore_gateway_url == url
        saver.save_profile.assert_called_once_with(profile)

    def test_no_output_leaves_profile_unchanged(self):
        profile = _profile()
        console = Mock()
        url = DeployCommand()._persist_websearch_gateway_url(profile, {}, console)
        assert url == ""
        assert profile.agentcore_gateway_url == ""

    def test_save_failure_is_non_fatal(self):
        profile = _profile()
        console = Mock()
        with patch("claude_code_with_bedrock.cli.commands.deploy.Config") as mock_config:
            mock_config.load.side_effect = RuntimeError("disk full")
            # Must not raise — URL persistence is best-effort.
            url = DeployCommand()._persist_websearch_gateway_url(profile, {"GatewayUrl": "https://x/mcp"}, console)
        assert url == "https://x/mcp"
        assert profile.agentcore_gateway_url == "https://x/mcp"


class TestWebSearchTargetPoll:
    """Wires AC1 — poll the connector target to READY; surface FAILED clearly."""

    def _client(self, statuses):
        """boto3 client mock whose list_gateway_targets walks `statuses`."""
        client = Mock()
        calls = {"i": 0}

        def list_targets(**kwargs):
            i = min(calls["i"], len(statuses) - 1)
            calls["i"] += 1
            status = statuses[i]
            return {"items": [{"targetId": "T1", "name": "ws", "status": status, "statusReasons": ["because"]}]}

        client.list_gateway_targets.side_effect = list_targets
        return client

    def test_polls_until_ready(self):
        client = self._client(["CREATING", "CREATING", "READY"])
        with patch("boto3.client", return_value=client):
            ok = DeployCommand()._poll_websearch_target_ready("gw-id", "us-east-1", Mock(), timeout=5, interval=0)
        assert ok is True
        assert client.list_gateway_targets.call_count == 3

    def test_failed_status_returns_false(self):
        client = self._client(["CREATING", "FAILED"])
        with patch("boto3.client", return_value=client):
            ok = DeployCommand()._poll_websearch_target_ready("gw-id", "us-east-1", Mock(), timeout=5, interval=0)
        assert ok is False

    def test_timeout_returns_false(self):
        client = self._client(["CREATING"])
        # interval=0, timeout=0 → one check then deadline exceeded.
        with patch("boto3.client", return_value=client):
            ok = DeployCommand()._poll_websearch_target_ready("gw-id", "us-east-1", Mock(), timeout=0, interval=0)
        assert ok is False


class TestWebSearchDeployCapabilities:
    """Regression — the websearch service role uses an explicit RoleName, so the
    deploy path MUST pass CAPABILITY_NAMED_IAM (not the CAPABILITY_IAM default).

    Caught by the T8 live run: the real deploy omitted capabilities and CFN
    rejected it with "Insufficient capabilities: Requires CAPABILITY_NAMED_IAM",
    while the show-commands path already printed NAMED_IAM (the two had drifted).
    """

    def test_deploy_passes_named_iam_capability(self):
        import io

        from rich.console import Console

        profile = _profile(aws_region="eu-west-1")
        # _deploy_stack drives a rich Progress bound to this console, so it must
        # be a real Console (a Mock can't act as a context manager).
        console = Console(file=io.StringIO())

        # CFN manager whose deploy_stack succeeds; capture its kwargs.
        # deploy_stack returns a result object with a `.success` flag.
        ws_manager = Mock()
        ws_manager.deploy_stack.return_value = Mock(success=True)

        cmd = DeployCommand()
        with (
            patch.object(cmd, "_websearch_cf_manager", return_value=ws_manager),
            patch.object(cmd, "_poll_websearch_target_ready", return_value=True),
            patch.object(cmd, "_persist_websearch_gateway_url", return_value="https://x/mcp"),
            patch(
                "claude_code_with_bedrock.cli.commands.deploy.get_stack_outputs",
                return_value={"GatewayId": "gw-1", "GatewayUrl": "https://x/mcp"},
            ),
        ):
            rc = cmd._deploy_stack("websearch", profile, console, Mock())

        assert rc == 0
        assert ws_manager.deploy_stack.called
        _, kwargs = ws_manager.deploy_stack.call_args
        assert kwargs["capabilities"] == ["CAPABILITY_NAMED_IAM"]
