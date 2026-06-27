"""
API Gateway REQUEST authorizer for the device-code bootstrap server.

Routing logic:
  - Handshake routes (/.well-known/*, /device/code, /verify, /callback, /oauth/token):
    Allow unconditionally (public endpoints for the device-code flow).
  - Data routes (/bootstrap, /plugins*):
    Require valid JWT Bearer token. Validates against JWKS (iss, aud, exp claims
    + signature via PyJWT if available, fallback to claims-only validation).
"""

import base64
import json
import os
import time
import urllib.request

# Environment variables
OIDC_ISSUER_URL = os.environ.get("OIDC_ISSUER_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_JWKS_ENDPOINT = os.environ.get("OIDC_JWKS_ENDPOINT", "")

# Cached JWKS
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_TTL = 300  # 5 minutes

# Handshake paths that don't require authentication
HANDSHAKE_PATHS = {
    "/.well-known/oauth-authorization-server",
    "/device/code",
    "/verify",
    "/callback",
    "/oauth/token",
}


def get_jwks():
    """Fetch JWKS from the IdP endpoint (cached)."""
    global _jwks_cache, _jwks_cache_time
    now = time.time()
    if _jwks_cache and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        req = urllib.request.Request(OIDC_JWKS_ENDPOINT)
        with urllib.request.urlopen(req, timeout=5) as resp:
            _jwks_cache = json.loads(resp.read().decode("utf-8"))
            _jwks_cache_time = now
    except Exception as e:
        print(f"Failed to fetch JWKS: {e}")
        if _jwks_cache:
            return _jwks_cache
        raise

    return _jwks_cache


def decode_jwt_payload(token):
    """Decode JWT payload without verification (for claims inspection)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    # Decode payload (part 1)
    payload_b64 = parts[1]
    # Add padding if needed
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding

    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)


def validate_jwt_with_pyjwt(token, jwks):
    """Attempt full JWT validation using PyJWT (if available)."""
    try:
        import jwt

        # Build signing keys from JWKS
        signing_keys = []
        for key_data in jwks.get("keys", []):
            if key_data.get("use", "sig") == "sig":
                signing_keys.append(jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data)))

        # Decode the header to find the right key
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        signing_key = None
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
                break

        if not signing_key and signing_keys:
            signing_key = signing_keys[0]

        if not signing_key:
            return None  # Fall back to claims-only

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=OIDC_ISSUER_URL,
            audience=OIDC_CLIENT_ID,
            options={"verify_exp": True},
        )
        return payload
    except ImportError:
        return None  # PyJWT not available, fallback
    except Exception as e:
        print(f"PyJWT validation failed: {e}")
        raise  # Re-raise to deny access


def validate_jwt_claims_only(token):
    """Fallback: validate JWT claims without cryptographic verification."""
    try:
        payload = decode_jwt_payload(token)
    except Exception as e:
        raise ValueError(f"Cannot decode JWT: {e}")

    # Check issuer
    iss = payload.get("iss", "")
    if iss != OIDC_ISSUER_URL:
        raise ValueError(f"Invalid issuer: {iss}")

    # Check audience (can be string or list)
    aud = payload.get("aud", "")
    if isinstance(aud, list):
        if OIDC_CLIENT_ID not in aud:
            raise ValueError(f"Invalid audience: {aud}")
    elif aud != OIDC_CLIENT_ID:
        raise ValueError(f"Invalid audience: {aud}")

    # Check expiration
    exp = payload.get("exp", 0)
    if time.time() > exp:
        raise ValueError("Token expired")

    return payload


def validate_token(token):
    """Validate a Bearer token. Returns the JWT payload or raises."""
    jwks = get_jwks()

    # Try PyJWT first (full cryptographic validation)
    result = validate_jwt_with_pyjwt(token, jwks)
    if result is not None:
        return result

    # Fallback to claims-only validation
    print("WARNING: Using claims-only JWT validation (PyJWT not available)")
    return validate_jwt_claims_only(token)


def generate_policy(principal_id, effect, resource, context=None):
    """Generate an IAM policy document for the authorizer response."""
    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def handler(event, context):
    """Lambda authorizer entry point."""
    method_arn = event.get("methodArn", "")
    path = event.get("path", "")

    # Extract path from methodArn if path not directly available
    # methodArn format: arn:aws:execute-api:{region}:{account}:{api-id}/{stage}/{method}/{path}
    if not path and method_arn:
        arn_parts = method_arn.split("/")
        if len(arn_parts) >= 4:
            path = "/" + "/".join(arn_parts[3:])

    # Normalize path
    path = path.rstrip("/") if path else ""

    # Build a wildcard resource ARN for the policy
    # Allow access to all methods/resources in this API
    if method_arn:
        arn_base = "/".join(method_arn.split("/")[:2])
        wildcard_arn = f"{arn_base}/*"
    else:
        wildcard_arn = "*"

    # Check if this is a handshake route (allow without auth)
    if path in HANDSHAKE_PATHS:
        return generate_policy("anonymous", "Allow", wildcard_arn)

    # Data routes require Bearer token
    auth_header = ""
    headers = event.get("headers") or {}
    # Headers can be mixed case
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_header = value
            break

    if not auth_header or not auth_header.startswith("Bearer "):
        print(f"Missing or invalid Authorization header for path: {path}")
        return generate_policy("anonymous", "Deny", wildcard_arn)

    token = auth_header[7:]  # Strip "Bearer "

    try:
        payload = validate_token(token)
        principal_id = payload.get("sub", payload.get("email", "user"))
        return generate_policy(
            principal_id,
            "Allow",
            wildcard_arn,
            context={
                "sub": payload.get("sub", ""),
                "email": payload.get("email", ""),
            },
        )
    except Exception as e:
        print(f"Token validation failed: {e}")
        return generate_policy("anonymous", "Deny", wildcard_arn)
