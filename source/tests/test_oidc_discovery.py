# ABOUTME: Tests for OIDC discovery helpers — well-known endpoint fetch and TLS thumbprint
# ABOUTME: All network calls are mocked; failure modes must surface as OidcDiscoveryError

import socket
import ssl
from unittest.mock import MagicMock, patch

import pytest
import requests

from claude_code_with_bedrock.cli.utils.oidc_discovery import (
    OidcDiscoveryError,
    compute_jwks_thumbprint,
    discover_oidc_endpoints,
)

# --- discover_oidc_endpoints --------------------------------------------------


class TestDiscoverEndpoints:
    def _mock_response(self, status_code=200, json_data=None, raises_value_error=False):
        response = MagicMock()
        response.status_code = status_code
        if raises_value_error:
            response.json.side_effect = ValueError("not json")
        else:
            response.json.return_value = json_data
        return response

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_happy_path(self, mock_get):
        mock_get.return_value = self._mock_response(json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/as/authorization.oauth2",
            "token_endpoint": "https://auth.example.com/as/token.oauth2",
            "jwks_uri": "https://auth.example.com/pf/JWKS",
            "scopes_supported": ["openid", "profile"],  # extra fields ignored
        })

        result = discover_oidc_endpoints("https://auth.example.com")

        assert result == {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/as/authorization.oauth2",
            "token_endpoint": "https://auth.example.com/as/token.oauth2",
            "jwks_uri": "https://auth.example.com/pf/JWKS",
        }
        mock_get.assert_called_once_with(
            "https://auth.example.com/.well-known/openid-configuration", timeout=10.0
        )

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_strips_trailing_slash_from_issuer(self, mock_get):
        mock_get.return_value = self._mock_response(json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/auth",
            "token_endpoint": "https://auth.example.com/token",
            "jwks_uri": "https://auth.example.com/jwks",
        })

        discover_oidc_endpoints("https://auth.example.com/")

        # Trailing slash stripped before /.well-known is appended
        mock_get.assert_called_once_with(
            "https://auth.example.com/.well-known/openid-configuration", timeout=10.0
        )

    def test_rejects_http_scheme(self):
        with pytest.raises(OidcDiscoveryError, match="must start with https"):
            discover_oidc_endpoints("http://auth.example.com")

    def test_rejects_no_scheme(self):
        with pytest.raises(OidcDiscoveryError, match="must start with https"):
            discover_oidc_endpoints("auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("DNS lookup failed")
        with pytest.raises(OidcDiscoveryError, match="Could not reach"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(OidcDiscoveryError, match="Could not reach"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_404(self, mock_get):
        mock_get.return_value = self._mock_response(status_code=404)
        with pytest.raises(OidcDiscoveryError, match="HTTP 404"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_500(self, mock_get):
        mock_get.return_value = self._mock_response(status_code=500)
        with pytest.raises(OidcDiscoveryError, match="HTTP 500"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_non_json_response(self, mock_get):
        mock_get.return_value = self._mock_response(raises_value_error=True)
        with pytest.raises(OidcDiscoveryError, match="non-JSON"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_json_array_rejected(self, mock_get):
        mock_get.return_value = self._mock_response(json_data=["not", "an", "object"])
        with pytest.raises(OidcDiscoveryError, match="not an object"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_missing_required_field(self, mock_get):
        # Missing token_endpoint and jwks_uri
        mock_get.return_value = self._mock_response(json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/auth",
        })
        with pytest.raises(OidcDiscoveryError, match="missing required fields"):
            discover_oidc_endpoints("https://auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.requests.get")
    def test_empty_string_field_treated_as_missing(self, mock_get):
        mock_get.return_value = self._mock_response(json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/auth",
            "token_endpoint": "",  # falsy — should count as missing
            "jwks_uri": "https://auth.example.com/jwks",
        })
        with pytest.raises(OidcDiscoveryError, match="token_endpoint"):
            discover_oidc_endpoints("https://auth.example.com")


# --- compute_jwks_thumbprint --------------------------------------------------


class TestComputeThumbprint:
    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.ssl.create_default_context")
    def test_happy_path(self, mock_ctx_factory, mock_connect):
        # SHA-1 of b"fake-der-cert" — verified out of band
        expected = "dfbb0083f8548e511da3b9e7029d03a519a2d1a5"
        fake_der = b"fake-der-cert"

        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = fake_der
        mock_ssock.__enter__.return_value = mock_ssock

        mock_context = MagicMock()
        mock_context.wrap_socket.return_value = mock_ssock
        mock_ctx_factory.return_value = mock_context

        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_connect.return_value = mock_sock

        result = compute_jwks_thumbprint("https://auth.example.com/pf/JWKS")

        assert result == expected
        mock_connect.assert_called_once_with(("auth.example.com", 443), timeout=10.0)
        mock_context.wrap_socket.assert_called_once_with(mock_sock, server_hostname="auth.example.com")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.ssl.create_default_context")
    def test_uses_custom_port(self, mock_ctx_factory, mock_connect):
        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = b"x"
        mock_ssock.__enter__.return_value = mock_ssock
        mock_context = MagicMock()
        mock_context.wrap_socket.return_value = mock_ssock
        mock_ctx_factory.return_value = mock_context
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_connect.return_value = mock_sock

        compute_jwks_thumbprint("https://auth.example.com:8443/jwks")

        mock_connect.assert_called_once_with(("auth.example.com", 8443), timeout=10.0)

    def test_rejects_http_scheme(self):
        with pytest.raises(OidcDiscoveryError, match="must use https"):
            compute_jwks_thumbprint("http://auth.example.com/jwks")

    def test_rejects_missing_hostname(self):
        with pytest.raises(OidcDiscoveryError, match="Could not extract hostname"):
            compute_jwks_thumbprint("https:///jwks")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    def test_dns_failure(self, mock_connect):
        mock_connect.side_effect = socket.gaierror("Name resolution failure")
        with pytest.raises(OidcDiscoveryError, match="TLS handshake .* failed"):
            compute_jwks_thumbprint("https://no-such-host.invalid/jwks")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    def test_connection_refused(self, mock_connect):
        mock_connect.side_effect = ConnectionRefusedError("refused")
        with pytest.raises(OidcDiscoveryError, match="TLS handshake"):
            compute_jwks_thumbprint("https://auth.example.com/jwks")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.ssl.create_default_context")
    def test_tls_handshake_failure(self, mock_ctx_factory, mock_connect):
        mock_context = MagicMock()
        mock_context.wrap_socket.side_effect = ssl.SSLError("handshake failed")
        mock_ctx_factory.return_value = mock_context
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_connect.return_value = mock_sock

        with pytest.raises(OidcDiscoveryError, match="TLS handshake"):
            compute_jwks_thumbprint("https://auth.example.com/jwks")

    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.socket.create_connection")
    @patch("claude_code_with_bedrock.cli.utils.oidc_discovery.ssl.create_default_context")
    def test_no_certificate_returned(self, mock_ctx_factory, mock_connect):
        mock_ssock = MagicMock()
        mock_ssock.getpeercert.return_value = None
        mock_ssock.__enter__.return_value = mock_ssock
        mock_context = MagicMock()
        mock_context.wrap_socket.return_value = mock_ssock
        mock_ctx_factory.return_value = mock_context
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_connect.return_value = mock_sock

        with pytest.raises(OidcDiscoveryError, match="No certificate"):
            compute_jwks_thumbprint("https://auth.example.com/jwks")
