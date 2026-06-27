# ABOUTME: Tests for the bootstrap_device_code Lambda function
# ABOUTME: Covers device-code generation, bootstrap response fields, plugins, and authorizer

"""Tests for bootstrap_device_code Lambda: handler + authorizer."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

LAMBDA_DIR = (
    Path(__file__).resolve().parents[2]
    / "deployment"
    / "infrastructure"
    / "lambda-functions"
    / "bootstrap_device_code"
)

INDEX_PATH = LAMBDA_DIR / "index.py"
AUTHORIZER_PATH = LAMBDA_DIR / "authorizer.py"


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://idp.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    monkeypatch.setenv("OIDC_TOKEN_ENDPOINT", "https://idp.example.com/oauth/token")
    monkeypatch.setenv("OIDC_AUTHORIZE_ENDPOINT", "https://idp.example.com/authorize")
    monkeypatch.setenv("OIDC_JWKS_ENDPOINT", "https://idp.example.com/.well-known/jwks.json")
    monkeypatch.setenv("INFERENCE_REGION", "us-west-2")
    monkeypatch.setenv("INFERENCE_MODELS", "claude-sonnet-4-20250514,claude-haiku-4-20250414")
    monkeypatch.setenv("API_BASE_URL", "https://bootstrap.example.com")
    monkeypatch.setenv("PLUGINS_REGISTRY_JSON", json.dumps({
        "plugins": [
            {"name": "example-org-policy", "version": "1.0.0", "url": "https://example.com/plugin.zip"}
        ]
    }))


def _load_module(path: Path, name_suffix: str = "") -> object:
    """Load a Lambda module fresh using importlib to avoid collisions."""
    module_name = f"bootstrap_device_code_{name_suffix}_{id(path)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    # Mock boto3 to avoid real AWS calls during import
    mock_boto3 = MagicMock()
    mock_table = MagicMock()
    mock_boto3.resource.return_value.Table.return_value = mock_table
    mock_boto3.client.return_value = MagicMock()

    with patch.dict(sys.modules, {"boto3": mock_boto3, "boto3.dynamodb.conditions": MagicMock()}):
        spec.loader.exec_module(module)

    return module


# ---------------------------------------------------------------------------
# Test generate_user_code
# ---------------------------------------------------------------------------


class TestGenerateUserCode:
    """Tests for user code generation."""

    def test_user_code_format(self):
        """User code should be 8 uppercase chars with a hyphen (XXXX-XXXX)."""
        module = _load_module(INDEX_PATH, "user_code")
        code = module.generate_user_code()
        assert len(code) == 9  # 4 + 1 (hyphen) + 4
        assert code[4] == "-"
        assert code[:4].isupper()
        assert code[5:].isupper()
        assert code[:4].isalpha()
        assert code[5:].isalpha()

    def test_user_code_excludes_ambiguous_chars(self):
        """User code should not contain O, I, or L (ambiguous chars)."""
        module = _load_module(INDEX_PATH, "user_code_chars")
        # Generate many codes to check probabilistically
        for _ in range(100):
            code = module.generate_user_code()
            for char in code.replace("-", ""):
                assert char not in ("O", "I", "L"), f"Ambiguous char {char} found in {code}"


# ---------------------------------------------------------------------------
# Test handle_device_code
# ---------------------------------------------------------------------------


class TestHandleDeviceCode:
    """Tests for POST /device/code handler."""

    def test_device_code_response_fields(self):
        """Response must include device_code, user_code, verification_uri."""
        module = _load_module(INDEX_PATH, "device_code")

        # Mock the table.put_item
        module.table = MagicMock()

        event = {"path": "/device/code", "httpMethod": "POST", "body": ""}
        response = module.handle_device_code(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "device_code" in body
        assert "user_code" in body
        assert "verification_uri" in body
        assert "verification_uri_complete" in body
        assert "expires_in" in body
        assert "interval" in body
        assert body["verification_uri"] == "https://bootstrap.example.com/verify"


# ---------------------------------------------------------------------------
# Test handle_bootstrap
# ---------------------------------------------------------------------------


class TestHandleBootstrap:
    """Tests for GET /bootstrap handler."""

    def test_bootstrap_response_fields(self):
        """Bootstrap response must include correct field names for Claude Desktop."""
        module = _load_module(INDEX_PATH, "bootstrap")

        event = {"path": "/bootstrap", "httpMethod": "GET"}
        response = module.handle_bootstrap(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])

        # Must have these fields
        assert body["inferenceProvider"] == "bedrock"
        assert body["inferenceBedrockRegion"] == "us-west-2"
        assert body["organizationPluginsUrl"] == "https://bootstrap.example.com/plugins/index.json"
        assert body["inferenceSessionLifetimeSec"] == 28800
        assert "expiresAt" in body
        assert isinstance(body["expiresAt"], int)

        # inferenceModels must be a JSON string (not a list)
        assert isinstance(body["inferenceModels"], str)
        models_parsed = json.loads(body["inferenceModels"])
        assert "claude-sonnet-4-20250514" in models_parsed
        assert "claude-haiku-4-20250414" in models_parsed

    def test_bootstrap_no_legacy_fields(self):
        """Bootstrap response must NOT include removed legacy fields."""
        module = _load_module(INDEX_PATH, "bootstrap_legacy")

        event = {"path": "/bootstrap", "httpMethod": "GET"}
        response = module.handle_bootstrap(event)

        body = json.loads(response["body"])
        assert "mcpServers" not in body
        assert "allowedModels" not in body
        assert "inferenceRegion" not in body


# ---------------------------------------------------------------------------
# Test handle_plugins
# ---------------------------------------------------------------------------


class TestHandlePlugins:
    """Tests for GET /plugins handler."""

    def test_plugins_returns_registry(self):
        """Plugins endpoint must return the configured registry."""
        module = _load_module(INDEX_PATH, "plugins")

        event = {"path": "/plugins/index.json", "httpMethod": "GET"}
        response = module.handle_plugins(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "plugins" in body
        assert len(body["plugins"]) == 1
        assert body["plugins"][0]["name"] == "example-org-policy"


# ---------------------------------------------------------------------------
# Test authorizer
# ---------------------------------------------------------------------------


class TestAuthorizer:
    """Tests for the REQUEST authorizer Lambda."""

    def _load_authorizer(self):
        """Load the authorizer module."""
        module_name = f"bootstrap_authorizer_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, AUTHORIZER_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def test_handshake_routes_allowed_without_token(self):
        """Handshake routes must be allowed without any auth header."""
        module = self._load_authorizer()
        handshake_paths = [
            "/.well-known/oauth-authorization-server",
            "/device/code",
            "/verify",
            "/callback",
            "/oauth/token",
        ]
        for path in handshake_paths:
            event = {
                "path": path,
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api-id/prod/GET/test",
                "headers": {},
            }
            result = module.handler(event, None)
            statement = result["policyDocument"]["Statement"][0]
            assert statement["Effect"] == "Allow", f"Expected Allow for {path}, got {statement['Effect']}"

    def test_data_routes_denied_without_token(self):
        """Data routes must be denied when no Authorization header is present."""
        module = self._load_authorizer()
        data_paths = ["/bootstrap", "/plugins", "/plugins/index.json"]
        for path in data_paths:
            event = {
                "path": path,
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api-id/prod/GET/test",
                "headers": {},
            }
            result = module.handler(event, None)
            statement = result["policyDocument"]["Statement"][0]
            assert statement["Effect"] == "Deny", f"Expected Deny for {path}, got {statement['Effect']}"

    def test_data_routes_denied_with_invalid_token(self):
        """Data routes must be denied with an invalid/malformed Bearer token."""
        module = self._load_authorizer()
        event = {
            "path": "/bootstrap",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api-id/prod/GET/test",
            "headers": {"Authorization": "Bearer invalid.token.here"},
        }
        result = module.handler(event, None)
        statement = result["policyDocument"]["Statement"][0]
        assert statement["Effect"] == "Deny"
