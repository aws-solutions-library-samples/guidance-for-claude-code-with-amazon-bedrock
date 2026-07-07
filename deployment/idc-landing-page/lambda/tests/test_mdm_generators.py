# ABOUTME: Tests for generate_mobileconfig/generate_reg_file in index.py (macOS/Windows MDM output)
# ABOUTME: These wrap the config dict as plist XML / .reg text - verifies key policy values round-trip

import json


def base_config():
    return {
        'inferenceProvider': 'bedrock',
        'inferenceCredentialKind': 'interactive',
        'inferenceBedrockRegion': 'us-east-1',
        'inferenceBedrockSsoStartUrl': 'https://d-test.awsapps.com/start',
        'inferenceBedrockSsoRegion': 'us-east-1',
        'inferenceBedrockSsoAccountId': '123456789012',
        'inferenceBedrockSsoRoleName': 'ClaudeCodeDeveloper',
        'inferenceModels': [{'name': 'us.anthropic.claude-sonnet-4', 'labelOverride': 'Sonnet'}],
        'deploymentOrganizationUuid': 'TEST-UUID',
    }


class TestGenerateMobileconfig:
    def test_contains_required_plist_structure(self, idx):
        xml = idx.generate_mobileconfig(base_config(), 'TEST-UUID', 'developer')
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert '<key>PayloadType</key>' in xml
        assert '<string>Configuration</string>' in xml

    def test_isLocalDevMcpEnabled_true_emitted_as_true_tag(self, idx):
        config = base_config()
        config['isLocalDevMcpEnabled'] = True
        xml = idx.generate_mobileconfig(config, 'TEST-UUID', 'developer')
        assert '<key>isLocalDevMcpEnabled</key>' in xml
        assert '<true/>' in xml

    def test_isLocalDevMcpEnabled_false_emitted_as_false_tag(self, idx):
        config = base_config()
        config['isLocalDevMcpEnabled'] = False
        xml = idx.generate_mobileconfig(config, 'TEST-UUID', 'developer')
        assert '<key>isLocalDevMcpEnabled</key>' in xml
        assert '<false/>' in xml

    def test_bootstrap_oidc_included_when_both_url_and_oidc_present(self, idx):
        oidc = {'clientId': 'abc', 'issuer': 'https://issuer.example.com', 'scopes': 'openid', 'redirectPort': 8080}
        xml = idx.generate_mobileconfig(
            base_config(), 'TEST-UUID', 'developer',
            bootstrap_url='https://bootstrap.example.com/api/bootstrap',
            bootstrap_oidc=oidc,
        )
        assert '<key>bootstrapEnabled</key>' in xml
        assert 'https://bootstrap.example.com/api/bootstrap' in xml
        assert json.dumps(oidc) in xml

    def test_bootstrap_omitted_when_url_missing(self, idx):
        xml = idx.generate_mobileconfig(base_config(), 'TEST-UUID', 'developer', bootstrap_url=None, bootstrap_oidc=None)
        assert 'bootstrapEnabled' not in xml

    def test_stdio_mcp_server_templates_rendered_as_managedMcpServers(self, idx):
        config = base_config()
        config['mcpServerTemplates'] = [
            {'name': 'internal-tool', 'command': 'npx', 'args': ['-y', 'my-mcp-server']},
        ]
        xml = idx.generate_mobileconfig(config, 'TEST-UUID', 'developer')
        assert '<key>managedMcpServers</key>' in xml
        assert '"transport": "stdio"' in xml
        assert '"command": "npx"' in xml


class TestGenerateRegFile:
    def test_is_utf16_safe_ascii_content(self, idx):
        content = idx.generate_reg_file(base_config(), 'developer')
        assert content.startswith('Windows Registry Editor Version 5.00')

    def test_isLocalDevMcpEnabled_true_is_dword_1(self, idx):
        config = base_config()
        config['isLocalDevMcpEnabled'] = True
        content = idx.generate_reg_file(config, 'developer')
        assert '"isLocalDevMcpEnabled"=dword:00000001' in content

    def test_isLocalDevMcpEnabled_false_is_dword_0(self, idx):
        config = base_config()
        config['isLocalDevMcpEnabled'] = False
        content = idx.generate_reg_file(config, 'developer')
        assert '"isLocalDevMcpEnabled"=dword:00000000' in content

    def test_can_be_encoded_as_utf16_le(self, idx):
        content = idx.generate_reg_file(base_config(), 'developer')
        # Must not raise - this is exactly how index.py writes it to S3
        encoded = content.encode('utf-16-le')
        assert len(encoded) > 0
