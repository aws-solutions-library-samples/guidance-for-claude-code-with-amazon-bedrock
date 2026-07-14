# ABOUTME: Tests for CoWork 3P MDM credential config generation (build_mdm_config)
# ABOUTME: CoWork uses inferenceBedrockProfile (AWS SDK credential_process); no credential helper

"""Tests for CoWork 3P MDM credential configuration.

CoWork authenticates via `inferenceBedrockProfile` — Claude Desktop resolves the
named AWS profile through the SDK, which runs credential-process. There is no
`inferenceCredentialHelper` (that MDM key requires a bare-token/`{"token": ...}`
output that credential-process does not produce).
"""

import json

from claude_code_with_bedrock.cli.utils.cowork_3p import (
    build_mdm_config,
    generate_json,
    generate_reg_file,
)


class TestBuildMdmConfig:
    def test_uses_bedrock_profile(self):
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="MyProfile",
        )
        assert config["inferenceBedrockProfile"] == "MyProfile"
        assert "inferenceCredentialHelper" not in config
        assert "inferenceCredentialHelperTtlSec" not in config

    def test_matches_expected_shape(self):
        config = build_mdm_config(
            bedrock_region="eu-west-1",
            model_aliases=["opus", "sonnet", "haiku"],
            profile_name="ClaudeCode",
        )
        assert config == {
            "inferenceProvider": "bedrock",
            "inferenceBedrockRegion": "eu-west-1",
            "inferenceBedrockProfile": "ClaudeCode",
            "inferenceModels": ["opus", "sonnet", "haiku"],
            "isClaudeCodeForDesktopEnabled": True,
            "isDesktopExtensionEnabled": True,
            "isDesktopExtensionDirectoryEnabled": True,
            "isDesktopExtensionSignatureRequired": True,
            "isLocalDevMcpEnabled": True,
        }

    def test_extra_keys_merged(self):
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            extra_keys={"coworkWebSearchEnabled": "true"},
        )
        assert config["coworkWebSearchEnabled"] == "true"


class TestGenerateRegFile:
    def test_reg_has_bedrock_profile_no_helper(self, tmp_path):
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["sonnet"],
            profile_name="Test",
        )
        reg_path = generate_reg_file(tmp_path, config)
        content = reg_path.read_text(encoding="utf-8")
        assert "inferenceBedrockProfile" in content
        assert "inferenceCredentialHelper" not in content


class TestGenerateJson:
    def test_json_includes_bedrock_profile(self, tmp_path):
        config = build_mdm_config(
            bedrock_region="us-west-2",
            model_aliases=["opus", "sonnet"],
            profile_name="MyProfile",
        )
        json_path = generate_json(tmp_path, config)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["inferenceBedrockProfile"] == "MyProfile"
        assert "inferenceCredentialHelper" not in data
