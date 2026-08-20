"""Regression test for issue #141: CognitoUserPoolClientId AllowedPattern too strict."""

import re

from tests.cfn_yaml import INFRA_DIR, load_resolved


class TestCognitoClientIdPattern:
    """Verify CognitoUserPoolClientId accepts AWS-documented lengths (1-128)."""

    def test_pattern_allows_variable_length(self):
        """AllowedPattern must not hard-code 26 chars — AWS allows 1-128."""
        template = load_resolved(INFRA_DIR / "bedrock-auth-cognito-pool.yaml")

        param = template["Parameters"]["CognitoUserPoolClientId"]
        pattern = param["AllowedPattern"]

        # Must accept IDs shorter and longer than 26 chars
        assert re.match(pattern, "a" * 25), f"Pattern {pattern!r} rejects 25-char client IDs (AWS allows 1-128)"
        assert re.match(pattern, "a" * 26), f"Pattern {pattern!r} rejects 26-char client IDs"
        assert re.match(pattern, "a" * 64), f"Pattern {pattern!r} rejects 64-char client IDs (AWS allows up to 128)"

    def test_pattern_rejects_invalid_chars(self):
        """Pattern must still reject uppercase, special chars."""
        template = load_resolved(INFRA_DIR / "bedrock-auth-cognito-pool.yaml")

        param = template["Parameters"]["CognitoUserPoolClientId"]
        pattern = param["AllowedPattern"]

        assert not re.match(pattern, "UPPERCASE123"), "Pattern should reject uppercase characters"
        assert not re.match(pattern, "has-dashes-123"), "Pattern should reject dashes"
        assert not re.match(pattern, ""), "Pattern should reject empty string"
