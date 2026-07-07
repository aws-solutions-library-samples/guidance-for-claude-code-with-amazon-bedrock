# ABOUTME: Regression tests for the bootstrap.json feature-toggle omission bug
# ABOUTME: Bootstrap responses must explicitly set every feature toggle key,
# ABOUTME: since Claude Desktop treats an omitted bootstrap key as "unset", not
# ABOUTME: "inherit from MDM" (see docs.claude.com/.../bootstrap#response-schema).

import json

import boto3
import pytest


FEATURE_TOGGLE_KEYS = [
    'isLocalDevMcpEnabled',
    'isDesktopExtensionEnabled',
    'isDesktopExtensionSignatureRequired',
    'coworkTabEnabled',
    'disableBundledSkills',
    'disableDeploymentModeChooser',
]


def _s3(idx):
    return boto3.client('s3', region_name='us-east-1')


def _run_generate_mdm_configs(idx, bucket, policies):
    """Call generate_mdm_configs with a minimal, valid set of arguments."""
    idx.generate_mdm_configs(
        config_key='developer',
        idc_start_url='https://d-test.awsapps.com/start',
        region='us-east-1',
        account_id='123456789012',
        role_name='ClaudeCodeDeveloper',
        models_list=[{'modelId': 'anthropic.claude-sonnet-4', 'modelName': 'Sonnet'}],
        policies=policies,
        managed_mcp_servers=[],
        mcp_server_templates=[],
        base_url='https://bootstrap.example.com',
    )


def _load_json_key(idx, bucket, key):
    s3 = _s3(idx)
    body = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
    return json.loads(body)


class TestBootstrapJsonAlwaysHasFeatureToggles:
    """bootstrap.json must contain every feature-toggle key explicitly,
    regardless of whether the value matches the app default."""

    @pytest.mark.parametrize('policies', [
        {},  # no policies configured -> everything should default explicitly
        {'isLocalDevMcpEnabled': True},
        {'isLocalDevMcpEnabled': False},
        {'isDesktopExtensionEnabled': False},
        {'coworkTabEnabled': False},
        {'disableBundledSkills': True},
        {'disableDeploymentModeChooser': False},
    ])
    def test_all_toggle_keys_present_in_bootstrap_json(self, idx, bucket, policies):
        _run_generate_mdm_configs(idx, bucket, policies)
        bootstrap_config = _load_json_key(idx, bucket, 'config/developer/bootstrap.json')

        for key in FEATURE_TOGGLE_KEYS:
            assert key in bootstrap_config, (
                f"bootstrap.json is missing '{key}'. Claude Desktop treats "
                f"omitted bootstrap keys as unset (not inherited from MDM), "
                f"so this key would silently disable/reset that feature."
            )

    def test_true_isLocalDevMcpEnabled_is_explicit_not_omitted(self, idx, bucket):
        """This is the exact bug: isLocalDevMcpEnabled=True (the default) used
        to be omitted from bootstrap.json because the writer only special-cased
        the False branch. Desktop then read it as unset instead of True,
        blocking local/stdio MCP servers even though MDM said they were allowed."""
        _run_generate_mdm_configs(idx, bucket, policies={'isLocalDevMcpEnabled': True})
        bootstrap_config = _load_json_key(idx, bucket, 'config/developer/bootstrap.json')
        assert bootstrap_config['isLocalDevMcpEnabled'] is True

    def test_false_isLocalDevMcpEnabled_is_preserved(self, idx, bucket):
        _run_generate_mdm_configs(idx, bucket, policies={'isLocalDevMcpEnabled': False})
        bootstrap_config = _load_json_key(idx, bucket, 'config/developer/bootstrap.json')
        assert bootstrap_config['isLocalDevMcpEnabled'] is False

    def test_default_json_still_omits_default_values(self, idx, bucket):
        """default.json (the static/MDM-oriented export) intentionally keeps
        omitting default-valued toggles - only bootstrap.json needs to be
        exhaustive. This guards against 'fixing' this by also bloating
        default.json unnecessarily."""
        _run_generate_mdm_configs(idx, bucket, policies={'isLocalDevMcpEnabled': True})
        default_config = _load_json_key(idx, bucket, 'config/developer/default.json')
        assert 'isLocalDevMcpEnabled' not in default_config


class TestBootstrapServingEndpointsPassThroughToggles:
    """The three /api/bootstrap-style handlers all read bootstrap.json from S3
    and copy over a fixed allowlist of policy_keys. As long as
    generate_mdm_configs() writes isLocalDevMcpEnabled explicitly, these
    handlers will forward it correctly. This test locks in that contract."""

    def _seed_bootstrap_json(self, idx, bucket, config_key, extra=None):
        payload = {
            'inferenceProvider': 'bedrock',
            'inferenceCredentialKind': 'interactive',
            'inferenceBedrockRegion': 'us-east-1',
            'inferenceModels': [{'name': 'us.anthropic.claude-sonnet-4', 'labelOverride': 'Sonnet'}],
            'deploymentOrganizationUuid': 'TEST-UUID',
            'isLocalDevMcpEnabled': True,
        }
        if extra:
            payload.update(extra)
        _s3(idx).put_object(
            Bucket=bucket,
            Key=f'config/{config_key}/bootstrap.json',
            Body=json.dumps(payload).encode('utf-8'),
        )

    def _seed_admin_config_with_group(self, idx, bucket, group_name='Claude-Code-Developers'):
        admin_config = {'mappings': [{'groupName': group_name, 'groupId': 'g-1'}]}
        _s3(idx).put_object(
            Bucket=bucket,
            Key='admin/config.json',
            Body=json.dumps(admin_config).encode('utf-8'),
        )

    def test_api_bootstrap_forwards_true_isLocalDevMcpEnabled(self, idx, bucket, monkeypatch):
        self._seed_admin_config_with_group(idx, bucket)
        self._seed_bootstrap_json(idx, bucket, config_key='developer', extra={'isLocalDevMcpEnabled': True})

        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.api_bootstrap({'email': 'alice@example.com'}, base_url='https://example.com')
        body = json.loads(result['body'])

        assert body.get('isLocalDevMcpEnabled') is True

    def test_api_bootstrap_forwards_false_isLocalDevMcpEnabled(self, idx, bucket, monkeypatch):
        self._seed_admin_config_with_group(idx, bucket)
        self._seed_bootstrap_json(idx, bucket, config_key='developer', extra={'isLocalDevMcpEnabled': False})

        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.api_bootstrap({'email': 'alice@example.com'}, base_url='https://example.com')
        body = json.loads(result['body'])

        assert body.get('isLocalDevMcpEnabled') is False

    def test_api_bootstrap_drops_stdio_managedMcpServers(self, idx, bucket, monkeypatch):
        """stdio-transport managedMcpServers entries must stay MDM-only - a
        bootstrap response cannot nominate local commands to run. Only
        http/sse entries are safe to forward over bootstrap."""
        self._seed_admin_config_with_group(idx, bucket)
        self._seed_bootstrap_json(
            idx, bucket, config_key='developer',
            extra={'managedMcpServers': [{'name': 'x', 'transport': 'stdio', 'command': 'foo'}]},
        )
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.api_bootstrap({'email': 'alice@example.com'}, base_url='https://example.com')
        body = json.loads(result['body'])

        assert 'managedMcpServers' not in body

    def test_api_bootstrap_forwards_http_managedMcpServers(self, idx, bucket, monkeypatch):
        """http/sse-transport managedMcpServers entries (e.g. AWS Knowledge
        MCP Server, AgentCore Gateway-backed servers) ARE safe over bootstrap
        and must be forwarded - Desktop's own client-side rules already
        permit network-based MCP servers via bootstrap."""
        self._seed_admin_config_with_group(idx, bucket)
        self._seed_bootstrap_json(
            idx, bucket, config_key='developer',
            extra={'managedMcpServers': [
                {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
            ]},
        )
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.api_bootstrap({'email': 'alice@example.com'}, base_url='https://example.com')
        body = json.loads(result['body'])

        assert body.get('managedMcpServers') == [
            {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
        ]

    def test_api_bootstrap_forwards_only_http_when_mixed_with_stdio(self, idx, bucket, monkeypatch):
        """A mix of stdio and http entries must only forward the http ones."""
        self._seed_admin_config_with_group(idx, bucket)
        self._seed_bootstrap_json(
            idx, bucket, config_key='developer',
            extra={'managedMcpServers': [
                {'name': 'local-tool', 'transport': 'stdio', 'command': 'foo'},
                {'name': 'aws-knowledge', 'transport': 'http', 'url': 'https://knowledge-mcp.global.api.aws'},
            ]},
        )
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])

        result = idx.api_bootstrap({'email': 'alice@example.com'}, base_url='https://example.com')
        body = json.loads(result['body'])

        names = [s['name'] for s in body.get('managedMcpServers', [])]
        assert names == ['aws-knowledge']
