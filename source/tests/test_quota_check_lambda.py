# ABOUTME: Tests for the quota_check Lambda function's daily enforcement logic
# ABOUTME: Covers both env-var (ENABLE_FINEGRAINED_QUOTAS=false) and DynamoDB-backed paths

"""Tests for quota_check Lambda daily enforcement (block vs alert)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


LAMBDA_PATH = (
    Path(__file__).resolve().parents[2]
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
    / "quota_check"
    / "index.py"
)


def _load_quota_check(env: dict) -> object:
    """Load the quota_check Lambda module fresh with the given environment.

    The module reads env vars at import time, so we must reload it after
    setting environment variables.
    """
    # Apply env vars before module import
    for key, value in env.items():
        os.environ[key] = value

    # Force a fresh import each time so module-level env reads take effect
    module_name = f"quota_check_index_{id(env)}"
    spec = importlib.util.spec_from_file_location(module_name, LAMBDA_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _build_event(email: str = "user@example.com", groups: list[str] | None = None) -> dict:
    claims: dict = {"email": email}
    if groups is not None:
        claims["groups"] = groups
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


def _parse(response: dict) -> dict:
    return json.loads(response["body"])


@pytest.fixture
def base_env():
    """Minimal env vars common to all tests."""
    return {
        "QUOTA_TABLE": "TestQuotaTable",
        "POLICIES_TABLE": "TestPoliciesTable",
        "MISSING_EMAIL_ENFORCEMENT": "block",
        "ERROR_HANDLING_MODE": "fail_closed",
    }


# ---------------------------------------------------------------------------
# Env-var path: ENABLE_FINEGRAINED_QUOTAS=false
# ---------------------------------------------------------------------------


class TestDailyEnforcementEnvVarPath:
    """ENABLE_FINEGRAINED_QUOTAS=false -> policy comes from env vars."""

    def _make_module(self, base_env, daily_mode: str):
        env = {
            **base_env,
            "ENABLE_FINEGRAINED_QUOTAS": "false",
            "MONTHLY_TOKEN_LIMIT": "1000",
            "DAILY_TOKEN_LIMIT": "100",
            "MONTHLY_ENFORCEMENT_MODE": "block",
            "DAILY_ENFORCEMENT_MODE": daily_mode,
        }
        return _load_quota_check(env)

    def _patch_usage_and_unblock(self, mod, daily_tokens: int, monthly_tokens: int = 0):
        mod.quota_table = MagicMock()
        # First call = unblock status (no item), second call = monthly usage
        mod.quota_table.get_item.side_effect = [
            {},  # no unblock entry
            {
                "Item": {
                    "total_tokens": monthly_tokens,
                    "daily_tokens": daily_tokens,
                    "daily_date": mod.datetime.now(mod.timezone.utc).strftime("%Y-%m-%d"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                }
            },
        ]

    def test_daily_block_mode_blocks_when_exceeded(self, base_env):
        mod = self._make_module(base_env, daily_mode="block")
        self._patch_usage_and_unblock(mod, daily_tokens=150)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is False
        assert body["reason"] == "daily_exceeded"

    def test_daily_alert_mode_allows_when_exceeded(self, base_env):
        mod = self._make_module(base_env, daily_mode="alert")
        self._patch_usage_and_unblock(mod, daily_tokens=150)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True
        assert body["reason"] == "within_quota"

    def test_daily_block_mode_allows_under_limit(self, base_env):
        mod = self._make_module(base_env, daily_mode="block")
        self._patch_usage_and_unblock(mod, daily_tokens=50)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True


# ---------------------------------------------------------------------------
# DynamoDB path: ENABLE_FINEGRAINED_QUOTAS=true
# ---------------------------------------------------------------------------


class TestDailyEnforcementFineGrainedPath:
    """ENABLE_FINEGRAINED_QUOTAS=true -> policy comes from DynamoDB.

    These tests cover the bug where get_policy() did not include
    daily_enforcement_mode in its returned dict, causing daily block mode
    to be silently downgraded to alert.
    """

    def _make_module(self, base_env):
        env = {
            **base_env,
            "ENABLE_FINEGRAINED_QUOTAS": "true",
        }
        return _load_quota_check(env)

    def _setup_mocks(
        self,
        mod,
        policy_item: dict,
        daily_tokens: int,
        monthly_tokens: int = 0,
    ):
        # policies_table: user policy hit
        mod.policies_table = MagicMock()
        mod.policies_table.get_item.return_value = {"Item": policy_item}

        # quota_table: no unblock, then monthly usage row
        mod.quota_table = MagicMock()
        mod.quota_table.get_item.side_effect = [
            {},  # unblock lookup
            {
                "Item": {
                    "total_tokens": monthly_tokens,
                    "daily_tokens": daily_tokens,
                    "daily_date": mod.datetime.now(mod.timezone.utc).strftime("%Y-%m-%d"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                }
            },
        ]

    def test_get_policy_returns_daily_enforcement_mode(self, base_env):
        """get_policy() must include daily_enforcement_mode from DynamoDB."""
        mod = self._make_module(base_env)
        mod.policies_table = MagicMock()
        mod.policies_table.get_item.return_value = {
            "Item": {
                "policy_type": "user",
                "identifier": "user@example.com",
                "monthly_token_limit": 1000,
                "daily_token_limit": 100,
                "warning_threshold_80": 800,
                "warning_threshold_90": 900,
                "enforcement_mode": "block",
                "daily_enforcement_mode": "block",
                "enabled": True,
            }
        }

        policy = mod.get_policy("user", "user@example.com")
        assert policy is not None
        assert policy["daily_enforcement_mode"] == "block"

    def test_get_policy_defaults_daily_enforcement_mode_to_alert(self, base_env):
        """When DynamoDB item omits the field, default to 'alert'."""
        mod = self._make_module(base_env)
        mod.policies_table = MagicMock()
        mod.policies_table.get_item.return_value = {
            "Item": {
                "policy_type": "user",
                "identifier": "user@example.com",
                "monthly_token_limit": 1000,
                "daily_token_limit": 100,
                "warning_threshold_80": 800,
                "warning_threshold_90": 900,
                "enforcement_mode": "block",
                "enabled": True,
                # daily_enforcement_mode intentionally omitted
            }
        }

        policy = mod.get_policy("user", "user@example.com")
        assert policy["daily_enforcement_mode"] == "alert"

    def test_finegrained_daily_block_mode_blocks_when_exceeded(self, base_env):
        """Regression: daily_enforcement_mode='block' from DynamoDB must block."""
        mod = self._make_module(base_env)
        self._setup_mocks(
            mod,
            policy_item={
                "policy_type": "user",
                "identifier": "user@example.com",
                "monthly_token_limit": 1000,
                "daily_token_limit": 100,
                "warning_threshold_80": 800,
                "warning_threshold_90": 900,
                "enforcement_mode": "block",
                "daily_enforcement_mode": "block",
                "enabled": True,
            },
            daily_tokens=150,
        )

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is False
        assert body["reason"] == "daily_exceeded"

    def test_finegrained_daily_alert_mode_allows_when_exceeded(self, base_env):
        mod = self._make_module(base_env)
        self._setup_mocks(
            mod,
            policy_item={
                "policy_type": "user",
                "identifier": "user@example.com",
                "monthly_token_limit": 1000,
                "daily_token_limit": 100,
                "warning_threshold_80": 800,
                "warning_threshold_90": 900,
                "enforcement_mode": "block",
                "daily_enforcement_mode": "alert",
                "enabled": True,
            },
            daily_tokens=150,
        )

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True
        assert body["reason"] == "within_quota"

    def test_finegrained_missing_daily_mode_defaults_to_alert(self, base_env):
        """If the DynamoDB item omits daily_enforcement_mode, treat as 'alert'."""
        mod = self._make_module(base_env)
        self._setup_mocks(
            mod,
            policy_item={
                "policy_type": "user",
                "identifier": "user@example.com",
                "monthly_token_limit": 1000,
                "daily_token_limit": 100,
                "warning_threshold_80": 800,
                "warning_threshold_90": 900,
                "enforcement_mode": "block",
                "enabled": True,
                # daily_enforcement_mode missing
            },
            daily_tokens=150,
        )

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True
        assert body["reason"] == "within_quota"
