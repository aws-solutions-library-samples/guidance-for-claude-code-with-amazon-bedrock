"""
Device-code bootstrap server handler.

Implements RFC 8628 device authorization grant using an existing OIDC IdP.
Routes:
  /.well-known/oauth-authorization-server → RFC 8414 metadata
  /device/code (POST)                     → generate device_code + user_code
  /verify (GET)                           → redirect to IdP authorize endpoint
  /callback (GET)                         → exchange code, mark device approved
  /oauth/token (POST)                     → poll for token
  /bootstrap (GET, Bearer)                → config JSON
  /plugins (GET, Bearer)                  → plugin registry
  /plugins/{name} (GET, Bearer)           → plugin registry
"""

import json
import os
import secrets
import string
import time
import urllib.request
import urllib.parse
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# Environment variables
TABLE_NAME = os.environ.get("TABLE_NAME", "")
OIDC_ISSUER_URL = os.environ.get("OIDC_ISSUER_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET_ARN = os.environ.get("OIDC_CLIENT_SECRET_ARN", "")
OIDC_TOKEN_ENDPOINT = os.environ.get("OIDC_TOKEN_ENDPOINT", "")
OIDC_AUTHORIZE_ENDPOINT = os.environ.get("OIDC_AUTHORIZE_ENDPOINT", "")
OIDC_JWKS_ENDPOINT = os.environ.get("OIDC_JWKS_ENDPOINT", "")
INFERENCE_REGION = os.environ.get("INFERENCE_REGION", "us-east-1")
INFERENCE_MODELS = os.environ.get("INFERENCE_MODELS", "")
PLUGINS_REGISTRY_JSON = os.environ.get("PLUGINS_REGISTRY_JSON", '{"plugins":[]}')
API_BASE_URL = os.environ.get("API_BASE_URL", "")

# Clients (reused across invocations)
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None
secrets_client = boto3.client("secretsmanager")

# Cached client secret
_client_secret_cache = None

# Constants
DEVICE_CODE_TTL_SECONDS = 300  # 5 minutes
USER_CODE_LENGTH = 8
POLL_INTERVAL_SECONDS = 5


def get_client_secret():
    """Retrieve OIDC client secret from SecretsManager (cached)."""
    global _client_secret_cache
    if _client_secret_cache is None:
        response = secrets_client.get_secret_value(SecretId=OIDC_CLIENT_SECRET_ARN)
        _client_secret_cache = response["SecretString"]
    return _client_secret_cache


def generate_user_code():
    """Generate a human-friendly user code (e.g. ABCD-EFGH)."""
    chars = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "")
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    return f"{part1}-{part2}"


def generate_device_code():
    """Generate a cryptographically random device code."""
    return secrets.token_urlsafe(32)


def json_response(status_code, body, headers=None):
    """Build an API Gateway proxy response."""
    resp = {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            **(headers or {}),
        },
        "body": json.dumps(body),
    }
    return resp


def redirect_response(location):
    """Build a 302 redirect response."""
    return {
        "statusCode": 302,
        "headers": {"Location": location},
        "body": "",
    }


def html_response(status_code, html):
    """Build an HTML response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": html,
    }


# ============================================================
# Route handlers
# ============================================================


def handle_oauth_metadata(event):
    """RFC 8414 OAuth Authorization Server Metadata."""
    base = API_BASE_URL.rstrip("/")
    metadata = {
        "issuer": base,
        "authorization_endpoint": f"{base}/verify",
        "token_endpoint": f"{base}/oauth/token",
        "device_authorization_endpoint": f"{base}/device/code",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "urn:ietf:params:oauth:grant-type:device_code",
        ],
        "code_challenge_methods_supported": ["S256"],
    }
    return json_response(200, metadata)


def handle_device_code(event):
    """POST /device/code - Generate device_code + user_code."""
    device_code = generate_device_code()
    user_code = generate_user_code()
    now = int(time.time())
    ttl = now + DEVICE_CODE_TTL_SECONDS

    table.put_item(
        Item={
            "device_code": device_code,
            "user_code": user_code,
            "status": "pending",
            "created_at": now,
            "ttl": ttl,
        }
    )

    base = API_BASE_URL.rstrip("/")
    return json_response(
        200,
        {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": f"{base}/verify",
            "verification_uri_complete": f"{base}/verify?user_code={user_code}",
            "expires_in": DEVICE_CODE_TTL_SECONDS,
            "interval": POLL_INTERVAL_SECONDS,
        },
    )


def handle_verify(event):
    """GET /verify - Redirect to IdP authorize endpoint with state=user_code."""
    params = event.get("queryStringParameters") or {}
    user_code = params.get("user_code", "")

    if not user_code:
        return html_response(
            400,
            "<html><body><h1>Missing user_code</h1>"
            "<p>Please use the verification URL provided by your device.</p>"
            "</body></html>",
        )

    base = API_BASE_URL.rstrip("/")
    callback_url = f"{base}/callback"

    authorize_params = urllib.parse.urlencode(
        {
            "client_id": OIDC_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": callback_url,
            "scope": "openid email profile",
            "state": user_code,
        }
    )

    redirect_url = f"{OIDC_AUTHORIZE_ENDPOINT}?{authorize_params}"
    return redirect_response(redirect_url)


def handle_callback(event):
    """GET /callback - Exchange code for tokens, mark device approved."""
    params = event.get("queryStringParameters") or {}
    code = params.get("code", "")
    state = params.get("state", "")  # user_code

    if not code or not state:
        return html_response(
            400,
            "<html><body><h1>Invalid callback</h1>"
            "<p>Missing authorization code or state.</p></body></html>",
        )

    # Exchange authorization code for tokens
    base = API_BASE_URL.rstrip("/")
    callback_url = f"{base}/callback"
    client_secret = get_client_secret()

    token_data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "client_id": OIDC_CLIENT_ID,
            "client_secret": client_secret,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OIDC_TOKEN_ENDPOINT,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_response = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return html_response(
            500,
            f"<html><body><h1>Token exchange failed</h1><p>{str(e)}</p></body></html>",
        )

    access_token = token_response.get("access_token", "")
    id_token = token_response.get("id_token", "")

    # Find the device code entry by user_code (GSI query)
    result = table.query(
        IndexName="user-code-index",
        KeyConditionExpression=Key("user_code").eq(state),
    )

    items = result.get("Items", [])
    if not items:
        return html_response(
            400,
            "<html><body><h1>Invalid or expired code</h1>"
            "<p>The user code has expired. Please start a new device authorization.</p>"
            "</body></html>",
        )

    item = items[0]
    device_code = item["device_code"]

    # Mark as approved with the tokens
    table.update_item(
        Key={"device_code": device_code},
        UpdateExpression="SET #s = :status, access_token = :at, id_token = :idt",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "approved",
            ":at": access_token,
            ":idt": id_token,
        },
    )

    return html_response(
        200,
        "<html><body><h1>Device Authorized</h1>"
        "<p>You have successfully authorized the device. "
        "You can close this window and return to your application.</p>"
        "</body></html>",
    )


def handle_oauth_token(event):
    """POST /oauth/token - Poll for token (device_code grant)."""
    body = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    params = urllib.parse.parse_qs(body)
    device_code = params.get("device_code", [""])[0]
    grant_type = params.get("grant_type", [""])[0]

    if grant_type != "urn:ietf:params:oauth:grant-type:device_code":
        return json_response(400, {"error": "unsupported_grant_type"})

    if not device_code:
        return json_response(400, {"error": "invalid_request", "error_description": "device_code is required"})

    # Look up the device code
    result = table.get_item(Key={"device_code": device_code})
    item = result.get("Item")

    if not item:
        return json_response(400, {"error": "expired_token", "error_description": "Device code not found or expired"})

    status = item.get("status", "pending")

    if status == "pending":
        return json_response(400, {"error": "authorization_pending"})

    if status == "approved":
        # Return the access token and mark as consumed
        table.update_item(
            Key={"device_code": device_code},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": "consumed"},
        )
        return json_response(
            200,
            {
                "access_token": item.get("access_token", ""),
                "token_type": "Bearer",
                "id_token": item.get("id_token", ""),
                "expires_in": 3600,
            },
        )

    # Already consumed or denied
    return json_response(400, {"error": "expired_token", "error_description": "Device code already used or denied"})


def handle_bootstrap(event):
    """GET /bootstrap - Return config JSON (requires Bearer token)."""
    base = API_BASE_URL.rstrip("/")
    models = [m.strip() for m in INFERENCE_MODELS.split(",") if m.strip()]

    config = {
        "mcpServers": {},
        "organizationPluginsUrl": f"{base}/plugins/index.json",
        "inferenceRegion": INFERENCE_REGION,
        "allowedModels": models,
    }
    return json_response(200, config)


def handle_plugins(event):
    """GET /plugins or /plugins/{name} - Return plugin registry."""
    try:
        registry = json.loads(PLUGINS_REGISTRY_JSON)
    except json.JSONDecodeError:
        registry = {"plugins": []}

    return json_response(200, registry)


# ============================================================
# Main handler (route dispatcher)
# ============================================================


def handler(event, context):
    """Lambda entry point - route by path."""
    path = event.get("path", "")
    method = event.get("httpMethod", "GET")

    # Normalize path
    path = path.rstrip("/")

    try:
        if path == "/.well-known/oauth-authorization-server":
            return handle_oauth_metadata(event)
        elif path == "/device/code" and method == "POST":
            return handle_device_code(event)
        elif path == "/verify" and method == "GET":
            return handle_verify(event)
        elif path == "/callback" and method == "GET":
            return handle_callback(event)
        elif path == "/oauth/token" and method == "POST":
            return handle_oauth_token(event)
        elif path == "/bootstrap" and method == "GET":
            return handle_bootstrap(event)
        elif path.startswith("/plugins"):
            return handle_plugins(event)
        else:
            return json_response(404, {"error": "not_found", "error_description": f"No route for {method} {path}"})
    except Exception as e:
        print(f"Unhandled error: {e}")
        return json_response(500, {"error": "server_error", "error_description": str(e)})
