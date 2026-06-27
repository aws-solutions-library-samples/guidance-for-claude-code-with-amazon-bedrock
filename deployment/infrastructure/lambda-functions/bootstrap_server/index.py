# ABOUTME: Lambda handler for the Claude Desktop Bootstrap Server
# ABOUTME: Validates OIDC Bearer tokens (JWT) against JWKS and returns per-user
# ABOUTME: configuration JSON for Claude Desktop dynamic provisioning

"""Claude Desktop Bootstrap Server Lambda handler.

Validates incoming JWT Bearer tokens against the configured OIDC provider's JWKS
endpoint, extracts user identity, and returns personalized configuration for
Claude Desktop clients.
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

# Optional: PyJWT with cryptography for RS256 verification
# Falls back to manual verification if not available in Lambda layer
try:
    import jwt
    from jwt import PyJWKClient

    HAS_PYJWT = True
except ImportError:
    HAS_PYJWT = False

# Configuration from environment variables
OIDC_ISSUER_URL = os.environ.get("OIDC_ISSUER_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_JWKS_ENDPOINT = os.environ.get("OIDC_JWKS_ENDPOINT", "")
DEFAULT_INFERENCE_REGION = os.environ.get("DEFAULT_INFERENCE_REGION", "us-east-1")
DEFAULT_INFERENCE_MODELS = os.environ.get("DEFAULT_INFERENCE_MODELS", "")
OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "")
INFERENCE_SESSION_LIFETIME_SEC = int(os.environ.get("INFERENCE_SESSION_LIFETIME_SEC", "28800"))

# JWKS cache (module-level for Lambda container reuse)
_jwks_client = None
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_TTL = 3600  # Cache JWKS for 1 hour

# Resolved JWKS endpoint (auto-discovered if not explicitly configured)
_resolved_jwks_endpoint = None


def _resolve_jwks_endpoint():
    """Resolve JWKS endpoint — use explicit config or discover from issuer."""
    global _resolved_jwks_endpoint
    if _resolved_jwks_endpoint:
        return _resolved_jwks_endpoint

    if OIDC_JWKS_ENDPOINT:
        _resolved_jwks_endpoint = OIDC_JWKS_ENDPOINT
        return _resolved_jwks_endpoint

    # Auto-discover from OIDC issuer's well-known configuration
    if OIDC_ISSUER_URL:
        discovery_url = OIDC_ISSUER_URL.rstrip("/") + "/.well-known/openid-configuration"
        try:
            req = urllib.request.Request(discovery_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                oidc_config = json.loads(resp.read())
                _resolved_jwks_endpoint = oidc_config.get("jwks_uri", "")
                return _resolved_jwks_endpoint
        except Exception:
            pass

    return ""


def _get_jwks_client():
    """Get or create a cached PyJWKClient instance."""
    global _jwks_client
    if _jwks_client is None and HAS_PYJWT:
        endpoint = _resolve_jwks_endpoint()
        if endpoint:
            _jwks_client = PyJWKClient(endpoint, cache_keys=True)
    return _jwks_client


def _fetch_jwks():
    """Fetch JWKS from the resolved endpoint with caching."""
    global _jwks_cache, _jwks_cache_time

    endpoint = _resolve_jwks_endpoint()
    if not endpoint:
        raise ValueError("No JWKS endpoint configured or discoverable from issuer")

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=5) as resp:
            _jwks_cache = json.loads(resp.read())
            _jwks_cache_time = now
            return _jwks_cache
    except Exception as e:
        raise ValueError(f"Failed to fetch JWKS from {endpoint}: {str(e)}")


def _validate_token(token: str) -> dict:
    """Validate JWT token and return decoded claims.

    Args:
        token: Raw JWT Bearer token string

    Returns:
        Decoded token claims dict

    Raises:
        ValueError: If token is invalid, expired, or signature verification fails
    """
    if not token:
        raise ValueError("No token provided")

    if not HAS_PYJWT:
        raise ValueError("PyJWT library not available — cannot validate tokens")

    try:
        # Get the signing key from JWKS
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Decode and validate the token
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=OIDC_ISSUER_URL,
            audience=OIDC_CLIENT_ID,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "require": ["exp", "iss", "sub"],
            },
        )
        return decoded

    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidIssuerError:
        raise ValueError("Invalid token issuer")
    except jwt.InvalidAudienceError:
        raise ValueError("Invalid token audience")
    except jwt.InvalidSignatureError:
        raise ValueError("Invalid token signature")
    except jwt.DecodeError as e:
        raise ValueError(f"Token decode error: {str(e)}")
    except Exception as e:
        raise ValueError(f"Token validation failed: {str(e)}")


def _build_config_response(claims: dict) -> dict:
    """Build the configuration response for a validated user.

    Args:
        claims: Decoded JWT claims

    Returns:
        Configuration dict for the Claude Desktop client
    """
    user_sub = claims.get("sub", "unknown")
    user_email = claims.get("email", claims.get("preferred_username", user_sub))

    # Calculate expiration (1 hour from now)
    expires_at = int(time.time()) + 3600

    # Build OTLP headers with user identity
    otlp_headers = {}
    if OTLP_ENDPOINT:
        otlp_headers = {
            "x-user-id": user_sub,
            "x-user-email": user_email,
        }

    # Parse models list
    models = [m.strip() for m in DEFAULT_INFERENCE_MODELS.split(",") if m.strip()]

    config = {
        "inferenceProvider": "bedrock",
        "inferenceRegion": DEFAULT_INFERENCE_REGION,
        "inferenceModels": models,
        "inferenceSessionLifetimeSec": INFERENCE_SESSION_LIFETIME_SEC,
        "expiresAt": expires_at,
        "user": {
            "sub": user_sub,
            "email": user_email,
        },
    }

    # Add OTEL configuration if endpoint is set
    if OTLP_ENDPOINT:
        config["otlpEndpoint"] = OTLP_ENDPOINT
        config["otlpHeaders"] = otlp_headers

    return config


def _response(status_code: int, body: dict, extra_headers: dict = None) -> dict:
    """Build a standard API Gateway v2 response.

    Args:
        status_code: HTTP status code
        body: Response body dict
        extra_headers: Additional headers to include

    Returns:
        API Gateway v2 response dict
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if extra_headers:
        headers.update(extra_headers)

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Main Lambda handler for the Bootstrap Server.

    Expects:
        - GET /config with Authorization: Bearer <token> header

    Returns:
        - 200: Configuration JSON on success
        - 401: Invalid or missing token
        - 403: User not authorized
        - 500: Internal server error
    """
    try:
        # Extract Authorization header
        headers = event.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header:
            return _response(401, {
                "error": "unauthorized",
                "message": "Missing Authorization header",
            })

        # Extract Bearer token
        if not auth_header.startswith("Bearer "):
            return _response(401, {
                "error": "unauthorized",
                "message": "Invalid authorization scheme — expected Bearer token",
            })

        token = auth_header[7:]  # Strip "Bearer " prefix

        # Validate token
        try:
            claims = _validate_token(token)
        except ValueError as e:
            error_msg = str(e)
            # Distinguish between auth errors
            if "expired" in error_msg.lower():
                return _response(401, {
                    "error": "token_expired",
                    "message": "Token has expired — please re-authenticate",
                })
            elif "issuer" in error_msg.lower() or "audience" in error_msg.lower():
                return _response(403, {
                    "error": "forbidden",
                    "message": f"Token validation failed: {error_msg}",
                })
            else:
                return _response(401, {
                    "error": "unauthorized",
                    "message": f"Token validation failed: {error_msg}",
                })

        # Build and return configuration
        config = _build_config_response(claims)

        return _response(200, config)

    except Exception as e:
        # Log the error for CloudWatch but don't leak details to client
        print(f"ERROR: Unhandled exception in bootstrap handler: {str(e)}")
        return _response(500, {
            "error": "internal_error",
            "message": "An internal error occurred",
        })
