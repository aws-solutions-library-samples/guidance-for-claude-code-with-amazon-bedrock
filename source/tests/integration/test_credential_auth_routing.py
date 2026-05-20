"""Integration tests for credential process auth server routing.

Validates that the MultiProviderAuth class correctly constructs OIDC endpoints
based on provider type and okta_auth_server configuration.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp directory simulating the credential binary's location."""
    return tmp_path


def _write_config(config_dir: Path, profile_name: str, config_data: dict):
    """Write a config.json to the given directory."""
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps({profile_name: config_data}))
    return config_path


class TestOktaAuthServerRouting:
    """Test Okta auth server endpoint construction."""

    def _create_auth(self, config_dir, profile_name, config_data):
        """Create MultiProviderAuth with mocked config path."""
        _write_config(config_dir, profile_name, config_data)

        with patch("credential_provider.__main__.Path") as mock_path_cls:
            # Make the binary_dir / "config.json" resolve to our temp config
            mock_path_cls.return_value = config_dir
            # Simpler: patch __file__ parent to return our config_dir
            pass

        # Directly patch _load_config to return our config
        from credential_provider.__main__ import MultiProviderAuth

        with patch.object(MultiProviderAuth, "_load_config", return_value=config_data), \
             patch.object(MultiProviderAuth, "_init_credential_storage"):
            auth = MultiProviderAuth(profile=profile_name)

        return auth

    def test_okta_custom_auth_server(self, config_dir):
        """Custom auth server → /oauth2/{server}/v1/ endpoints."""
        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "okta_auth_server": "aus123456789",
            "provider_type": "okta",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, "TestProfile", config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/aus123456789/v1/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/aus123456789/v1/token"

    def test_okta_default_auth_server(self, config_dir):
        """'default' auth server → /oauth2/default/v1/ endpoints."""
        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "okta_auth_server": "default",
            "provider_type": "okta",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, "TestProfile", config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/default/v1/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/default/v1/token"

    def test_okta_org_auth_server_empty_string(self, config_dir):
        """Empty okta_auth_server → Org auth server endpoints (no server segment)."""
        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "okta_auth_server": "",
            "provider_type": "okta",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, "TestProfile", config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/v1/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/v1/token"

    def test_okta_no_auth_server_field(self, config_dir):
        """Missing okta_auth_server field → falls back to Org auth server."""
        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "provider_type": "okta",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, "TestProfile", config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/v1/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/v1/token"


class TestProviderTypeRouting:
    """Test that different provider types get correct endpoint templates."""

    def _create_auth(self, config_dir, config_data, profile_name="TestProfile"):
        _write_config(config_dir, profile_name, config_data)

        from credential_provider.__main__ import MultiProviderAuth

        with patch.object(MultiProviderAuth, "_load_config", return_value=config_data), \
             patch.object(MultiProviderAuth, "_init_credential_storage"):
            auth = MultiProviderAuth(profile=profile_name)

        return auth

    def test_azure_endpoints(self, config_dir):
        """Azure AD provider uses /oauth2/v2.0/ endpoints."""
        config_data = {
            "provider_domain": "login.microsoftonline.com/tenant-id",
            "client_id": "azure-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "provider_type": "azure",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/v2.0/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/v2.0/token"

    def test_auth0_endpoints(self, config_dir):
        """Auth0 provider uses /authorize and /oauth/token."""
        config_data = {
            "provider_domain": "mycompany.auth0.com",
            "client_id": "auth0-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "provider_type": "auth0",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, config_data)

        assert auth.provider_config["authorize_endpoint"] == "/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth/token"

    def test_cognito_endpoints(self, config_dir):
        """Cognito provider uses /oauth2/ endpoints."""
        config_data = {
            "provider_domain": "mypool.auth.us-east-1.amazoncognito.com",
            "client_id": "cognito-client-id",
            "identity_pool_id": "us-east-1:pool-id",
            "provider_type": "cognito",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = self._create_auth(config_dir, config_data)

        assert auth.provider_config["authorize_endpoint"] == "/oauth2/authorize"
        assert auth.provider_config["token_endpoint"] == "/oauth2/token"

    def test_unknown_provider_raises(self, config_dir):
        """Unknown provider type raises ValueError."""
        config_data = {
            "provider_domain": "unknown.example.com",
            "client_id": "some-client",
            "identity_pool_id": "us-east-1:pool-id",
            "provider_type": "unsupported_provider",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        from credential_provider.__main__ import MultiProviderAuth

        with patch.object(MultiProviderAuth, "_load_config", return_value=config_data), \
             patch.object(MultiProviderAuth, "_init_credential_storage"):
            with pytest.raises(ValueError, match="Unknown provider type"):
                MultiProviderAuth(profile="TestProfile")


class TestFederationTypeDetection:
    """Test that federation type (cognito vs direct STS) is detected correctly."""

    def test_direct_sts_federation(self):
        """federated_role_arn present → direct STS federation detected."""
        from credential_provider.__main__ import MultiProviderAuth

        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client",
            "federated_role_arn": "arn:aws:iam::123456789:role/BedrockRole",
            "provider_type": "okta",
            "okta_auth_server": "default",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = MultiProviderAuth.__new__(MultiProviderAuth)
        auth.debug = False
        auth._detect_federation_type(config_data)

        assert config_data["federation_type"] == "direct"

    def test_cognito_federation(self):
        """identity_pool_id present, no role → cognito federation detected."""
        from credential_provider.__main__ import MultiProviderAuth

        config_data = {
            "provider_domain": "mycompany.okta.com",
            "client_id": "test-client",
            "identity_pool_id": "us-east-1:abc-123",
            "provider_type": "okta",
            "okta_auth_server": "default",
            "aws_region": "us-east-1",
            "credential_storage": "session",
        }

        auth = MultiProviderAuth.__new__(MultiProviderAuth)
        auth.debug = False
        auth._detect_federation_type(config_data)

        assert config_data["federation_type"] == "cognito"
