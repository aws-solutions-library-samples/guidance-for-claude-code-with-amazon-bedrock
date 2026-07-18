# ABOUTME: Tests for GovCloud model support — Opus 4.8 registry entry, partition-aware
# ABOUTME: wizard filtering, and us-gov tier/alias resolution (no commercial fallback).

"""GovCloud model selection tests.

Claude Opus 4.8 is available in AWS GovCloud (announced 2026-05; in-region in
us-gov-west-1, geo-routed from us-gov-east-1 via the us-gov CRIS prefix).
These tests pin:

- the opus-4-8-govcloud registry entry,
- the wizard offering ONLY partition-compatible models (GovCloud regions see
  us-gov models; commercial regions never see them),
- tier resolution for the us-gov prefix (DEFAULT_*_MODEL aliases), including
  the GovCloud haiku→sonnet fallback and NO fallback to commercial CRIS —
  us-gov is a separate partition, a commercial model ID can never work there.
"""

from __future__ import annotations

from claude_code_with_bedrock.cli.commands.init import _model_keys_for_region
from claude_code_with_bedrock.models import (
    CLAUDE_MODELS,
    get_claude_code_alias,
    resolve_model_for_tier,
)


class TestOpusGovCloudRegistryEntry:
    def test_entry_exists_with_us_gov_profile(self):
        model = CLAUDE_MODELS["opus-4-8-govcloud"]
        profile = model["profiles"]["us-gov"]
        assert profile["model_id"] == "us-gov.anthropic.claude-opus-4-8"
        assert set(profile["source_regions"]) == {"us-gov-west-1", "us-gov-east-1"}

    def test_all_govcloud_entries_use_us_gov_prefix(self):
        for key, model in CLAUDE_MODELS.items():
            if not key.endswith("-govcloud"):
                continue
            for profile in model["profiles"].values():
                assert profile["model_id"].startswith("us-gov."), (
                    f"{key} must use the us-gov CRIS prefix, got {profile['model_id']}"
                )


class TestWizardPartitionFiltering:
    def test_govcloud_region_offers_only_govcloud_models(self):
        keys = _model_keys_for_region("us-gov-west-1")
        assert "opus-4-8-govcloud" in keys
        assert "sonnet-4-5-govcloud" in keys
        assert not [k for k in keys if not k.endswith("-govcloud")], (
            f"commercial models offered for a GovCloud region: {keys}"
        )

    def test_commercial_region_hides_govcloud_models(self):
        keys = _model_keys_for_region("us-east-1")
        assert "opus-4-8" in keys
        assert not [k for k in keys if k.endswith("-govcloud")], (
            f"GovCloud models offered for a commercial region: {keys}"
        )

    def test_unknown_or_missing_region_defaults_to_commercial(self):
        assert "opus-4-8-govcloud" not in _model_keys_for_region(None)
        assert "opus-4-8-govcloud" not in _model_keys_for_region("")


class TestUsGovTierResolution:
    def test_opus_tier_resolves_govcloud_opus(self):
        assert resolve_model_for_tier("opus", "us-gov") == "us-gov.anthropic.claude-opus-4-8"

    def test_sonnet_tier_resolves_govcloud_sonnet(self):
        assert resolve_model_for_tier("sonnet", "us-gov") == "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"

    def test_haiku_tier_falls_back_to_govcloud_sonnet(self):
        """GovCloud has no Haiku — the haiku tier must fall through to the
        GovCloud Sonnet, never to a commercial model."""
        resolved = resolve_model_for_tier("haiku", "us-gov")
        assert resolved is not None
        assert resolved.startswith("us-gov.")

    def test_us_gov_never_falls_back_to_commercial(self):
        """us-gov is a data-residency AND partition boundary: any resolution
        for the us-gov prefix must yield a us-gov.* ID or nothing."""
        for tier in ("haiku", "sonnet", "opus", "fable"):
            resolved = resolve_model_for_tier(tier, "us-gov")
            assert resolved is None or resolved.startswith("us-gov."), (
                f"tier {tier!r} resolved commercial model {resolved!r} for us-gov"
            )

    def test_commercial_tiers_unchanged_by_govcloud_entries(self):
        assert resolve_model_for_tier("opus", "us") == "us.anthropic.claude-opus-4-8"
        assert resolve_model_for_tier("sonnet", "us").startswith("us.anthropic.claude-sonnet-5")

    def test_alias_for_govcloud_model_ids(self):
        assert get_claude_code_alias("us-gov.anthropic.claude-opus-4-8") == "opus"
        assert get_claude_code_alias("us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0") == "sonnet"
