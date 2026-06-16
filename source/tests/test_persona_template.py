# ABOUTME: Tests for the persona CloudFormation renderer (persona_template.render_personas_stack).
# ABOUTME: Asserts valid YAML, per-persona roles, the all-3-ARN-shapes Deny (spec D8), and bedrock: namespace.

"""Unit tests for ``persona_template.render_personas_stack``.

The renderer is a pure function, so these tests render representative persona
sets and assert on the parsed CloudFormation structure. The headline guard is
spec Decision **D8** / FR-2.3: a restricted persona's Deny must span all three
Bedrock ARN shapes (foundation-model, inference-profile,
application-inference-profile) — a foundation-model-only Deny is bypassable via
cross-region inference profiles. The dedicated bypass-guard test lives in
Group 4 (``test_persona_policy_bypass.py``); this file proves the renderer
emits the correct shape in the first place.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claude_code_with_bedrock.persona_template import render_personas_stack

# The two reference personas from design §3. Engineering is unrestricted;
# Sales is restricted (Haiku-only) and must carry the all-shapes Deny + a
# permission boundary.
ENGINEERING = {
    "name": "engineering",
    "display_name": "Engineering",
    "group": "eng-team",
    "allowed_models": ["anthropic.*"],
    "denied_models": [],
    "monthly_token_limit": 300000000,
    "enforcement_mode": "block",
    "cost_tags": {"Team": "Engineering"},
}
SALES = {
    "name": "sales",
    "display_name": "Sales",
    "group": "sales-team",
    "allowed_models": ["anthropic.*haiku*"],
    "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
    "monthly_token_limit": 10000000,
    "enforcement_mode": "block",
    "cost_tags": {"Team": "Sales"},
}

ISSUER_HOST = "company.okta.com"
GROUPS_CLAIM = "groups"

# The three Bedrock ARN resource-prefixes that Allow/Deny must span.
ARN_SHAPE_PREFIXES = ("foundation-model", "inference-profile", "application-inference-profile")


@pytest.fixture
def rendered_doc() -> dict:
    """Render the two reference personas and return the parsed CFN document."""
    yaml_text = render_personas_stack([ENGINEERING, SALES], GROUPS_CLAIM, ISSUER_HOST)
    # Full-form intrinsics → a plain SafeLoader parses without custom tags.
    return yaml.safe_load(yaml_text)


def _resources(doc: dict) -> dict:
    return doc["Resources"]


def _find_role(doc: dict, stem: str) -> dict:
    return _resources(doc)[f"{stem}Role"]


def _find_policy(doc: dict, stem: str) -> dict:
    return _resources(doc)[f"{stem}Policy"]


def _statements(policy_resource: dict) -> list[dict]:
    return policy_resource["Properties"]["PolicyDocument"]["Statement"]


def _arn_str(resource) -> str:
    """Normalize a policy Resource entry to its string form.

    Model ARNs are emitted as ``{"Fn::Sub": "arn:${AWS::Partition}:..."}`` so the
    partition pseudo-parameter resolves at deploy time; ``"*"`` and other plain
    strings pass through unchanged.
    """
    if isinstance(resource, dict) and "Fn::Sub" in resource:
        return resource["Fn::Sub"]
    return resource


def _arn_strs(resources) -> list[str]:
    if isinstance(resources, str):
        return [resources]
    return [_arn_str(r) for r in resources]


def test_renders_valid_yaml_and_template_shell(rendered_doc):
    """Output parses as YAML and carries the expected top-level CFN structure."""
    assert rendered_doc["AWSTemplateFormatVersion"] == "2010-09-09"
    assert "Persona" in rendered_doc["Description"]
    params = rendered_doc["Parameters"]
    assert params["AuthStackName"]["Type"] == "String"
    assert params["AllowedBedrockRegions"]["Type"] == "CommaDelimitedList"


def test_both_persona_roles_present(rendered_doc):
    """Each persona yields a role + access policy under sanitized logical ids."""
    resources = _resources(rendered_doc)
    assert "EngTeamRole" not in resources  # logical id derives from NAME, not group
    assert "EngineeringRole" in resources
    assert "EngineeringPolicy" in resources
    assert "SalesRole" in resources
    assert "SalesPolicy" in resources
    assert resources["EngineeringRole"]["Type"] == "AWS::IAM::Role"


def test_trust_policy_uses_imported_oidc_provider_and_groups_condition(rendered_doc):
    """Trust policy federates the imported OIDC ARN and gates on the groups claim."""
    role = _find_role(rendered_doc, "Sales")
    statement = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]

    # Federated principal is an Fn::ImportValue of <AuthStackName>-OIDCProviderArn.
    federated = statement["Principal"]["Federated"]
    assert "Fn::ImportValue" in federated
    assert federated["Fn::ImportValue"]["Fn::Sub"] == "${AuthStackName}-OIDCProviderArn"

    # Web-identity + tag-session, matching the auth templates.
    assert set(statement["Action"]) == {"sts:AssumeRoleWithWebIdentity", "sts:TagSession"}

    # Group condition uses ForAnyValue:StringEquals on "<issuer>:groups" -> [group].
    cond = statement["Condition"]["ForAnyValue:StringEquals"]
    key = f"{ISSUER_HOST}:{GROUPS_CLAIM}"
    assert key in cond
    assert cond[key] == ["sales-team"]


def test_sales_deny_spans_all_three_arn_shapes(rendered_doc):
    """R-highest: the restricted persona's Deny must cover every ARN shape (spec D8)."""
    policy = _find_policy(rendered_doc, "Sales")
    deny = [s for s in _statements(policy) if s["Effect"] == "Deny"]
    assert deny, "sales persona must have an explicit Deny statement"
    deny_resources = _arn_strs(deny[0]["Resource"])

    # Every ARN shape must appear, for every denied glob.
    for prefix in ARN_SHAPE_PREFIXES:
        matching = [r for r in deny_resources if f":{prefix}/" in r]
        assert matching, f"Deny missing ARN shape {prefix}; resources={deny_resources}"

    # And the denied model globs must be present (sonnet + opus), proving we did
    # not silently drop one. Inference-profile shapes get a leading '*' because
    # those ARNs carry a region/system prefix ahead of the model id.
    joined = "\n".join(deny_resources)
    assert "sonnet" in joined
    assert "opus" in joined
    assert "foundation-model/anthropic.*sonnet*" in joined
    assert "inference-profile/*anthropic.*sonnet*" in joined
    assert "application-inference-profile/*anthropic.*opus*" in joined


def test_global_cris_allow_glob_actually_matches_real_global_model_ids():
    """The region-less global-CRIS Allow/Deny globs must MATCH real ``global.anthropic.*``
    model ids — not merely exist.

    Regression for an inert-statement bug: the global FM ARN was emitted as
    ``foundation-model/anthropic.*haiku*`` (no leading ``*``), but a real global model id
    is ``global.anthropic.claude-haiku-…``. IAM resource matching is anchored, so the
    glob never matched the id — the Allow granted nothing on the global path and the Deny
    guarded a path it could never reach (both fail closed, so no bypass, but global models
    were silently unusable for every persona). The prior tests only asserted the ARN
    *string was present*, which is exactly why this slipped three hardening passes. This
    test models IAM's anchored wildcard match with ``fnmatch`` against a concrete global id.
    """
    import fnmatch

    doc = yaml.safe_load(render_personas_stack([SALES], GROUPS_CLAIM, ISSUER_HOST))

    def _global_fm_globs(effect: str, keyword: str) -> list[str]:
        out: list[str] = []
        for policy_stem in ("Sales", "SalesBoundary"):
            policy = _resources(doc).get(f"{policy_stem}")
            if not policy:
                continue
            for stmt in _statements(policy):
                if stmt["Effect"] != effect:
                    continue
                for arn in _arn_strs(stmt["Resource"]):
                    marker = ":bedrock:::foundation-model/"
                    if marker in arn and keyword in arn:
                        out.append(arn.split(marker, 1)[1])
        return out

    # Sales: haiku allowed, sonnet/opus denied. Use the real shipped global ids.
    real_global_haiku = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    real_global_opus = "global.anthropic.claude-opus-4-7"

    allow_haiku_globs = _global_fm_globs("Allow", "haiku")
    assert allow_haiku_globs, "sales must emit a region-less global FM Allow for its allowed (haiku) models"
    assert any(fnmatch.fnmatchcase(real_global_haiku, g) for g in allow_haiku_globs), (
        f"global FM Allow globs {allow_haiku_globs} do not match the real global haiku id "
        f"{real_global_haiku!r} — the global Allow is inert (anchored-match bug)."
    )

    deny_opus_globs = _global_fm_globs("Deny", "opus")
    assert deny_opus_globs, "sales must emit a region-less global FM Deny for its denied (opus) models"
    assert any(fnmatch.fnmatchcase(real_global_opus, g) for g in deny_opus_globs), (
        f"global FM Deny globs {deny_opus_globs} do not match the real global opus id "
        f"{real_global_opus!r} — a denied model is reachable via global routing."
    )


def test_version_pinned_deny_glob_gets_trailing_wildcard():
    """L5: a denied glob WITHOUT a trailing wildcard must be normalized to cover
    versioned model ids (e.g. `anthropic.claude-opus-4-7` → matches
    `us.anthropic.claude-opus-4-7-v1:0`). Without the trailing `*`, the inference-profile
    Deny would silently under-match the real invoked id."""
    persona = {
        "name": "pinned",
        "group": "pinned-team",
        "allowed_models": ["anthropic.*haiku*"],
        # Operator pins a version with NO trailing wildcard — the footgun case.
        "denied_models": ["anthropic.claude-opus-4-7"],
    }
    doc = yaml.safe_load(render_personas_stack([persona], GROUPS_CLAIM, ISSUER_HOST))
    deny = [s for s in _statements(_find_policy(doc, "Pinned")) if s["Effect"] == "Deny"]
    assert deny, "restricted persona must have a Deny"
    joined = "\n".join(_arn_strs(deny[0]["Resource"]))
    # The normalized glob ends in '*', so the foundation-model Deny is
    # 'anthropic.claude-opus-4-7*' and the inference-profile Deny is
    # '*anthropic.claude-opus-4-7*' — both match the versioned '…-v1:0' id.
    assert "foundation-model/anthropic.claude-opus-4-7*" in joined
    assert "inference-profile/*anthropic.claude-opus-4-7*" in joined
    # No bare (wildcard-less) form should remain that would miss the version suffix.
    assert "foundation-model/anthropic.claude-opus-4-7\n" not in joined + "\n"


def test_trailing_wildcard_deny_glob_is_not_double_starred():
    """A glob that already ends in '*' must not gain a second one."""
    persona = {
        "name": "already",
        "group": "g",
        "allowed_models": ["anthropic.*haiku*"],
        "denied_models": ["anthropic.*opus*"],
    }
    doc = yaml.safe_load(render_personas_stack([persona], GROUPS_CLAIM, ISSUER_HOST))
    deny = [s for s in _statements(_find_policy(doc, "Already")) if s["Effect"] == "Deny"]
    joined = "\n".join(_arn_strs(deny[0]["Resource"]))
    assert "opus**" not in joined  # no double wildcard
    assert "foundation-model/anthropic.*opus*" in joined


def test_engineering_has_no_deny_and_no_boundary(rendered_doc):
    """An unrestricted persona (empty denied_models) gets no Deny and no boundary."""
    policy = _find_policy(rendered_doc, "Engineering")
    assert not [s for s in _statements(policy) if s["Effect"] == "Deny"]

    resources = _resources(rendered_doc)
    assert "EngineeringBoundary" not in resources
    assert "PermissionsBoundary" not in _find_role(rendered_doc, "Engineering")["Properties"]


def test_restricted_persona_gets_permission_boundary(rendered_doc):
    """Sales (restricted) gets a permission-boundary ManagedPolicy wired onto the role."""
    resources = _resources(rendered_doc)
    assert "SalesBoundary" in resources
    assert resources["SalesBoundary"]["Type"] == "AWS::IAM::ManagedPolicy"

    role_props = _find_role(rendered_doc, "Sales")["Properties"]
    assert role_props["PermissionsBoundary"] == {"Ref": "SalesBoundary"}

    # The boundary itself must also carry the all-shapes Deny so it actually caps.
    boundary_stmts = resources["SalesBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    boundary_deny = [s for s in boundary_stmts if s["Effect"] == "Deny"]
    assert boundary_deny
    boundary_deny_resources = _arn_strs(boundary_deny[0]["Resource"])
    for prefix in ARN_SHAPE_PREFIXES:
        assert any(f":{prefix}/" in r for r in boundary_deny_resources)


def test_invoke_actions_match_auth_template_set(rendered_doc):
    """Invoke actions match the shipped auth-template set (Converse is authorized via InvokeModel).

    Listing bedrock:Converse explicitly is functionally redundant and trips a
    stale-DB cfn-lint warning, so the renderer grants the same actions the
    bedrock-auth-*.yaml templates do; this test pins that decision.
    """
    policy = _find_policy(rendered_doc, "Engineering")
    allow_invoke = next(
        s for s in _statements(policy) if s["Effect"] == "Allow" and "bedrock:InvokeModel" in s["Action"]
    )
    assert set(allow_invoke["Action"]) == {
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:CallWithBearerToken",
    }
    assert "bedrock:Converse" not in allow_invoke["Action"]


def test_allow_invoke_is_region_scoped_and_partition_aware(rendered_doc):
    """Allow-invoke statement is scoped by aws:RequestedRegion and uses ${AWS::Partition}."""
    policy = _find_policy(rendered_doc, "Engineering")
    allow_invoke = next(
        s for s in _statements(policy) if s["Effect"] == "Allow" and "bedrock:InvokeModel" in s["Action"]
    )
    cond = allow_invoke["Condition"]["StringEquals"]["aws:RequestedRegion"]
    assert cond == {"Ref": "AllowedBedrockRegions"}
    arns = _arn_strs(allow_invoke["Resource"])
    assert all(r.startswith("arn:${AWS::Partition}:bedrock:") for r in arns)
    # Engineering "anthropic.*" expands across all three shapes (3 ARNs).
    assert len(arns) == 3


def test_namespaced_put_metric_data(rendered_doc):
    """PutMetricData is granted but namespace-scoped to the project + AWS/Bedrock."""
    policy = _find_policy(rendered_doc, "Engineering")
    metric_stmt = next(
        s for s in _statements(policy) if s["Action"] == ["cloudwatch:PutMetricData"]
    )
    namespaces = metric_stmt["Condition"]["StringEquals"]["cloudwatch:namespace"]
    assert "ClaudeCode/Bedrock/Usage" in namespaces


def test_outputs_export_role_arns(rendered_doc):
    """Each persona exports {Stem}RoleArn = !GetAtt {Stem}Role.Arn with a stack-scoped name."""
    outputs = rendered_doc["Outputs"]
    assert outputs["SalesRoleArn"]["Value"] == {"Fn::GetAtt": ["SalesRole", "Arn"]}
    assert outputs["SalesRoleArn"]["Export"]["Name"] == {"Fn::Sub": "${AWS::StackName}-Sales-RoleArn"}
    assert "EngineeringRoleArn" in outputs


def test_no_bedrock_runtime_namespace_anywhere():
    """iam-actions.md: the bedrock-runtime: namespace does not exist and must never appear."""
    yaml_text = render_personas_stack([ENGINEERING, SALES], GROUPS_CLAIM, ISSUER_HOST)
    assert "bedrock-runtime:" not in yaml_text


def test_no_hardcoded_role_names():
    """cfn-naming.md: rendered roles must not pin an explicit RoleName."""
    yaml_text = render_personas_stack([ENGINEERING, SALES], GROUPS_CLAIM, ISSUER_HOST)
    doc = yaml.safe_load(yaml_text)
    for name, res in doc["Resources"].items():
        if res["Type"] == "AWS::IAM::Role":
            assert "RoleName" not in res["Properties"], f"{name} pins a RoleName"


def test_empty_allowed_models_defaults_to_anthropic():
    """Empty or ['*'] allowed_models resolves to anthropic.* (vendor-scoped, not literal *)."""
    persona = {"name": "all", "group": "all-team", "allowed_models": []}
    doc = yaml.safe_load(render_personas_stack([persona], GROUPS_CLAIM, ISSUER_HOST))
    policy = doc["Resources"]["AllPolicy"]
    allow_invoke = next(
        s for s in policy["Properties"]["PolicyDocument"]["Statement"]
        if s["Effect"] == "Allow" and "bedrock:InvokeModel" in s["Action"]
    )
    arns = _arn_strs(allow_invoke["Resource"])
    assert any("foundation-model/anthropic.*" in r for r in arns)
    assert not any(r.endswith("/*") for r in arns)  # not literal wildcard


def test_logical_id_sanitization_for_hyphenated_names():
    """Persona names with hyphens/symbols sanitize to valid alphanumeric logical ids."""
    persona = {"name": "data-science", "group": "ds-team", "allowed_models": ["anthropic.*"]}
    doc = yaml.safe_load(render_personas_stack([persona], GROUPS_CLAIM, ISSUER_HOST))
    assert "DataScienceRole" in doc["Resources"]
    assert "DataScienceRoleArn" in doc["Outputs"]


def test_empty_personas_raises():
    """An empty persona list is a caller bug and must fail loudly."""
    with pytest.raises(ValueError, match="at least one persona"):
        render_personas_stack([], GROUPS_CLAIM, ISSUER_HOST)


def test_missing_name_or_group_raises():
    """A persona without name/group cannot produce a valid role."""
    with pytest.raises(ValueError, match="name.*group"):
        render_personas_stack([{"name": "x"}], GROUPS_CLAIM, ISSUER_HOST)


def test_colliding_logical_ids_raise():
    """Distinct names that sanitize to the same logical id must be rejected, not silently merged."""
    personas = [
        {"name": "data-science", "group": "a", "allowed_models": ["anthropic.*"]},
        {"name": "data science", "group": "b", "allowed_models": ["anthropic.*"]},
    ]
    with pytest.raises(ValueError, match="collides"):
        render_personas_stack(personas, GROUPS_CLAIM, ISSUER_HOST)


# Parameters the committed example fixture was rendered with (see its header).
_EXAMPLE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "deployment"
    / "infrastructure"
    / "bedrock-personas.example.yaml"
)
_EXAMPLE_ISSUER_HOST = "auth.example.com"
_EXAMPLE_GROUPS_CLAIM = "groups"


def test_committed_example_fixture_matches_renderer():
    """The committed CI fixture must not drift from the renderer.

    ``deployment/infrastructure/bedrock-personas.example.yaml`` is a generated
    artifact (rendered from REFERENCE_PERSONAS) that CI cfn-lints as a stand-in
    for real rendered output. If the renderer changes but the fixture isn't
    regenerated, CI would lint a stale template and the drift would go unnoticed.
    This guards that: regenerate the fixture (and keep its ``# DO NOT EDIT``
    header) whenever the renderer output changes.
    """
    from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS

    committed = _EXAMPLE_FIXTURE.read_text(encoding="utf-8")
    committed_body = "\n".join(line for line in committed.splitlines() if not line.startswith("#"))
    rendered = render_personas_stack(REFERENCE_PERSONAS, _EXAMPLE_GROUPS_CLAIM, _EXAMPLE_ISSUER_HOST)

    # Compare parsed structures so comment/whitespace differences don't matter.
    assert yaml.safe_load(committed_body) == yaml.safe_load(rendered), (
        "bedrock-personas.example.yaml is out of sync with persona_template.render_personas_stack — "
        "regenerate it from REFERENCE_PERSONAS (issuer host 'auth.example.com')."
    )
