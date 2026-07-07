# ABOUTME: Tests for the /api/bootstrap-style handlers in index.py
# ABOUTME: api_bootstrap (session cookie), api_bootstrap_with_jwt (OIDC access token via Cognito GetUser)

import json
import time

import boto3

from tests.conftest import mock_cognito_get_user


def _s3(idx):
    return boto3.client('s3', region_name='us-east-1')


def _seed_bootstrap_json(idx, bucket, config_key, extra=None):
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


def _seed_admin_config_with_group(idx, bucket, group_name='Claude-Code-Developers'):
    admin_config = {'mappings': [{'groupName': group_name, 'groupId': 'g-1'}]}
    _s3(idx).put_object(
        Bucket=bucket,
        Key='admin/config.json',
        Body=json.dumps(admin_config).encode('utf-8'),
    )


class TestApiBootstrapWithJwt:
    def test_returns_config_for_matched_group(self, idx, bucket, monkeypatch):
        _seed_admin_config_with_group(idx, bucket)
        _seed_bootstrap_json(idx, bucket, config_key='developer')
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])
        mock_cognito_get_user(idx, monkeypatch, email='alice@example.com')

        result = idx.api_bootstrap_with_jwt('a-valid-looking-access-token')
        body = json.loads(result['body'])

        assert result['statusCode'] == 200
        assert body['inferenceBedrockRegion'] == 'us-east-1'
        assert body['isLocalDevMcpEnabled'] is True
        # No managedMcpServers seeded in this test's bootstrap.json, so none forwarded
        assert 'managedMcpServers' not in body

    def test_token_cognito_rejects_returns_401(self, idx, bucket, monkeypatch):
        """verify_cognito_access_token() returning None (e.g. Cognito's
        GetUser call failed - expired, revoked, or malformed token) must
        result in 401, not be silently accepted."""
        monkeypatch.setattr(idx, 'verify_cognito_access_token', lambda token: None)
        result = idx.api_bootstrap_with_jwt('garbage-token')
        assert result['statusCode'] == 401

    def test_empty_token_returns_401(self, idx, bucket):
        result = idx.api_bootstrap_with_jwt('')
        assert result['statusCode'] == 401

    def test_no_matching_group_returns_403(self, idx, bucket, monkeypatch):
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: [])
        mock_cognito_get_user(idx, monkeypatch, email='alice@example.com')

        result = idx.api_bootstrap_with_jwt('a-valid-looking-access-token')
        assert result['statusCode'] == 403

    def test_expiresAt_is_set_and_in_the_future(self, idx, bucket, monkeypatch):
        _seed_admin_config_with_group(idx, bucket)
        _seed_bootstrap_json(idx, bucket, config_key='developer')
        monkeypatch.setattr(idx, 'get_user_idc_groups', lambda email: ['Claude-Code-Developers'])
        mock_cognito_get_user(idx, monkeypatch, email='alice@example.com')

        result = idx.api_bootstrap_with_jwt('a-valid-looking-access-token')
        body = json.loads(result['body'])

        assert body['expiresAt'] > time.time()
