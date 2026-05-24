"""Device Authorization Flow Lambda — generates codes, verifies, and issues tokens."""

import json
import os
import secrets
import string
import time

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("DEVICE_CODES_TABLE", "NexusDeviceCodes"))

COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "3lf5anq78ekk6fpfsi3307mhg2")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "us-east-13mbtsslmt.auth.us-east-1.amazoncognito.com")
VERIFICATION_URI = os.environ.get("VERIFICATION_URI", "https://nexus.allcode.com/device")
CODE_LIFETIME = 600  # 10 minutes


def generate_user_code():
    """Generate a human-readable 8-char code like ABCD-1234."""
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{digits}"


def generate_device_code():
    """Generate a secure random device code for polling."""
    return secrets.token_urlsafe(32)


def handle_request_code(event):
    """POST /api/device/code — CLI requests a new device code."""
    user_code = generate_user_code()
    device_code = generate_device_code()
    expires_at = int(time.time()) + CODE_LIFETIME

    table.put_item(Item={
        "user_code": user_code,
        "device_code": device_code,
        "status": "pending",
        "expires_at": expires_at,
        "tokens": None,
    })

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({
            "user_code": user_code,
            "device_code": device_code,
            "verification_uri": VERIFICATION_URI,
            "expires_in": CODE_LIFETIME,
            "interval": 3,
        }),
    }


def handle_poll(event):
    """POST /api/device/token — CLI polls for completion."""
    body = json.loads(event.get("body", "{}"))
    device_code = body.get("device_code", "")

    if not device_code:
        return _resp(400, {"error": "missing device_code"})

    # Find by device_code (scan since it's not the PK)
    result = table.scan(
        FilterExpression="device_code = :dc",
        ExpressionAttributeValues={":dc": device_code},
    )
    items = result.get("Items", [])
    if not items:
        return _resp(404, {"error": "invalid_device_code"})

    item = items[0]

    if int(item.get("expires_at", 0)) < int(time.time()):
        return _resp(400, {"error": "expired_token"})

    if item["status"] == "pending":
        return _resp(200, {"status": "authorization_pending"})

    if item["status"] == "complete":
        # Return tokens and clean up
        tokens = item.get("tokens", {})
        table.delete_item(Key={"user_code": item["user_code"]})
        return _resp(200, {"status": "complete", "tokens": tokens})

    return _resp(200, {"status": item["status"]})


def handle_verify(event):
    """POST /api/device/verify — verification page submits user_code + tokens."""
    body = json.loads(event.get("body", "{}"))
    user_code = body.get("user_code", "").upper().strip()
    id_token = body.get("id_token", "")
    access_token = body.get("access_token", "")

    if not user_code:
        return _resp(400, {"error": "missing user_code"})

    # Look up the code
    try:
        result = table.get_item(Key={"user_code": user_code})
        item = result.get("Item")
    except Exception:
        item = None

    if not item:
        return _resp(404, {"error": "invalid_code"})

    if int(item.get("expires_at", 0)) < int(time.time()):
        return _resp(400, {"error": "expired_code"})

    if item["status"] != "pending":
        return _resp(400, {"error": "code_already_used"})

    # Mark as complete with tokens if provided
    update_expr = "SET #s = :s"
    expr_values = {":s": "complete"}
    if id_token:
        update_expr += ", tokens = :t"
        expr_values[":t"] = {"id_token": id_token, "access_token": access_token}

    table.update_item(
        Key={"user_code": user_code},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )

    return _resp(200, {"status": "verified"})


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type,Authorization"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")

    if method == "OPTIONS":
        return _resp(200, {})

    if path == "/api/device/code" and method == "POST":
        return handle_request_code(event)
    elif path == "/api/device/token" and method == "POST":
        return handle_poll(event)
    elif path == "/api/device/verify" and method == "POST":
        return handle_verify(event)

    return _resp(404, {"error": "not found"})
