# ABOUTME: Tests PBAC declared-order group resolution (PERSONA_ORDER) in both quota Lambdas
# ABOUTME: Verifies first-declared-wins when set, and legacy most-restrictive-wins when unset

"""Tests for PERSONA_ORDER declared-order resolution in the quota Lambdas.

Spec decision D3: persona-based access control changes group-tier quota
resolution to *declared-order precedence* (first matching group wins), gated
on the PERSONA_ORDER env var. When PERSONA_ORDER is empty/unset, the legacy
"most-restrictive-wins" (lowest monthly_token_limit) behavior is preserved
exactly. Both quota_check and quota_monitor must agree.

These modules read configuration (incl. PERSONA_ORDER) at import time, so each
test loads the module fresh with the desired environment.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_LAMBDA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
)
QUOTA_CHECK_PATH = _LAMBDA_ROOT / "quota_check" / "index.py"
QUOTA_MONITOR_PATH = _LAMBDA_ROOT / "quota_monitor" / "index.py"


def _load_module(path: Path, env: dict) -> object:
    """Load a Lambda module fresh with the given environment.

    The module reads env vars at import time, so a fresh import is required
    for module-level reads (e.g. PERSONA_ORDER) to take effect.
    """
    for key, value in env.items():
        os.environ[key] = value

    module_name = f"{path.parent.name}_index_{id(env)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Canned group policies. "sales" is the MORE restrictive policy (lower monthly
# limit); "eng" is the LESS restrictive. A user in BOTH groups is the key case:
#   - declared-order eng,sales  -> eng   (first declared wins, ignores limits)
#   - legacy (unset)            -> sales (most restrictive wins)
GROUP_POLICIES = {
    "eng": {
        "policy_type": "group",
        "identifier": "eng",
        "monthly_token_limit": 300_000_000,
        "daily_token_limit": None,
        "warning_threshold_80": 240_000_000,
        "warning_threshold_90": 270_000_000,
        "enforcement_mode": "block",
        "daily_enforcement_mode": "alert",
        "enabled": True,
    },
    "sales": {
        "policy_type": "group",
        "identifier": "sales",
        "monthly_token_limit": 10_000_000,
        "daily_token_limit": None,
        "warning_threshold_80": 8_000_000,
        "warning_threshold_90": 9_000_000,
        "enforcement_mode": "block",
        "daily_enforcement_mode": "alert",
        "enabled": True,
    },
}


# ---------------------------------------------------------------------------
# quota_check: resolve_quota_for_user(email, groups) with mocked get_policy
# ---------------------------------------------------------------------------


class TestQuotaCheckPersonaOrder:
    """quota_check group-tier resolution under PBAC vs legacy modes."""

    def _make_module(self, persona_order: str | None):
        env = {
            "QUOTA_TABLE": "TestQuotaTable",
            "POLICIES_TABLE": "TestPoliciesTable",
            "ENABLE_FINEGRAINED_QUOTAS": "true",  # use DynamoDB-backed group lookups
        }
        if persona_order is not None:
            env["PERSONA_ORDER"] = persona_order
        else:
            os.environ.pop("PERSONA_ORDER", None)
        return _load_module(QUOTA_CHECK_PATH, env)

    def _stub_get_policy(self, mod):
        """Stub get_policy so only the canned group policies exist.

        user:* and default:* lookups miss (None) so resolution exercises the
        group tier exclusively.
        """

        def fake_get_policy(policy_type, identifier):
            if policy_type == "group":
                return GROUP_POLICIES.get(identifier)
            return None

        mod.get_policy = MagicMock(side_effect=fake_get_policy)

    def test_declared_order_first_group_wins_over_more_restrictive(self):
        """PBAC mode: declared order eng,sales -> eng even though sales is stricter."""
        mod = self._make_module("eng,sales")
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("u@example.com", ["sales", "eng"])
        assert policy["identifier"] == "eng"
        assert policy["monthly_token_limit"] == 300_000_000

    def test_declared_order_respects_reversed_precedence(self):
        """PBAC mode: declared order sales,eng -> sales (first declared)."""
        mod = self._make_module("sales,eng")
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("u@example.com", ["eng", "sales"])
        assert policy["identifier"] == "sales"

    def test_legacy_unset_picks_most_restrictive(self):
        """Legacy mode (PERSONA_ORDER unset): same user -> sales (most restrictive)."""
        mod = self._make_module(None)
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("u@example.com", ["eng", "sales"])
        assert policy["identifier"] == "sales"
        assert policy["monthly_token_limit"] == 10_000_000

    def test_legacy_empty_string_picks_most_restrictive(self):
        """Empty PERSONA_ORDER string is treated as legacy mode."""
        mod = self._make_module("")
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("u@example.com", ["eng", "sales"])
        assert policy["identifier"] == "sales"

    def test_pbac_single_group_match(self):
        """PBAC mode: user in only one declared group resolves to it."""
        mod = self._make_module("eng,sales")
        self._stub_get_policy(mod)

        policy = mod.resolve_quota_for_user("u@example.com", ["eng"])
        assert policy["identifier"] == "eng"

    def test_pbac_no_declared_group_falls_through_to_default(self):
        """PBAC mode: user has a group policy not in PERSONA_ORDER -> default tier.

        Declared order is the sole group authority in PBAC mode, so an
        unlisted group must NOT fall back to most-restrictive.
        """
        mod = self._make_module("eng")  # sales NOT declared

        default_policy = {
            "policy_type": "default",
            "identifier": "default",
            "monthly_token_limit": 50_000_000,
            "daily_token_limit": None,
            "warning_threshold_80": 0,
            "warning_threshold_90": 0,
            "enforcement_mode": "alert",
            "daily_enforcement_mode": "alert",
            "enabled": True,
        }

        def fake_get_policy(policy_type, identifier):
            if policy_type == "group":
                return GROUP_POLICIES.get(identifier)
            if policy_type == "default":
                return default_policy
            return None

        mod.get_policy = MagicMock(side_effect=fake_get_policy)

        policy = mod.resolve_quota_for_user("u@example.com", ["sales"])
        assert policy["policy_type"] == "default"
        assert policy["identifier"] == "default"

    def test_user_policy_still_takes_precedence_over_group(self):
        """PBAC mode does not change user > group precedence."""
        mod = self._make_module("eng,sales")

        user_policy = {
            "policy_type": "user",
            "identifier": "u@example.com",
            "monthly_token_limit": 5_000_000,
            "daily_token_limit": None,
            "warning_threshold_80": 0,
            "warning_threshold_90": 0,
            "enforcement_mode": "block",
            "daily_enforcement_mode": "alert",
            "enabled": True,
        }

        def fake_get_policy(policy_type, identifier):
            if policy_type == "user":
                return user_policy
            if policy_type == "group":
                return GROUP_POLICIES.get(identifier)
            return None

        mod.get_policy = MagicMock(side_effect=fake_get_policy)

        policy = mod.resolve_quota_for_user("u@example.com", ["eng", "sales"])
        assert policy["policy_type"] == "user"


# ---------------------------------------------------------------------------
# quota_monitor: resolve_user_quota(email, groups, policies_cache)
# ---------------------------------------------------------------------------


class TestQuotaMonitorPersonaOrder:
    """quota_monitor group-tier resolution under PBAC vs legacy modes."""

    def _make_module(self, persona_order: str | None):
        env = {
            "QUOTA_TABLE": "TestQuotaTable",
            "POLICIES_TABLE": "TestPoliciesTable",
            "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test",
            "ENABLE_FINEGRAINED_QUOTAS": "true",
        }
        if persona_order is not None:
            env["PERSONA_ORDER"] = persona_order
        else:
            os.environ.pop("PERSONA_ORDER", None)
        return _load_module(QUOTA_MONITOR_PATH, env)

    @staticmethod
    def _cache():
        return {
            "group:eng": GROUP_POLICIES["eng"],
            "group:sales": GROUP_POLICIES["sales"],
        }

    def test_declared_order_first_group_wins_over_more_restrictive(self):
        """PBAC mode: declared order eng,sales -> eng even though sales is stricter."""
        mod = self._make_module("eng,sales")
        policy = mod.resolve_user_quota("u@example.com", ["sales", "eng"], self._cache())
        assert policy["identifier"] == "eng"
        assert policy["monthly_token_limit"] == 300_000_000

    def test_declared_order_respects_reversed_precedence(self):
        mod = self._make_module("sales,eng")
        policy = mod.resolve_user_quota("u@example.com", ["eng", "sales"], self._cache())
        assert policy["identifier"] == "sales"

    def test_legacy_unset_picks_most_restrictive(self):
        """Legacy mode: same user -> sales (most restrictive)."""
        mod = self._make_module(None)
        policy = mod.resolve_user_quota("u@example.com", ["eng", "sales"], self._cache())
        assert policy["identifier"] == "sales"
        assert policy["monthly_token_limit"] == 10_000_000

    def test_legacy_empty_string_picks_most_restrictive(self):
        mod = self._make_module("")
        policy = mod.resolve_user_quota("u@example.com", ["eng", "sales"], self._cache())
        assert policy["identifier"] == "sales"

    def test_pbac_single_group_match(self):
        mod = self._make_module("eng,sales")
        policy = mod.resolve_user_quota("u@example.com", ["eng"], self._cache())
        assert policy["identifier"] == "eng"

    def test_pbac_no_declared_group_falls_through_to_default(self):
        """PBAC mode: a group not in PERSONA_ORDER falls through to default."""
        mod = self._make_module("eng")  # sales NOT declared
        cache = dict(self._cache())
        cache["default:default"] = {
            "policy_type": "default",
            "identifier": "default",
            "monthly_token_limit": 50_000_000,
            "daily_token_limit": None,
            "warning_threshold_80": 0,
            "warning_threshold_90": 0,
            "enforcement_mode": "alert",
            "enabled": True,
        }
        policy = mod.resolve_user_quota("u@example.com", ["sales"], cache)
        assert policy["policy_type"] == "default"

    def test_user_policy_still_takes_precedence_over_group(self):
        mod = self._make_module("eng,sales")
        cache = dict(self._cache())
        cache["user:u@example.com"] = {
            "policy_type": "user",
            "identifier": "u@example.com",
            "monthly_token_limit": 5_000_000,
            "daily_token_limit": None,
            "warning_threshold_80": 0,
            "warning_threshold_90": 0,
            "enforcement_mode": "block",
            "enabled": True,
        }
        policy = mod.resolve_user_quota("u@example.com", ["eng", "sales"], cache)
        assert policy["policy_type"] == "user"


# ---------------------------------------------------------------------------
# Cross-Lambda parity: both resolvers agree for the same inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "persona_order,expected_identifier",
    [
        ("eng,sales", "eng"),  # PBAC: first declared wins
        ("sales,eng", "sales"),
        (None, "sales"),  # legacy: most restrictive wins
    ],
)
def test_quota_check_and_monitor_agree(persona_order, expected_identifier):
    """quota_check and quota_monitor resolve the same group for the same inputs."""
    check = TestQuotaCheckPersonaOrder()
    check_mod = check._make_module(persona_order)
    check._stub_get_policy(check_mod)
    check_policy = check_mod.resolve_quota_for_user("u@example.com", ["eng", "sales"])

    monitor = TestQuotaMonitorPersonaOrder()
    monitor_mod = monitor._make_module(persona_order)
    monitor_policy = monitor_mod.resolve_user_quota(
        "u@example.com", ["eng", "sales"], monitor._cache()
    )

    assert check_policy["identifier"] == expected_identifier
    assert monitor_policy["identifier"] == expected_identifier
    assert check_policy["identifier"] == monitor_policy["identifier"]


# ---------------------------------------------------------------------------
# L5: user->group persistence (quota_check writes, quota_monitor reads) so the
# claim-less monitor can resolve per-persona ALERT thresholds.
# ---------------------------------------------------------------------------


class TestUserGroupPersistence:
    """quota_check.store_user_groups <-> quota_monitor.get_user_groups round-trip."""

    def _check_mod(self):
        return _load_module(
            QUOTA_CHECK_PATH,
            {"QUOTA_TABLE": "T", "POLICIES_TABLE": "P", "ENABLE_FINEGRAINED_QUOTAS": "true"},
        )

    def _monitor_mod(self):
        return _load_module(
            QUOTA_MONITOR_PATH,
            {"QUOTA_TABLE": "T", "POLICIES_TABLE": "P", "ENABLE_FINEGRAINED_QUOTAS": "true"},
        )

    def test_store_user_groups_writes_groups_record_with_ttl(self):
        mod = self._check_mod()
        mod.quota_table = MagicMock()
        mod.store_user_groups("alice@example.com", ["eng", "sales"])

        mod.quota_table.put_item.assert_called_once()
        item = mod.quota_table.put_item.call_args.kwargs["Item"]
        assert item["pk"] == "USER#alice@example.com"
        assert item["sk"] == "GROUPS"  # distinct sk keeps it out of the MONTH# usage scan
        assert item["groups"] == ["eng", "sales"]
        assert isinstance(item["ttl"], int) and item["ttl"] > 0

    def test_store_user_groups_is_non_fatal_on_write_error(self):
        # A table write failure (e.g. read-only role) must NOT raise — credential
        # issuance must never be blocked by best-effort group persistence.
        mod = self._check_mod()
        mod.quota_table = MagicMock()
        mod.quota_table.put_item.side_effect = Exception("AccessDenied")
        mod.store_user_groups("alice@example.com", ["eng"])  # must not raise

    def _event(self, email="alice@example.com", groups=("eng",)):
        """Minimal API-Gateway-JWT-authorizer event the quota_check handler expects."""
        return {
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"email": email, "groups": ",".join(groups)}}}
            }
        }

    def _drive_handler_capture_store(self, persona_order: str):
        """Run quota_check.lambda_handler with PERSONA_ORDER set as given; return whether
        store_user_groups was invoked. Quota resolution is stubbed so the handler reaches
        (and passes) the store gate without real DynamoDB."""
        from unittest.mock import patch

        mod = _load_module(
            QUOTA_CHECK_PATH,
            {"QUOTA_TABLE": "T", "POLICIES_TABLE": "P", "ENABLE_FINEGRAINED_QUOTAS": "true",
             "PERSONA_ORDER": persona_order},
        )
        # Stub the heavy downstream so the handler returns cleanly after the gate.
        mod.resolve_quota_for_user = lambda *a, **k: None  # no policy -> unlimited/allow
        with patch.object(mod, "store_user_groups") as store:
            mod.lambda_handler(self._event(), None)
        return store.called

    def test_groups_written_in_pbac_mode(self):
        """L6: PERSONA_ORDER set -> the handler persists the user's groups."""
        assert self._drive_handler_capture_store("eng,sales") is True

    def test_groups_not_written_in_legacy_mode(self):
        """L6: PERSONA_ORDER unset -> the `and PERSONA_ORDER` gate skips the write
        (no unused DynamoDB writes/storage outside PBAC). This FAILS if someone drops
        the PERSONA_ORDER guard from the call site."""
        assert self._drive_handler_capture_store("") is False

    def test_get_user_groups_reads_back_record(self):
        mod = self._monitor_mod()
        mod.quota_table = MagicMock()
        mod.quota_table.get_item.return_value = {
            "Item": {"pk": "USER#alice@example.com", "sk": "GROUPS", "groups": ["eng", "sales"]}
        }
        assert mod.get_user_groups("alice@example.com") == ["eng", "sales"]

    def test_get_user_groups_returns_empty_on_miss_or_error(self):
        mod = self._monitor_mod()
        mod.quota_table = MagicMock()
        mod.quota_table.get_item.return_value = {}  # no Item
        assert mod.get_user_groups("nobody@example.com") == []
        mod.quota_table.get_item.side_effect = Exception("boom")
        assert mod.get_user_groups("err@example.com") == []  # swallowed, [] fallback

    def test_monitor_resolves_persona_via_stored_groups_in_pbac_mode(self):
        # The payoff: with PERSONA_ORDER set and a user's groups available from the
        # stored record, the monitor resolves the FIRST declared group's policy
        # (per-persona alerting) instead of always defaulting.
        monitor = TestQuotaMonitorPersonaOrder()
        mod = monitor._make_module("eng,sales")  # declared order: eng first
        groups = mod.get_user_groups  # ensure attribute exists
        assert callable(groups)
        policy = mod.resolve_user_quota("u@example.com", ["sales", "eng"], monitor._cache())
        assert policy["identifier"] == "eng"  # first DECLARED (eng), not most-restrictive (sales)

    def test_usage_scan_filter_excludes_groups_record(self):
        """M2 regression: the monitor's usage scan must filter sk == MONTH#<month>, so the
        USER#<email>/GROUPS bookkeeping record (sk="GROUPS") never pollutes usage totals.

        If someone "simplified" the scan to only ``pk begins_with USER#`` (dropping the sk
        equality), every user's GROUPS row would be counted as a zero-token user and corrupt
        alerting. We capture the actual FilterExpression the monitor builds and prove it
        evaluates FALSE for a GROUPS-sk item and TRUE for a MONTH#-sk item.
        """
        from datetime import datetime, timezone

        mod = self._monitor_mod()
        # Stub the PromQL fetch so the handler reaches the scan step with no delta work.
        mod.fetch_usage_from_promql = lambda: {}

        captured = {}

        def fake_scan(**kwargs):
            # Capture the FilterExpression the production code passes to DynamoDB.
            captured["filter"] = kwargs.get("FilterExpression")
            return {"Items": []}

        mod.quota_table = MagicMock()
        mod.quota_table.scan.side_effect = fake_scan
        mod.lambda_handler({}, None)

        expr = captured.get("filter")
        assert expr is not None, "monitor usage scan must pass a FilterExpression"

        # Walk the captured boto3 ConditionBase tree and collect (attr_name, operator,
        # value) leaves so we can assert the sk constraint is an equality on
        # MONTH#<current_month> — NOT a begins_with that would also admit the GROUPS row.
        from boto3.dynamodb.conditions import ConditionBase

        leaves: list[tuple] = []

        def _walk(node) -> None:
            built = node.get_expression()
            op = built["operator"]
            values = built["values"]
            if any(isinstance(v, ConditionBase) for v in values):
                for v in values:
                    if isinstance(v, ConditionBase):
                        _walk(v)
                return
            # Leaf: values are (Attr/Key, literal). The attr's name is on .name.
            attr = values[0]
            literal = values[1] if len(values) > 1 else None
            leaves.append((getattr(attr, "name", None), op, literal))

        _walk(expr)

        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        # The sk leaf must be an equality on MONTH#<current_month> (excludes sk="GROUPS").
        sk_leaves = [lf for lf in leaves if lf[0] == "sk"]
        assert sk_leaves, f"usage scan filter has no sk constraint; leaves={leaves}"
        assert any(op == "=" and val == f"MONTH#{current_month}" for _name, op, val in sk_leaves), (
            "usage scan filter lost its sk == MONTH#<month> equality — a GROUPS record "
            f"(sk='GROUPS') could be counted as usage. sk leaves: {sk_leaves}"
        )
        # And no leaf should ever match the GROUPS bookkeeping record.
        assert not any(val == "GROUPS" for _name, _op, val in leaves)
