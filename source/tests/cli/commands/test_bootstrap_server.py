# ABOUTME: Unit tests for the Claude Desktop Bootstrap Server Lambda handler
# ABOUTME: Tests token validation, response format, error handling, and config generation

"""Tests for the bootstrap_server Lambda handler."""

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# Add the lambda function directory to path for import
_LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "deployment",
        "infrastructure",
        "lambda-functions",
        "bootstrap_server",
    )
)
sys.path.insert(0, _LAMBDA_DIR)


@pytest.fixture(autouse=True)
def set_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://example.okta.com/oauth2/default")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_JWKS_ENDPOINT", "https://example.okta.com/oauth2/default/v1/keys")
    monkeypatch.setenv("DEFAULT_INFERENCE_REGION", "us-west-2")
    monkeypatch.setenv(
        "DEFAULT_INFERENCE_MODELS",
        "us.anthropic.claude-sonnet-4-20250514-v1:0,us.anthropic.claude-opus-4-20250514-v1:0",
    )
    monkeypatch.setenv("OTLP_ENDPOINT", "https://otel.example.com/v1/traces")
    monkeypatch.setenv("INFERENCE_SESSION_LIFETIME_SEC", "14400")


@pytest.fixture
def reload_handler(set_env_vars):
    """Reload the handler module after env vars are set."""
    import importlib.util

    # Remove any cached 'index' module to avoid cross-test pollution
    if "index" in sys.modules:
        del sys.modules["index"]

    # Load specifically from the bootstrap_server directory
    spec = importlib.util.spec_from_file_location("index", os.path.join(_LAMBDA_DIR, "index.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["index"] = module
    spec.loader.exec_module(module)
    return module


class TestLambdaHandler:
    """Tests for lambda_handler function."""

    def test_missing_authorization_header(self, reload_handler):
        """Should return 401 when Authorization header is missing."""
        event = {"headers": {}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "unauthorized"
        assert "Missing Authorization header" in body["message"]

    def test_invalid_auth_scheme(self, reload_handler):
        """Should return 401 when auth scheme is not Bearer."""
        event = {"headers": {"authorization": "Basic dXNlcjpwYXNz"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "unauthorized"
        assert "Bearer" in body["message"]

    def test_empty_bearer_token(self, reload_handler):
        """Should return 401 when Bearer token is empty."""
        event = {"headers": {"authorization": "Bearer "}}

        with patch.object(reload_handler, "_validate_token", side_effect=ValueError("No token provided")):
            response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401

    @patch("index._validate_token")
    def test_expired_token(self, mock_validate, reload_handler):
        """Should return 401 with token_expired error for expired tokens."""
        mock_validate.side_effect = ValueError("Token has expired")

        event = {"headers": {"authorization": "Bearer expired.token.here"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "token_expired"

    @patch("index._validate_token")
    def test_invalid_issuer(self, mock_validate, reload_handler):
        """Should return 403 for invalid issuer."""
        mock_validate.side_effect = ValueError("Invalid token issuer")

        event = {"headers": {"authorization": "Bearer bad.issuer.token"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert body["error"] == "forbidden"

    @patch("index._validate_token")
    def test_invalid_audience(self, mock_validate, reload_handler):
        """Should return 403 for invalid audience."""
        mock_validate.side_effect = ValueError("Invalid token audience")

        event = {"headers": {"authorization": "Bearer bad.audience.token"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert body["error"] == "forbidden"

    @patch("index._validate_token")
    def test_invalid_signature(self, mock_validate, reload_handler):
        """Should return 401 for invalid signature."""
        mock_validate.side_effect = ValueError("Invalid token signature")

        event = {"headers": {"authorization": "Bearer bad.sig.token"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "unauthorized"

    @patch("index._validate_token")
    def test_successful_config_response(self, mock_validate, reload_handler):
        """Should return 200 with full config for valid token."""
        mock_validate.return_value = {
            "sub": "user123",
            "email": "user@example.com",
            "iss": "https://example.okta.com/oauth2/default",
            "aud": "test-client-id",
            "exp": int(time.time()) + 3600,
        }

        event = {"headers": {"authorization": "Bearer valid.token.here"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])

        # Check required fields
        assert body["inferenceProvider"] == "bedrock"
        assert body["inferenceRegion"] == "us-west-2"
        assert body["inferenceModels"] == [
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "us.anthropic.claude-opus-4-20250514-v1:0",
        ]
        assert body["inferenceSessionLifetimeSec"] == 14400
        assert "expiresAt" in body
        assert body["expiresAt"] > int(time.time())

        # Check user info
        assert body["user"]["sub"] == "user123"
        assert body["user"]["email"] == "user@example.com"

        # Check OTEL config
        assert body["otlpEndpoint"] == "https://otel.example.com/v1/traces"
        assert body["otlpHeaders"]["x-user-id"] == "user123"
        assert body["otlpHeaders"]["x-user-email"] == "user@example.com"

    @patch("index._validate_token")
    def test_cache_control_header(self, mock_validate, reload_handler):
        """Should include Cache-Control: no-store in all responses."""
        mock_validate.return_value = {
            "sub": "user123",
            "email": "user@example.com",
        }

        event = {"headers": {"authorization": "Bearer valid.token.here"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["headers"]["Cache-Control"] == "no-store"

    @patch("index._validate_token")
    def test_content_type_header(self, mock_validate, reload_handler):
        """Should return application/json content type."""
        mock_validate.return_value = {
            "sub": "user123",
            "email": "user@example.com",
        }

        event = {"headers": {"authorization": "Bearer valid.token.here"}}
        response = reload_handler.lambda_handler(event, None)

        assert response["headers"]["Content-Type"] == "application/json"

    @patch("index._validate_token")
    def test_no_otel_when_endpoint_empty(self, mock_validate, reload_handler, monkeypatch):
        """Should not include OTEL fields when endpoint is empty."""
        monkeypatch.setenv("OTLP_ENDPOINT", "")
        # Reload to pick up new env var using explicit path (avoids module collision)
        import importlib.util

        if "index" in sys.modules:
            del sys.modules["index"]
        spec = importlib.util.spec_from_file_location("index", os.path.join(_LAMBDA_DIR, "index.py"))
        handler = importlib.util.module_from_spec(spec)
        sys.modules["index"] = handler
        spec.loader.exec_module(handler)

        mock_validate_new = MagicMock(
            return_value={
                "sub": "user123",
                "email": "user@example.com",
            }
        )

        with patch.object(handler, "_validate_token", mock_validate_new):
            event = {"headers": {"authorization": "Bearer valid.token.here"}}
            response = handler.lambda_handler(event, None)

        body = json.loads(response["body"])
        assert "otlpEndpoint" not in body
        assert "otlpHeaders" not in body

    @patch("index._validate_token")
    def test_user_identity_from_sub_claim(self, mock_validate, reload_handler):
        """Should extract user identity from sub claim."""
        mock_validate.return_value = {
            "sub": "auth0|abc123",
            "preferred_username": "jsmith",
        }

        event = {"headers": {"authorization": "Bearer valid.token.here"}}
        response = reload_handler.lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["user"]["sub"] == "auth0|abc123"
        # Falls back to preferred_username when email is missing
        assert body["user"]["email"] == "jsmith"

    @patch("index._validate_token")
    def test_expires_at_is_one_hour_from_now(self, mock_validate, reload_handler):
        """Should set expiresAt to approximately 1 hour from now."""
        mock_validate.return_value = {"sub": "user123", "email": "test@test.com"}

        event = {"headers": {"authorization": "Bearer valid.token.here"}}
        before = int(time.time()) + 3600
        response = reload_handler.lambda_handler(event, None)
        after = int(time.time()) + 3600

        body = json.loads(response["body"])
        assert before <= body["expiresAt"] <= after

    def test_unhandled_exception_returns_500(self, reload_handler):
        """Should return 500 for unhandled exceptions without leaking details."""
        # Trigger an unexpected error by passing a non-dict event
        with patch.object(reload_handler, "_validate_token", side_effect=RuntimeError("unexpected")):
            event = {"headers": {"authorization": "Bearer valid.token.here"}}
            response = reload_handler.lambda_handler(event, None)

            # The RuntimeError is caught by the outer handler
            assert response["statusCode"] == 500
            body = json.loads(response["body"])
            assert body["error"] == "internal_error"
            assert "unexpected" not in body["message"]  # Don't leak internal error

    def test_authorization_header_case_insensitive(self, reload_handler):
        """Should handle Authorization header in different cases."""
        # API Gateway v2 normalizes headers to lowercase
        event = {"headers": {"Authorization": ""}}
        response = reload_handler.lambda_handler(event, None)

        assert response["statusCode"] == 401


class TestValidateToken:
    """Tests for _validate_token function."""

    def test_empty_token_raises(self, reload_handler):
        """Should raise ValueError for empty token."""
        with pytest.raises(ValueError, match="No token provided"):
            reload_handler._validate_token("")

    def test_none_token_raises(self, reload_handler):
        """Should raise ValueError for None token."""
        with pytest.raises(ValueError, match="No token provided"):
            reload_handler._validate_token(None)

    @patch("index.HAS_PYJWT", False)
    def test_no_pyjwt_raises(self, reload_handler):
        """Should raise ValueError when PyJWT is not available."""
        reload_handler.HAS_PYJWT = False
        with pytest.raises(ValueError, match="PyJWT library not available"):
            reload_handler._validate_token("some.token.here")
        reload_handler.HAS_PYJWT = True  # restore


class TestBuildConfigResponse:
    """Tests for _build_config_response function."""

    def test_basic_config_structure(self, reload_handler):
        """Should return properly structured config."""
        claims = {"sub": "user1", "email": "user1@example.com"}
        config = reload_handler._build_config_response(claims)

        assert config["inferenceProvider"] == "bedrock"
        assert config["inferenceRegion"] == "us-west-2"
        assert isinstance(config["inferenceModels"], list)
        assert config["inferenceSessionLifetimeSec"] == 14400
        assert "expiresAt" in config
        assert config["user"]["sub"] == "user1"
        assert config["user"]["email"] == "user1@example.com"

    def test_models_parsed_from_comma_separated(self, reload_handler):
        """Should parse comma-separated model list."""
        claims = {"sub": "u", "email": "e"}
        config = reload_handler._build_config_response(claims)

        assert len(config["inferenceModels"]) == 2
        assert "us.anthropic.claude-sonnet-4-20250514-v1:0" in config["inferenceModels"]
        assert "us.anthropic.claude-opus-4-20250514-v1:0" in config["inferenceModels"]

    def test_fallback_to_sub_when_no_email(self, reload_handler):
        """Should use sub claim when email is missing."""
        claims = {"sub": "user-sub-id"}
        config = reload_handler._build_config_response(claims)

        assert config["user"]["email"] == "user-sub-id"
