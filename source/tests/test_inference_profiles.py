# ABOUTME: Tests for Application Inference Profile helper functions in models.py
# ABOUTME: Covers enabled-model filtering, ARN construction, profile naming, and tag building

"""Tests for Application Inference Profile helper functions.

Covers:
- get_enabled_inference_profile_models()
- get_inference_profile_source_arn()
- get_application_profile_name()
- get_application_profile_tags()
"""

import hashlib
import re

import pytest

from claude_code_with_bedrock.models import (
    INFERENCE_PROFILE_MODELS,
    get_application_profile_name,
    get_application_profile_tags,
    get_enabled_inference_profile_models,
    get_inference_profile_source_arn,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_hex8(value: str) -> str:
    """Return the first 8 hex characters of the SHA-256 digest of *value*."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# get_enabled_inference_profile_models()
# ---------------------------------------------------------------------------


class TestGetEnabledInferenceProfileModels:
    """Tests for get_enabled_inference_profile_models()."""

    def test_returns_dict(self):
        result = get_enabled_inference_profile_models()
        assert isinstance(result, dict)

    def test_all_live_models_are_present(self):
        """Every key whose enabled flag is True in the source dict must appear."""
        expected = {k for k, v in INFERENCE_PROFILE_MODELS.items() if v.get("enabled", False)}
        result = get_enabled_inference_profile_models()
        assert set(result.keys()) == expected

    def test_disabled_models_are_absent(self, monkeypatch):
        """Models with enabled=False must not appear in the result."""
        patched = {
            "model-a": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/a", "enabled": True},
            "model-b": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/b", "enabled": False},
            "model-c": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/c", "enabled": True},
        }
        monkeypatch.setattr("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched)

        result = get_enabled_inference_profile_models()

        assert "model-a" in result
        assert "model-b" not in result
        assert "model-c" in result

    def test_returns_empty_dict_when_all_disabled(self, monkeypatch):
        patched = {
            "model-a": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/a", "enabled": False},
            "model-b": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/b", "enabled": False},
        }
        monkeypatch.setattr("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched)

        result = get_enabled_inference_profile_models()

        assert result == {}

    def test_returns_empty_dict_when_catalogue_is_empty(self, monkeypatch):
        monkeypatch.setattr("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", {})

        result = get_enabled_inference_profile_models()

        assert result == {}

    def test_missing_enabled_key_treated_as_disabled(self, monkeypatch):
        """An entry with no 'enabled' key should be excluded (defaults to False)."""
        patched = {
            "model-no-flag": {"source_model_arn": "arn:aws:bedrock:{region}::foundation-model/x"},
        }
        monkeypatch.setattr("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched)

        result = get_enabled_inference_profile_models()

        assert "model-no-flag" not in result

    def test_result_contains_full_model_entry(self):
        """Values in the result are the complete entry dicts, not just the flag."""
        result = get_enabled_inference_profile_models()
        for key, entry in result.items():
            assert "source_model_arn" in entry
            assert "enabled" in entry
            assert entry["enabled"] is True


# ---------------------------------------------------------------------------
# get_inference_profile_source_arn()
# ---------------------------------------------------------------------------


class TestGetInferenceProfileSourceArn:
    """Tests for get_inference_profile_source_arn()."""

    # -- happy path -----------------------------------------------------------

    @pytest.mark.parametrize("model_key", list(INFERENCE_PROFILE_MODELS.keys()))
    def test_known_enabled_model_returns_arn(self, model_key):
        """Every currently-enabled model key should resolve without error."""
        entry = INFERENCE_PROFILE_MODELS[model_key]
        if not entry.get("enabled", False):
            pytest.skip(f"{model_key} is disabled")

        arn = get_inference_profile_source_arn(model_key, "us-east-1")
        assert isinstance(arn, str)
        assert arn.startswith("arn:aws:bedrock:")

    def test_region_substitution_us_east_1(self):
        model_key = next(k for k, v in INFERENCE_PROFILE_MODELS.items() if v.get("enabled", False))
        arn = get_inference_profile_source_arn(model_key, "us-east-1")
        assert "us-east-1" in arn
        assert "{region}" not in arn

    def test_region_substitution_eu_central_1(self):
        model_key = next(k for k, v in INFERENCE_PROFILE_MODELS.items() if v.get("enabled", False))
        arn = get_inference_profile_source_arn(model_key, "eu-central-1")
        assert "eu-central-1" in arn
        assert "{region}" not in arn

    @pytest.mark.parametrize("region", ["us-east-1", "us-west-2", "eu-central-1", "ap-northeast-1"])
    def test_arn_format_for_each_region(self, region):
        """ARN must match the canonical Bedrock foundation-model ARN structure."""
        model_key = next(k for k, v in INFERENCE_PROFILE_MODELS.items() if v.get("enabled", False))
        arn = get_inference_profile_source_arn(model_key, region)
        # arn:aws:bedrock:<region>::foundation-model/<model-id>
        assert re.match(
            r"arn:aws:bedrock:[a-z0-9-]+::foundation-model/.+",
            arn,
        ), f"ARN '{arn}' does not match expected pattern"

    def test_specific_model_arn_opus(self):
        """Spot-check the opus-4-6 ARN against the known template value."""
        if not INFERENCE_PROFILE_MODELS.get("opus-4-6", {}).get("enabled", False):
            pytest.skip("opus-4-6 is disabled in current config")

        arn = get_inference_profile_source_arn("opus-4-6", "us-east-1")
        assert arn == "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-opus-4-6-v1"

    def test_specific_model_arn_sonnet(self):
        """Spot-check the sonnet-4-6 ARN against the known template value."""
        if not INFERENCE_PROFILE_MODELS.get("sonnet-4-6", {}).get("enabled", False):
            pytest.skip("sonnet-4-6 is disabled in current config")

        arn = get_inference_profile_source_arn("sonnet-4-6", "eu-west-1")
        assert arn == "arn:aws:bedrock:eu-west-1::foundation-model/anthropic.claude-sonnet-4-6-20251120-v1:0"

    # -- error path -----------------------------------------------------------

    def test_raises_value_error_for_unknown_model(self):
        with pytest.raises(ValueError, match="Unknown inference profile model"):
            get_inference_profile_source_arn("does-not-exist", "us-east-1")

    def test_raises_value_error_for_disabled_model(self, monkeypatch):
        patched = {
            "disabled-model": {
                "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.claude-fake-v1",
                "enabled": False,
            }
        }
        monkeypatch.setattr("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched)

        with pytest.raises(ValueError, match="disabled"):
            get_inference_profile_source_arn("disabled-model", "us-east-1")

    def test_error_message_contains_model_key(self):
        with pytest.raises(ValueError) as exc_info:
            get_inference_profile_source_arn("totally-unknown-key", "us-east-1")
        assert "totally-unknown-key" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_application_profile_name()
# ---------------------------------------------------------------------------


class TestGetApplicationProfileName:
    """Tests for get_application_profile_name()."""

    # -- output structure -----------------------------------------------------

    def test_returns_string(self):
        assert isinstance(get_application_profile_name("user@example.com", "sonnet-4-6"), str)

    def test_name_starts_with_claude_code_prefix(self):
        name = get_application_profile_name("user@example.com", "sonnet-4-6")
        assert name.startswith("claude-code-")

    def test_name_ends_with_model_key(self):
        name = get_application_profile_name("user@example.com", "sonnet-4-6")
        assert name.endswith("-sonnet-4-6")

    def test_name_contains_hash(self):
        """The 8-char SHA-256 hash of the email must be embedded in the name."""
        email = "user@example.com"
        expected_hash = _sha256_hex8(email)
        name = get_application_profile_name(email, "sonnet-4-6")
        assert expected_hash in name

    def test_name_max_64_chars(self):
        """Profile names must never exceed 64 characters (AWS limit)."""
        name = get_application_profile_name("user@example.com", "sonnet-4-6")
        assert len(name) <= 64

    def test_name_max_64_chars_long_email(self):
        """64-char limit must hold even for unusually long email addresses."""
        long_email = "a.very.long.user.name.that.goes.on.and.on@extremely-long-domain-name.example.com"
        name = get_application_profile_name(long_email, "haiku-4-5")
        assert len(name) <= 64

    def test_name_only_safe_chars(self):
        """AWS Application Inference Profile names allow [a-zA-Z0-9-]."""
        name = get_application_profile_name("user+tag@example.com", "sonnet-4-6")
        assert re.match(r"^[a-zA-Z0-9-]+$", name), f"Unsafe characters found in '{name}'"

    # -- email sanitization ---------------------------------------------------

    @pytest.mark.parametrize("email,expected_fragment", [
        ("mario.rossi@example.com", "mario-rossi-example-com"),
        ("user+tag@domain.org",     "user-tag-domain-org"),
        ("User.Name@Company.COM",   "user-name-company-com"),
        ("first_last@host.io",      "first-last-host-io"),
    ])
    def test_sanitized_email_appears_in_name(self, email, expected_fragment):
        name = get_application_profile_name(email, "sonnet-4-6")
        assert expected_fragment in name, (
            f"Expected '{expected_fragment}' to appear in '{name}' for email '{email}'"
        )

    def test_at_sign_replaced(self):
        name = get_application_profile_name("user@example.com", "sonnet-4-6")
        assert "@" not in name

    def test_dot_replaced(self):
        name = get_application_profile_name("first.last@example.com", "sonnet-4-6")
        # dots become dashes; no raw dots in the output
        assert "." not in name

    def test_plus_replaced(self):
        name = get_application_profile_name("user+alias@example.com", "sonnet-4-6")
        assert "+" not in name

    def test_uppercase_lowercased(self):
        name = get_application_profile_name("User@EXAMPLE.COM", "sonnet-4-6")
        assert name == name.lower()

    def test_consecutive_specials_produce_single_dash(self):
        """Multiple consecutive special characters should collapse to one dash."""
        # e.g. user__name or user--name → user-name in the sanitized portion
        name = get_application_profile_name("user__name@example.com", "sonnet-4-6")
        assert "--" not in name

    # -- collision resistance -------------------------------------------------

    def test_different_emails_normalizing_to_same_string_differ(self):
        """
        'user+tag@example.com' and 'user-tag@example.com' both sanitize to
        'user-tag-example-com' but must produce different profile names because
        their SHA-256 hashes differ.
        """
        email_a = "user+tag@example.com"
        email_b = "user-tag@example.com"

        name_a = get_application_profile_name(email_a, "sonnet-4-6")
        name_b = get_application_profile_name(email_b, "sonnet-4-6")

        # Sanity: they do normalize to the same slug
        sanitized_a = re.sub(r"[^a-z0-9-]", "-", email_a.lower())
        sanitized_b = re.sub(r"[^a-z0-9-]", "-", email_b.lower())
        assert re.sub(r"-{2,}", "-", sanitized_a).strip("-") == re.sub(r"-{2,}", "-", sanitized_b).strip("-"), (
            "Precondition: the two emails must sanitize to the same slug for this test to be meaningful"
        )

        # Their profile names must be different because the hashes differ
        assert name_a != name_b

    def test_same_email_different_model_keys_differ(self):
        name_a = get_application_profile_name("user@example.com", "sonnet-4-6")
        name_b = get_application_profile_name("user@example.com", "haiku-4-5")
        assert name_a != name_b

    def test_same_email_same_model_key_is_deterministic(self):
        email, model = "user@example.com", "sonnet-4-6"
        assert get_application_profile_name(email, model) == get_application_profile_name(email, model)

    # -- documented example ---------------------------------------------------

    def test_documented_example(self):
        """Validate the exact example from the docstring."""
        # mario.rossi@example.com + sonnet-4-6
        # → claude-code-mario-rossi-example-com-<hash>-sonnet-4-6
        email = "mario.rossi@example.com"
        model = "sonnet-4-6"
        expected_hash = _sha256_hex8(email)
        name = get_application_profile_name(email, model)

        assert name == f"claude-code-mario-rossi-example-com-{expected_hash}-{model}"

    # -- truncation at 64 chars -----------------------------------------------

    def test_truncation_leaves_hash_intact(self):
        """When the email is long enough to force truncation the hash must still appear."""
        long_email = "averylongfirstname.averylonglastname@verylongcompanyname.example.com"
        expected_hash = _sha256_hex8(long_email)
        model = "sonnet-4-6"
        name = get_application_profile_name(long_email, model)

        assert len(name) <= 64
        assert expected_hash in name
        assert name.endswith(f"-{model}")


# ---------------------------------------------------------------------------
# get_application_profile_tags()
# ---------------------------------------------------------------------------


class TestGetApplicationProfileTags:
    """Tests for get_application_profile_tags()."""

    # -- return type ----------------------------------------------------------

    def test_returns_list(self):
        result = get_application_profile_tags("user@example.com", {})
        assert isinstance(result, list)

    def test_each_item_is_dict_with_key_and_value(self):
        result = get_application_profile_tags("user@example.com", {})
        for tag in result:
            assert "Key" in tag
            assert "Value" in tag

    # -- email tag always present ---------------------------------------------

    def test_email_tag_always_present(self):
        result = get_application_profile_tags("user@example.com", {})
        keys = [t["Key"] for t in result]
        assert "user.email" in keys

    def test_email_tag_value_is_correct(self):
        email = "someone@corp.example.com"
        result = get_application_profile_tags(email, {})
        email_tags = [t for t in result if t["Key"] == "user.email"]
        assert len(email_tags) == 1
        assert email_tags[0]["Value"] == email

    def test_email_tag_present_even_with_empty_claims(self):
        result = get_application_profile_tags("a@b.com", {})
        assert any(t["Key"] == "user.email" for t in result)

    # -- optional claims included when present --------------------------------

    @pytest.mark.parametrize("claim_key,tag_key", [
        ("custom:cost_center", "cost_center"),
        ("custom:department",  "department"),
        ("custom:organization", "organization"),
        ("custom:team",        "team"),
    ])
    def test_optional_claim_included_when_present(self, claim_key, tag_key):
        claims = {claim_key: "engineering"}
        result = get_application_profile_tags("user@example.com", claims)
        tag_keys = [t["Key"] for t in result]
        assert tag_key in tag_keys

    @pytest.mark.parametrize("claim_key,tag_key,value", [
        ("custom:cost_center", "cost_center",   "CC-1234"),
        ("custom:department",  "department",    "Platform Engineering"),
        ("custom:organization","organization",  "ACME Corp"),
        ("custom:team",        "team",          "backend"),
    ])
    def test_optional_claim_value_is_correct(self, claim_key, tag_key, value):
        claims = {claim_key: value}
        result = get_application_profile_tags("user@example.com", claims)
        matching = [t for t in result if t["Key"] == tag_key]
        assert len(matching) == 1
        assert matching[0]["Value"] == value

    def test_all_claims_present(self):
        claims = {
            "custom:cost_center": "CC-999",
            "custom:department":  "Finance",
            "custom:organization": "GlobalCorp",
            "custom:team":        "data",
        }
        result = get_application_profile_tags("user@example.com", claims)
        tag_keys = {t["Key"] for t in result}
        assert {"user.email", "cost_center", "department", "organization", "team"} == tag_keys

    # -- absent claims not included -------------------------------------------

    @pytest.mark.parametrize("claim_key,tag_key", [
        ("custom:cost_center", "cost_center"),
        ("custom:department",  "department"),
        ("custom:organization", "organization"),
        ("custom:team",        "team"),
    ])
    def test_absent_claim_not_included(self, claim_key, tag_key):
        # Provide all claims except this one
        all_claims = {
            "custom:cost_center": "CC",
            "custom:department":  "Dept",
            "custom:organization": "Org",
            "custom:team":        "Team",
        }
        del all_claims[claim_key]
        result = get_application_profile_tags("user@example.com", all_claims)
        tag_keys = [t["Key"] for t in result]
        assert tag_key not in tag_keys

    def test_no_optional_claims_only_email_tag(self):
        result = get_application_profile_tags("user@example.com", {})
        assert len(result) == 1
        assert result[0]["Key"] == "user.email"

    def test_unknown_claims_ignored(self):
        claims = {"custom:unknown_field": "some-value", "sub": "abc123"}
        result = get_application_profile_tags("user@example.com", claims)
        tag_keys = [t["Key"] for t in result]
        assert "unknown_field" not in tag_keys
        assert "sub" not in tag_keys
        # Only the email tag
        assert len(result) == 1

    # -- 256-char truncation --------------------------------------------------

    def test_email_truncated_at_256_chars(self):
        long_email = "a" * 300 + "@example.com"
        result = get_application_profile_tags(long_email, {})
        email_tag = next(t for t in result if t["Key"] == "user.email")
        assert len(email_tag["Value"]) <= 256

    @pytest.mark.parametrize("claim_key,tag_key", [
        ("custom:cost_center", "cost_center"),
        ("custom:department",  "department"),
        ("custom:organization","organization"),
        ("custom:team",        "team"),
    ])
    def test_claim_value_truncated_at_256_chars(self, claim_key, tag_key):
        long_value = "x" * 300
        claims = {claim_key: long_value}
        result = get_application_profile_tags("user@example.com", claims)
        matching = next((t for t in result if t["Key"] == tag_key), None)
        assert matching is not None
        assert len(matching["Value"]) <= 256

    def test_short_values_not_truncated(self):
        claims = {
            "custom:cost_center": "CC-1",
            "custom:department":  "Eng",
        }
        result = get_application_profile_tags("user@example.com", claims)
        for tag in result:
            if tag["Key"] == "cost_center":
                assert tag["Value"] == "CC-1"
            if tag["Key"] == "department":
                assert tag["Value"] == "Eng"

    def test_exactly_256_char_value_not_truncated(self):
        exact_value = "b" * 256
        claims = {"custom:team": exact_value}
        result = get_application_profile_tags("user@example.com", claims)
        team_tag = next(t for t in result if t["Key"] == "team")
        assert team_tag["Value"] == exact_value
        assert len(team_tag["Value"]) == 256

    # -- tag values are strings -----------------------------------------------

    def test_numeric_claim_value_coerced_to_string(self):
        """Claims may arrive as non-string types; values must be strings for boto3."""
        claims = {"custom:cost_center": 42}
        result = get_application_profile_tags("user@example.com", claims)
        cc_tag = next(t for t in result if t["Key"] == "cost_center")
        assert isinstance(cc_tag["Value"], str)
        assert cc_tag["Value"] == "42"
