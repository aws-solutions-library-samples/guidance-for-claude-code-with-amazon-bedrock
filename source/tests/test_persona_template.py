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
