"""Regression test for issue #141: CognitoUserPoolClientId AllowedPattern too strict."""

import re
from pathlib import Path

import yaml

INFRA_DIR = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure"


# Custom YAML loader that handles CloudFormation intrinsic functions
class CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag_constructor(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", _cfn_tag_constructor)


class TestCognitoClientIdPattern:
    """Verify CognitoUserPoolClientId accepts AWS-documented lengths (1-128)."""

    def test_pattern_allows_variable_length(self):
        """AllowedPattern must not hard-code 26 chars — AWS allows 1-128."""
        template_path = INFRA_DIR / "bedrock-auth-cognito-pool.yaml"
        with open(template_path, encoding="utf-8") as f:
            template = yaml.load(f, Loader=CfnLoader)

        param = template["Parameters"]["CognitoUserPoolClientId"]
        pattern = param["AllowedPattern"]

        # Must accept IDs shorter and longer than 26 chars
        assert re.match(pattern, "a" * 25), f"Pattern {pattern!r} rejects 25-char client IDs (AWS allows 1-128)"
        assert re.match(pattern, "a" * 26), f"Pattern {pattern!r} rejects 26-char client IDs"
        assert re.match(pattern, "a" * 64), f"Pattern {pattern!r} rejects 64-char client IDs (AWS allows up to 128)"

    def test_pattern_rejects_invalid_chars(self):
        """Pattern must still reject uppercase, special chars."""
        template_path = INFRA_DIR / "bedrock-auth-cognito-pool.yaml"
        with open(template_path, encoding="utf-8") as f:
            template = yaml.load(f, Loader=CfnLoader)

        param = template["Parameters"]["CognitoUserPoolClientId"]
        pattern = param["AllowedPattern"]

        assert not re.match(pattern, "UPPERCASE123"), "Pattern should reject uppercase characters"
        assert not re.match(pattern, "has-dashes-123"), "Pattern should reject dashes"
        assert not re.match(pattern, ""), "Pattern should reject empty string"
