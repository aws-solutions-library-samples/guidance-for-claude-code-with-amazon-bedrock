"""
Shared Bedrock pricing utility for Claude Code with Bedrock.

Provides per-model, per-token-type pricing rates. Used by:
- Cost estimator Lambda (dashboard cost metrics)
- Quota Lambda (cost-based enforcement mode)

Pricing is hardcoded with the ability to override via environment variable
or CF parameter. This is more reliable than the AWS Pricing API which has
poor filter support for Bedrock models and delayed updates.
"""

import json
import os

# Current Bedrock pricing per 1M tokens (USD) — as of June 2026
# Source: https://aws.amazon.com/bedrock/pricing/
DEFAULT_RATES = {
    "opus": {
        "input": 5.00,
        "output": 25.00,
        "cache_read": 0.50,
        "cache_write": 6.25,
    },
    "sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "haiku": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
}

# Environment variable for overriding rates (JSON string)
PRICING_OVERRIDE_ENV = "BEDROCK_PRICING_RATES_JSON"


def get_pricing_rates() -> dict:
    """Get per-model, per-token-type pricing rates ($/MTok).

    Checks BEDROCK_PRICING_RATES_JSON env var for overrides,
    falls back to hardcoded DEFAULT_RATES.

    Returns:
        dict: {family: {input: float, output: float, cache_read: float, cache_write: float}}
    """
    override = os.environ.get(PRICING_OVERRIDE_ENV, "").strip()
    if override:
        try:
            custom_rates = json.loads(override)
            # Merge with defaults (custom rates override per-family)
            merged = dict(DEFAULT_RATES)
            for family, rates in custom_rates.items():
                if family in merged:
                    merged[family].update(rates)
                else:
                    merged[family] = rates
            return merged
        except (json.JSONDecodeError, TypeError, AttributeError):
            # Invalid JSON — fall back to defaults
            pass

    return dict(DEFAULT_RATES)


# Cross-region inference surcharge multiplier
# Models invoked via cross-region inference profiles (us.anthropic.*, eu.anthropic.*)
# incur a 10% surcharge over standard regional pricing.
CROSS_REGION_MULTIPLIER = 1.1


def get_model_family(model_id: str) -> str:
    """Extract model family from a Bedrock model ID or CRIS profile.

    Examples:
        "anthropic.claude-sonnet-4-6-20250514-v1:0" → "sonnet"
        "us.anthropic.claude-opus-4-8-20260301-v1:0" → "opus"
        "anthropic.claude-haiku-4-5-20250901-v1:0" → "haiku"
        "claude-sonnet-4-6" → "sonnet"
    """
    model_lower = model_id.lower()
    if "opus" in model_lower:
        return "opus"
    elif "haiku" in model_lower:
        return "haiku"
    else:
        # Default to sonnet (most common model)
        return "sonnet"


def is_cross_region(model_id: str) -> bool:
    """Determine if a model ID is a cross-region inference profile.

    Cross-region profiles are prefixed with a region code:
        us.anthropic.claude-*  (US cross-region)
        eu.anthropic.claude-*  (EU cross-region)

    Standard regional models start with:
        anthropic.claude-*
    """
    model_lower = model_id.lower()
    # Cross-region profiles have a geo prefix before 'anthropic'
    return bool(
        model_lower.startswith(("us.", "eu.", "ap."))
        and "anthropic" in model_lower
    )


def calculate_cost(tokens_by_type: dict, model_family: str, rates: dict = None,
                   model_id: str = None) -> float:
    """Calculate cost in USD for a set of token counts by type.

    Args:
        tokens_by_type: {token_type: count} e.g. {"input": 1000, "output": 500, ...}
        model_family: "opus", "sonnet", or "haiku"
        rates: pricing rates dict (default: get_pricing_rates())
        model_id: optional full model ID — used to detect cross-region surcharge

    Returns:
        Estimated cost in USD (includes cross-region surcharge if applicable)
    """
    if rates is None:
        rates = get_pricing_rates()

    family_rates = rates.get(model_family, rates.get("sonnet", {}))
    total_cost = 0.0

    for token_type, count in tokens_by_type.items():
        rate_per_mtok = family_rates.get(token_type, family_rates.get("input", 3.0))
        total_cost += (count / 1_000_000) * rate_per_mtok

    # Apply cross-region inference surcharge (10%) if applicable
    if model_id and is_cross_region(model_id):
        total_cost *= CROSS_REGION_MULTIPLIER

    return total_cost
