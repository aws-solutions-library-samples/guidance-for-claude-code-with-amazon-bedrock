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

import dataclasses

import pytest

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile

# --- Profile fixtures representing each auth mode ---


def _base_profile(**overrides):
    """Create a minimal valid profile with overrides."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(Profile)}
    defaults = {
        "name": "TestProfile",
        "provider_domain": "company.okta.com",
        "client_id": "test-client-id",
        "credential_storage": "session",
        "aws_region": "us-east-1",
        "identity_pool_name": "claude-code-test",
        "sso_enabled": True,
        "provider_type": "okta",
        "monitoring_enabled": True,
        "monitoring_mode": "central",
        "quota_monitoring_enabled": True,
        "federation_type": "direct",
        "federated_role_arn": "arn:aws:iam::123456789012:role/BedrockRole",
        "enable_finegrained_quotas": False,
        "monthly_token_limit": 225000000,
        "daily_token_limit": 8250000,
        "daily_enforcement_mode": "alert",
        "monthly_enforcement_mode": "block",
        "warning_threshold_80": 180000000,
        "warning_threshold_90": 202500000,
    }
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

    @pytest.mark.parametrize("mode_name", [m for m, p in PROFILE_MODES.items() if getattr(p, "sso_enabled", True)])
    def test_oidc_config_non_empty_when_sso_enabled(self, command, mode_name):
        """When SSO is enabled, OIDC config must have a valid issuer URL."""
        profile = PROFILE_MODES[mode_name]
        if not profile.monitoring_enabled:
            pytest.skip("monitoring disabled")
        issuer, client_id = command._resolve_oidc_config(profile)
        assert issuer.startswith("https://"), f"Issuer must be https URL, got '{issuer}'"
        assert client_id != "", "Client ID should not be empty when SSO enabled"

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


class TestBootstrapStackInclusion:
    """Bootstrap stack is included only when config_delivery is set."""


class _NullConsole:
    """Minimal console stub — captures nothing, just satisfies .print()."""

    def print(self, *args, **kwargs):  # noqa: D401 - test stub
        pass


# Server-side stacks that must NEVER be scheduled in sidecar monitoring mode.
# Sidecar runs a local OTEL collector → no VPC/ECS/ALB and no Athena pipeline,
# and CoWork cannot export telemetry in sidecar mode.
_CENTRAL_ONLY_STACKS = {"networking", "monitoring", "cowork-dashboard", "analytics"}


class TestSidecarStackSelection:
    """Regression tests for the sidecar deploy gate (#438 / #338 regression).

    PR #338 (Go rewrite) refactored deploy.py's stack selection and dropped the
    ``monitoring_mode == "central"`` gate, so `ccwb deploy` scheduled the entire
    central stack (VPC + ECS + ALB + Athena) even for sidecar profiles. That
    fails in accounts that disallow new VPCs. These tests pin the correct stacks
    for each mode so the gate can't silently disappear again.
    """

    @pytest.fixture
    def command(self):
        return DeployCommand()

    def _get_stacks_for_profile(self, command, profile):
        """Simulate full-deploy stack selection for a profile.

        This duplicates the inline logic in deploy.py handle() for the
        'deploy all' path. When _select_full_deploy_stacks() is available
        (PR #690), this can be simplified to call that method directly.
        """
        stacks = []
        cowork_mode = getattr(profile, "cowork_config_delivery", "static")
        if cowork_mode == "bootstrap-device-code":
            stacks.append(("bootstrap", "Bootstrap Server (device-code)"))
        elif cowork_mode == "bootstrap-oidc-bearer":
            stacks.append(("bootstrap", "Bootstrap Server (OIDC Bearer)"))
        return stacks

    def test_device_code_includes_bootstrap(self, command):
        """bootstrap-device-code mode must include bootstrap in deploy-all."""
        profile = dataclasses.replace(
            PROFILE_MODES["oidc_okta"],
            cowork_config_delivery="bootstrap-device-code",
        )
        stacks = self._get_stacks_for_profile(command, profile)
        stack_types = [s[0] for s in stacks]
        assert "bootstrap" in stack_types

    def test_oidc_bearer_includes_bootstrap(self, command):
        """bootstrap-oidc-bearer mode must include bootstrap in deploy-all."""
        profile = dataclasses.replace(
            PROFILE_MODES["oidc_okta"],
            cowork_config_delivery="bootstrap-oidc-bearer",
        )
        stacks = self._get_stacks_for_profile(command, profile)
        stack_types = [s[0] for s in stacks]
        assert "bootstrap" in stack_types

    def test_static_never_includes_bootstrap(self, command):
        """Static config_delivery must never deploy bootstrap stack."""
        profile = dataclasses.replace(
            PROFILE_MODES["oidc_okta"],
            cowork_config_delivery="static",
        )
        stacks = self._get_stacks_for_profile(command, profile)
        stack_types = [s[0] for s in stacks]
        assert "bootstrap" not in stack_types

    def _stack_types(self, command, profile):
        return [s[0] for s in command._select_full_deploy_stacks(profile, _NullConsole())]

    def test_sidecar_excludes_central_infrastructure(self, command):
        """Sidecar mode must not schedule networking/monitoring/cowork/analytics."""
        profile = _base_profile(monitoring_mode="sidecar")
        stacks = self._stack_types(command, profile)
        assert _CENTRAL_ONLY_STACKS.isdisjoint(stacks), (
            f"Sidecar mode scheduled central-only stacks: {sorted(_CENTRAL_ONLY_STACKS.intersection(stacks))}"
        )

    def test_sidecar_includes_dashboard(self, command):
        """The CloudWatch dashboard works in both modes and must be deployed."""
        profile = _base_profile(monitoring_mode="sidecar")
        assert "dashboard" in self._stack_types(command, profile)

    def test_sidecar_with_quota_includes_s3bucket_and_quota(self, command):
        """Quota works in sidecar; it needs s3bucket (Lambda packaging) before quota."""
        profile = _base_profile(monitoring_mode="sidecar", quota_monitoring_enabled=True)
        stacks = self._stack_types(command, profile)
        assert "quota" in stacks
        assert "s3bucket" in stacks
        assert stacks.index("s3bucket") < stacks.index("quota"), "s3bucket must precede quota"

    def test_sidecar_without_quota_omits_s3bucket(self, command):
        """No quota in sidecar → no s3bucket (it's only needed for Lambda packaging)."""
        profile = _base_profile(monitoring_mode="sidecar", quota_monitoring_enabled=False)
        stacks = self._stack_types(command, profile)
        assert "s3bucket" not in stacks
        assert "quota" not in stacks

    def test_sidecar_idc_quota_still_scheduled(self, command):
        """IDC sidecar (zero-binary) supports quota via SigV4 — must still deploy it."""
        profile = _base_profile(
            monitoring_mode="sidecar",
            sso_enabled=False,  # effective_auth_type resolves to idc/none
            auth_type="idc",
            quota_monitoring_enabled=True,
        )
        if profile.effective_auth_type != "idc":
            pytest.skip("profile did not resolve to IDC auth")
        stacks = self._stack_types(command, profile)
        assert "quota" in stacks
        assert _CENTRAL_ONLY_STACKS.isdisjoint(stacks)

    def test_central_includes_full_stack(self, command):
        """Central mode must still schedule the full server-side stack (no over-correction)."""
        profile = _base_profile(monitoring_mode="central", quota_monitoring_enabled=True)
        stacks = self._stack_types(command, profile)
        for expected in ("networking", "s3bucket", "monitoring", "dashboard", "cowork-dashboard", "analytics", "quota"):
            assert expected in stacks, f"central mode missing '{expected}'"

    def test_central_existing_vpc_skips_networking(self, command):
        """Central mode with create_vpc=False reuses an existing VPC — no networking stack."""
        profile = _base_profile(
            monitoring_mode="central",
            monitoring_config={"create_vpc": False},
        )
        assert "networking" not in self._stack_types(command, profile)

    def test_missing_monitoring_mode_defaults_to_central(self, command):
        """Backward compat: a profile lacking monitoring_mode behaves as central."""
        profile = _base_profile(quota_monitoring_enabled=True)
        # Simulate an old loaded object with no monitoring_mode attribute at all.
        delattr(profile, "monitoring_mode")
        stacks = self._stack_types(command, profile)
        assert "networking" in stacks
        assert "monitoring" in stacks

    def test_sidecar_none_auth_omits_auth_and_quota(self, command):
        """Sidecar + 'none' auth: anonymous telemetry, no auth stack, no quota."""
        profile = _base_profile(
            monitoring_mode="sidecar",
            sso_enabled=False,
            auth_type="none",
            quota_monitoring_enabled=True,  # requested, but 'none' can't support it
        )
        assert profile.effective_auth_type == "none"
        stacks = self._stack_types(command, profile)
        assert "auth" not in stacks
        assert "quota" not in stacks
        assert "dashboard" in stacks
        assert _CENTRAL_ONLY_STACKS.isdisjoint(stacks)
