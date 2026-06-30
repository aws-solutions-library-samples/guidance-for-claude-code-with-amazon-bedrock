# ABOUTME: Backward-compat regression — pre-persona configs and legacy quota must still work
# ABOUTME: Proves PBAC changes are additive: no persona keys, FederatedRoleARN path, most-restrictive quota

"""Regression tests guarding existing (pre-persona) deployments.

Persona-based access control (spec D3, NFR-1) is strictly additive. A customer
who upgrades `ccwb` without configuring any persona must see *zero* behavior
change. This module locks that down across the three layers the feature touched:

1. **Config** — a pre-persona profile dict (no ``personas`` / ``groups_claim_name``
   / ``fallback_persona`` keys) loads cleanly with the documented defaults, and
   ``effective_auth_type`` still derives from the legacy ``sso_enabled`` boolean
   (auth-type-compat.md).
2. **Packaging** — ``_create_config`` (an explicit allowlist, research F10) emits
   **no** persona keys for a non-persona profile, so ``config.json`` keeps its
   exact historical shape and the Go helper falls back to ``FederatedRoleARN``.
3. **Quota** — with ``PERSONA_ORDER`` unset, group-tier resolution preserves the
   legacy most-restrictive-wins semantics (lowest ``monthly_token_limit``).

The exhaustive PBAC-vs-legacy matrix lives in ``test_lambda_persona_order.py``
(task #18); here we assert only the *legacy-preserved* direction as a regression.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claude_code_with_bedrock.config import Profile

_LAMBDA_ROOT = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure" / "lambda-functions"
QUOTA_CHECK_PATH = _LAMBDA_ROOT / "quota_check" / "index.py"


# A representative pre-persona profile dict: the shape `ccwb` wrote before PBAC.
# Deliberately omits personas / groups_claim_name / fallback_persona entirely.
LEGACY_PROFILE_DICT = {
    "name": "ClaudeCode",
    "provider_domain": "company.okta.com",
    "client_id": "0oa1example",
    "aws_region": "us-east-1",
    "credential_storage": "session",
    "identity_pool_name": "claude-code-auth",
    "federated_role_arn": "arn:aws:iam::111122223333:role/claude-code-federated",
    "federation_type": "direct",
    "sso_enabled": True,
}


class TestLegacyConfigLoads:
    """A pre-persona profile dict loads with persona defaults, no crash."""

    def test_persona_fields_default_when_absent(self):
        profile = Profile.from_dict(LEGACY_PROFILE_DICT)
        assert profile.personas == []
        assert profile.groups_claim_name == "groups"
        assert profile.fallback_persona is None

    def test_federated_role_arn_preserved(self):
        """The role the helper falls back to must survive the round trip."""
        profile = Profile.from_dict(LEGACY_PROFILE_DICT)
        assert profile.federated_role_arn == "arn:aws:iam::111122223333:role/claude-code-federated"

    def test_effective_auth_type_oidc_for_legacy_sso_enabled(self):
        profile = Profile.from_dict(LEGACY_PROFILE_DICT)
        assert profile.effective_auth_type == "oidc"

    def test_effective_auth_type_none_when_sso_disabled(self):
        data = dict(LEGACY_PROFILE_DICT, sso_enabled=False)
        profile = Profile.from_dict(data)
        assert profile.effective_auth_type == "none"

    def test_effective_auth_type_inferred_when_sso_field_missing(self):
        """Profiles saved before the sso_enabled field still resolve a type."""
        data = {k: v for k, v in LEGACY_PROFILE_DICT.items() if k != "sso_enabled"}
        profile = Profile.from_dict(data)
        # from_dict infers sso_enabled from a real provider domain (!= "none").
        assert profile.effective_auth_type in {"oidc", "none"}

    def test_roundtrip_to_dict_has_no_surprise_persona_payload(self):
        """to_dict on a legacy profile must not invent persona content."""
        profile = Profile.from_dict(LEGACY_PROFILE_DICT)
        as_dict = profile.to_dict()
        # personas defaults to [] (may be present as empty); it must never be
        # populated with phantom personas for a legacy profile.
        assert as_dict.get("personas", []) == []
        assert as_dict.get("fallback_persona") is None


class TestPackageConfigOmitsPersonas:
    """package._create_config must emit no persona keys for a non-persona profile."""

    def test_no_persona_keys_in_config_json(self, tmp_path):
        from claude_code_with_bedrock.cli.commands.package import PackageCommand

        profile = Profile.from_dict(LEGACY_PROFILE_DICT)
        cmd = PackageCommand()
        config_path = cmd._create_config(
            output_dir=tmp_path,
            profile=profile,
            federation_identifier=profile.federated_role_arn,
            federation_type="direct",
            profile_name="ClaudeCode",
        )

        data = json.loads(config_path.read_text(encoding="utf-8"))
        entry = data["ClaudeCode"]
        assert "personas" not in entry
        assert "groups_claim_name" not in entry
        assert "fallback_persona" not in entry
        # Sanity: the legacy federation shape is intact.
        assert entry["federated_role_arn"] == profile.federated_role_arn
        assert entry["federation_type"] == "direct"


def _load_quota_check(persona_order: str | None) -> object:
    """Load quota_check/index.py fresh with the given PERSONA_ORDER env.

    The module reads PERSONA_ORDER at import time, so a fresh import is required
    for the env to take effect (same approach as test_lambda_persona_order.py).
    """
    env = {
        "QUOTA_TABLE": "TestQuotaTable",
        "POLICIES_TABLE": "TestPoliciesTable",
        "ENABLE_FINEGRAINED_QUOTAS": "true",  # don't short-circuit to env defaults
    }
    if persona_order is not None:
        env["PERSONA_ORDER"] = persona_order
    else:
        os.environ.pop("PERSONA_ORDER", None)
    for key, value in env.items():
        os.environ[key] = value

    module_name = f"quota_check_index_bwc_{id(env)}"
    spec = importlib.util.spec_from_file_location(module_name, QUOTA_CHECK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# eng = lenient (high limit), sales = restrictive (low limit).
_GROUP_POLICIES = {
    "eng": {"policy_type": "group", "identifier": "eng", "monthly_token_limit": 300_000_000, "enabled": True},
    "sales": {"policy_type": "group", "identifier": "sales", "monthly_token_limit": 10_000_000, "enabled": True},
}


class TestLegacyQuotaMostRestrictive:
    """With PERSONA_ORDER unset, multi-group users get the most-restrictive policy."""

    def _stub_get_policy(self, mod):
        def fake_get_policy(policy_type, identifier):
            if policy_type == "group":
                return _GROUP_POLICIES.get(identifier)
            return None

        mod.get_policy = MagicMock(side_effect=fake_get_policy)

    def test_unset_persona_order_picks_lowest_limit(self):
        mod = _load_quota_check(None)
        # Guard: PERSONA_ORDER really is empty in the loaded module.
        assert mod.PERSONA_ORDER == []
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("user@example.com", ["eng", "sales"])
        assert policy["identifier"] == "sales"
        assert policy["monthly_token_limit"] == 10_000_000

    def test_unset_persona_order_independent_of_group_order(self):
        """Most-restrictive wins regardless of the order groups are presented."""
        mod = _load_quota_check(None)
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("user@example.com", ["sales", "eng"])
        assert policy["identifier"] == "sales"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
