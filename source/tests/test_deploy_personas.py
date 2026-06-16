# ABOUTME: Tests for deploy command persona + budgets orchestration.
# ABOUTME: Covers scheduling gates, Cognito skip, OIDC-import guard, group-policy seeding, idempotent AIPs — all mocked, no AWS.

"""Tests for ``DeployCommand`` persona-based access + budgets orchestration.

These exercise the deploy-time wiring added for persona-based access control:
the scheduling gates in ``handle()`` and the ``_deploy_persona_stack`` /
``_deploy_budgets_stack`` / ``_seed_persona_group_policies`` helpers. Everything
that touches AWS (``get_stack_outputs``, ``CloudFormationManager``,
``QuotaPolicyManager``, ``boto3``) is mocked — these tests never make a network
call (per the task: use unittest.mock; do NOT hit AWS).
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile

DEPLOY_MOD = "claude_code_with_bedrock.cli.commands.deploy"

# Two reference personas (design §3) — engineering unrestricted, sales restricted.
ENGINEERING = {
    "name": "engineering",
    "group": "eng-team",
    "allowed_models": ["anthropic.*"],
    "denied_models": [],
    "monthly_token_limit": 300000000,
    "enforcement_mode": "block",
    "cost_tags": {"Team": "Engineering"},
    "budget_amount_usd": 500,
}
SALES = {
    "name": "sales",
    "group": "sales-team",
    "allowed_models": ["anthropic.*haiku*"],
    "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
    "monthly_token_limit": 10000000,
    "enforcement_mode": "block",
    "cost_tags": {"Team": "Sales"},
    "budget_amount_usd": 50,
}


def _persona_profile(*, auth_type="oidc", personas=None, provider_type="okta"):
    """Build a Mock Profile that the persona deploy path can consume."""
    profile = Mock(spec=Profile)
    profile.profile_name = "test-profile"
    profile.aws_region = "us-east-1"
    profile.identity_pool_name = "test-pool"
    profile.provider_type = provider_type
    profile.provider_domain = "company.okta.com"
    profile.client_id = "abc123"
    profile.federation_type = "direct"
    profile.sso_enabled = auth_type == "oidc"
    profile.effective_auth_type = auth_type
    profile.personas = personas if personas is not None else [ENGINEERING, SALES]
    profile.groups_claim_name = "groups"
    profile.fallback_persona = None
    profile.allowed_bedrock_regions = ["us-east-1", "us-west-2"]
    profile.account_budget_amount_usd = None
    profile.stack_names = {}
    return profile


# ---------------------------------------------------------------------------
# Scheduling gates (replay handle()'s all-stacks persona block)
# ---------------------------------------------------------------------------
class TestPersonaScheduling:
    """Drives the REAL scheduling gate (DeployCommand._should_schedule_personas).

    Previously this test re-implemented the gate logic in a private ``_schedule`` copy,
    so a regression in handle()'s actual gate (e.g. flipping the OIDC check) would not
    be caught. We now call the production predicate directly; ``handle()`` uses the same
    method, so these assertions track the shipped behavior. The ``personas`` non-empty
    precondition that guards the gate in handle() is asserted explicitly here.
    """

    def _scheduled(self, profile) -> list[str]:
        """Replicate handle()'s outer guard (personas non-empty) + the REAL gate."""
        if not getattr(profile, "personas", []):
            return []
        if DeployCommand._should_schedule_personas(profile):
            return ["persona", "budgets"]
        return []

    def test_persona_and_budgets_scheduled_for_oidc_with_personas(self):
        assert self._scheduled(_persona_profile()) == ["persona", "budgets"]

    def test_gate_true_for_oidc(self):
        assert DeployCommand._should_schedule_personas(_persona_profile()) is True

    def test_skipped_when_no_personas(self):
        assert self._scheduled(_persona_profile(personas=[])) == []

    def test_skipped_when_auth_type_not_oidc(self):
        assert self._scheduled(_persona_profile(auth_type="idc")) == []
        assert self._scheduled(_persona_profile(auth_type="none")) == []

    def test_gate_false_when_not_oidc(self):
        assert DeployCommand._should_schedule_personas(_persona_profile(auth_type="idc")) is False
        assert DeployCommand._should_schedule_personas(_persona_profile(auth_type="none")) is False


# ---------------------------------------------------------------------------
# _resolve_issuer_host (#30 CRITICAL regression — issuer-url-format.md)
#
# The persona trust condition key MUST equal the auth stack's registered
# OIDC-provider Url with ONLY the scheme stripped. The earlier `rstrip("/")`
# bug dropped Auth0's REQUIRED trailing slash → every Auth0 persona user
# silently hard-denied. These tests pin the exact per-provider form; the Auth0
# case FAILS against the buggy rstrip code and PASSES after the fix.
# ---------------------------------------------------------------------------
class TestResolveIssuerHost:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_okta_bare_domain_no_slash(self, command):
        # Okta OIDC provider is registered at https://${OktaDomain} (bare domain).
        profile = _persona_profile(provider_type="okta")
        assert command._resolve_issuer_host(profile) == "company.okta.com"
        assert not command._resolve_issuer_host(profile).endswith("/")

    def test_auth0_preserves_trailing_slash(self, command):
        # REGRESSION (#30): Auth0 provider is registered as https://${Auth0Domain}/.
        # The STS condition key MUST keep the trailing slash → company.auth0.com/.
        # This assertion FAILS against the old rstrip("/") implementation.
        profile = _persona_profile(provider_type="auth0")
        profile.provider_domain = "company.auth0.com"
        host = command._resolve_issuer_host(profile)
        assert host == "company.auth0.com/", f"Auth0 slash dropped → all Auth0 personas hard-deny; got {host!r}"
        assert host.endswith("/")
        # The full trust-condition key the renderer builds:
        assert f"{host}:groups" == "company.auth0.com/:groups"

    def test_azure_v2_suffix_no_trailing_slash(self, command):
        # Azure provider is registered as https://login.microsoftonline.com/<tenant>/v2.0 (NO slash).
        profile = _persona_profile(provider_type="azure")
        profile.provider_domain = "login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
        host = command._resolve_issuer_host(profile)
        assert host == "login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
        assert host.endswith("/v2.0")
        assert not host.endswith("/")

    def test_generic_uses_oidc_issuer_url_not_provider_domain(self, command):
        # REGRESSION (review HIGH): the generic auth template registers the OIDC
        # provider as `Url: !Ref OidcIssuerUrl` (fed from profile.oidc_issuer_url),
        # NOT provider_domain. The trust-condition issuer-host MUST derive from
        # oidc_issuer_url, scheme-stripped, preserving any path (e.g. Keycloak/
        # Teleport realm path). Using provider_domain (which the bug did) emits the
        # wrong condition key → every generic-provider persona user is hard-denied.
        profile = _persona_profile(provider_type="generic")
        # The two fields are DISTINCT for generic providers:
        profile.provider_domain = "sso.example.com"
        profile.oidc_issuer_url = "https://sso.example.com/realms/prod"
        host = command._resolve_issuer_host(profile)
        assert host == "sso.example.com/realms/prod", (
            f"generic issuer-host must derive from oidc_issuer_url (got {host!r}); "
            "deriving from provider_domain silently hard-denies all generic persona users"
        )
        assert f"{host}:groups" == "sso.example.com/realms/prod:groups"

    def test_generic_issuer_scheme_stripped(self, command):
        # Generic provider with issuer == domain (no extra path): scheme-stripped.
        profile = _persona_profile(provider_type="generic")
        profile.provider_domain = "id.example.com"
        profile.oidc_issuer_url = "https://id.example.com"
        assert command._resolve_issuer_host(profile) == "id.example.com"

    def test_cognito_pool_host(self, command):
        profile = _persona_profile(provider_type="cognito")
        profile.cognito_user_pool_id = "us-east-1_abc123"
        assert command._resolve_issuer_host(profile) == "cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123"


# ---------------------------------------------------------------------------
# _deploy_persona_stack
# ---------------------------------------------------------------------------
class TestDeployPersonaStack:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    @pytest.fixture
    def console(self):
        return MagicMock()

    @pytest.fixture
    def deploy_with_cf(self):
        """A stand-in for the nested deploy closure; records its call, returns 0."""
        return MagicMock(return_value=0)

    def test_skips_when_not_oidc(self, command, console, deploy_with_cf):
        profile = _persona_profile(auth_type="none")
        result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)
        assert result == 0
        deploy_with_cf.assert_not_called()

    def test_invalid_persona_fails_before_render(self, command, console, deploy_with_cf):
        # REGRESSION (review MEDIUM): a hand-edited config with a bad enforcement_mode
        # must FAIL the deploy (validate_personas), not silently render infra that
        # downgrades block→alert. Returns 1, never reaches deploy/render.
        bad = {**ENGINEERING, "enforcement_mode": "deny"}  # typo: not alert|block
        profile = _persona_profile(personas=[bad])
        result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)
        assert result == 1
        deploy_with_cf.assert_not_called()

    def test_non_dns_safe_persona_name_fails_before_render(self, command, console, deploy_with_cf):
        # REGRESSION: a persona name that is not DNS/IAM-safe sanitizes into an
        # invalid CloudFormation logical id (and an illegal IAM resource name). It
        # must be rejected by validate_personas at the top of the deploy path —
        # returning 1 and never rendering/deploying — rather than failing opaquely
        # at CloudFormation create time.
        bad = {**ENGINEERING, "name": "data science"}  # space → not DNS/IAM-safe
        profile = _persona_profile(personas=[bad])
        result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)
        assert result == 1
        deploy_with_cf.assert_not_called()

    def test_cognito_federation_skips_with_warning(self, command, console, deploy_with_cf):
        profile = _persona_profile()
        with patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={"FederationType": "cognito"}):
            result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)
        assert result == 0  # skip is not a failure
        deploy_with_cf.assert_not_called()

    def test_missing_oidc_provider_arn_fails_clearly(self, command, console, deploy_with_cf):
        profile = _persona_profile()
        # Direct federation but no OIDCProviderArn export → clear stack-ordering error.
        with patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={"FederationType": "direct"}):
            result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)
        assert result == 1
        deploy_with_cf.assert_not_called()

    def test_happy_path_renders_deploys_and_seeds(self, command, console, deploy_with_cf, tmp_path):
        profile = _persona_profile()

        # Auth stack exports a direct-mode OIDC provider ARN.
        auth_outputs = {
            "FederationType": "direct",
            "OIDCProviderArn": "arn:aws:iam::111122223333:oidc-provider/company.okta.com",
        }

        seed = MagicMock()
        aips = MagicMock()
        writeback = MagicMock()
        dashboard = MagicMock()
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value=auth_outputs),
            patch.object(command, "_seed_persona_group_policies", seed),
            patch.object(command, "_create_persona_inference_profiles", aips),
            patch.object(command, "_write_back_persona_role_arns", writeback),
            patch.object(command, "_deploy_persona_dashboard", dashboard),
            patch.object(command, "_resolve_issuer_host", return_value="company.okta.com"),
            patch(f"{DEPLOY_MOD}.Path") as mock_path,
        ):
            # Redirect the build dir under tmp_path so the write touches no repo files.
            mock_path.return_value.parents.__getitem__.return_value = tmp_path
            result = command._deploy_persona_stack(profile, console, Mock(), deploy_with_cf)

        assert result == 0
        # The persona stack itself is deployed once here. The dashboard deploy is a
        # separate call (_deploy_persona_dashboard, patched out above) made inline after
        # seeding — so deploy_with_cf is invoked exactly once for the persona stack.
        deploy_with_cf.assert_called_once()
        args, kwargs = deploy_with_cf.call_args
        # positional: (template_path, stack_name, params, capabilities, ...)
        # Stack name uses the "persona" type verbatim so `ccwb destroy` matches it.
        assert args[1] == "test-pool-persona"
        params = args[2]
        assert any(p.startswith("AuthStackName=") for p in params)
        assert any(p.startswith("AllowedBedrockRegions=") for p in params)
        assert args[3] == ["CAPABILITY_NAMED_IAM"]
        # Post-deploy steps ran: role_arn write-back + group-policy + AIP seeding + dashboard.
        writeback.assert_called_once()
        seed.assert_called_once()
        aips.assert_called_once()
        dashboard.assert_called_once()

    def test_deploy_failure_skips_seeding(self, command, console, tmp_path):
        profile = _persona_profile()
        failing_deploy = MagicMock(return_value=1)
        auth_outputs = {
            "FederationType": "direct",
            "OIDCProviderArn": "arn:aws:iam::111122223333:oidc-provider/company.okta.com",
        }
        seed = MagicMock()
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value=auth_outputs),
            patch.object(command, "_seed_persona_group_policies", seed),
            patch.object(command, "_create_persona_inference_profiles", MagicMock()),
            patch.object(command, "_resolve_issuer_host", return_value="company.okta.com"),
            patch(f"{DEPLOY_MOD}.Path") as mock_path,
        ):
            mock_path.return_value.parents.__getitem__.return_value = tmp_path
            result = command._deploy_persona_stack(profile, console, Mock(), failing_deploy)
        assert result == 1
        seed.assert_not_called()  # don't seed policies if the stack didn't deploy


# ---------------------------------------------------------------------------
# _seed_persona_group_policies (spec D6)
# ---------------------------------------------------------------------------
class TestSeedPersonaGroupPolicies:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_seeds_group_policy_per_persona(self, command):
        profile = _persona_profile()
        console = MagicMock()
        manager = MagicMock()

        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={"PoliciesTableName": "quota-policies"}),
            patch("claude_code_with_bedrock.quota_policies.QuotaPolicyManager", return_value=manager),
        ):
            command._seed_persona_group_policies(profile, console)

        # One create_policy per persona, all GROUP type with the persona's group identifier.
        assert manager.create_policy.call_count == 2
        identifiers = {kw["identifier"] for _a, kw in manager.create_policy.call_args_list}
        assert identifiers == {"eng-team", "sales-team"}
        for _a, kw in manager.create_policy.call_args_list:
            from claude_code_with_bedrock.models import PolicyType

            assert kw["policy_type"] == PolicyType.GROUP

    def test_skips_when_no_policies_table(self, command):
        profile = _persona_profile()
        console = MagicMock()
        manager = MagicMock()
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={}),
            patch("claude_code_with_bedrock.quota_policies.QuotaPolicyManager", return_value=manager),
        ):
            command._seed_persona_group_policies(profile, console)
        manager.create_policy.assert_not_called()

    def test_existing_policy_is_tolerated(self, command):
        from claude_code_with_bedrock.quota_policies import PolicyAlreadyExistsError

        profile = _persona_profile(personas=[ENGINEERING])
        console = MagicMock()
        manager = MagicMock()
        manager.create_policy.side_effect = PolicyAlreadyExistsError("exists")
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={"PoliciesTableName": "t"}),
            patch("claude_code_with_bedrock.quota_policies.QuotaPolicyManager", return_value=manager),
        ):
            # Must not raise — already-exists is a benign skip.
            command._seed_persona_group_policies(profile, console)
        manager.create_policy.assert_called_once()


# ---------------------------------------------------------------------------
# _deploy_budgets_stack
# ---------------------------------------------------------------------------
class TestDeployBudgetsStack:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_skips_when_no_budgets_configured(self, command):
        # Personas without budget_amount_usd and no account budget → nothing to deploy.
        personas = [
            {"name": "engineering", "group": "eng-team", "allowed_models": ["anthropic.*"]},
        ]
        profile = _persona_profile(personas=personas)
        profile.account_budget_amount_usd = None
        deploy = MagicMock(return_value=0)
        result = command._deploy_budgets_stack(profile, MagicMock(), deploy)
        assert result == 0
        deploy.assert_not_called()

    def test_renders_and_deploys_when_persona_budget_present(self, command, tmp_path):
        profile = _persona_profile()  # eng + sales both carry budget_amount_usd
        deploy = MagicMock(return_value=0)
        with patch(f"{DEPLOY_MOD}.Path") as mock_path:
            mock_path.return_value.parents.__getitem__.return_value = tmp_path
            result = command._deploy_budgets_stack(profile, MagicMock(), deploy)
        assert result == 0
        deploy.assert_called_once()
        args, _kwargs = deploy.call_args
        assert args[1] == "test-pool-budgets"
        assert args[3] == ["CAPABILITY_IAM"]

    def test_skips_when_not_oidc(self, command):
        profile = _persona_profile(auth_type="none")
        deploy = MagicMock(return_value=0)
        result = command._deploy_budgets_stack(profile, MagicMock(), deploy)
        assert result == 0
        deploy.assert_not_called()


# ---------------------------------------------------------------------------
# _deploy_persona_dashboard (FR-7 observability, step-9 gap fix)
#
# The dashboard is deployed INLINE by the persona flow (not a scheduled stack
# type), so destroy.py does not list it in DESTROYABLE_STACKS. The method uses
# the committed static template and skips cleanly if it's missing.
# ---------------------------------------------------------------------------
class TestDeployPersonaDashboard:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_deploys_dashboard_with_expected_name_and_params(self, command, tmp_path):
        profile = _persona_profile()
        deploy = MagicMock(return_value=0)
        # Redirect project_root/deployment/infrastructure/bedrock-personas-dashboard.yaml
        # to a real tmp file so template.exists() is True.
        fake_template = tmp_path / "bedrock-personas-dashboard.yaml"
        fake_template.write_text("Resources: {}", encoding="utf-8")
        with patch(f"{DEPLOY_MOD}.Path") as mock_path:
            (
                mock_path.return_value.parents.__getitem__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value
            ) = fake_template
            result = command._deploy_persona_dashboard(profile, MagicMock(), deploy)
        assert result == 0
        deploy.assert_called_once()
        args, _kwargs = deploy.call_args
        # Stack name uses the "persona-dashboard" type verbatim so destroy/orphan-check matches.
        assert args[1] == "test-pool-persona-dashboard"
        params = args[2]
        assert any(p.startswith("MetricsRegion=") for p in params)

    def test_skips_when_template_missing(self, command, tmp_path):
        profile = _persona_profile()
        deploy = MagicMock(return_value=0)
        missing = tmp_path / "nope.yaml"  # does not exist
        with patch(f"{DEPLOY_MOD}.Path") as mock_path:
            (
                mock_path.return_value.parents.__getitem__.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value
            ) = missing
            result = command._deploy_persona_dashboard(profile, MagicMock(), deploy)
        # Missing template → skip (return 0), no deploy, no crash.
        assert result == 0
        deploy.assert_not_called()


# ---------------------------------------------------------------------------
# _compute_persona_order (PBAC declared-order bridge, spec D3)
# ---------------------------------------------------------------------------
class TestComputePersonaOrder:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_groups_joined_in_declared_order(self, command):
        # Declared order eng then sales → "eng-team,sales-team" (NOT sorted).
        profile = _persona_profile(personas=[ENGINEERING, SALES])
        assert command._compute_persona_order(profile) == "eng-team,sales-team"

    def test_declared_order_is_preserved_when_reversed(self, command):
        profile = _persona_profile(personas=[SALES, ENGINEERING])
        assert command._compute_persona_order(profile) == "sales-team,eng-team"

    def test_empty_when_no_personas(self, command):
        # Empty string keeps the quota Lambdas in legacy most-restrictive mode.
        assert command._compute_persona_order(_persona_profile(personas=[])) == ""

    def test_empty_when_not_oidc(self, command):
        assert command._compute_persona_order(_persona_profile(auth_type="idc")) == ""

    def test_duplicate_groups_deduplicated_preserving_order(self, command):
        personas = [
            {"name": "a", "group": "shared"},
            {"name": "b", "group": "other"},
            {"name": "c", "group": "shared"},
        ]
        assert command._compute_persona_order(_persona_profile(personas=personas)) == "shared,other"


# ---------------------------------------------------------------------------
# _write_back_persona_role_arns (role_arn contract for ccwb package, spec §4.2)
# ---------------------------------------------------------------------------
class TestWriteBackPersonaRoleArns:
    @pytest.fixture
    def command(self):
        return DeployCommand()

    def test_populates_role_arn_from_stack_outputs(self, command):
        # Mutable persona dicts (not the module-level constants) so the test can assert mutation.
        personas = [
            {"name": "engineering", "group": "eng-team"},
            {"name": "sales", "group": "sales-team"},
        ]
        profile = _persona_profile(personas=personas)
        # Output keys use the renderer's sanitized stem: engineering->Engineering, sales->Sales.
        outputs = {
            "EngineeringRoleArn": "arn:aws:iam::111122223333:role/p-Engineering",
            "SalesRoleArn": "arn:aws:iam::111122223333:role/p-Sales",
        }
        # Patch Config so the persist step never touches the real filesystem.
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value=outputs),
            patch("claude_code_with_bedrock.config.Config") as mock_config,
        ):
            command._write_back_persona_role_arns(profile, "test-pool-personas", MagicMock())

        assert personas[0]["role_arn"] == "arn:aws:iam::111122223333:role/p-Engineering"
        assert personas[1]["role_arn"] == "arn:aws:iam::111122223333:role/p-Sales"
        # Persisted exactly once so `ccwb package` (a separate invocation) sees the ARNs.
        mock_config.load.return_value.save_profile.assert_called_once_with(profile)

    def test_hyphenated_persona_name_maps_to_sanitized_output_key(self, command):
        personas = [{"name": "data-science", "group": "ds-team"}]
        profile = _persona_profile(personas=personas)
        outputs = {"DataScienceRoleArn": "arn:aws:iam::111122223333:role/p-DataScience"}
        with (
            patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value=outputs),
            patch("claude_code_with_bedrock.config.Config"),
        ):
            command._write_back_persona_role_arns(profile, "stack", MagicMock())
        assert personas[0]["role_arn"] == "arn:aws:iam::111122223333:role/p-DataScience"

    def test_missing_output_does_not_crash(self, command):
        personas = [{"name": "engineering", "group": "eng-team"}]
        profile = _persona_profile(personas=personas)
        with patch(f"{DEPLOY_MOD}.get_stack_outputs", return_value={}):
            # Must not raise; role_arn simply stays unset.
            command._write_back_persona_role_arns(profile, "stack", MagicMock())
        assert "role_arn" not in personas[0]


# ---------------------------------------------------------------------------
# Per-tier Application Inference Profile creation (FR-5.1)
# ---------------------------------------------------------------------------
class TestPersonaInferenceProfiles:
    """_create_persona_inference_profiles: per-tier AIPs from CRIS sources,
    partition-aware (L-a fix), with ARN read-back into the persona dicts."""

    @pytest.fixture
    def command(self):
        return DeployCommand()

    def _fake_bedrock_client(self, created):
        """A boto3-bedrock stand-in that records create calls and returns ARNs."""
        client = MagicMock()

        # No pre-existing profiles.
        paginator = MagicMock()
        paginator.paginate.return_value = [{"inferenceProfileSummaries": []}]
        client.get_paginator.return_value = paginator

        def _create(**kwargs):
            name = kwargs["inferenceProfileName"]
            created.append(kwargs)
            arn = f"arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/{name}"
            return {"inferenceProfileArn": arn}

        client.create_inference_profile.side_effect = _create
        return client

    def _profile(self, personas):
        profile = Mock(spec=Profile)
        profile.aws_region = "us-east-1"
        profile.identity_pool_name = "pool"
        profile.cross_region_profile = "us"
        profile.personas = personas
        return profile

    def test_per_tier_aips_created_from_cris_source(self, command):
        created = []
        client = self._fake_bedrock_client(created)
        sales = {"name": "sales", "group": "s", "allowed_models": ["anthropic.*haiku*"],
                 "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"], "cost_tags": {"Team": "Sales"}}
        profile = self._profile([sales])
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())

        # Sales is haiku-only → exactly one AIP, named pool-sales-haiku.
        assert [c["inferenceProfileName"] for c in created] == ["pool-sales-haiku"]
        # copyFrom must be a cross-Region (system-defined) inference profile, not a
        # bare foundation-model (else the AIP is single-Region and breaks CRIS).
        src = created[0]["modelSource"]["copyFrom"]
        assert ":inference-profile/us." in src
        assert "foundation-model/" not in src
        # ARN wired back into the persona dict for package serialization (FR-5.1).
        assert sales["inference_profile_arns"]["haiku"].endswith("application-inference-profile/pool-sales-haiku")

    def test_data_residency_denied_fallback_tier_is_skipped(self, command):
        # LOW 3: under a data-residency prefix where a tier has no model, cris_source_arn
        # falls back to another tier's model id. If that fallback id is DENIED by the
        # persona, an AIP built from it would only AccessDenied at runtime — so it must be
        # skipped. Persona allows all but denies sonnet, deployed jp: opus/jp resolves to
        # jp.anthropic.claude-sonnet-4-6 (denied) → opus AIP skipped; haiku still created.
        created = []
        client = self._fake_bedrock_client(created)
        res = {"name": "res", "group": "r", "allowed_models": ["anthropic.*"],
               "denied_models": ["anthropic.*sonnet*"], "cost_tags": {"Team": "Res"}}
        profile = self._profile([res])
        profile.cross_region_profile = "jp"
        profile.aws_region = "ap-northeast-1"
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())
        names = sorted(c["inferenceProfileName"] for c in created)
        # opus is entitled but its jp source is a denied sonnet model → skipped.
        assert names == ["pool-res-haiku"], f"opus (denied sonnet fallback) must be skipped; got {names}"
        assert "opus" not in res.get("inference_profile_arns", {})

    def test_engineering_gets_all_three_tiers(self, command):
        created = []
        client = self._fake_bedrock_client(created)
        eng = {"name": "eng", "group": "e", "allowed_models": ["anthropic.*"], "denied_models": [],
               "cost_tags": {"Team": "Eng"}}
        profile = self._profile([eng])
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())
        names = sorted(c["inferenceProfileName"] for c in created)
        assert names == ["pool-eng-haiku", "pool-eng-opus", "pool-eng-sonnet"]
        assert set(eng["inference_profile_arns"]) == {"haiku", "sonnet", "opus"}

    def test_govcloud_partition_in_source_arn(self, command):
        created = []
        client = self._fake_bedrock_client(created)
        profile = self._profile([{"name": "sales", "group": "s", "allowed_models": ["anthropic.*haiku*"],
                                  "cost_tags": {"T": "x"}}])
        profile.aws_region = "us-gov-west-1"
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())
        # L-a fix: source ARN is partition-aware (aws-us-gov), not hardcoded arn:aws:.
        assert created[0]["modelSource"]["copyFrom"].startswith("arn:aws-us-gov:bedrock:us-gov-west-1::")

    def test_cost_tags_and_persona_tier_tags_attached(self, command):
        created = []
        client = self._fake_bedrock_client(created)
        profile = self._profile([{"name": "sales", "group": "s", "allowed_models": ["anthropic.*haiku*"],
                                  "cost_tags": {"Team": "Sales"}}])
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())
        tags = {t["key"]: t["value"] for t in created[0]["tags"]}
        assert tags["Team"] == "Sales"
        assert tags["Persona"] == "sales"
        assert tags["Tier"] == "haiku"

    def test_existing_profile_arn_read_back_without_recreate(self, command):
        # An AIP that already exists must be reused (ARN read back), not recreated.
        client = MagicMock()
        existing_arn = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/pool-sales-haiku"
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "inferenceProfileSummaries": [
                {"inferenceProfileName": "pool-sales-haiku", "inferenceProfileArn": existing_arn}
            ]
        }]
        client.get_paginator.return_value = paginator
        sales = {"name": "sales", "group": "s", "allowed_models": ["anthropic.*haiku*"], "cost_tags": {"T": "x"}}
        profile = self._profile([sales])
        with patch("boto3.client", return_value=client), patch("claude_code_with_bedrock.config.Config"):
            command._create_persona_inference_profiles(profile, MagicMock())
        client.create_inference_profile.assert_not_called()
        assert sales["inference_profile_arns"]["haiku"] == existing_arn


# ---------------------------------------------------------------------------
# _check_orphaned_stacks — the inline persona-dashboard must not be mis-flagged
# as an orphan on a normal persona deploy (it is deployed inline by
# _deploy_persona_stack, so it never appears in deploying_types).
# ---------------------------------------------------------------------------
class TestOrphanedStackCheck:
    """Guards the persona-dashboard orphan false-positive.

    The dashboard is deployed inline by the persona flow, not as a scheduled stack
    type, so it is never in ``deploying_types``. Before the fix, every all-stacks
    re-deploy with personas configured flagged the live dashboard as orphaned and
    offered to delete it. It must only be flagged once the ``persona`` stack itself
    is no longer being deployed (personas removed from config).
    """

    def _command(self):
        return DeployCommand()

    def _profile(self):
        profile = Mock(spec=Profile)
        profile.identity_pool_name = "test-pool"
        profile.stack_names = {}
        return profile

    def test_inline_dashboard_not_flagged_when_persona_deploying(self):
        """persona stack deploying → its inline dashboard is NOT an orphan."""
        command = self._command()
        profile = self._profile()
        cf_manager = MagicMock()
        # Only the persona-dashboard exists; everything else is absent.
        cf_manager.get_stack_status.side_effect = (
            lambda name: "CREATE_COMPLETE" if name == "test-pool-persona-dashboard" else None
        )
        # 'persona' IS being deployed (personas configured) — dashboard rides along.
        stacks_to_deploy = [("auth", "Auth"), ("persona", "Persona-Based Access Control")]
        orphaned = command._check_orphaned_stacks(stacks_to_deploy, profile, cf_manager, MagicMock())
        flagged = {t for t, _n, _s in orphaned}
        assert "persona-dashboard" not in flagged, (
            "persona-dashboard rides along with the persona deploy and must not be "
            "reported as orphaned when the persona stack is deploying"
        )

    def test_leftover_dashboard_flagged_when_persona_removed(self):
        """personas removed (persona stack NOT deploying) → leftover dashboard IS an orphan."""
        command = self._command()
        profile = self._profile()
        cf_manager = MagicMock()
        cf_manager.get_stack_status.side_effect = (
            lambda name: "CREATE_COMPLETE" if name == "test-pool-persona-dashboard" else None
        )
        # 'persona' is NOT in the deploy set (personas removed from config).
        stacks_to_deploy = [("auth", "Auth")]
        orphaned = command._check_orphaned_stacks(stacks_to_deploy, profile, cf_manager, MagicMock())
        flagged = {t for t, _n, _s in orphaned}
        assert "persona-dashboard" in flagged, (
            "a leftover persona-dashboard must be detected as orphaned once personas "
            "are removed and the persona stack is no longer deployed"
        )
