# ABOUTME: Tests for identity pool name validation (length + format)
# ABOUTME: Prevents issue #86 (target group name >32 chars)

"""Tests for validate_identity_pool_name."""

import pytest

from claude_code_with_bedrock.cli.commands.init import validate_identity_pool_name


class TestValidateIdentityPoolName:
    """Identity pool name validation must catch format and length issues."""

    def test_valid_short_name(self):
        assert validate_identity_pool_name("claude-code") is True

    def test_valid_max_length(self):
        assert validate_identity_pool_name("a" * 20) is True

    def test_rejects_too_long(self):
        result = validate_identity_pool_name("a" * 21)
        assert result is not True
        assert "too long" in result or "max 20" in result

    def test_rejects_special_characters(self):
        result = validate_identity_pool_name("my pool!")
        assert result is not True
        assert "Invalid" in result or "invalid" in result.lower()

    def test_rejects_empty(self):
        result = validate_identity_pool_name("")
        assert result is not True

    def test_allows_hyphens_and_underscores(self):
        assert validate_identity_pool_name("my_pool-name") is True

    def test_default_name_passes(self):
        """The default 'claude-code-auth' must always pass."""
        assert validate_identity_pool_name("claude-code-auth") is True

    def test_existing_long_names_caught_early(self):
        """Names that would cause target group failures are rejected."""
        # identity_pool_name + "-monitoring" + "-tg" must be <=32
        # "very-long-identity-pool" = 23 chars → stack "...-monitoring" = 34 → "-tg" = 37 > 32
        result = validate_identity_pool_name("very-long-identity-pool-x")
        assert result is not True
