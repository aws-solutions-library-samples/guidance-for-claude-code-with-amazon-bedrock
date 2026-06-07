# ABOUTME: Tests for shared pricing utility and cost estimator logic
# ABOUTME: Validates pricing rates, model family extraction, and cost calculation

"""Tests for cost estimator and shared pricing utility."""

import json
import os
import sys
from unittest.mock import patch

import pytest

# Add lambda-functions to path for imports
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "deployment", "infrastructure", "lambda-functions"
))

from shared.pricing import (
    DEFAULT_RATES,
    calculate_cost,
    get_model_family,
    get_pricing_rates,
)


class TestGetModelFamily:
    """Tests for model family extraction from Bedrock model IDs."""

    def test_opus_standard(self):
        assert get_model_family("anthropic.claude-opus-4-8-20260301-v1:0") == "opus"

    def test_opus_cross_region(self):
        assert get_model_family("us.anthropic.claude-opus-4-8-20260301-v1:0") == "opus"

    def test_sonnet_standard(self):
        assert get_model_family("anthropic.claude-sonnet-4-6-20250514-v1:0") == "sonnet"

    def test_haiku_standard(self):
        assert get_model_family("anthropic.claude-haiku-4-5-20250901-v1:0") == "haiku"

    def test_short_model_name(self):
        assert get_model_family("claude-sonnet-4-6") == "sonnet"

    def test_unknown_defaults_to_sonnet(self):
        assert get_model_family("some-unknown-model") == "sonnet"

    def test_case_insensitive(self):
        assert get_model_family("ANTHROPIC.CLAUDE-OPUS-4-8") == "opus"


class TestGetPricingRates:
    """Tests for pricing rate loading with override support."""

    def test_default_rates_returned(self):
        with patch.dict(os.environ, {}, clear=True):
            rates = get_pricing_rates()
            assert rates["opus"]["input"] == 5.00
            assert rates["sonnet"]["output"] == 15.00
            assert rates["haiku"]["cache_read"] == 0.10

    def test_override_via_env_var(self):
        override = json.dumps({"opus": {"input": 10.00}})
        with patch.dict(os.environ, {"BEDROCK_PRICING_RATES_JSON": override}):
            rates = get_pricing_rates()
            assert rates["opus"]["input"] == 10.00
            # Other rates unchanged
            assert rates["opus"]["output"] == 25.00
            assert rates["sonnet"]["input"] == 3.00

    def test_invalid_json_falls_back_to_defaults(self):
        with patch.dict(os.environ, {"BEDROCK_PRICING_RATES_JSON": "not json"}):
            rates = get_pricing_rates()
            assert rates == DEFAULT_RATES

    def test_empty_env_var_uses_defaults(self):
        with patch.dict(os.environ, {"BEDROCK_PRICING_RATES_JSON": ""}):
            rates = get_pricing_rates()
            assert rates == DEFAULT_RATES

    def test_custom_family_added(self):
        override = json.dumps({"custom_model": {"input": 2.0, "output": 8.0}})
        with patch.dict(os.environ, {"BEDROCK_PRICING_RATES_JSON": override}):
            rates = get_pricing_rates()
            assert rates["custom_model"]["input"] == 2.0
            # Defaults still present
            assert "sonnet" in rates


class TestCalculateCost:
    """Tests for cost calculation with per-token-type rates."""

    def test_basic_calculation(self):
        tokens = {"input": 1_000_000, "output": 1_000_000}
        # Sonnet: input=$3/MTok, output=$15/MTok → $3 + $15 = $18
        cost = calculate_cost(tokens, "sonnet")
        assert cost == pytest.approx(18.0)

    def test_cache_reads_are_cheap(self):
        tokens = {"cache_read": 10_000_000}
        # Sonnet cache_read: $0.30/MTok → 10 × $0.30 = $3.00
        cost = calculate_cost(tokens, "sonnet")
        assert cost == pytest.approx(3.0)

    def test_cache_reads_vs_input_ratio(self):
        """Cache reads should be 10x cheaper than input for same volume."""
        input_cost = calculate_cost({"input": 1_000_000}, "sonnet")
        cache_cost = calculate_cost({"cache_read": 1_000_000}, "sonnet")
        assert input_cost / cache_cost == pytest.approx(10.0)

    def test_realistic_session(self):
        """Realistic Claude Code session: 23K input, 125K output, 1.3M cache_write, 15.5M cache_read."""
        tokens = {
            "input": 23_000,
            "output": 125_000,
            "cache_write": 1_300_000,
            "cache_read": 15_500_000,
        }
        # Sonnet rates: 23K×$3 + 125K×$15 + 1.3M×$3.75 + 15.5M×$0.30 (all per MTok)
        # = $0.069 + $1.875 + $4.875 + $4.65 = $11.469
        cost = calculate_cost(tokens, "sonnet")
        assert cost == pytest.approx(11.469, rel=0.01)

    def test_opus_is_more_expensive(self):
        tokens = {"input": 1_000_000}
        sonnet_cost = calculate_cost(tokens, "sonnet")
        opus_cost = calculate_cost(tokens, "opus")
        assert opus_cost > sonnet_cost

    def test_empty_tokens(self):
        cost = calculate_cost({}, "sonnet")
        assert cost == 0.0

    def test_custom_rates(self):
        custom_rates = {"sonnet": {"input": 100.0, "output": 200.0}}
        cost = calculate_cost({"input": 1_000_000}, "sonnet", rates=custom_rates)
        assert cost == pytest.approx(100.0)

    def test_unknown_token_type_uses_input_rate(self):
        """Unknown token types fall back to input rate."""
        tokens = {"unknown_type": 1_000_000}
        cost = calculate_cost(tokens, "sonnet")
        # Falls back to input rate: $3.00/MTok
        assert cost == pytest.approx(3.0)
