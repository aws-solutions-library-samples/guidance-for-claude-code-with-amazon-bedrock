# ABOUTME: OIDC discovery helpers — fetches .well-known config and computes JWKS TLS thumbprint
# ABOUTME: Used by `ccwb init` to auto-populate generic OIDC profile fields

"""OIDC discovery and JWKS TLS thumbprint computation.

Both functions raise OidcDiscoveryError on any failure. Callers should catch and
fall back to manual entry — these helpers are convenience, not correctness-critical.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

import requests


class OidcDiscoveryError(Exception):
    """Raised when discovery or thumbprint computation fails."""


REQUIRED_DISCOVERY_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")


def discover_oidc_endpoints(issuer_url: str, timeout: float = 10.0) -> dict[str, str]:
    """Fetch {issuer}/.well-known/openid-configuration and return endpoint URLs.

    Args:
        issuer_url: Issuer URL, e.g. https://auth.example.com (with or without trailing slash).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: issuer, authorization_endpoint, token_endpoint, jwks_uri.

    Raises:
        OidcDiscoveryError: On network error, non-200 response, non-JSON body, or
            missing required fields. The message is suitable for user display.
    """
    if not issuer_url.startswith("https://"):
        raise OidcDiscoveryError(f"Issuer URL must start with https:// — got {issuer_url!r}")

    discovery_url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"

    try:
        response = requests.get(discovery_url, timeout=timeout)
    except requests.RequestException as e:
        raise OidcDiscoveryError(f"Could not reach {discovery_url}: {e}") from e

    if response.status_code != 200:
        raise OidcDiscoveryError(
            f"Discovery endpoint returned HTTP {response.status_code} from {discovery_url}"
        )

    try:
        data: Any = response.json()
    except ValueError as e:
        raise OidcDiscoveryError(f"Discovery endpoint returned non-JSON response: {e}") from e

    if not isinstance(data, dict):
        raise OidcDiscoveryError("Discovery endpoint returned JSON that is not an object")

    missing = [f for f in REQUIRED_DISCOVERY_FIELDS if not data.get(f)]
    if missing:
        raise OidcDiscoveryError(f"Discovery response missing required fields: {', '.join(missing)}")

    return {f: data[f] for f in REQUIRED_DISCOVERY_FIELDS}


def compute_jwks_thumbprint(jwks_uri: str, timeout: float = 10.0) -> str:
    """Compute the SHA-1 thumbprint of the leaf TLS cert presented by the JWKS host.

    AWS IAM OIDC providers historically required the thumbprint of the topmost
    intermediate cert in the chain. Since 2023 IAM auto-trusts JWKS hosts signed
    by public CAs, so the thumbprint is largely ceremonial for those — but we
    still need *some* valid value to pass to the OIDCProvider resource.

    Returns the SHA-1 of the leaf cert. The Python stdlib does not expose the
    full chain (only `get_verified_chain` in 3.13+), and the leaf-cert thumbprint
    works in practice for both public-CA and self-signed enterprise IdPs because
    AWS now validates the JWKS endpoint at AssumeRoleWithWebIdentity time.

    Args:
        jwks_uri: Full JWKS URL, e.g. https://auth.example.com/pf/JWKS.
        timeout: TCP connect timeout in seconds.

    Returns:
        40-character lowercase hex SHA-1 fingerprint (no colons).

    Raises:
        OidcDiscoveryError: On URL parse error, DNS failure, TLS handshake error,
            or any other failure to retrieve the cert. The message is suitable for
            user display.
    """
    parsed = urlparse(jwks_uri)
    if parsed.scheme != "https":
        raise OidcDiscoveryError(f"JWKS URI must use https:// — got {jwks_uri!r}")

    host = parsed.hostname
    if not host:
        raise OidcDiscoveryError(f"Could not extract hostname from {jwks_uri!r}")
    port = parsed.port or 443

    try:
        # ssl.get_server_certificate returns the leaf in PEM. We use a
        # custom socket dance instead so we get DER directly and surface
        # better errors than get_server_certificate's generic SSLError.
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                der_cert = ssock.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError, socket.gaierror) as e:
        raise OidcDiscoveryError(f"TLS handshake to {host}:{port} failed: {e}") from e

    if not der_cert:
        raise OidcDiscoveryError(f"No certificate returned from {host}:{port}")

    return hashlib.sha1(der_cert).hexdigest()  # noqa: S324 — SHA-1 required by IAM OIDC API
