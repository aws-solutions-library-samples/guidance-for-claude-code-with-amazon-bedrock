# ABOUTME: Tests for cost-based quota enforcement mode
# ABOUTME: Validates the _calculate_usage_cost function and cost-mode limit checking

"""Tests for cost-based quota enforcement (#208 follow-up)."""

import os
import sys

import pytest

# Add lambda-functions to path
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "deployment", "infrastructure", "lambda-functions"
))

from quota_check.index import _calculate_usage_cost


class TestCalculateUsageCost:
    """Tests for converting DynamoDB usage data to USD cost."""

    def test_basic_sonnet_cost(self):
        """Input-only usage at Sonnet rates."""
        usage = {
            "total_tokens": 1_000_000,
            "daily_tokens": 500_000,
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_tokens": 0,
        }
        result = _calculate_usage_cost(usage, "sonnet")
        # 1M input × $3/MTok = $3.00
        assert result["monthly_cost"] == pytest.approx(3.0, rel=0.01)

    def test_mixed_token_types(self):
        """Realistic mix of token types."""
        usage = {
            "total_tokens": 17_000_000,  # input + output + cache_write + cache_read
            "daily_tokens": 17_000_000,
            "input_tokens": 23_000,
            "output_tokens": 125_000,
            "cache_tokens": 15_500_000,  # cache_read
            # cache_write derived: 17M - 23K - 125K - 15.5M = 1.352M
        }
        result = _calculate_usage_cost(usage, "sonnet")
        # 23K×$3 + 125K×$15 + 15.5M×$0.30 + 1.352M×$3.75 (all per MTok)
        # = $0.069 + $1.875 + $4.65 + $5.07 = $11.664
        assert result["monthly_cost"] == pytest.approx(11.664, rel=0.05)

    def test_cache_heavy_usage_is_cheap(self):
        """Cache-dominated usage should be much cheaper than raw token count suggests."""
        usage = {
            "total_tokens": 16_000_000,
            "daily_tokens": 16_000_000,
            "input_tokens": 100_000,
            "output_tokens": 100_000,
            "cache_tokens": 15_800_000,  # 99% cache reads
        }
        result = _calculate_usage_cost(usage, "sonnet")
        # If all were input-priced: 16M × $3 = $48
        # Actual: 100K×$3 + 100K×$15 + 15.8M×$0.30 + 0 cache_write
        # = $0.30 + $1.50 + $4.74 = $6.54
        assert result["monthly_cost"] < 10.0  # Much less than $48

    def test_zero_usage(self):
        """Zero tokens = zero cost."""
        usage = {
            "total_tokens": 0,
            "daily_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
        }
        result = _calculate_usage_cost(usage, "sonnet")
        assert result["monthly_cost"] == 0.0
        assert result["daily_cost"] == 0.0

    def test_daily_cost_proportional(self):
        """Daily cost is proportional to daily/monthly token ratio."""
        usage = {
            "total_tokens": 10_000_000,
            "daily_tokens": 1_000_000,  # 10% of monthly
            "input_tokens": 10_000_000,
            "output_tokens": 0,
            "cache_tokens": 0,
        }
        result = _calculate_usage_cost(usage, "sonnet")
        assert result["daily_cost"] == pytest.approx(result["monthly_cost"] * 0.1, rel=0.01)

    def test_opus_more_expensive(self):
        """Same usage should cost more on Opus than Sonnet."""
        usage = {
            "total_tokens": 1_000_000,
            "daily_tokens": 1_000_000,
            "input_tokens": 500_000,
            "output_tokens": 500_000,
            "cache_tokens": 0,
        }
        sonnet_result = _calculate_usage_cost(usage, "sonnet")
        opus_result = _calculate_usage_cost(usage, "opus")
        assert opus_result["monthly_cost"] > sonnet_result["monthly_cost"]

    def test_negative_cache_write_clamped_to_zero(self):
        """If token counts are inconsistent, cache_write derivation won't go negative."""
        usage = {
            "total_tokens": 100_000,  # Less than sum of parts (inconsistent data)
            "daily_tokens": 100_000,
            "input_tokens": 50_000,
            "output_tokens": 50_000,
            "cache_tokens": 50_000,  # Sum = 150K > total
        }
        result = _calculate_usage_cost(usage, "sonnet")
        # Should not raise, cache_write = max(0, 100K-50K-50K-50K) = 0
        assert result["monthly_cost"] >= 0


class TestTokenModeUnchanged:
    """Regression tests: token mode behavior must not change."""

    def test_quota_mode_defaults_to_token(self):
        """QUOTA_MODE defaults to 'token' when not set."""
        from quota_check.index import QUOTA_MODE
        # In test environment, env var isn't set → should be 'token'
        assert QUOTA_MODE == "token"

    def test_cost_limits_default_to_zero(self):
        """Cost limits default to 0 (disabled) so token mode isn't affected."""
        from quota_check.index import MONTHLY_COST_LIMIT, DAILY_COST_LIMIT
        assert MONTHLY_COST_LIMIT == 0
        assert DAILY_COST_LIMIT == 0
