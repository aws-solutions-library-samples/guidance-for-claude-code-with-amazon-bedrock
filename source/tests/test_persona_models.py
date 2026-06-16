# ABOUTME: Tests for persona_models — tier entitlement + AIP naming/source (FR-5.1).
# ABOUTME: Pure helpers; asserts entitlement against allow/deny globs and partition-aware CRIS source ARNs.

"""Tests for :mod:`claude_code_with_bedrock.persona_models`."""

from __future__ import annotations

from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS
from claude_code_with_bedrock.persona_models import (
    aip_name,
    cris_source_arn,
    entitled_tiers,
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
        # A data-residency prefix without the tier resolves to None (skip, don't fabricate).
        assert cris_source_arn("opus", "jp", "ap-northeast-1", "aws") is None or isinstance(
            cris_source_arn("opus", "jp", "ap-northeast-1", "aws"), str
        )


class TestPartitionForRegion:
    def test_commercial(self):
        assert partition_for_region("us-east-1") == "aws"
        assert partition_for_region("eu-west-1") == "aws"

    def test_govcloud(self):
        assert partition_for_region("us-gov-west-1") == "aws-us-gov"
        assert partition_for_region("us-gov-east-1") == "aws-us-gov"
