# ABOUTME: Tests for generic OIDC (PingFederate, Keycloak, etc.) landing-page distribution support
# ABOUTME: Validates allowlist, required endpoints, config round-trip, deploy params, and CFN template

"""Tests for generic OIDC support on the landing-page distribution.

Previously the landing page only supported Okta/Azure/Auth0/Cognito, while SSO auth
already supported a 'generic' provider. This wires generic OIDC (PingFederate, Keycloak,
ForgeRock, etc.) through the validator, config round-trip, deploy params, and CFN template.
"""

from pathlib import Path

import pytest

from claude_code_with_bedrock.config import Profile
from claude_code_with_bedrock.validators import validate_profile

SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SOURCE_ROOT.parents[0]
DEPLOY_PY = SOURCE_ROOT / "claude_code_with_bedrock" / "cli" / "commands" / "deploy.py"
INIT_PY = SOURCE_ROOT / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"
LANDING_TEMPLATE = REPO_ROOT / "deployment" / "infrastructure" / "landing-page-distribution.yaml"


class TestGenericDistributionValidator:
    """Validator accepts generic and enforces its required endpoints."""

    @pytest.fixture
    def base_profile(self):
        return {
            "name": "my-profile",
            "provider_domain": "myorg.okta.com",
            "client_id": "0oa1234567890abcdef",
            "credential_storage": "keyring",
            "aws_region": "us-east-1",
            "identity_pool_name": "my-pool",
            "distribution_type": "landing-page",
            "distribution_idp_client_id": "web-client-id",
        }

    def test_generic_provider_is_accepted(self, base_profile):
        """'generic' is a valid distribution_idp_provider when endpoints are supplied."""
        base_profile.update(
            {
                "distribution_idp_provider": "generic",
                "distribution_idp_issuer": "https://auth.example.com",
                "distribution_idp_authorization_endpoint": "https://auth.example.com/as/authorization.oauth2",
                "distribution_idp_token_endpoint": "https://auth.example.com/as/token.oauth2",
                "distribution_idp_userinfo_endpoint": "https://auth.example.com/idp/userinfo.openid",
            }
        )
        result = validate_profile(base_profile)
        assert result.valid is True, result.errors

    def test_generic_requires_issuer_and_endpoints(self, base_profile):
        """Generic provider without explicit endpoints fails validation."""
        base_profile["distribution_idp_provider"] = "generic"
        result = validate_profile(base_profile)
        assert result.valid is False
        for field in (
            "distribution_idp_issuer",
            "distribution_idp_authorization_endpoint",
            "distribution_idp_token_endpoint",
            "distribution_idp_userinfo_endpoint",
        ):
            assert any(field in e for e in result.errors), f"missing error for {field}"

    def test_generic_does_not_require_domain(self, base_profile):
        """Generic providers supply endpoints directly, so idp_domain is not required."""
        base_profile.update(
            {
                "distribution_idp_provider": "generic",
                "distribution_idp_issuer": "https://auth.example.com",
                "distribution_idp_authorization_endpoint": "https://auth.example.com/authorize",
                "distribution_idp_token_endpoint": "https://auth.example.com/token",
                "distribution_idp_userinfo_endpoint": "https://auth.example.com/userinfo",
            }
        )
        # No distribution_idp_domain set
        result = validate_profile(base_profile)
        assert result.valid is True, result.errors
        assert not any("distribution_idp_domain" in e for e in result.errors)

    def test_okta_still_requires_domain(self, base_profile):
        """Regression: non-generic providers still require a domain."""
        base_profile["distribution_idp_provider"] = "okta"
        result = validate_profile(base_profile)
        assert result.valid is False
        assert any("distribution_idp_domain" in e for e in result.errors)

    def test_unknown_distribution_provider_rejected(self, base_profile):
        """An unsupported provider is still rejected with an updated message."""
        base_profile["distribution_idp_provider"] = "pingfederate"
        result = validate_profile(base_profile)
        assert result.valid is False
        assert any("generic" in e for e in result.errors)


class TestGenericDistributionProfileFields:
    """Profile dataclass carries the new generic OIDC distribution fields."""

    def test_profile_has_generic_distribution_fields(self):
        profile = Profile(
            name="p",
            provider_domain="auth.example.com",
            client_id="cid",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="pool",
            distribution_idp_provider="generic",
            distribution_idp_issuer="https://auth.example.com",
            distribution_idp_authorization_endpoint="https://auth.example.com/authorize",
            distribution_idp_token_endpoint="https://auth.example.com/token",
            distribution_idp_userinfo_endpoint="https://auth.example.com/userinfo",
        )
        assert profile.distribution_idp_issuer == "https://auth.example.com"
        assert profile.distribution_idp_authorization_endpoint.endswith("/authorize")
        assert profile.distribution_idp_token_endpoint.endswith("/token")
        assert profile.distribution_idp_userinfo_endpoint.endswith("/userinfo")

    def test_generic_distribution_fields_default_none(self):
        """Backward-compat: profiles without the new fields default to None."""
        profile = Profile(
            name="p",
            provider_domain="auth.example.com",
            client_id="cid",
            credential_storage="keyring",
            aws_region="us-east-1",
            identity_pool_name="pool",
        )
        assert profile.distribution_idp_issuer is None
        assert profile.distribution_idp_authorization_endpoint is None
        assert profile.distribution_idp_token_endpoint is None
        assert profile.distribution_idp_userinfo_endpoint is None


class TestGenericDistributionDeployParams:
    """deploy.py wires generic OIDC params to the CloudFormation stack."""

    def test_deploy_has_generic_branch(self):
        source = DEPLOY_PY.read_text(encoding="utf-8")
        assert 'profile.distribution_idp_provider == "generic"' in source

    def test_deploy_passes_generic_params(self):
        source = DEPLOY_PY.read_text(encoding="utf-8")
        for param in (
            "GenericIssuer={profile.distribution_idp_issuer",
            "GenericAuthorizationEndpoint={profile.distribution_idp_authorization_endpoint",
            "GenericTokenEndpoint={profile.distribution_idp_token_endpoint",
            "GenericUserInfoEndpoint={profile.distribution_idp_userinfo_endpoint",
            "GenericClientId={profile.distribution_idp_client_id}",
            "GenericClientSecretArn={profile.distribution_idp_client_secret_arn}",
        ):
            assert param in source, f"missing deploy param: {param}"


class TestGenericDistributionInitRoundTrip:
    """init.py offers generic and round-trips the new fields through config."""

    def test_init_offers_generic_choice(self):
        source = INIT_PY.read_text(encoding="utf-8")
        assert 'value="generic"' in source
        assert "PingFederate" in source

    def test_init_maps_generic_fields_both_directions(self):
        source = INIT_PY.read_text(encoding="utf-8")
        # config -> Profile (load)
        assert '"distribution_idp_issuer": config_data.get("distribution", {}).get("idp_issuer")' in source
        # Profile -> config (save)
        assert '"idp_issuer": getattr(profile, "distribution_idp_issuer", None)' in source


class TestGenericDistributionTemplate:
    """landing-page CFN template supports generic OIDC."""

    def test_template_allows_generic(self):
        text = LANDING_TEMPLATE.read_text(encoding="utf-8")
        assert "AllowedValues: [okta, azure, auth0, cognito, generic]" in text

    def test_template_has_generic_parameters(self):
        text = LANDING_TEMPLATE.read_text(encoding="utf-8")
        for param in (
            "GenericIssuer:",
            "GenericAuthorizationEndpoint:",
            "GenericTokenEndpoint:",
            "GenericUserInfoEndpoint:",
            "GenericClientId:",
            "GenericClientSecretArn:",
        ):
            assert param in text, f"missing CFN parameter: {param}"

    def test_template_oidc_config_falls_back_to_generic(self):
        """The AuthenticateOidcConfig else-branch references generic params."""
        text = LANDING_TEMPLATE.read_text(encoding="utf-8")
        assert "!Ref GenericIssuer" in text
        assert "!Ref GenericAuthorizationEndpoint" in text
        assert "!Ref GenericTokenEndpoint" in text
        assert "!Ref GenericUserInfoEndpoint" in text
        assert "!Ref GenericClientId" in text
        assert "resolve:secretsmanager:${GenericClientSecretArn}" in text
