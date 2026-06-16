# ABOUTME: Pure renderer that turns a persona list into a CloudFormation YAML stack.
# ABOUTME: Emits one IAM role + Bedrock policy (+ permission boundary) per persona; no IO.

"""Persona CloudFormation stack renderer.

Per ``spec.md`` Decision **D1**, CloudFormation cannot iterate over an
arbitrary number of personas, so the persona stack is *rendered* in Python
from ``Profile.personas`` and then deployed through the existing
``CloudFormationManager``. This module is the heart of that approach.

``render_personas_stack`` is a pure function (no file or network IO) so it is
trivially unit-testable and safe to call from the deploy orchestration. It
emits, for each persona:

* an ``AWS::IAM::Role`` whose trust policy federates the imported OIDC
  provider and is gated on the user's ``groups`` claim
  (``ForAnyValue:StringEquals`` on ``<issuer_host>:groups``);
* an ``AWS::IAM::ManagedPolicy`` granting Bedrock invoke on the persona's
  ``allowed_models`` and **explicitly denying** ``denied_models`` across all
  three Bedrock ARN shapes — ``foundation-model/*``, ``inference-profile/*``
  and ``application-inference-profile/*`` (spec D8 / FR-2.3: a
  foundation-model-only Deny is bypassable via cross-region inference
  profiles, which is the single highest-severity risk in the design);
* for restricted personas (non-empty ``denied_models``) an additional
  ``AWS::IAM::ManagedPolicy`` used as a *permission boundary* that caps the
  role to the allowed model set, wired onto the role's ``PermissionsBoundary``;
* an ``Output`` exporting the role ARN as ``${AWS::StackName}-{Name}-RoleArn``
  so ``ccwb package`` can read it back into ``config.json``.

Design choices that matter for correctness:

* The template is built as a Python ``dict`` using **full-form** intrinsic
  functions (``{"Fn::Sub": ...}``, ``{"Fn::ImportValue": ...}``) and dumped
  with ``yaml.safe_dump``. Full-form intrinsics are valid CloudFormation and
  parse with a plain ``yaml.safe_load`` — no custom loader needed — which keeps
  both the renderer and its tests simple and robust.
* IAM actions use the ``bedrock:`` namespace only (never ``bedrock-runtime:``;
  see ``.claude/rules/iam-actions.md``).
* No hardcoded resource names; everything region/partition-aware via
  ``${AWS::Partition}`` and the ``AllowedBedrockRegions`` parameter
  (``.claude/rules/cfn-naming.md``, ``region-availability.md``).
"""

from __future__ import annotations

import re

import yaml

# Bedrock invoke actions granted to a persona for its allowed models. Kept in
# the bedrock: namespace (iam-actions.md) and aligned EXACTLY with the shared
# BedrockAccessPolicy in the existing auth templates (bedrock-auth-*.yaml).
#
# Note on the Converse API: Bedrock authorizes Converse / ConverseStream under
# the bedrock:InvokeModel / bedrock:InvokeModelWithResponseStream permissions
# (there is no separate IAM action enforced for them at runtime), which is why
# the shipped auth policies grant only these. Listing bedrock:Converse here adds
# no functional access and trips a cfn-lint W3037 against cfn-lint's (stale) IAM
# action database, so we intentionally match the auth-template action set.
_INVOKE_ACTIONS: list[str] = [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:CallWithBearerToken",
]

# Read-only discovery actions every persona needs so the client can enumerate
# models/profiles. Scoped to "*" (these are List/Get, not invoke).
_LIST_ACTIONS: list[str] = [
    "bedrock:ListFoundationModels",
    "bedrock:GetFoundationModel",
    "bedrock:ListInferenceProfiles",
    "bedrock:GetInferenceProfile",
]

# The three Bedrock ARN *shapes* a model can be invoked through. Allow and Deny
# must both span all three (spec D8): a Deny that only covers foundation-model
# is bypassable by invoking the same model via a cross-region inference profile.
# Each entry is a (region_segment, account_segment, resource_prefix) tuple used
# to build "arn:${AWS::Partition}:bedrock:<region>:<account>:<prefix>/<glob>".
_ARN_SHAPES: list[tuple[str, str, str]] = [
    ("*", "", "foundation-model"),  # foundation models are account-less
    ("*", "*", "inference-profile"),
    ("*", "*", "application-inference-profile"),
]


def _logical_id(name: str) -> str:
    """Sanitize a persona name into an alphanumeric CloudFormation logical-id stem.

    CloudFormation logical IDs must be ``[A-Za-z0-9]+`` and unique within the
    template. We strip every other character and upper-case the first letter so
    ``eng-team`` -> ``EngTeam``. Resulting stems are combined with a fixed
    suffix (``Role``, ``Policy``, ``Boundary``) by the caller.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", " ", name)
    parts = [p for p in cleaned.split(" ") if p]
    if not parts:
        # Degenerate names (all-symbol) still need a stable, valid id.
        return "Persona"
    stem = "".join(p[:1].upper() + p[1:] for p in parts)
    # Logical id must start with a letter.
    if not stem[0].isalpha():
        stem = "P" + stem
    return stem


def _model_resource_arns(globs: list[str], prefix: str, account_segment: str) -> list[dict]:
    """Build partition-aware Bedrock ARNs for a list of model-id globs and one ARN shape.

    A model-id glob such as ``anthropic.*haiku*`` is placed directly into the
    resource suffix (IAM resource wildcards use the same ``*`` syntax). For the
    inference-profile shapes a leading ``*`` is prepended because those ARNs
    carry a region/system prefix (e.g. ``us.anthropic.…``) ahead of the model
    id, so ``anthropic.*sonnet*`` must match ``…/us.anthropic.claude-…-sonnet``.

    Each ARN is returned as an ``{"Fn::Sub": "..."}`` mapping because the ARN
    embeds the ``${AWS::Partition}`` pseudo-parameter, which CloudFormation only
    resolves inside ``Fn::Sub`` (a bare ``${AWS::Partition}`` in a string is a
    cfn-lint E1029 error and never substitutes at deploy time).
    """
    region = "*"
    arns: list[dict] = []
    for glob in globs:
        suffix = glob
        if prefix in ("inference-profile", "application-inference-profile") and not glob.startswith("*"):
            suffix = "*" + glob
        if account_segment:
            arn = f"arn:${{AWS::Partition}}:bedrock:{region}:{account_segment}:{prefix}/{suffix}"
        else:
            arn = f"arn:${{AWS::Partition}}:bedrock:{region}::{prefix}/{suffix}"
        arns.append({"Fn::Sub": arn})
    return arns


def _all_shape_arns(globs: list[str]) -> list[dict]:
    """All ARNs for the given globs across every Bedrock ARN shape (Allow/Deny use this)."""
    out: list[dict] = []
    for _region, account_segment, prefix in _ARN_SHAPES:
        out.extend(_model_resource_arns(globs, prefix, account_segment))
    return out


def _normalize_allowed(allowed: list[str] | None) -> list[str]:
    """Resolve the allowed-models list to concrete globs.

    Empty or ``["*"]`` means "all Anthropic models" (the project only ships
    Anthropic access), expressed as ``anthropic.*`` so the Allow stays scoped
    to the vendor rather than literally ``*``.
    """
    if not allowed or allowed == ["*"]:
        return ["anthropic.*"]
    return list(allowed)


def _persona_resources(persona: dict, groups_claim_name: str, issuer_host: str) -> dict:
    """Build the {logical_id: resource} fragment for a single persona."""
    name = persona["name"]
    group = persona["group"]
    allowed = _normalize_allowed(persona.get("allowed_models"))
    denied = list(persona.get("denied_models") or [])
    restricted = bool(denied)

    stem = _logical_id(name)
    role_id = f"{stem}Role"
    policy_id = f"{stem}Policy"
    boundary_id = f"{stem}Boundary"

    # Trust condition key is the issuer host without scheme, suffixed ":groups"
    # (issuer-url-format.md). ForAnyValue:StringEquals matches array claims.
    groups_condition_key = f"{issuer_host}:{groups_claim_name}"

    # --- Bedrock access policy (Allow + Deny across all 3 ARN shapes) ---
    statements: list[dict] = [
        {
            "Sid": "AllowBedrockInvokeAllowedModels",
            "Effect": "Allow",
            "Action": list(_INVOKE_ACTIONS),
            "Resource": _all_shape_arns(allowed),
            "Condition": {"StringEquals": {"aws:RequestedRegion": {"Ref": "AllowedBedrockRegions"}}},
        }
    ]
    if restricted:
        # Explicit Deny wins over any Allow and must cover every ARN shape so a
        # cross-region inference profile cannot be used to reach a denied model.
        statements.append(
            {
                "Sid": "DenyBedrockInvokeDeniedModels",
                "Effect": "Deny",
                "Action": list(_INVOKE_ACTIONS),
                "Resource": _all_shape_arns(denied),
            }
        )
    statements.append(
        {
            "Sid": "AllowBedrockListAndGet",
            "Effect": "Allow",
            "Action": list(_LIST_ACTIONS),
            "Resource": "*",
        }
    )
    # Namespaced metric publication for usage telemetry. Scoped by namespace via
    # a condition so the persona role can only write the project's metrics.
    statements.append(
        {
            "Sid": "AllowNamespacedPutMetricData",
            "Effect": "Allow",
            "Action": ["cloudwatch:PutMetricData"],
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "cloudwatch:namespace": ["ClaudeCode/Bedrock/Usage", "AWS/Bedrock"]
                }
            },
        }
    )

    access_policy = {
        "Type": "AWS::IAM::ManagedPolicy",
        "Properties": {
            # Plain string: the persona name is interpolated in Python, so there
            # is no CloudFormation variable here (Fn::Sub would be a W1020 warning).
            "Description": f"Bedrock access policy for persona {name}",
            "PolicyDocument": {"Version": "2012-10-17", "Statement": statements},
        },
    }

    # --- IAM role with OIDC group-gated trust ---
    role_properties: dict = {
        "Description": f"Persona role for {name} (group {group})",
        "MaxSessionDuration": 43200,
        "AssumeRolePolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Federated": {
                            "Fn::ImportValue": {"Fn::Sub": "${AuthStackName}-OIDCProviderArn"}
                        }
                    },
                    "Action": ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
                    "Condition": {
                        "ForAnyValue:StringEquals": {groups_condition_key: [group]}
                    },
                }
            ],
        },
        "ManagedPolicyArns": [{"Ref": policy_id}],
        "Tags": [
            {"Key": "Purpose", "Value": "Claude Code Persona Access"},
            {"Key": "Persona", "Value": name},
            {"Key": "PersonaGroup", "Value": group},
        ],
    }

    resources: dict = {policy_id: access_policy}

    if restricted:
        # Permission boundary caps the role's effective permissions to the
        # allowed model set even if the access policy is later widened. It mirrors
        # the Allow (so the role keeps working) but, being a boundary, the role
        # can never exceed it.
        boundary_statements = [
            {
                "Sid": "BoundaryAllowBedrockInvoke",
                "Effect": "Allow",
                "Action": list(_INVOKE_ACTIONS),
                "Resource": _all_shape_arns(allowed),
                "Condition": {"StringEquals": {"aws:RequestedRegion": {"Ref": "AllowedBedrockRegions"}}},
            },
            {
                "Sid": "BoundaryDenyDeniedModels",
                "Effect": "Deny",
                "Action": list(_INVOKE_ACTIONS),
                "Resource": _all_shape_arns(denied),
            },
            {
                "Sid": "BoundaryAllowListAndMetrics",
                "Effect": "Allow",
                "Action": list(_LIST_ACTIONS) + ["cloudwatch:PutMetricData"],
                "Resource": "*",
            },
        ]
        resources[boundary_id] = {
            "Type": "AWS::IAM::ManagedPolicy",
            "Properties": {
                "Description": f"Permission boundary for restricted persona {name}",
                "PolicyDocument": {"Version": "2012-10-17", "Statement": boundary_statements},
            },
        }
        role_properties["PermissionsBoundary"] = {"Ref": boundary_id}

    resources[role_id] = {"Type": "AWS::IAM::Role", "Properties": role_properties}
    return resources


def render_personas_stack(
    personas: list[dict],
    groups_claim_name: str,
    issuer_host: str,
) -> str:
    """Render the persona CloudFormation stack as YAML.

    Args:
        personas: ordered list of persona dicts (canonical shape from spec
            §4.1). Each must carry ``name`` and ``group``; ``allowed_models``,
            ``denied_models`` are optional.
        groups_claim_name: the OIDC claim that carries group membership
            (``groups``, ``cognito:groups``, ``roles``, …). Becomes part of the
            trust-condition key.
        issuer_host: the OIDC issuer host *without* scheme (e.g.
            ``company.okta.com`` or ``login.microsoftonline.com/<tenant>/v2.0``);
            the trust condition key is ``<issuer_host>:<groups_claim_name>``.

    Returns:
        A CloudFormation template document as a YAML string. Parses with a plain
        ``yaml.safe_load`` (full-form intrinsics, no custom tags).

    Raises:
        ValueError: if ``personas`` is empty (an empty persona stack is
            meaningless and almost certainly a caller bug) or a persona is
            missing ``name``/``group``.
    """
    if not personas:
        raise ValueError("render_personas_stack requires at least one persona")

    resources: dict = {}
    outputs: dict = {}
    seen_ids: set[str] = set()

    for persona in personas:
        name = persona.get("name")
        group = persona.get("group")
        if not name or not group:
            raise ValueError(f"persona missing required 'name'/'group': {persona!r}")

        stem = _logical_id(name)
        if stem in seen_ids:
            # Distinct persona names that sanitize to the same logical id would
            # silently collide and overwrite resources — fail loudly instead.
            raise ValueError(
                f"persona name {name!r} collides with another persona's logical id {stem!r}"
            )
        seen_ids.add(stem)

        resources.update(_persona_resources(persona, groups_claim_name, issuer_host))

        role_id = f"{stem}Role"
        outputs[f"{stem}RoleArn"] = {
            "Description": f"Role ARN for persona {name}",
            "Value": {"Fn::GetAtt": [role_id, "Arn"]},
            "Export": {"Name": {"Fn::Sub": f"${{AWS::StackName}}-{stem}-RoleArn"}},
        }

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Claude Code with Bedrock - Persona-Based Access Control Stack",
        "Parameters": {
            "AuthStackName": {
                "Type": "String",
                "Description": (
                    "Name of the authentication stack that exports "
                    "<AuthStackName>-OIDCProviderArn (imported for the trust policy)."
                ),
            },
            "AllowedBedrockRegions": {
                "Type": "CommaDelimitedList",
                "Description": "AWS regions in which persona roles may invoke Bedrock.",
            },
        },
        "Resources": resources,
        "Outputs": outputs,
    }

    # sort_keys=False preserves our logical ordering; default_flow_style=False
    # gives block style. allow_unicode keeps any non-ASCII display names intact.
    return yaml.safe_dump(template, sort_keys=False, default_flow_style=False, allow_unicode=True)
