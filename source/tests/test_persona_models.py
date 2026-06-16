# ABOUTME: Tests for persona_models — tier entitlement + AIP naming/source (FR-5.1).
# ABOUTME: Pure helpers; asserts entitlement against allow/deny globs and partition-aware CRIS source ARNs.

"""Tests for :mod:`claude_code_with_bedrock.persona_models`."""

from __future__ import annotations

from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS
from claude_code_with_bedrock.persona_models import (
    aip_name,
    cris_source_arn,
    entitled_tiers,
    model_id_is_denied,
    partition_for_region,
    primary_tier,
)


class TestEntitledTiers:
    def test_empty_allowed_means_all_tiers(self):
        assert entitled_tiers({}) == ["haiku", "sonnet", "opus"]
        assert entitled_tiers({"allowed_models": []}) == ["haiku", "sonnet", "opus"]
        assert entitled_tiers({"allowed_models": ["*"]}) == ["haiku", "sonnet", "opus"]

    def test_reference_engineering_gets_all(self):
        eng = next(p for p in REFERENCE_PERSONAS if p["name"] == "engineering")
        assert entitled_tiers(eng) == ["haiku", "sonnet", "opus"]
        assert primary_tier(eng) == "opus"

    def test_reference_sales_haiku_only(self):
        sales = next(p for p in REFERENCE_PERSONAS if p["name"] == "sales")
        assert entitled_tiers(sales) == ["haiku"]
        assert primary_tier(sales) == "haiku"

    def test_deny_overrides_allow(self):
        # Allowed all, but sonnet+opus denied → haiku only.
        p = {"allowed_models": ["anthropic.*"], "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"]}
        assert entitled_tiers(p) == ["haiku"]

    def test_everything_denied_is_empty(self):
        p = {"allowed_models": ["anthropic.*"], "denied_models": ["anthropic.*"]}
        assert entitled_tiers(p) == []
        assert primary_tier(p) is None

    def test_sonnet_only_allow_glob(self):
        assert entitled_tiers({"allowed_models": ["anthropic.*sonnet*"]}) == ["sonnet"]


class TestEntitledTiersVersionExactProbe:
    """L2: ``cris_prefix`` probes a tier with its RESOLVED CRIS model id so a
    version-pinned deny on that tier's own model excludes the tier — keeping the
    AIP set deploy creates in lockstep with what the IAM Deny actually blocks (no
    AIP sourced from a denied model → no runtime AccessDenied on that tier)."""

    def test_version_pinned_deny_excludes_tier_with_cris_prefix(self):
        # Deny the LATEST opus by its exact version (no trailing wildcard) — the footgun
        # shape. Derive the denied id from the catalog (the bare latest us-opus id) rather
        # than hardcoding a version, so this tracks whatever the current latest opus is and
        # never goes stale on a model bump.
        from claude_code_with_bedrock.models import resolve_model_for_tier

        latest_us_opus = resolve_model_for_tier("opus", "us")  # e.g. us.anthropic.claude-opus-4-8
        bare_latest_opus = latest_us_opus.split(".", 1)[1]  # -> anthropic.claude-opus-4-8
        p = {"allowed_models": ["anthropic.*"], "denied_models": [bare_latest_opus]}
        tiers = entitled_tiers(p, cris_prefix="us")
        assert "opus" not in tiers, (
            "a version-pinned deny matching the tier's resolved model must exclude that "
            f"tier when probed with cris_prefix; denied {bare_latest_opus!r}, got {tiers}"
        )
        # haiku + sonnet remain entitled (their resolved ids are not denied).
        assert tiers == ["haiku", "sonnet"]

    def test_version_pinned_deny_is_MISSED_without_cris_prefix(self):
        # Proves the gap the fix closes: the version-less probe (anthropic.claude-opus)
        # is NOT matched by the version-pinned deny glob, so opus stays (wrongly)
        # entitled — which is exactly why deploy passes cris_prefix.
        p = {"allowed_models": ["anthropic.*"], "denied_models": ["anthropic.claude-opus-4-7"]}
        assert "opus" in entitled_tiers(p)  # no cris_prefix → version-less probe

    def test_family_glob_personas_resolve_identically_with_or_without_prefix(self):
        # Backward-compat: the reference personas (tier-family globs like anthropic.*opus*)
        # resolve to the same tiers regardless of cris_prefix — the fix only changes the
        # version-pinned case, never the family-glob case the shipped personas use.
        for persona in REFERENCE_PERSONAS:
            assert entitled_tiers(persona) == entitled_tiers(persona, cris_prefix="us")

    def test_data_residency_cross_tier_fallback_keeps_versionless_probe(self):
        # opus/jp resolves to a SONNET id (jp has no opus model). If _tier_probe probed
        # the opus tier with that resolved sonnet id, a persona that denies SONNET would
        # then ALSO (wrongly) exclude opus. The guard (use the resolved id only when it
        # contains the tier's own token) keeps the version-less `anthropic.claude-opus`
        # probe in this cross-tier-fallback case, so the sonnet deny does not touch opus.
        #
        # A `denied_models` is REQUIRED here for the probe to be load-bearing: with an
        # allow-all/no-deny persona, every tier is entitled via the allow_all shortcut
        # regardless of the probe, so the test would pass even if the guard were removed
        # (a tautology). Denying sonnet makes the probe content decide opus's fate.
        p = {"allowed_models": ["anthropic.*"], "denied_models": ["anthropic.*sonnet*"]}
        tiers = entitled_tiers(p, cris_prefix="jp")
        assert "opus" in tiers, (
            "opus must stay entitled under jp despite opus/jp resolving to a sonnet id — "
            f"the _tier_probe tier-token guard keeps the version-less opus probe; got {tiers}"
        )
        # And the deny is genuinely active (sonnet excluded) — proving the persona isn't
        # vacuously allow-all and the guard is what spares opus, not an absent deny.
        assert "sonnet" not in tiers, f"sonnet must be denied (deny is active); got {tiers}"


class TestModelIdIsDenied:
    """Guards the data-residency cross-tier-fallback AIP skip (LOW 3)."""

    def test_denied_glob_matches_prefixed_id(self):
        # The IAM Deny shape: a *sonnet* deny must match a region/global-prefixed sonnet id.
        p = {"denied_models": ["anthropic.*sonnet*"]}
        assert model_id_is_denied("jp.anthropic.claude-sonnet-4-6", p) is True
        assert model_id_is_denied("global.anthropic.claude-sonnet-4-6", p) is True

    def test_allowed_tier_id_not_denied(self):
        p = {"denied_models": ["anthropic.*sonnet*"]}
        assert model_id_is_denied("us.anthropic.claude-haiku-4-5", p) is False
        assert model_id_is_denied("us.anthropic.claude-opus-4-7", p) is False

    def test_version_pinned_deny_matches_versioned_id(self):
        # Trailing-* normalization: a version-pinned deny still matches the versioned id.
        p = {"denied_models": ["anthropic.claude-opus-4-7"]}
        assert model_id_is_denied("us.anthropic.claude-opus-4-7-v1:0", p) is True

    def test_no_denied_models_is_never_denied(self):
        assert model_id_is_denied("global.anthropic.claude-opus-4-7", {}) is False
        assert model_id_is_denied("global.anthropic.claude-opus-4-7", {"denied_models": []}) is False


class TestAipNaming:
    def test_name_shape(self):
        assert aip_name("ClaudeCode", "sales", "haiku") == "ClaudeCode-sales-haiku"


class TestCrisSourceArn:
    def test_commercial_partition(self):
        arn = cris_source_arn("haiku", "us", "us-east-1", "aws")
        assert arn is not None
        assert arn.startswith("arn:aws:bedrock:us-east-1::inference-profile/")
        # CRIS ids are region-prefixed (us./eu./...), proving a cross-Region source.
        assert "inference-profile/us." in arn

    def test_govcloud_partition(self):
        arn = cris_source_arn("sonnet", "us", "us-gov-west-1", "aws-us-gov")
        assert arn is not None
        assert arn.startswith("arn:aws-us-gov:bedrock:us-gov-west-1::inference-profile/")

    def test_unresolvable_tier_returns_none(self):
        # An unknown tier has no candidate models, so no CRIS source resolves and
        # the helper returns None (the caller then SKIPS that tier rather than
        # fabricating a bogus ARN). Hard `is None` assertion — the prior
        # `is None or isinstance(str)` form was always true and tested nothing.
        assert cris_source_arn("bogus-tier", "us", "us-east-1", "aws") is None

    def test_data_residency_prefix_falls_back_within_prefix(self):
        # A data-residency prefix (jp/eu/au) that lacks the exact tier resolves to
        # ANOTHER model WITH THE SAME PREFIX (never global/us) — proving residency
        # is preserved. opus has no jp profile, so jp.opus falls back to a jp.* model.
        arn = cris_source_arn("opus", "jp", "ap-northeast-1", "aws")
        assert arn is not None
        assert "inference-profile/jp." in arn, f"data-residency must stay in-prefix, got {arn}"


class TestPartitionForRegion:
    def test_commercial(self):
        assert partition_for_region("us-east-1") == "aws"
        assert partition_for_region("eu-west-1") == "aws"

    def test_govcloud(self):
        assert partition_for_region("us-gov-west-1") == "aws-us-gov"
        assert partition_for_region("us-gov-east-1") == "aws-us-gov"
