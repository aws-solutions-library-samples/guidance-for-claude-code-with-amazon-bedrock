"""AllCode Nexus - AWS Marketplace Registration Lambda.

Handles the redirect after a customer subscribes on AWS Marketplace.
Resolves the customer token and provisions their account.
"""

import json
import os

import boto3

CHECKPOINTS_TABLE = os.environ.get("CHECKPOINTS_TABLE", "MeteringCheckpoints")

dynamodb = boto3.resource("dynamodb")
checkpoints_table = dynamodb.Table(CHECKPOINTS_TABLE)
marketplace = boto3.client("meteringmarketplace")


def lambda_handler(event, context):
    """Handle Marketplace registration redirect."""
    # Extract token from query params (GET) or body (POST)
    params = event.get("queryStringParameters", {}) or {}
    token = params.get("x-amzn-marketplace-token", params.get("token", ""))

    # If POST, check body (URL-encoded form data)
    if not token and event.get("body"):
        import urllib.parse
        body = event["body"]
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode()
        parsed = urllib.parse.parse_qs(body)
        token = parsed.get("x-amzn-marketplace-token", [""])[0] or parsed.get("token", [""])[0]

    if not token:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html"},
            "body": """<!DOCTYPE html>
<html>
<head><title>AllCode Nexus - Registration</title></head>
<body style="font-family: sans-serif; max-width: 600px; margin: 50px auto; text-align: center;">
    <h1>AllCode Nexus</h1>
    <p>Welcome! This page handles subscription registration from AWS Marketplace.</p>
    <p>If you arrived here directly, please subscribe through <a href="https://aws.amazon.com/marketplace">AWS Marketplace</a> first.</p>
    <p><a href="https://nexus.allcode.com">Go to AllCode Nexus →</a></p>
</body>
</html>""",
        }

    # Resolve the customer
    try:
        result = marketplace.resolve_customer(RegistrationToken=token)
        customer_id = result["CustomerIdentifier"]
        product_code = result["ProductCode"]
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "text/html"},
            "body": f"<h1>Error</h1><p>Could not verify subscription: {str(e)}</p>",
        }

    # Store customer info
    checkpoints_table.put_item(Item={
        "pk": "CUSTOMER",
        "sk": customer_id,
        "product_code": product_code,
        "status": "active",
        "registered_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })

    # Notify Slack #allcode-nexus
    try:
        import urllib.request
        token_table = dynamodb.Table("IntegrationTokens")
        tok = token_table.get_item(Key={"pk": "ORG#allcode", "sk": "slack"})
        slack_token = tok.get("Item", {}).get("access_token", "")
        if slack_token:
            msg = f"🎉 *New Marketplace Subscription!*\n>Customer ID: {customer_id}\n>Product: {product_code}"
            data = json.dumps({"channel": "C0B28HHRMAM", "text": msg}).encode()
            req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=data, headers={"Authorization": f"Bearer {slack_token}", "Content-Type": "application/json"})
            urllib.request.urlopen(req)
    except Exception:
        pass

    # Return redirect to Nexus landing page
    return {
        "statusCode": 302,
        "headers": {
            "Location": "https://nexus.allcode.com?subscribed=true",
        },
        "body": "",
    }
