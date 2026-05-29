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


# ---------------------------------------------------------------------------
# Contract tests: response schema validation
# ---------------------------------------------------------------------------


# Required keys in every quota_check response body
RESPONSE_REQUIRED_KEYS = {"allowed"}

# Keys expected when a quota policy exists and user is within quota
NORMAL_RESPONSE_KEYS = {
    "allowed", "reason", "enforcement_mode", "usage", "policy", "unblock_status", "message"
}

# Valid values for 'reason' field
VALID_REASONS = {
    "within_quota", "monthly_exceeded", "daily_exceeded",
    "no_policy", "no_email", "unblocked", "missing_email_claim",
}

# Valid values for 'enforcement_mode' field
VALID_ENFORCEMENT_MODES = {"alert", "block", None}


class TestResponseSchemaContract:
    """Contract tests ensuring quota_check Lambda responses conform to expected schema.

    The credential-process binary parses these responses. If the schema changes,
    credential-process breaks silently (users get blocked or allowed incorrectly).
    These tests ensure both sides agree on the contract.
    """

    def _make_module(self, base_env, **overrides):
        env = {
            **base_env,
            "ENABLE_FINEGRAINED_QUOTAS": "false",
            "MONTHLY_TOKEN_LIMIT": "1000",
            "DAILY_TOKEN_LIMIT": "100",
            "MONTHLY_ENFORCEMENT_MODE": "block",
            "DAILY_ENFORCEMENT_MODE": "block",
            **overrides,
        }
        return _load_quota_check(env)

    def _patch_usage(self, mod, daily_tokens: int = 0, monthly_tokens: int = 0):
        mod.quota_table = MagicMock()
        mod.quota_table.get_item.side_effect = [
            {},  # unblock
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

    def test_response_is_valid_json_with_status_code(self, base_env):
        """Lambda returns dict with statusCode and JSON-parseable body."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        response = mod.lambda_handler(_build_event(), None)
        assert "statusCode" in response
        assert "body" in response
        assert isinstance(response["statusCode"], int)
        body = json.loads(response["body"])
        assert isinstance(body, dict)

    def test_allowed_response_has_required_keys(self, base_env):
        """When allowed=True, response includes all expected keys."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True
        for key in NORMAL_RESPONSE_KEYS:
            assert key in body, f"Missing key '{key}' in allowed response"

    def test_blocked_response_has_required_keys(self, base_env):
        """When allowed=False, response includes all expected keys."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=150)  # exceeds 100 limit

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is False
        for key in NORMAL_RESPONSE_KEYS:
            assert key in body, f"Missing key '{key}' in blocked response"

    def test_reason_field_is_valid_enum(self, base_env):
        """'reason' field uses a known value."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["reason"] in VALID_REASONS, f"Unknown reason: {body['reason']}"

    def test_enforcement_mode_is_valid(self, base_env):
        """'enforcement_mode' is alert, block, or None."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["enforcement_mode"] in VALID_ENFORCEMENT_MODES

    def test_usage_summary_structure(self, base_env):
        """'usage' field contains expected token count keys."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=50, monthly_tokens=200)

        body = _parse(mod.lambda_handler(_build_event(), None))
        usage = body["usage"]
        assert usage is not None
        assert "monthly_tokens" in usage
        assert "monthly_limit" in usage
        assert "monthly_percent" in usage
        assert "daily_tokens" in usage
        assert "daily_limit" in usage

    def test_policy_field_structure(self, base_env):
        """'policy' field contains type and identifier."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        policy = body["policy"]
        assert policy is not None
        assert "type" in policy
        assert "identifier" in policy

    def test_unblock_status_structure(self, base_env):
        """'unblock_status' field contains is_unblocked boolean."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert "unblock_status" in body
        assert "is_unblocked" in body["unblock_status"]
        assert isinstance(body["unblock_status"]["is_unblocked"], bool)

    def test_message_field_is_string(self, base_env):
        """'message' field is always a human-readable string."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, daily_tokens=0)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0

    def test_monthly_exceeded_sets_reason_correctly(self, base_env):
        """Monthly limit exceeded returns reason='monthly_exceeded'."""
        mod = self._make_module(base_env)
        self._patch_usage(mod, monthly_tokens=1500)  # exceeds 1000 limit

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is False
        assert body["reason"] == "monthly_exceeded"

    def test_no_policy_response(self, base_env):
        """When MONTHLY_TOKEN_LIMIT=0 (disabled), returns no_policy."""
        mod = self._make_module(base_env, MONTHLY_TOKEN_LIMIT="0", DAILY_TOKEN_LIMIT="0")
        self._patch_usage(mod)

        body = _parse(mod.lambda_handler(_build_event(), None))
        assert body["allowed"] is True
        assert body["reason"] == "no_policy"


class TestInputValidationContract:
    """Contract tests for input handling — ensures malformed requests don't crash."""

    def _make_module(self, base_env):
        env = {
            **base_env,
            "ENABLE_FINEGRAINED_QUOTAS": "false",
            "MONTHLY_TOKEN_LIMIT": "1000",
            "DAILY_TOKEN_LIMIT": "100",
            "MONTHLY_ENFORCEMENT_MODE": "block",
            "DAILY_ENFORCEMENT_MODE": "block",
        }
        return _load_quota_check(env)

    def test_missing_email_claim(self, base_env):
        """Request with no email in JWT claims returns structured response."""
        mod = self._make_module(base_env)
        event = {"requestContext": {"authorizer": {"jwt": {"claims": {}}}}}

        response = mod.lambda_handler(event, None)
        assert response["statusCode"] == 200
        body = _parse(response)
        assert "allowed" in body
        assert body.get("reason") == "missing_email_claim"

    def test_missing_authorizer_context(self, base_env):
        """Request with no authorizer context does not crash."""
        mod = self._make_module(base_env)
        event = {"requestContext": {}}

        response = mod.lambda_handler(event, None)
        assert response["statusCode"] == 200
        body = _parse(response)
        assert "allowed" in body

    def test_empty_event(self, base_env):
        """Completely empty event does not crash the Lambda."""
        mod = self._make_module(base_env)

        response = mod.lambda_handler({}, None)
        assert response["statusCode"] == 200
        body = _parse(response)
        assert "allowed" in body

    def test_missing_email_blocked_by_default(self, base_env):
        """Missing email defaults to blocked (fail-closed security)."""
        env = {**base_env, "MISSING_EMAIL_ENFORCEMENT": "block"}
        mod = _load_quota_check({
            **env,
            "ENABLE_FINEGRAINED_QUOTAS": "false",
            "MONTHLY_TOKEN_LIMIT": "1000",
            "DAILY_TOKEN_LIMIT": "100",
            "MONTHLY_ENFORCEMENT_MODE": "block",
            "DAILY_ENFORCEMENT_MODE": "block",
        })
        event = {"requestContext": {"authorizer": {"jwt": {"claims": {}}}}}

        body = _parse(mod.lambda_handler(event, None))
        assert body["allowed"] is False
