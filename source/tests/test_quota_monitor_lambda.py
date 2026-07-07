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


class TestCostEstimateTokenTypes:
    """Regression: cost must price all four token types, including cacheCreation.

    The metric's `type` dimension is camelCase (input/output/cacheRead/
    cacheCreation) but the rate tables use snake_case keys (input/output/
    cache_read/cache_write). The old code only rewrote cacheRead->cache_read, so
    cacheCreation looked up a non-existent key and priced at $0 — dropping the
    cache-write share of the cost, which is usually the majority of tokens.
    """

    def _run_cost(self, mod, type_model_vector):
        """Drive fetch_usage_from_promql with a canned type+model breakdown.

        Only the (user.email, type, model) query returns data; the primary
        total, type-only, and CoWork queries return empty so we isolate the
        cost calculation. Returns the users dict.
        """

        def fake_query(query, time_param=None):
            if ", type, model)" in query and "claude_code.token.usage" in query:
                return type_model_vector
            return []

        mod._promql_query = fake_query
        return mod.fetch_usage_from_promql()

    def test_cache_creation_is_priced(self, base_env):
        """A cacheCreation-only breakdown must produce a non-zero cost."""
        mod = _load_quota_monitor(base_env)
        # opus cache_write rate = 6.25 / 1M tokens; 1,000,000 tokens -> $6.25
        vector = [
            {
                "metric": {"user.email": "a@b.com", "type": "cacheCreation", "model": "claude-opus-4-8"},
                "value": [0, "1000000"],
            }
        ]
        users = self._run_cost(mod, vector)
        assert users["a@b.com"]["cost_usd"] == pytest.approx(6.25)

    def test_all_four_types_priced(self, base_env):
        """input/output/cacheRead/cacheCreation each contribute to the cost."""
        mod = _load_quota_monitor(base_env)
        # opus rates per 1M: input 5.00, output 25.00, cache_read 0.50, cache_write 6.25
        vector = [
            {"metric": {"user.email": "a@b.com", "type": "input", "model": "claude-opus-4-8"}, "value": [0, "1000000"]},
            {
                "metric": {"user.email": "a@b.com", "type": "output", "model": "claude-opus-4-8"},
                "value": [0, "1000000"],
            },
            {
                "metric": {"user.email": "a@b.com", "type": "cacheRead", "model": "claude-opus-4-8"},
                "value": [0, "1000000"],
            },
            {
                "metric": {"user.email": "a@b.com", "type": "cacheCreation", "model": "claude-opus-4-8"},
                "value": [0, "1000000"],
            },
        ]
        users = self._run_cost(mod, vector)
        assert users["a@b.com"]["cost_usd"] == pytest.approx(5.00 + 25.00 + 0.50 + 6.25)


class TestPromQLAggregationFunction:
    """Regression: token.usage is a Counter exported with DELTA temporality.

    increase() assumes cumulative temporality and misreads the delta sawtooth's
    down-steps as counter resets, returning empty/understated results. That froze
    the DynamoDB row and surfaced as "Daily Tokens: 0" in `ccwb quota usage` while
    Athena/CloudWatch (which sum the deltas) stayed correct. Aggregation MUST use
    sum_over_time(). The existing tests mock fetch_usage_from_promql out entirely,
    so the query construction — where the bug lived — was never exercised.
    """

    def _capture_queries(self, mod, primary_total="531643"):
        """Monkeypatch _promql_query to record every query string it receives.

        Returns the list that accumulates the queries. Only the primary
        per-user total query gets a non-empty vector so the aggregation has
        something to fold in; the rest return empty so cost/CoWork paths no-op.
        """
        captured = []

        def fake_query(query, time_param=None):
            captured.append(query)
            is_primary = 'sum by ("user.email")' in query and ", type" not in query and ", model" not in query
            if is_primary and "claude_code.token.usage" in query:
                return [{"metric": {"user.email": "a@b.com"}, "value": [0, primary_total]}]
            return []

        mod._promql_query = fake_query
        return captured

    def test_claude_code_queries_use_sum_over_time_not_increase(self, base_env):
        mod = _load_quota_monitor(base_env)
        captured = self._capture_queries(mod)

        mod.fetch_usage_from_promql()

        cc_queries = [q for q in captured if "claude_code.token.usage" in q]
        assert cc_queries, "expected at least one claude_code.token.usage query"
        for q in cc_queries:
            assert "sum_over_time(" in q, f"delta metric must use sum_over_time: {q}"
            assert "increase(" not in q, f"increase() is wrong for a delta metric: {q}"

    def test_cowork_queries_use_sum_over_time_not_increase(self, base_env):
        mod = _load_quota_monitor(base_env)
        captured = self._capture_queries(mod)

        mod.fetch_usage_from_promql()

        cowork_queries = [q for q in captured if "ClaudeCoWork" in q]
        assert cowork_queries, "expected CoWork token.usage queries"
        for q in cowork_queries:
            assert "sum_over_time(" in q, f"CoWork delta metric must use sum_over_time: {q}"
            assert "increase(" not in q, f"increase() is wrong for a delta metric: {q}"

    def test_aggregated_total_flows_through(self, base_env):
        """A non-empty primary vector must be recorded (not skipped as delta<=0)."""
        mod = _load_quota_monitor(base_env)
        self._capture_queries(mod, primary_total="531643")

        users = mod.fetch_usage_from_promql()

        assert users.get("a@b.com", {}).get("total_tokens") == 531643
