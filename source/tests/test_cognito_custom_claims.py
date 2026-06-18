# ABOUTME: Tests for custom:* claim prefix priority in otel_helper extract_user_info
# ABOUTME: Ensures Cognito custom attributes take precedence over standard claim names

"""Regression tests for custom:* attribute priority in otel_helper."""

import importlib.util
from pathlib import Path

# Load otel_helper/__main__.py as a module without conflicting with pytest's __main__
_spec = importlib.util.spec_from_file_location(
    "otel_helper_main",
    Path(__file__).resolve().parents[1] / "otel_helper" / "__main__.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
extract_user_info = _module.extract_user_info


class TestCustomClaimPriority:
    """Verify custom:* prefixed claims take priority over standard names."""

    def test_custom_department_takes_priority(self):
        """custom:department overrides department claim."""
        payload = {
            "email": "alice@co.com",
            "sub": "abc123",
            "department": "fallback-dept",
            "custom:department": "cloud-foundations",
        }
        result = extract_user_info(payload)
        assert result["department"] == "cloud-foundations"

    def test_custom_team_takes_priority(self):
        """custom:team overrides team claim."""
        payload = {
            "email": "alice@co.com",
            "sub": "abc123",
            "team": "fallback-team",
            "custom:team": "platform-eng",
        }
        result = extract_user_info(payload)
        assert result["team"] == "platform-eng"

    def test_custom_cost_center_takes_priority(self):
        """custom:cost_center overrides cost_center claim."""
        payload = {
            "email": "alice@co.com",
            "sub": "abc123",
            "cost_center": "fallback-cc",
            "custom:cost_center": "CC-1234",
        }
        result = extract_user_info(payload)
        assert result["cost_center"] == "CC-1234"

    def test_falls_back_to_standard_when_no_custom(self):
        """Standard claims still work when custom:* prefix not present."""
        payload = {
            "email": "bob@co.com",
            "sub": "def456",
            "department": "engineering",
            "team": "backend",
            "cost_center": "CC-5678",
        }
        result = extract_user_info(payload)
        assert result["department"] == "engineering"
        assert result["team"] == "backend"
        assert result["cost_center"] == "CC-5678"

    def test_defaults_when_no_claims_at_all(self):
        """Falls back to defaults when neither custom: nor standard claims exist."""
        payload = {
            "email": "carol@co.com",
            "sub": "ghi789",
        }
        result = extract_user_info(payload)
        assert result["department"] == "unspecified"
        assert result["team"] == "default-team"
        assert result["cost_center"] == "general"
        assert result["manager"] == "unassigned"
        assert result["location"] == "remote"
        assert result["role"] == "user"

    def test_empty_custom_claim_falls_through(self):
        """Empty custom:* values are skipped (falsy), standard claim used instead."""
        payload = {
            "email": "dave@co.com",
            "sub": "jkl012",
            "custom:department": "",
            "department": "real-dept",
        }
        result = extract_user_info(payload)
        assert result["department"] == "real-dept"
