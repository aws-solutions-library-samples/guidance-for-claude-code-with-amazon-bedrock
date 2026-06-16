# ABOUTME: Reference persona definitions (engineering, sales) seeded by the init wizard.
# ABOUTME: Canonical-shape dicts per spec §4.1 / design §3; importable by wizard and tests.

"""Reference personas.

``REFERENCE_PERSONAS`` is the seed set the init wizard offers and the docs describe
(design §3). Each entry uses the canonical persona shape from ``spec.md#4.1``:

  * **engineering** — broad access to all Anthropic models.
  * **sales** — Haiku only; Sonnet and Opus explicitly denied (the restricted persona
    that exercises the inference-profile Deny invariant in the bypass test).

These are plain ``dict`` objects (not a dataclass) so they round-trip cleanly through
``Profile.personas`` (``list[dict]``) and pass ``validate_personas`` with no errors.
"""

from typing import Any

REFERENCE_PERSONAS: list[dict[str, Any]] = [
    {
        "name": "engineering",
        "display_name": "Engineering",
        "group": "eng-team",
        "allowed_models": ["anthropic.*"],
        "denied_models": [],
        "monthly_token_limit": 300_000_000,
        "daily_token_limit": None,
        "enforcement_mode": "block",
        "budget_amount_usd": None,
        "cost_tags": {"Team": "Engineering"},
    },
    {
        "name": "sales",
        "display_name": "Sales",
        "group": "sales-team",
        "allowed_models": ["anthropic.*haiku*"],
        "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
        "monthly_token_limit": 10_000_000,
        "daily_token_limit": None,
        "enforcement_mode": "block",
        "budget_amount_usd": None,
        "cost_tags": {"Team": "Sales"},
    },
]
