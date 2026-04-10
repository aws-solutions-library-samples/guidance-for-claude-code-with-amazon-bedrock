# ABOUTME: Tests for Application Inference Profile model configuration functions
# ABOUTME: Covers INFERENCE_PROFILE_MODELS, DEFAULT_INFERENCE_PROFILE_MODEL,
# ABOUTME: get_enabled_inference_profile_models, get_inference_profile_source_arn,
# ABOUTME: get_application_profile_name, and get_application_profile_tags

"""Tests for the Application Inference Profile model configuration functions."""

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from claude_code_with_bedrock.models import (
    DEFAULT_INFERENCE_PROFILE_MODEL,
    INFERENCE_PROFILE_MODELS,
    get_application_profile_name,
    get_application_profile_tags,
    get_enabled_inference_profile_models,
    get_inference_profile_source_arn,
)

# ---------------------------------------------------------------------------
# INFERENCE_PROFILE_MODELS structure
# ---------------------------------------------------------------------------


class TestInferenceProfileModelsStructure:
    """Validate the static INFERENCE_PROFILE_MODELS dictionary."""

    def test_three_models_present(self):
        """All three expected model keys must be present."""
        # Arrange
        expected_keys = {"opus-4-6", "sonnet-4-6", "haiku-4-5"}

        # Act / Assert
        assert set(INFERENCE_PROFILE_MODELS.keys()) == expected_keys

    def test_each_model_has_required_keys(self):
        """Every model entry must contain source_model_arn, display_name, description, enabled."""
        required = {"source_model_arn", "display_name", "description", "enabled"}

        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            missing = required - set(config.keys())
            assert not missing, f"Model '{model_key}' is missing keys: {missing}"

    def test_all_models_enabled_by_default(self):
        """Every model shipped in the dict must start enabled."""
        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            assert config["enabled"] is True, f"Model '{model_key}' should be enabled by default"

    def test_source_model_arn_contains_region_placeholder(self):
        """source_model_arn for every model must contain the {region} placeholder."""
        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            assert (
                "{region}" in config["source_model_arn"]
            ), f"Model '{model_key}' source_model_arn missing {{region}} placeholder"

    def test_source_model_arn_is_bedrock_arn_template(self):
        """source_model_arn must look like a valid Bedrock foundation-model ARN template."""
        pattern = re.compile(r"^arn:aws:bedrock:\{region\}::foundation-model/anthropic\..+$")
        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            assert pattern.match(
                config["source_model_arn"]
            ), f"Model '{model_key}' has unexpected ARN format: {config['source_model_arn']}"

    def test_display_names_are_non_empty_strings(self):
        """display_name must be a non-empty string for every model."""
        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            assert (
                isinstance(config["display_name"], str) and config["display_name"]
            ), f"Model '{model_key}' has empty or invalid display_name"

    def test_descriptions_are_non_empty_strings(self):
        """description must be a non-empty string for every model."""
        for model_key, config in INFERENCE_PROFILE_MODELS.items():
            assert (
                isinstance(config["description"], str) and config["description"]
            ), f"Model '{model_key}' has empty or invalid description"


# ---------------------------------------------------------------------------
# DEFAULT_INFERENCE_PROFILE_MODEL
# ---------------------------------------------------------------------------


class TestDefaultInferenceProfileModel:
    """Validate the DEFAULT_INFERENCE_PROFILE_MODEL constant."""

    def test_default_is_a_key_in_inference_profile_models(self):
        """DEFAULT_INFERENCE_PROFILE_MODEL must be a valid key."""
        assert DEFAULT_INFERENCE_PROFILE_MODEL in INFERENCE_PROFILE_MODELS

    def test_default_model_is_enabled(self):
        """The default model must have enabled=True."""
        config = INFERENCE_PROFILE_MODELS[DEFAULT_INFERENCE_PROFILE_MODEL]
        assert config["enabled"] is True

    def test_default_model_is_a_string(self):
        """DEFAULT_INFERENCE_PROFILE_MODEL must be a non-empty string."""
        assert isinstance(DEFAULT_INFERENCE_PROFILE_MODEL, str)
        assert DEFAULT_INFERENCE_PROFILE_MODEL


# ---------------------------------------------------------------------------
# get_enabled_inference_profile_models
# ---------------------------------------------------------------------------


class TestGetEnabledInferenceProfileModels:
    """Tests for get_enabled_inference_profile_models()."""

    def test_returns_all_models_when_all_enabled(self):
        """When all models are enabled the function returns the full set."""
        # Arrange — all models in INFERENCE_PROFILE_MODELS are enabled
        enabled = get_enabled_inference_profile_models()

        # Act / Assert
        assert set(enabled.keys()) == set(INFERENCE_PROFILE_MODELS.keys())

    def test_returns_only_enabled_models(self):
        """When one model is disabled it must be excluded from the result."""
        # Arrange
        patched = {
            "opus-4-6": {"source_model_arn": "arn:...", "display_name": "A", "description": "d", "enabled": True},
            "sonnet-4-6": {"source_model_arn": "arn:...", "display_name": "B", "description": "d", "enabled": False},
            "haiku-4-5": {"source_model_arn": "arn:...", "display_name": "C", "description": "d", "enabled": True},
        }

        with patch("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched):
            # Act
            enabled = get_enabled_inference_profile_models()

        # Assert
        assert "opus-4-6" in enabled
        assert "haiku-4-5" in enabled
        assert "sonnet-4-6" not in enabled

    def test_excludes_disabled_model_completely(self):
        """A disabled model must not appear under any circumstances."""
        patched = {
            "sonnet-4-6": {"source_model_arn": "arn:...", "display_name": "X", "description": "d", "enabled": False},
        }

        with patch("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched):
            enabled = get_enabled_inference_profile_models()

        assert enabled == {}

    def test_returns_empty_dict_when_all_disabled(self):
        """Returns an empty dict when every model is disabled."""
        patched = {
            "opus-4-6": {"enabled": False},
            "sonnet-4-6": {"enabled": False},
        }

        with patch("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched):
            enabled = get_enabled_inference_profile_models()

        assert enabled == {}

    def test_returns_dict_not_reference(self):
        """The returned mapping must not be the same object as INFERENCE_PROFILE_MODELS."""
        enabled = get_enabled_inference_profile_models()
        assert enabled is not INFERENCE_PROFILE_MODELS

    def test_returned_entries_preserve_config(self):
        """Enabled entries must carry the full configuration dict unchanged."""
        enabled = get_enabled_inference_profile_models()
        for key, config in enabled.items():
            assert config == INFERENCE_PROFILE_MODELS[key]


# ---------------------------------------------------------------------------
# get_inference_profile_source_arn
# ---------------------------------------------------------------------------


class TestGetInferenceProfileSourceArn:
    """Tests for get_inference_profile_source_arn()."""

    def test_returns_arn_with_region_substituted(self):
        """The {region} placeholder is replaced with the supplied region."""
        # Arrange
        region = "us-east-1"

        # Act
        arn = get_inference_profile_source_arn("sonnet-4-6", region)

        # Assert
        assert region in arn
        assert "{region}" not in arn

    def test_correct_arn_for_sonnet_4_6_us_east_1(self):
        """Spot-check the full ARN value for sonnet-4-6 in us-east-1."""
        arn = get_inference_profile_source_arn("sonnet-4-6", "us-east-1")
        assert arn == ("arn:aws:bedrock:us-east-1::foundation-model/" "anthropic.claude-sonnet-4-6-20251120-v1:0")

    def test_correct_arn_for_opus_4_6_eu_west_1(self):
        """Spot-check the full ARN value for opus-4-6 in eu-west-1."""
        arn = get_inference_profile_source_arn("opus-4-6", "eu-west-1")
        assert arn == ("arn:aws:bedrock:eu-west-1::foundation-model/" "anthropic.claude-opus-4-6-v1")

    def test_correct_arn_for_haiku_4_5(self):
        """Spot-check the full ARN value for haiku-4-5."""
        arn = get_inference_profile_source_arn("haiku-4-5", "ap-northeast-1")
        assert arn == ("arn:aws:bedrock:ap-northeast-1::foundation-model/" "anthropic.claude-haiku-4-5-20251001-v1:0")

    def test_different_regions_produce_different_arns(self):
        """The same model key with two distinct regions must produce distinct ARNs."""
        arn_us = get_inference_profile_source_arn("sonnet-4-6", "us-east-1")
        arn_eu = get_inference_profile_source_arn("sonnet-4-6", "eu-central-1")
        assert arn_us != arn_eu

    def test_raises_value_error_for_unknown_model_key(self):
        """ValueError must be raised when the model key does not exist."""
        with pytest.raises(ValueError, match="Unknown inference profile model"):
            get_inference_profile_source_arn("does-not-exist", "us-east-1")

    def test_raises_value_error_for_disabled_model(self):
        """ValueError must be raised when the model is disabled."""
        patched = {
            "sonnet-4-6": {
                "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.test",
                "display_name": "Test",
                "description": "Test",
                "enabled": False,
            }
        }

        with patch("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched):
            with pytest.raises(ValueError, match="disabled"):
                get_inference_profile_source_arn("sonnet-4-6", "us-east-1")

    def test_error_message_contains_model_key_for_unknown(self):
        """The ValueError message must mention the unknown key."""
        bad_key = "totally-unknown-model"
        with pytest.raises(ValueError, match=bad_key):
            get_inference_profile_source_arn(bad_key, "us-east-1")

    def test_error_message_contains_model_key_for_disabled(self):
        """The ValueError message for a disabled model must mention the key."""
        patched = {
            "my-model": {
                "source_model_arn": "arn:aws:bedrock:{region}::foundation-model/anthropic.x",
                "display_name": "X",
                "description": "X",
                "enabled": False,
            }
        }

        with patch("claude_code_with_bedrock.models.INFERENCE_PROFILE_MODELS", patched):
            with pytest.raises(ValueError, match="my-model"):
                get_inference_profile_source_arn("my-model", "us-east-1")


# ---------------------------------------------------------------------------
# get_application_profile_name
# ---------------------------------------------------------------------------


class TestGetApplicationProfileName:
    """Tests for get_application_profile_name()."""

    def test_basic_email_produces_expected_format(self):
        """A plain email and model key yield a name starting with 'claude-code-'."""
        # Arrange / Act
        name = get_application_profile_name("mario.rossi@example.com", "sonnet-4-6")

        # Assert
        assert name.startswith("claude-code-")
        assert "sonnet-4-6" in name

    def test_result_is_at_most_64_characters(self):
        """The profile name must never exceed the 64-character AWS limit."""
        name = get_application_profile_name("mario.rossi@example.com", "sonnet-4-6")
        assert len(name) <= 64

    def test_long_email_still_within_64_characters(self):
        """Even a very long email must produce a name <= 64 characters."""
        long_email = "a" * 80 + "@" + "b" * 80 + ".com"
        name = get_application_profile_name(long_email, "sonnet-4-6")
        assert len(name) <= 64

    def test_special_chars_in_email_plus_sign(self):
        """A '+' in the email is replaced and the name stays within the limit."""
        name = get_application_profile_name("user+tag@example.com", "sonnet-4-6")
        assert len(name) <= 64
        # '+' must not appear in the result
        assert "+" not in name

    def test_special_chars_in_email_quotes(self):
        """Double-quotes in the email are replaced and the name is valid."""
        name = get_application_profile_name('"user"@example.com', "sonnet-4-6")
        assert len(name) <= 64
        assert '"' not in name

    def test_special_chars_in_email_spaces(self):
        """Spaces in the email are replaced and the name is valid."""
        name = get_application_profile_name("first last@example.com", "sonnet-4-6")
        assert len(name) <= 64
        assert " " not in name

    def test_different_emails_produce_different_names(self):
        """Two emails that normalize identically must still differ due to hash suffix."""
        # 'user+tag@example.com' and 'user-tag@example.com' normalize the same way
        name_a = get_application_profile_name("user+tag@example.com", "sonnet-4-6")
        name_b = get_application_profile_name("user-tag@example.com", "sonnet-4-6")
        assert name_a != name_b

    def test_same_inputs_produce_same_name(self):
        """Calling the function twice with the same args is deterministic."""
        name_1 = get_application_profile_name("alice@example.com", "haiku-4-5")
        name_2 = get_application_profile_name("alice@example.com", "haiku-4-5")
        assert name_1 == name_2

    def test_result_only_contains_allowed_characters(self):
        """The name must only contain lowercase letters, digits, and hyphens."""
        emails = [
            "simple@test.com",
            "USER@UPPER.COM",
            "tricky+plus@sub.domain.org",
            '"quoted"@example.com',
            "first last@example.com",
        ]
        allowed = re.compile(r"^[a-z0-9-]+$")
        for email in emails:
            name = get_application_profile_name(email, "sonnet-4-6")
            assert allowed.match(name), f"Profile name '{name}' for email '{email}' contains disallowed characters"

    def test_result_starts_with_claude_code(self):
        """The profile name must always begin with 'claude-code-'."""
        name = get_application_profile_name("test@example.com", "opus-4-6")
        assert name.startswith("claude-code-")

    def test_model_key_appears_in_name(self):
        """The model key must be embedded at the end of the profile name."""
        for model_key in ("opus-4-6", "sonnet-4-6", "haiku-4-5"):
            name = get_application_profile_name("test@example.com", model_key)
            assert name.endswith(f"-{model_key}"), f"Expected name to end with '-{model_key}', got: {name}"

    def test_uppercase_email_lowercased_in_name(self):
        """Upper-case characters in the email must be lower-cased in the name."""
        name = get_application_profile_name("ALICE@EXAMPLE.COM", "sonnet-4-6")
        assert name == name.lower()

    def test_hash_suffix_is_8_hex_chars(self):
        """The SHA-256 email hash embedded in the name must be exactly 8 hex chars."""
        name = get_application_profile_name("alice@example.com", "sonnet-4-6")
        # Format: claude-code-<sanitized>-<8hex>-<model_key>
        # Strip prefix and suffix, extract the 8-char hex segment
        without_prefix = name[len("claude-code-") :]
        without_suffix = without_prefix[: -len("-sonnet-4-6")]
        hash_part = without_suffix.rsplit("-", 1)[-1]
        assert len(hash_part) == 8
        assert re.fullmatch(r"[0-9a-f]{8}", hash_part)


# ---------------------------------------------------------------------------
# get_application_profile_tags
# ---------------------------------------------------------------------------


class TestGetApplicationProfileTags:
    """Tests for get_application_profile_tags()."""

    def test_basic_case_email_and_all_claims(self):
        """All four custom claims map to corresponding tags when present."""
        # Arrange
        email = "alice@example.com"
        claims = {
            "custom:cost_center": "CC-001",
            "custom:department": "Engineering",
            "custom:organization": "ACME",
            "custom:team": "Platform",
        }

        # Act
        tags = get_application_profile_tags(email, claims)

        # Assert — five tags total (email + 4 claims)
        assert len(tags) == 5
        keys = [t["Key"] for t in tags]
        assert "user.email" in keys
        assert "cost_center" in keys
        assert "department" in keys
        assert "organization" in keys
        assert "team" in keys

    def test_email_only_no_custom_claims(self):
        """When no custom claims are present only the email tag is returned."""
        tags = get_application_profile_tags("bob@example.com", {})

        assert len(tags) == 1
        assert tags[0]["Key"] == "user.email"
        assert tags[0]["Value"] == "bob@example.com"

    def test_missing_optional_claims_are_skipped(self):
        """Missing claims must not produce tags with empty values."""
        claims = {"custom:cost_center": "CC-002"}
        tags = get_application_profile_tags("carol@example.com", claims)

        keys = [t["Key"] for t in tags]
        assert "cost_center" in keys
        assert "department" not in keys
        assert "organization" not in keys
        assert "team" not in keys

    def test_user_email_tag_is_first(self):
        """user.email must always be the first tag in the list."""
        claims = {
            "custom:cost_center": "CC-003",
            "custom:team": "DevOps",
        }
        tags = get_application_profile_tags("dave@example.com", claims)

        assert tags[0]["Key"] == "user.email"

    def test_user_email_value_matches_input(self):
        """The value of the user.email tag must equal the email argument."""
        email = "eve@company.org"
        tags = get_application_profile_tags(email, {})

        assert tags[0]["Value"] == email

    def test_tag_values_truncated_to_256_chars(self):
        """Values longer than 256 characters must be truncated."""
        long_value = "x" * 300
        long_email = "a" * 300 + "@example.com"
        claims = {"custom:cost_center": long_value}

        tags = get_application_profile_tags(long_email, claims)

        for tag in tags:
            assert len(tag["Value"]) <= 256, f"Tag '{tag['Key']}' value exceeds 256 chars: {len(tag['Value'])}"

    def test_email_exactly_256_chars_not_truncated(self):
        """An email of exactly 256 characters must not be trimmed further."""
        email_256 = "a" * 244 + "@example.com"  # 244 + 12 = 256
        assert len(email_256) == 256
        tags = get_application_profile_tags(email_256, {})

        assert tags[0]["Value"] == email_256

    def test_tag_format_is_key_value_dicts(self):
        """Every tag must be a dict with exactly 'Key' and 'Value' entries."""
        tags = get_application_profile_tags("test@example.com", {"custom:team": "Ops"})

        for tag in tags:
            assert set(tag.keys()) == {"Key", "Value"}, f"Unexpected tag structure: {tag}"

    def test_returns_list(self):
        """get_application_profile_tags must always return a list."""
        result = get_application_profile_tags("test@example.com", {})
        assert isinstance(result, list)

    def test_none_claim_value_is_skipped(self):
        """A claim present in the JWT but with a None value must not produce a tag."""
        # claims.get() returns None when key is absent, but explicit None should also be skipped
        claims = {"custom:cost_center": None}
        tags = get_application_profile_tags("frank@example.com", claims)

        keys = [t["Key"] for t in tags]
        assert "cost_center" not in keys

    def test_empty_string_claim_value_is_skipped(self):
        """An empty string claim value must not produce a tag."""
        claims = {"custom:department": ""}
        tags = get_application_profile_tags("grace@example.com", claims)

        keys = [t["Key"] for t in tags]
        assert "department" not in keys

    def test_claim_values_converted_to_string(self):
        """Non-string claim values must be coerced to str before tagging."""
        claims = {"custom:cost_center": 42}
        tags = get_application_profile_tags("henry@example.com", claims)

        cost_tag = next(t for t in tags if t["Key"] == "cost_center")
        assert cost_tag["Value"] == "42"
        assert isinstance(cost_tag["Value"], str)
