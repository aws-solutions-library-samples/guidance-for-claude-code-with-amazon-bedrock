# ABOUTME: Per-persona model-tier entitlement + Application Inference Profile naming/source (FR-5.1).
# ABOUTME: Pure helpers shared by deploy (create AIPs) and destroy (delete them) so names never drift.

"""Per-persona model routing helpers (FR-5.1).

A persona's ``allowed_models`` / ``denied_models`` globs decide which Claude
*tiers* (haiku / sonnet / opus) it may invoke. For cost attribution we create one
tagged **Application Inference Profile** (AIP) per entitled tier, each wrapping the
tier's **cross-Region (system-defined) inference profile** so routing stays
CRIS-aware (AWS requires a CRIS modelSource for a multi-Region AIP — a bare
foundation-model source would pin the AIP to a single Region and break Claude
Code's cross-Region routing).

These helpers are pure (no boto3 / no IO) so they're unit-testable and usable by
both the deploy path (create + read-back ARNs) and the destroy path (delete by
the same names). Keeping the naming here is the single source of truth — the same
lesson as the persona logical-id sanitizer.
"""

from __future__ import annotations

import fnmatch

# The Claude tiers a persona can be entitled to, in ascending capability order.
# Order matters: the "primary" tier (used for bare ANTHROPIC_MODEL) is the
# highest-capability tier the persona is entitled to.
TIERS: tuple[str, ...] = ("haiku", "sonnet", "opus")

# Substring that identifies each tier inside an Anthropic model id / glob, used to
# decide entitlement against the persona's allow/deny globs (which look like
# "anthropic.*haiku*"). Bedrock model ids embed the tier name, e.g.
# "anthropic.claude-3-5-haiku-20241022-v1:0".
_TIER_TOKEN: dict[str, str] = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}


def _matches_any(globs: list[str], probe: str, *, infer_profile_shape: bool = False) -> bool:
    """True if *probe* matches any glob in *globs* (case-insensitive fnmatch).

    When ``infer_profile_shape`` is set, each glob is matched the SAME way the IAM
    policy matches it on the inference-profile ARN shape: a leading ``*`` is
    prepended (the CRIS id carries a region/``global.`` prefix ahead of the
    ``anthropic.`` token) so a probe like ``us.anthropic.claude-opus-4-7-v1:0``
    matches a glob like ``anthropic.*opus*``. This keeps entitlement resolution in
    lockstep with the rendered Deny when probing with a concrete resolved model id.
    """
    probe_l = probe.lower()
    for g in globs:
        if not isinstance(g, str):
            continue
        pattern = g.lower()
        if infer_profile_shape and not pattern.startswith("*"):
            pattern = "*" + pattern
        if fnmatch.fnmatch(probe_l, pattern):
            return True
    return False


def entitled_tiers(persona: dict, cris_prefix: str | None = None) -> list[str]:
    """Return the tiers a persona may invoke, in ascending capability order.

    A tier is entitled when a representative model id for that tier is matched by
    ``allowed_models`` (empty / ``["*"]`` => all tiers) and NOT matched by
    ``denied_models``. The deny check mirrors the IAM policy's explicit Deny so
    the AIP set a persona gets lines up with what its role can actually invoke.

    Example: sales (allowed ``anthropic.*haiku*``, denied
    ``anthropic.*sonnet*``/``anthropic.*opus*``) => ``["haiku"]``.

    ``cris_prefix`` (e.g. ``"us"``, ``"eu"``) makes the probe **version-exact**: the
    tier is probed with the *resolved* CRIS model id that its AIP would actually
    ``copyFrom`` (e.g. ``us.anthropic.claude-opus-4-7-v1:0``), matched with the
    inference-profile ARN shape. This closes a footgun: a *version-pinned* deny like
    ``anthropic.claude-opus-4-7`` does NOT match the version-less probe
    ``anthropic.claude-opus``, so without ``cris_prefix`` the tier would be reported
    entitled and deploy would create an opus AIP whose source is the very model the
    IAM Deny blocks — yielding a runtime ``AccessDenied`` for that tier. Probing the
    concrete resolved id keeps the AIP set the deploy creates aligned with what the
    role can invoke. When ``cris_prefix`` is omitted (callers that only need "is any
    tier entitled", e.g. budgets), the conservative version-less probe is used.
    """
    allowed = persona.get("allowed_models") or []
    denied = persona.get("denied_models") or []
    allow_all = not allowed or allowed == ["*"]

    result: list[str] = []
    for tier in TIERS:
        probe = _tier_probe(tier, cris_prefix)
        # When probing a concrete resolved id (cris_prefix set), match denied/allowed
        # globs the same way the IAM inference-profile shape does (leading-* prepend),
        # so entitlement stays in lockstep with the rendered Deny.
        shaped = cris_prefix is not None
        if denied and _matches_any(denied, probe, infer_profile_shape=shaped):
            continue
        if allow_all or _matches_any(allowed, probe, infer_profile_shape=shaped):
            result.append(tier)
    return result


def _tier_probe(tier: str, cris_prefix: str | None) -> str:
    """The model-id probe used to test a tier's allow/deny entitlement.

    Without ``cris_prefix``: a version-less representative id (``anthropic.claude-opus``)
    — the historical, conservative behavior. With ``cris_prefix``: the resolved CRIS
    model id the tier's AIP would ``copyFrom`` (carries the real version + region
    prefix), so version-pinned deny globs are honored.

    The resolved id is used as the probe **only when it actually belongs to the tier**
    (its id contains the tier token). For a data-residency prefix where a tier has no
    model, ``resolve_model_for_tier`` falls back across tiers (e.g. ``opus``/``jp`` →
    ``jp.anthropic.claude-sonnet-…``); probing the opus tier with a *sonnet* id would
    muddy entitlement, so we keep the version-less opus probe in that case. This scopes
    the version-exact behavior precisely to "a version-pinned deny on the tier's own
    model" — the real footgun — without entangling it with cross-tier fallback."""
    version_less = f"anthropic.claude-{_TIER_TOKEN[tier]}"
    if cris_prefix is None:
        return version_less
    from claude_code_with_bedrock.models import resolve_model_for_tier

    resolved = resolve_model_for_tier(tier, cris_prefix)
    if resolved and _TIER_TOKEN[tier] in resolved.lower():
        return resolved
    return version_less


def primary_tier(persona: dict) -> str | None:
    """The persona's default tier for bare ANTHROPIC_MODEL (highest entitled).

    Returns None when the persona is entitled to no tier (degenerate config —
    e.g. everything denied), in which case no model override is emitted.
    """
    tiers = entitled_tiers(persona)
    if not tiers:
        return None
    # TIERS is ascending capability; the last entitled is the most capable.
    return tiers[-1]


def aip_name(pool_name: str, persona_name: str, tier: str) -> str:
    """Deterministic AIP name for a persona tier: ``{pool}-{persona}-{tier}``.

    Used by deploy (create), the ARN read-back, and destroy (delete) so all three
    derive the identical name. Kept simple/ASCII; persona names are validated
    DNS/IAM-safe upstream (persona_validation.VALID_NAME_RE).
    """
    return f"{pool_name}-{persona_name}-{tier}"


def cris_source_arn(tier: str, cris_prefix: str, region: str, partition: str) -> str | None:
    """Build the cross-Region inference-profile ARN to ``copyFrom`` for a tier.

    A multi-Region AIP must be created from a CRIS (system-defined) inference
    profile, whose id is the CRIS-prefixed model id (e.g.
    ``us.anthropic.claude-haiku-…``). Returns None when no model resolves for the
    tier+prefix (e.g. a data-residency prefix without that tier), so the caller
    skips that tier rather than building a bogus ARN.

    The ARN is partition-aware (``aws`` / ``aws-us-gov``) — fixes the prior
    hardcoded ``arn:aws:`` source (region-availability.md / NFR-8 GovCloud).
    """
    from claude_code_with_bedrock.models import resolve_model_for_tier

    cris_model_id = resolve_model_for_tier(tier, cris_prefix)
    if not cris_model_id:
        return None
    # System-defined (CRIS) inference profiles are account-less, like
    # foundation models: arn:<partition>:bedrock:<region>::inference-profile/<id>
    return f"arn:{partition}:bedrock:{region}::inference-profile/{cris_model_id}"


def partition_for_region(region: str) -> str:
    """Resolve the ARN partition for an AWS region (commercial vs GovCloud)."""
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    return "aws"
