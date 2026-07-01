# ABOUTME: Tests for the web search gateway wiring (config + deploy)
# ABOUTME: Covers Profile backward-compat, provider/region guards, and CFN param derivation

"""Unit tests for the AgentCore web search gateway deploy wiring (PR 2)."""

from claude_code_with_bedrock.cli.commands.deploy import (
    _websearch_discovery_url,
    build_websearch_params,
    get_websearch_region,
    websearch_preflight,
)
from claude_code_with_bedrock.config import WEBSEARCH_SUPPORTED_REGIONS, Profile


def _cognito_profile(**overrides) -> Profile:
    data = {
        "name": "test",
        "provider_domain": "us-east-1abc.auth.us-east-1.amazoncognito.com",
        "client_id": "client123",
        "credential_storage": "keyring",
        "aws_region": "eu-central-1",
        "identity_pool_name": "ccwb",
        "provider_type": "cognito",
        "cognito_user_pool_id": "eu-central-1_AbCdEf",
        "web_search_enabled": True,
    }
    data.update(overrides)
    return Profile.from_dict(data)


def _azure_profile(**overrides) -> Profile:
    data = {
        "name": "test",
        "provider_domain": "login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        "client_id": "appclient123",
        "credential_storage": "keyring",
        "aws_region": "eu-central-1",
        "identity_pool_name": "ccwb",
        "provider_type": "azure",
        "oidc_issuer_url": "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0",
        "web_search_enabled": True,
        "websearch_jwt_audience": "api://appclient123",
    }
    data.update(overrides)
    return Profile.from_dict(data)


# --- Backward compatibility (Req 2.3, 2.4, 2.5, 10.4) ---


def test_profile_without_websearch_fields_loads_with_defaults():
    """A profile saved before this feature loads with web search disabled."""
    legacy = {
        "name": "legacy",
        "provider_domain": "example.okta.com",
        "client_id": "abc",
        "credential_storage": "session",
        "aws_region": "us-west-2",
        "identity_pool_name": "ccwb",
    }
    profile = Profile.from_dict(legacy)
    assert profile.web_search_enabled is False
    assert profile.websearch_region is None
    assert profile.websearch_jwt_audience is None
    assert profile.websearch_domain_denylist == []


def test_profile_websearch_roundtrip():
    """to_dict/from_dict preserves the web search fields."""
    profile = _cognito_profile(websearch_region="us-east-1", websearch_domain_denylist=["bad.com"])
    restored = Profile.from_dict(profile.to_dict())
    assert restored.web_search_enabled is True
    assert restored.websearch_region == "us-east-1"
    assert restored.websearch_domain_denylist == ["bad.com"]


# --- Region default (Req 4.2) ---


def test_get_websearch_region_defaults_to_supported():
    profile = _cognito_profile(websearch_region=None)
    assert get_websearch_region(profile) == WEBSEARCH_SUPPORTED_REGIONS[0] == "us-east-1"


def test_get_websearch_region_uses_profile_value():
    profile = _cognito_profile(websearch_region="us-east-1")
    assert get_websearch_region(profile) == "us-east-1"


# --- Provider/region guards (Req 6.2, 6.3, 4.8, 5.9, 5.10) ---


def test_preflight_ok_for_cognito():
    ok, msg = websearch_preflight(_cognito_profile())
    assert ok is True
    assert msg is None


def test_preflight_ok_for_azure_with_audience():
    ok, msg = websearch_preflight(_azure_profile())
    assert ok is True
    assert msg is None


def test_preflight_ok_for_okta():
    profile = _cognito_profile(provider_type="okta", provider_domain="company.okta.com")
    ok, msg = websearch_preflight(profile)
    assert ok is True


def test_preflight_ok_for_auth0():
    profile = _cognito_profile(provider_type="auth0", provider_domain="tenant.auth0.com")
    ok, msg = websearch_preflight(profile)
    assert ok is True


def test_preflight_ok_for_google():
    profile = _cognito_profile(provider_type="google", provider_domain="accounts.google.com")
    ok, msg = websearch_preflight(profile)
    assert ok is True


def test_preflight_blocks_non_oidc_provider():
    ok, msg = websearch_preflight(_cognito_profile(provider_type="idc"))
    assert ok is False
    assert "OIDC" in msg


def test_preflight_ok_for_azure_without_audience():
    """Audience is optional: Entra defaults to validating aud == client_id."""
    ok, msg = websearch_preflight(_azure_profile(websearch_jwt_audience=None))
    assert ok is True
    assert msg is None


def test_preflight_blocks_unsupported_region():
    ok, msg = websearch_preflight(_cognito_profile(websearch_region="eu-west-1"))
    assert ok is False
    assert "eu-west-1" in msg


def test_preflight_blocks_cognito_without_pool():
    ok, msg = websearch_preflight(_cognito_profile(cognito_user_pool_id=None))
    assert ok is False
    assert "cognito_user_pool_id" in msg


# --- Discovery URL derivation (Req 5.1, 5.2) ---


def test_discovery_url_cognito_uses_pool_region():
    url = _websearch_discovery_url(_cognito_profile())
    assert url == (
        "https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_AbCdEf/.well-known/openid-configuration"
    )


def test_discovery_url_azure_uses_tenant():
    url = _websearch_discovery_url(_azure_profile())
    assert url == (
        "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0/.well-known/openid-configuration"
    )


def test_discovery_url_okta():
    profile = _cognito_profile(provider_type="okta", provider_domain="company.okta.com")
    url = _websearch_discovery_url(profile)
    assert url == "https://company.okta.com/oauth2/default/.well-known/openid-configuration"


def test_discovery_url_auth0():
    profile = _cognito_profile(provider_type="auth0", provider_domain="tenant.auth0.com")
    url = _websearch_discovery_url(profile)
    assert url == "https://tenant.auth0.com/.well-known/openid-configuration"


def test_discovery_url_google():
    profile = _cognito_profile(provider_type="google", provider_domain="accounts.google.com")
    url = _websearch_discovery_url(profile)
    assert url == "https://accounts.google.com/.well-known/openid-configuration"


# --- CFN parameter derivation (Req 5.3, 5.4, 3.7) ---


def test_params_cognito_uses_client_id_as_audience():
    params = build_websearch_params(_cognito_profile(websearch_region="us-east-1"))
    assert "ClientId=client123" in params
    assert any(p.startswith("DiscoveryUrl=") for p in params)
    assert not any(p.startswith("WebSearchRegion=") for p in params)
    assert not any(p.startswith("DomainExcludeList=") for p in params)


def test_params_azure_custom_audience_overrides_client_id():
    params = build_websearch_params(_azure_profile())
    assert "ClientId=api://appclient123" in params
    assert any(p.startswith("DiscoveryUrl=") for p in params)


def test_params_azure_without_audience_falls_back_to_client_id():
    params = build_websearch_params(_azure_profile(websearch_jwt_audience=None))
    assert "ClientId=appclient123" in params


def test_params_okta_uses_client_id_as_audience():
    profile = _cognito_profile(provider_type="okta", provider_domain="company.okta.com")
    params = build_websearch_params(profile)
    assert "ClientId=client123" in params


def test_params_include_domain_denylist_when_set():
    params = build_websearch_params(_cognito_profile(websearch_domain_denylist=["a.com", "b.com"]))
    assert "DomainExcludeList=a.com,b.com" in params


# --- Deploy-all failure handling (Option C): websearch is optional/non-fatal ---


def _deploy_all_loop_source() -> str:
    """The body of the deploy-all loop in deploy.py (source-level contract test)."""
    import inspect

    from claude_code_with_bedrock.cli.commands import deploy as deploy_mod

    src = inspect.getsource(deploy_mod)
    start = src.index("for stack_type, description in stacks_to_deploy:")
    # Stop at the post-loop "if failed:" handling.
    end = src.index("if failed:", start)
    return src[start:end]


def test_deploy_all_treats_websearch_failure_as_non_fatal():
    """A failed optional websearch stack must not abort the whole `ccwb deploy` run.

    In the deploy-all loop a non-zero result for the websearch stack should
    `continue` (warn + remediation) rather than set failed/break, while other
    stacks remain fatal.
    """
    loop = _deploy_all_loop_source()
    # The websearch branch continues instead of failing the whole run.
    assert 'if stack_type == "websearch":' in loop
    ws_branch = loop[loop.index('if stack_type == "websearch":') :]
    # Within the websearch failure branch, we continue and never set failed = True.
    continue_idx = ws_branch.index("continue")
    assert "failed = True" not in ws_branch[:continue_idx]
    # Non-websearch failures still abort.
    assert "failed = True" in loop
    assert "break" in loop
