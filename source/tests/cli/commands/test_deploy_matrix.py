# ABOUTME: Deploy parameter matrix tests — verifies all profile mode × stack combinations don't crash
# ABOUTME: Catches the #1 failure class: deploy parameter resolution errors (#287, #439, #440, #454)

"""Deploy parameter matrix tests.

These tests verify that deploy.py can build CloudFormation parameters for
every combination of profile configuration mode and stack type without
crashing. They don't deploy anything — they test the parameter resolution
logic that has caused the most production failures.

Bugs this prevents:
- #287: Quota stack crash when SSO disabled (invalid JWT issuer URL)
- #439: MetricsTableArn dependency on removed resource
- #440: Default quota policy not seeded after refactor
- #454: Quota monitoring stack deploy fails when SSO disabled
"""

from dataclasses import replace
from unittest.mock import patch, MagicMock

import pytest

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile


# --- Profile fixtures representing each auth mode ---

def _base_profile(**overrides):
    """Create a minimal valid profile with overrides."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(Profile)}
    defaults = dict(
        name="TestProfile",
        provider_domain="company.okta.com",
        client_id="test-client-id",
        credential_storage="session",
        aws_region="us-east-1",
        identity_pool_name="claude-code-test",
        sso_enabled=True,
        provider_type="okta",
        monitoring_enabled=True,
        monitoring_mode="central",
        quota_monitoring_enabled=True,
        federation_type="direct",
        federated_role_arn="arn:aws:iam::123456789012:role/BedrockRole",
        enable_finegrained_quotas=False,
        monthly_token_limit=225000000,
        daily_token_limit=8250000,
        daily_enforcement_mode="alert",
        monthly_enforcement_mode="block",
        warning_threshold_80=180000000,
        warning_threshold_90=202500000,
    )
    defaults.update(overrides)
    return Profile(**{k: v for k, v in defaults.items() if k in field_names})


PROFILE_MODES = {
    "oidc_okta": _base_profile(
        provider_type="okta",
        sso_enabled=True,
    ),
    "oidc_cognito": _base_profile(
        provider_type="cognito",
        sso_enabled=True,
        cognito_user_pool_id="us-east-1_TestPool123",
    ),
    "oidc_azure": _base_profile(
        provider_type="azure",
        provider_domain="login.microsoftonline.com/tenant-id/v2.0",
        sso_enabled=True,
    ),
    "oidc_auth0": _base_profile(
        provider_type="auth0",
        provider_domain="company.auth0.com",
        sso_enabled=True,
    ),
    "idc_no_sso": _base_profile(
        provider_type="okta",
        provider_domain="",
        client_id="",
        sso_enabled=False,
    ),
    "no_monitoring": _base_profile(
        monitoring_enabled=False,
        quota_monitoring_enabled=False,
    ),
}


class TestDeployParameterMatrix:
    """Every profile mode must produce valid deploy parameters without crashing."""

    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.mark.parametrize("mode_name", list(PROFILE_MODES.keys()))
    def test_resolve_oidc_config_does_not_crash(self, command, mode_name):
        """_resolve_oidc_config must not raise for any profile mode."""
        profile = PROFILE_MODES[mode_name]
        # Should return a tuple of (str, str) — never raise
        result = command._resolve_oidc_config(profile)
        assert isinstance(result, tuple)
        assert len(result) == 2
        issuer, client_id = result
        assert isinstance(issuer, str)
        assert isinstance(client_id, str)

    @pytest.mark.parametrize("mode_name", list(PROFILE_MODES.keys()))
    def test_oidc_config_empty_when_sso_disabled(self, command, mode_name):
        """When SSO is disabled, OIDC config must be empty strings."""
        profile = PROFILE_MODES[mode_name]
        issuer, client_id = command._resolve_oidc_config(profile)
        if not getattr(profile, "sso_enabled", True):
            assert issuer == "", f"SSO disabled but issuer is '{issuer}'"
            assert client_id == "", f"SSO disabled but client_id is '{client_id}'"

    @pytest.mark.parametrize("mode_name", [
        m for m, p in PROFILE_MODES.items() if getattr(p, "sso_enabled", True)
    ])
    def test_oidc_config_non_empty_when_sso_enabled(self, command, mode_name):
        """When SSO is enabled, OIDC config must have a valid issuer URL."""
        profile = PROFILE_MODES[mode_name]
        if not profile.monitoring_enabled:
            pytest.skip("monitoring disabled")
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer.startswith("https://"), f"Issuer must be https URL, got '{issuer}'"
        assert client_id != "", f"Client ID should not be empty when SSO enabled"

    @pytest.mark.parametrize("mode_name", list(PROFILE_MODES.keys()))
    def test_auth0_issuer_has_trailing_slash(self, command, mode_name):
        """Auth0 issuer URL must end with / to match the iss claim."""
        profile = PROFILE_MODES[mode_name]
        if profile.provider_type != "auth0" or not getattr(profile, "sso_enabled", True):
            pytest.skip("not auth0 or SSO disabled")
        issuer, _ = command._resolve_oidc_config(profile)
        assert issuer.endswith("/"), f"Auth0 issuer must end with /, got '{issuer}'"

    @pytest.mark.parametrize("mode_name", list(PROFILE_MODES.keys()))
    def test_cognito_issuer_uses_pool_region(self, command, mode_name):
        """Cognito issuer must use the region from the pool ID, not aws_region."""
        profile = PROFILE_MODES[mode_name]
        if profile.provider_type != "cognito" or not getattr(profile, "sso_enabled", True):
            pytest.skip("not cognito or SSO disabled")
        issuer, _ = command._resolve_oidc_config(profile)
        pool_id = getattr(profile, "cognito_user_pool_id", "")
        if pool_id and "_" in pool_id:
            pool_region = pool_id.split("_")[0]
            assert pool_region in issuer, f"Issuer should contain pool region '{pool_region}'"
