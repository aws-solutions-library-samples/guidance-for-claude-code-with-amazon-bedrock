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


def _iam_glob_match(runtime_arn: str, policy_arns: list[str]) -> bool:
    """True if any policy ARN glob MATCHES the concrete runtime ARN (IAM semantics).

    The single matching engine for this suite. A policy ARN is a glob (``*`` = any run)
    with ``${AWS::Partition}`` standing in for the partition; we substitute it and use
    ``fnmatch`` (case-insensitive, anchored) — exactly how the live IAM Deny/Allow
    evaluates a resource. ``.`` is a literal in ``fnmatch`` (only ``*``/``?``/``[]`` are
    special), matching IAM's treatment of model-id dots.

    Fidelity caveat: this is a faithful model of IAM resource matching ONLY while ARNs
    and globs stay free of ``[``/``]`` (fnmatch treats those as a character class; IAM
    treats them as literals) and case-insensitivity is acceptable (IAM resource matching
    is case-sensitive, but every shipped Anthropic id/glob is already lowercase). Both
    hold for the current model catalog; a future bracketed or mixed-case id would need a
    real glob-to-regex translation here.
    """
    import fnmatch

    runtime_l = runtime_arn.lower()
    for pattern in policy_arns:
        pat = pattern.replace("${AWS::Partition}", "aws").lower()
        if fnmatch.fnmatch(runtime_l, pat):
            return True
    return False


def _real_model_id(keyword: str, *, prefixed: bool) -> str:
    """A real denied/allowed model id for *keyword*, in the form a shape carries.

    ``prefixed=False`` (foundation-model shape) → the BARE id
    (``anthropic.claude-opus-4-8``); ``prefixed=True`` (inference-profile shapes) → the
    region/CRIS-prefixed id (``us.anthropic.claude-opus-4-8``). Resolved from the same
    catalog deploy uses, so the test tracks the real model ids rather than a synthetic
    stand-in.
    """
    from claude_code_with_bedrock.models import resolve_model_for_tier

    mid = resolve_model_for_tier(keyword, "us") or f"anthropic.claude-{keyword}-x"
    if not prefixed and mid.split(".", 1)[0] in ("us", "eu", "apac", "global"):
        mid = mid.split(".", 1)[1]  # strip region prefix → bare FM id
    return mid


def _shape_runtime_arn(prefix: str, model_id: str) -> str:
    """A concrete runtime ARN for *model_id* on the given ARN *shape*."""
    part, region, acct = "aws", "us-east-1", "111122223333"
    if prefix == "foundation-model":
        return f"arn:{part}:bedrock:{region}::foundation-model/{model_id}"
    return f"arn:{part}:bedrock:{region}:{acct}:{prefix}/{model_id}"


def _shapes_covered_for_keyword(arns: list[str], keyword: str) -> set[str]:
    """ARN-shape prefixes whose Deny glob MATCHES a real denied-model id for *keyword*.

    Strengthened from substring-presence to glob-MATCH (the audit fix): for each shape
    we build a representative real model-id ARN — BARE id for ``foundation-model``,
    region-prefixed id for the inference-profile shapes (the forms Bedrock actually
    authorizes) — and report the shape covered only if a Deny resource of that shape
    *matches* it under IAM anchored-wildcard semantics. A present-but-inert glob (the
    original global-CRIS bug class) therefore no longer counts as covered. The shape
    segment is matched with a leading colon (``:foundation-model/``) so
    ``inference-profile`` does not also match ``application-inference-profile``.
    """
    covered: set[str] = set()
    for prefix in ARN_SHAPE_PREFIXES:
        model_id = _real_model_id(keyword, prefixed=(prefix != "foundation-model"))
        runtime = _shape_runtime_arn(prefix, model_id)
        shape_denies = [a for a in arns if f":{prefix}/" in a]
        if shape_denies and _iam_glob_match(runtime, shape_denies):
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
        from claude_code_with_bedrock.models import resolve_model_for_tier

        template = _render([_sales_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        # Match-based (not substring-present): the region-less global FM Deny glob must
        # actually MATCH the real global-CRIS denied id. A present-but-anchored glob
        # (the bug we fixed) is present yet non-matching, so this fails on it.
        region_less_denies = [a for a in deny_arns if ":bedrock:::foundation-model/" in a]
        for keyword in DENIED_MODEL_KEYWORDS:
            global_id = resolve_model_for_tier(keyword, "global")
            assert global_id and global_id.startswith("global."), (
                f"expected a real global {keyword} id, got {global_id!r}"
            )
            runtime = f"arn:aws:bedrock:::foundation-model/{global_id}"
            assert _iam_glob_match(runtime, region_less_denies), (
                f"sales Deny does not MATCH the real global-CRIS {keyword} id {global_id!r} on the "
                f"region-less FM ARN — global routing could bypass the restriction. "
                f"region-less Deny globs={region_less_denies}"
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

    def test_global_allow_actually_matches_the_allowed_global_model_id(self):
        """Positive companion to the scoping test: the global Allow must MATCH the real
        allowed (haiku) global model id — not merely be present and free of denied tiers.

        Without this, an inert global Allow glob (the bug we just fixed) would still pass
        the negative scoping check above (no ``opus``/``sonnet`` substring) while granting
        nothing. This asserts sales' global FM Allow matches the real
        ``global.anthropic.…-haiku-…`` id on the region-less FM ARN.
        """
        from claude_code_with_bedrock.models import resolve_model_for_tier

        template = _render([_sales_persona()])
        global_allow_arns: list[str] = []
        for resource in template["Resources"].values():
            if resource.get("Type") != "AWS::IAM::ManagedPolicy":
                continue
            for stmt in resource["Properties"]["PolicyDocument"]["Statement"]:
                if stmt.get("Effect") == "Allow" and "Global" in stmt.get("Sid", ""):
                    global_allow_arns.extend(_arn_strings(stmt["Resource"]))
        assert global_allow_arns, "sales must render a region-less global FM Allow for haiku"

        allowed_global_haiku = resolve_model_for_tier("haiku", "global")
        assert allowed_global_haiku and allowed_global_haiku.startswith("global."), (
            f"expected a real global haiku id, got {allowed_global_haiku!r}"
        )
        runtime = f"arn:aws:bedrock:::foundation-model/{allowed_global_haiku}"
        assert _iam_glob_match(runtime, global_allow_arns), (
            f"the global FM Allow does not MATCH the allowed global haiku id "
            f"{allowed_global_haiku!r} — the Allow is inert (anchored-glob bug); "
            f"globs={global_allow_arns}"
        )

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


class TestSalesDenyMatchesRealModelIds:
    """Semantic bypass guard: the rendered Deny must *match* the real denied model
    ids an attacker could submit — not merely *contain* an ARN string.

    The other tests in this file are **presence/substring** checks (`:foundation-model/`
    segment exists, keyword is a substring of some ARN). That is the exact weakness that
    let the inert global-CRIS glob (`anthropic.*opus*` vs `global.anthropic.…opus`) pass
    three review passes: a Deny ARN was *present* but its glob did not *match* the real
    id. This class closes that gap by reconstructing the runtime ARN for each real denied
    model id (across every prefix shape Claude Code invokes through) and asserting the
    rendered Deny glob actually matches it under IAM's anchored-wildcard semantics —
    i.e. the model genuinely cannot be invoked, on any shape.
    """

    @staticmethod
    def _runtime_arns() -> list[str]:
        """Every realistic **model-id-bearing** ARN Bedrock authorizes a denied
        (sonnet/opus) invocation against — pairing each ARN *shape* with the model-id
        *form* that shape actually carries. Getting the pairing right is the point: a
        region prefix (``us.``, ``global.``) appears on the **inference-profile** shapes,
        while the **foundation-model** shape carries the **bare** id. Each entry is a
        concrete ARN the rendered Deny glob must match.

        Note: an AWS-created *application*-inference-profile gets an OPAQUE id (no
        ``anthropic.`` token), so it is intentionally NOT enumerated here — the persona's
        Allow (``*anthropic.*haiku*``) also can't match an opaque id, so such a call fails
        closed by implicit-deny, and the persona has no ``CreateInferenceProfile`` anyway.
        This set therefore covers the model-id-bearing forms, not literally every ARN.
        """
        from claude_code_with_bedrock.models import resolve_model_for_tier

        part, region, acct = "aws", "us-east-1", "111122223333"
        arns: list[str] = []
        for tier in ("sonnet", "opus"):  # sales denies both
            # Foundation-model shape → BARE id (no region prefix), account-less.
            bare = resolve_model_for_tier(tier, "us")
            if bare:
                bare = bare.split(".", 1)[1] if bare.split(".", 1)[0] in ("us", "eu", "apac", "global") else bare
                arns.append(f"arn:{part}:bedrock:{region}::foundation-model/{bare}")
            # Inference-profile + application-inference-profile shapes → region/global-PREFIXED id.
            for prefix in ("us", "eu", "apac", "global"):
                mid = resolve_model_for_tier(tier, prefix)
                if not mid:
                    continue
                arns.append(f"arn:{part}:bedrock:{region}:{acct}:inference-profile/{mid}")
                arns.append(f"arn:{part}:bedrock:{region}:{acct}:application-inference-profile/{mid}")
                # global-CRIS also invokes the region-less FM ARN (RequestedRegion=unspecified).
                if mid.startswith("global."):
                    arns.append(f"arn:{part}:bedrock:::foundation-model/{mid}")
        return sorted(set(arns))

    @staticmethod
    def _deny_matches(runtime_arn: str, deny_arns: list[str]) -> bool:
        """True if any Deny resource glob matches the concrete runtime ARN.

        Delegates to the module-level ``_iam_glob_match`` so this suite has a single
        IAM-matching engine (the same one the strengthened ``_shapes_covered_for_keyword``
        uses).
        """
        return _iam_glob_match(runtime_arn, deny_arns)

    def test_every_real_denied_model_is_matched_on_every_shape(self):
        template = _render([_sales_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        assert deny_arns, "sales persona must render Deny resources"

        runtime_arns = self._runtime_arns()
        assert runtime_arns, "expected at least one realistic denied-model ARN to test"
        unmatched = [a for a in runtime_arns if not self._deny_matches(a, deny_arns)]

        assert not unmatched, (
            "the sales Deny does not MATCH these real denied-model invocation ARNs "
            "(present-but-non-matching globs are the inert-policy bypass class):\n  "
            + "\n  ".join(unmatched)
        )

    def test_guard_catches_a_prefix_anchored_glob_that_misses_global(self):
        """Meta: a Deny built without the leading-`*` (anchored at `anthropic.`) must be
        caught as NOT matching a `global.anthropic.…` id — proving this guard would have
        flagged the original inert global-CRIS glob."""
        anchored_deny = [
            "arn:${AWS::Partition}:bedrock:::foundation-model/anthropic.*opus*",  # no leading *
        ]
        global_opus = "arn:aws:bedrock:::foundation-model/global.anthropic.claude-opus-4-7"
        assert not self._deny_matches(global_opus, anchored_deny), (
            "an anchored anthropic.* glob must NOT match a global.anthropic id — if this "
            "passes, the match-based guard is toothless"
        )
        # And the real renderer's Deny DOES match it (regression for the global-CRIS fix).
        template = _render([_sales_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        assert self._deny_matches(global_opus, deny_arns)


class TestCustomPersonaDenyMatchesRealModelIds:
    """Match-based bypass guard for a NON-reference, version-pinned custom persona.

    The rest of this suite renders only the reference ``sales`` persona (tier-family
    globs ``anthropic.*opus*``). A renderer regression that broke only *version-pinned*
    custom denies (a different glob shape an operator may hand-author) would not be
    caught here and would fall back to the older presence-based
    ``test_version_pinned_deny_glob_gets_trailing_wildcard`` in ``test_persona_template``.
    This closes that asymmetry: render a custom persona that denies opus *by version*
    (the bare latest opus id, no trailing ``*`` — the footgun shape) and assert the
    rendered Deny actually MATCHES every real opus invocation ARN under IAM semantics.

    The pinned version is derived from the model catalog (the bare latest us-opus id)
    rather than hardcoded, so a model bump (e.g. opus 4-7 → 4-8) doesn't strand the test.
    """

    @staticmethod
    def _bare_latest_opus() -> str:
        """The version-pinned deny target: the bare latest opus id (no region prefix).

        e.g. ``anthropic.claude-opus-4-8``. Resolved from the catalog so the test pins
        whatever the current latest opus is.
        """
        from claude_code_with_bedrock.models import resolve_model_for_tier

        latest = resolve_model_for_tier("opus", "us")  # e.g. us.anthropic.claude-opus-4-8
        return latest.split(".", 1)[1] if latest.split(".", 1)[0] in ("us", "eu", "apac", "global") else latest

    def _custom_persona(self) -> dict:
        return {
            "name": "research",
            "display_name": "Research",
            "group": "research-team",
            "allowed_models": ["anthropic.*"],
            # Version-pinned, no trailing wildcard — relies on _normalize_denied + the
            # inference-profile leading-* to still match the versioned/prefixed invoked id.
            "denied_models": [self._bare_latest_opus()],
            "enforcement_mode": "block",
            "cost_tags": {"Team": "Research"},
        }

    def _real_opus_arns(self) -> list[str]:
        """Realistic invocation ARNs for the pinned opus version, per shape — including a
        VERSION-SUFFIXED runtime form.

        Bedrock invokes a model by its full versioned id (``…-v1:0``) even when the
        catalog's resolved id is unsuffixed. The operator pinned the deny WITHOUT a
        trailing ``*``; only ``_normalize_denied``'s trailing-``*`` lets that glob still
        match the suffixed runtime id on the inference-profile shapes. We include both the
        catalog id and an explicit ``-v1:0`` form so the test exercises (and has teeth
        against) the normalization, not just the unsuffixed match.
        """
        from claude_code_with_bedrock.models import resolve_model_for_tier

        part, region, acct = "aws", "us-east-1", "111122223333"
        arns: list[str] = []
        bare = resolve_model_for_tier("opus", "us")
        if bare:
            bare = bare.split(".", 1)[1] if bare.split(".", 1)[0] in ("us", "eu", "apac", "global") else bare
            arns.append(f"arn:{part}:bedrock:{region}::foundation-model/{bare}")
        for prefix in ("us", "eu", "apac", "global"):
            mid = resolve_model_for_tier("opus", prefix)
            if not mid:
                continue
            for runtime_id in (mid, f"{mid}-v1:0"):  # catalog id + the versioned runtime form
                arns.append(f"arn:{part}:bedrock:{region}:{acct}:inference-profile/{runtime_id}")
                arns.append(f"arn:{part}:bedrock:{region}:{acct}:application-inference-profile/{runtime_id}")
                if mid.startswith("global."):
                    arns.append(f"arn:{part}:bedrock:::foundation-model/{runtime_id}")
        return sorted(set(arns))

    def test_version_pinned_custom_deny_matches_every_real_opus_arn(self):
        template = _render([self._custom_persona()])
        deny_arns: list[str] = []
        for stmt in _deny_statements(template):
            deny_arns.extend(_arn_strings(stmt["Resource"]))
        assert deny_arns, "custom persona with a denied model must render Deny resources"

        # Only assert against opus ids the pinned glob actually targets (the latest-version
        # family). A data-residency prefix that resolves to a DIFFERENT opus version the
        # persona did NOT pin is correctly NOT denied, so filter to the pinned family.
        # _bare_latest_opus() is e.g. "anthropic.claude-opus-4-8" → family token "opus-4-8".
        family = self._bare_latest_opus().split("claude-", 1)[-1]
        targeted = [a for a in self._real_opus_arns() if family in a]
        assert targeted, f"expected at least one real {family} invocation ARN"
        # Sanity: the suffixed runtime form must be present so the trailing-* normalization
        # is genuinely exercised (this is what gives the test teeth vs _normalize_denied).
        assert any(a.endswith("-v1:0") for a in targeted), "expected a versioned runtime ARN in the set"
        unmatched = [a for a in targeted if not _iam_glob_match(a, deny_arns)]
        assert not unmatched, (
            f"the version-pinned custom Deny does not MATCH these real {family} ARNs "
            "(version-pinned custom-persona bypass class):\n  " + "\n  ".join(unmatched)
        )


class TestEngineeringHasNoDeny:
    """The unrestricted persona (engineering) has no denied models -> no Deny statement."""

    def test_engineering_renders_without_deny(self):
        eng = next(p for p in REFERENCE_PERSONAS if p["name"] == "engineering")
        assert eng["denied_models"] == []
        template = _render([eng])
        assert _deny_statements(template) == []
