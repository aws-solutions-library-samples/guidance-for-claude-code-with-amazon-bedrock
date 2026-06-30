# ABOUTME: Tests for the quota_monitor Lambda's stale-day guard on the daily counter
# ABOUTME: Idle users whose daily_date is not today must not re-alert as "daily exceeded"

"""Tests for quota_monitor daily stale-day reset in the threshold/alert step.

Regression: an idle user's daily_tokens froze above the daily limit and a fresh
"Daily Token Quota EXCEEDED" alert went out every new UTC day, because the
threshold step read daily_tokens verbatim (without the stale-day guard that
quota_check already applies).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

LAMBDA_PATH = (
    Path(__file__).resolve().parents[2]
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
    / "quota_monitor"
    / "index.py"
)


def _load_quota_monitor(env: dict) -> object:
    """Load the quota_monitor Lambda module fresh with the given environment."""
    for key, value in env.items():
        os.environ[key] = value

    module_name = f"quota_monitor_index_{id(env)}"
    spec = importlib.util.spec_from_file_location(module_name, LAMBDA_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def base_env():
    return {
        "QUOTA_TABLE": "TestQuotaTable",
        "POLICIES_TABLE": "TestPoliciesTable",
        "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test-alerts",
        "ENABLE_FINEGRAINED_QUOTAS": "false",
        "MONTHLY_TOKEN_LIMIT": "40000000",
    }


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _scan_response(items: list[dict]) -> dict:
    """A single-page DynamoDB scan response (no LastEvaluatedKey)."""
    return {"Items": items}


def _patch_monitor(mod, scan_item: dict, daily_token_limit: int = 2_000_000):
    """Wire the monitor so it skips PromQL/update and scans a single user row.

    Returns the MagicMock SNS client for assertions on published alerts.
    """
    # No new activity -> update step is a no-op and daily reset never happens
    # via update_quota_metrics (this is the idle-user condition).
    mod.fetch_usage_from_promql = MagicMock(return_value={})

    mod.quota_table = MagicMock()
    mod.quota_table.scan.return_value = _scan_response([scan_item])
    # get_sent_alerts issues a query; return no prior alerts.
    mod.quota_table.query.return_value = {"Items": []}

    # Force the env-var policy to carry a daily limit so daily checks run.
    base_policy = {
        "policy_type": "default",
        "identifier": "environment",
        "monthly_token_limit": 40_000_000,
        "daily_token_limit": daily_token_limit,
        "warning_threshold_80": 32_000_000,
        "warning_threshold_90": 36_000_000,
        "enforcement_mode": "alert",
        "enabled": True,
    }
    mod.resolve_user_quota = MagicMock(return_value=base_policy)

    mod.sns_client = MagicMock()
    return mod.sns_client


def _daily_alert_published(sns_client) -> bool:
    """True if any SNS publish call carried a Daily Token Quota alert."""
    for call in sns_client.publish.call_args_list:
        subject = call.kwargs.get("Subject", "")
        if "Daily Token Quota" in subject:
            return True
    return False


class TestStaleDailyReset:
    def test_idle_user_stale_day_no_daily_alert(self, base_env):
        """daily_date=yesterday + daily_tokens over limit + no activity -> no alert."""
        mod = _load_quota_monitor(base_env)
        sns = _patch_monitor(
            mod,
            scan_item={
                "email": "idle.user@example.com",
                "total_tokens": 3_355_533,
                "daily_tokens": 3_355_533,  # frozen, above 2,000,000 limit
                "daily_date": _yesterday(),
            },
        )

        result = mod.lambda_handler({}, None)
        assert result["statusCode"] == 200
        assert not _daily_alert_published(sns), "stale daily counter must not re-alert"

    def test_active_user_same_day_over_limit_still_alerts(self, base_env):
        """daily_date=today + over limit -> daily alert IS generated (no over-correction)."""
        mod = _load_quota_monitor(base_env)
        sns = _patch_monitor(
            mod,
            scan_item={
                "email": "active.user@example.com",
                "total_tokens": 3_355_533,
                "daily_tokens": 3_355_533,  # above 2,000,000 limit, today
                "daily_date": _today(),
            },
        )

        result = mod.lambda_handler({}, None)
        assert result["statusCode"] == 200
        assert _daily_alert_published(sns), "genuine same-day over-limit must still alert"

    def test_build_usage_entry_zeros_stale_daily(self, base_env):
        """_build_usage_entry applies the stale-day guard; monthly is untouched."""
        mod = _load_quota_monitor(base_env)
        item = {
            "email": "idle.user@example.com",
            "total_tokens": 3_355_533,
            "daily_tokens": 3_355_533,
            "daily_date": _yesterday(),
        }
        entry = mod._build_usage_entry(item, _today())
        assert entry["daily_tokens"] == 0
        assert entry["total_tokens"] == 3_355_533

    def test_build_usage_entry_keeps_same_day_daily(self, base_env):
        mod = _load_quota_monitor(base_env)
        item = {
            "email": "active.user@example.com",
            "total_tokens": 3_355_533,
            "daily_tokens": 3_355_533,
            "daily_date": _today(),
        }
        entry = mod._build_usage_entry(item, _today())
        assert entry["daily_tokens"] == 3_355_533
