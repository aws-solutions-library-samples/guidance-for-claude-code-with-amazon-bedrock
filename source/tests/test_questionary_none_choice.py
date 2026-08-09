# ABOUTME: Regression tests for questionary's value=None title-fallback corrupting
# ABOUTME: profiles ("Disabled" leaked into distribution_type, flipping deploys on).

"""questionary.Choice(value=None) falls back to the choice TITLE.

The init wizard's "Disabled"/"Skip" choices were built with value=None, so
selecting them returned the title string ("Disabled", "Skip CodeBuild (...)",
"Skip (no Route53 managed domain)") instead of None. Selecting "Disabled" for
distribution therefore saved enable_distribution=True with
distribution_type="Disabled" — and sidecar deploys scheduled the networking
and distribution stacks the user had explicitly declined.

Covers: the questionary behavior itself (so a library change is noticed), the
Profile.from_dict heal for already-corrupted profiles, the deploy-side effect,
and a source guard so value=None choices can't creep back into the wizard.
"""

from __future__ import annotations

import re
from pathlib import Path

import questionary

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile

INIT_PY = Path(__file__).resolve().parents[1] / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"


class _NullConsole:
    def print(self, *args, **kwargs):
        pass


def _profile_dict(**overrides) -> dict:
    base = {
        "name": "heal-test",
        "provider_domain": "company.okta.com",
        "client_id": "client-123",
        "credential_storage": "session",
        "aws_region": "us-gov-west-1",
        "identity_pool_name": "gov-pool",
        "auth_type": "oidc",
        "monitoring_enabled": True,
        "monitoring_mode": "sidecar",
        "analytics_enabled": False,
    }
    base.update(overrides)
    return base


class TestQuestionaryTitleFallback:
    def test_choice_value_none_falls_back_to_title(self):
        """Pin the library behavior this whole bug class rests on. If a
        questionary upgrade changes this, the wizard sentinels can be removed."""
        assert questionary.Choice("Disabled", value=None).value == "Disabled"

    def test_init_wizard_has_no_none_valued_choices(self):
        """Source guard: every 'Disabled'/'Skip' Choice must carry an explicit
        sentinel (see _CHOICE_NONE in init.py), never value=None."""
        source = INIT_PY.read_text(encoding="utf-8")
        offenders = [
            line.strip() for line in source.splitlines() if re.search(r"questionary\.Choice\(.*value=None", line)
        ]
        assert not offenders, (
            "questionary.Choice(value=None) returns the choice TITLE, not None — "
            f"use _CHOICE_NONE and map it back after .ask(): {offenders}"
        )


class TestProfileHeal:
    def test_corrupted_distribution_type_heals_to_disabled(self):
        loaded = Profile.from_dict(_profile_dict(enable_distribution=True, distribution_type="Disabled"))
        assert loaded.enable_distribution is False
        assert loaded.distribution_type is None

    def test_valid_distribution_types_untouched(self):
        for dist_type in ("presigned-s3", "landing-page"):
            loaded = Profile.from_dict(_profile_dict(enable_distribution=True, distribution_type=dist_type))
            assert loaded.enable_distribution is True
            assert loaded.distribution_type == dist_type

    def test_legacy_enabled_without_type_still_migrates(self):
        """Pre-distribution_type profiles must keep migrating to presigned-s3."""
        loaded = Profile.from_dict(_profile_dict(enable_distribution=True))
        assert loaded.enable_distribution is True
        assert loaded.distribution_type == "presigned-s3"

    def test_corrupted_codebuild_region_heals(self):
        loaded = Profile.from_dict(
            _profile_dict(
                enable_codebuild=True,
                codebuild_region="Skip CodeBuild (build Windows binaries manually)",
            )
        )
        assert loaded.codebuild_region is None

    def test_valid_codebuild_region_untouched(self):
        loaded = Profile.from_dict(_profile_dict(enable_codebuild=True, codebuild_region="us-east-1"))
        assert loaded.codebuild_region == "us-east-1"

    def test_corrupted_hosted_zone_heals(self):
        loaded = Profile.from_dict(_profile_dict(distribution_hosted_zone_id="Skip (no Route53 managed domain)"))
        assert loaded.distribution_hosted_zone_id is None

    def test_valid_hosted_zone_untouched(self):
        loaded = Profile.from_dict(_profile_dict(distribution_hosted_zone_id="Z0123456789ABCDEF"))
        assert loaded.distribution_hosted_zone_id == "Z0123456789ABCDEF"


class TestDeployEffect:
    def test_healed_profile_schedules_no_networking_or_distribution(self):
        """The user-visible regression: a sidecar profile corrupted by the
        'Disabled' choice scheduled networking + distribution stacks."""
        profile = Profile.from_dict(_profile_dict(enable_distribution=True, distribution_type="Disabled"))
        stacks = [s for s, _ in DeployCommand()._select_full_deploy_stacks(profile, _NullConsole())]
        assert "networking" not in stacks, f"networking scheduled for disabled distribution: {stacks}"
        assert "distribution" not in stacks, f"distribution scheduled despite 'Disabled': {stacks}"
