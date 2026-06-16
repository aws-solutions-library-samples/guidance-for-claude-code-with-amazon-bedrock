# ABOUTME: R-highest security regression — sales persona Deny must block ALL 3 Bedrock ARN shapes.
# ABOUTME: Guards against the customer-guide's bypassable foundation-model-only Deny (spec §7, FR-2.3).

"""Inference-profile bypass guard test.

This is the single most important security test in the persona feature. The risk
(spec §7 "R-highest", FR-2.3, decision D8): a restricted persona's Deny that only
covers ``foundation-model/*`` is silently bypassable — the same denied model can be
invoked through a **cross-region inference profile** (``us.anthropic.claude-…-sonnet``)
or an **application inference profile**. The persona renderer therefore must emit the
Deny across all three Bedrock ARN shapes:

    1. arn:<part>:bedrock:*::foundation-model/<glob>
    2. arn:<part>:bedrock:*:*:inference-profile/<glob>
    3. arn:<part>:bedrock:*:*:application-inference-profile/<glob>

The tests render the **sales** reference persona (Haiku-only; Sonnet+Opus denied) and
assert the Deny resource set covers every shape for both sonnet and opus. The final
test proves the guard has teeth: a Deny that drops any shape MUST fail the assertion.
"""

from __future__ import annotations

import yaml

from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS
from claude_code_with_bedrock.persona_template import render_personas_stack

ISSUER_HOST = "company.okta.com"
GROUPS_CLAIM = "groups"

# The three ARN-shape resource prefixes that a Deny must span.
ARN_SHAPE_PREFIXES = ("foundation-model", "inference-profile", "application-inference-profile")
DENIED_MODEL_KEYWORDS = ("sonnet", "opus")


def _sales_persona() -> dict:
    sales = next(p for p in REFERENCE_PERSONAS if p["name"] == "sales")
    # Precondition: the reference sales persona actually denies sonnet + opus.
    assert sales["denied_models"], "sales reference persona must declare denied_models"
    return sales


def _render(personas: list[dict]) -> dict:
    """Render personas and parse the YAML into a plain dict (full-form intrinsics)."""
    return yaml.safe_load(render_personas_stack(personas, GROUPS_CLAIM, ISSUER_HOST))


def _arn_strings(resource) -> list[str]:
    """Flatten a policy statement Resource into the raw ARN strings.

    The renderer emits each ARN as ``{"Fn::Sub": "arn:..."}``; Resource may be a
    single such mapping or a list of them (or a bare string for ``"*"``).
    """
    items = resource if isinstance(resource, list) else [resource]
    arns: list[str] = []
    for item in items:
        if isinstance(item, dict) and "Fn::Sub" in item:
            arns.append(item["Fn::Sub"])
        elif isinstance(item, str):
            arns.append(item)
    return arns


def _deny_statements(template: dict) -> list[dict]:
    """All Deny statements across every ManagedPolicy in the rendered template."""
    denies: list[dict] = []
    for resource in template["Resources"].values():
        if resource.get("Type") != "AWS::IAM::ManagedPolicy":
            continue
        for stmt in resource["Properties"]["PolicyDocument"]["Statement"]:
            if stmt.get("Effect") == "Deny":
                denies.append(stmt)
    return denies


def _shapes_covered_for_keyword(arns: list[str], keyword: str) -> set[str]:
    """Which ARN-shape prefixes have a Deny ARN matching the given model keyword."""
    covered: set[str] = set()
    for arn in arns:
        if keyword not in arn:
            continue
        for prefix in ARN_SHAPE_PREFIXES:
            # Match the resource segment, e.g. ":foundation-model/" — anchored by the
            # leading colon so "inference-profile" does not also match
            # "application-inference-profile".
            if f":{prefix}/" in arn:
                covered.add(prefix)
    return covered


class TestSalesDenyCoversAllArnShapes:
    def test_a_deny_statement_exists(self):
        template = _render([_sales_persona()])
        assert _deny_statements(template), "sales persona must produce at least one Deny statement"

    def test_deny_covers_all_three_shapes_for_sonnet_and_opus(self):
        """The core invariant: every denied model is denied on all 3 ARN shapes."""
        template = _render([_sales_persona()])
        # Collect every Deny ARN from the access policy (the boundary also denies,
        # but the access-policy Deny alone must be complete).
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))

        for keyword in DENIED_MODEL_KEYWORDS:
            covered = _shapes_covered_for_keyword(deny_arns, keyword)
            missing = set(ARN_SHAPE_PREFIXES) - covered
            assert not missing, (
                f"sales Deny for '{keyword}' is missing ARN shape(s) {sorted(missing)} — "
                f"this is the bypassable-policy regression (spec §7 R-highest). "
                f"Covered: {sorted(covered)}."
            )

    def test_access_policy_deny_is_self_sufficient(self):
        """The Deny in the access policy (not only the boundary) covers all shapes.

        A reviewer relying on the access policy alone must see full coverage, so we
        assert specifically against the ``DenyBedrockInvokeDeniedModels`` statement.
        """
        template = _render([_sales_persona()])
        access_denies = [
            s for s in _deny_statements(template) if s.get("Sid") == "DenyBedrockInvokeDeniedModels"
        ]
        assert access_denies, "expected a DenyBedrockInvokeDeniedModels statement in the access policy"
        arns = _arn_strings(access_denies[0]["Resource"])
        for keyword in DENIED_MODEL_KEYWORDS:
            assert _shapes_covered_for_keyword(arns, keyword) == set(ARN_SHAPE_PREFIXES)

    def test_deny_covers_global_cris_foundation_model_arn(self):
        """Global cross-Region inference path is also denied (region-less FM ARN).

        Global-CRIS models (``global.anthropic.…``) invoke against the region-less
        ARN ``arn:<part>:bedrock:::foundation-model/<id>`` with
        ``aws:RequestedRegion="unspecified"``. After the renderer gained a global FM
        *Allow* (so personas can use global models), the Deny must explicitly cover the
        same region-less shape or a denied model becomes reachable via global routing.
        """
        template = _render([_sales_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        for keyword in DENIED_MODEL_KEYWORDS:
            # A region-less FM ARN has an empty region segment: ":bedrock:::foundation-model/".
            global_fm = [a for a in deny_arns if ":bedrock:::foundation-model/" in a and keyword in a]
            assert global_fm, (
                f"sales Deny for '{keyword}' is missing the region-less global-CRIS "
                f"foundation-model ARN — global routing could bypass the restriction."
            )

    def test_global_allow_is_scoped_to_allowed_models_only(self):
        """The new global FM Allow must NOT grant denied models (haiku only for sales)."""
        template = _render([_sales_persona()])
        for resource in template["Resources"].values():
            if resource.get("Type") != "AWS::IAM::ManagedPolicy":
                continue
            for stmt in resource["Properties"]["PolicyDocument"]["Statement"]:
                if stmt.get("Effect") == "Allow" and "Global" in stmt.get("Sid", ""):
                    arns = _arn_strings(stmt["Resource"])
                    # Every global Allow ARN must be region-less FM and must NOT name a denied tier.
                    for arn in arns:
                        assert ":bedrock:::foundation-model/" in arn
                        for denied_kw in DENIED_MODEL_KEYWORDS:
                            assert denied_kw not in arn, f"global Allow leaks denied model '{denied_kw}': {arn}"

    def test_foundation_model_only_deny_would_fail_the_guard(self):
        """Meta-test: prove the guard has teeth.

        Simulate the bad (bypassable) policy — a Deny that covers only
        ``foundation-model`` — and assert the same coverage check the real test uses
        would flag it as incomplete. If this ever passes, the guard above is toothless.
        """
        bypassable_arns = [
            "arn:${AWS::Partition}:bedrock:*::foundation-model/*anthropic.*sonnet*",
            "arn:${AWS::Partition}:bedrock:*::foundation-model/*anthropic.*opus*",
        ]
        for keyword in DENIED_MODEL_KEYWORDS:
            covered = _shapes_covered_for_keyword(bypassable_arns, keyword)
            assert covered == {"foundation-model"}
            assert set(ARN_SHAPE_PREFIXES) - covered == {
                "inference-profile",
                "application-inference-profile",
            }

    def test_guard_has_teeth_against_renderer_mutation(self, monkeypatch):
        """Stronger meta-test: mutate the RENDERER to foundation-model-only and prove the
        real coverage check fails.

        ``test_foundation_model_only_deny_would_fail_the_guard`` proves the *checker* isn't
        degenerate, but it feeds hardcoded ARNs and never exercises the renderer. This test
        closes that gap: it patches the renderer's ``_ARN_SHAPES`` down to foundation-model
        only, re-renders the real sales persona, and asserts the same all-three-shapes
        assertion the production guard uses now reports the inference-profile shapes missing.
        If a regression dropped the inference-profile ARNs from the renderer, the guard above
        catches it — this proves that.
        """
        import claude_code_with_bedrock.persona_template as pt

        monkeypatch.setattr(pt, "_ARN_SHAPES", [("*", "", "foundation-model")])
        template = _render([_sales_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        for keyword in DENIED_MODEL_KEYWORDS:
            covered = _shapes_covered_for_keyword(deny_arns, keyword)
            missing = set(ARN_SHAPE_PREFIXES) - covered
            assert missing == {"inference-profile", "application-inference-profile"}, (
                "Mutating the renderer to foundation-model-only should make the guard detect "
                f"missing shapes, but it reported covered={sorted(covered)}."
            )


class TestEngineeringHasNoDeny:
    """The unrestricted persona (engineering) has no denied models -> no Deny statement."""

    def test_engineering_renders_without_deny(self):
        eng = next(p for p in REFERENCE_PERSONAS if p["name"] == "engineering")
        assert eng["denied_models"] == []
        template = _render([eng])
        assert _deny_statements(template) == []
