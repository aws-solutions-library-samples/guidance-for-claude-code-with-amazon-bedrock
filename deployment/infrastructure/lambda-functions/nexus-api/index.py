"""AllCode Nexus API - Lambda handler for reading metrics, users, and quotas."""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

METRICS_TABLE = os.environ.get("METRICS_TABLE", "ClaudeCodeMetrics")
POLICIES_TABLE = os.environ.get("POLICIES_TABLE", "QuotaPolicies")
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
metrics_table = dynamodb.Table(METRICS_TABLE)
policies_table = dynamodb.Table(POLICIES_TABLE)
quota_table = dynamodb.Table(QUOTA_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def get_caller_email(event):
    """Extract email from JWT claims."""
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    return claims.get("email", claims.get("preferred_username", claims.get("sub", "unknown")))


def handle_summary(event):
    """GET /api/metrics/summary - org-wide usage."""
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # Query recent metrics summaries
    result = metrics_table.query(
        KeyConditionExpression=Key("pk").eq("METRICS") & Key("sk").gte(thirty_days_ago),
        Limit=100,
        ScanIndexForward=False,
    )
    items = result.get("Items", [])

    total_tokens = sum(int(i.get("total_tokens", 0)) for i in items)
    unique_users = max((int(i.get("unique_users", 0)) for i in items), default=0)

    # Build daily token history
    daily = {}
    for item in items:
        date = item.get("timestamp", "")[:10]
        daily[date] = daily.get(date, 0) + int(item.get("total_tokens", 0))

    token_history = [{"date": k, "tokens": v} for k, v in sorted(daily.items())]

    # Top users from latest summary
    top_users = []
    if items:
        raw_top = items[0].get("top_users", [])
        for u in raw_top[:10]:
            if isinstance(u, dict):
                top_users.append({"email": u.get("user", ""), "tokens": int(u.get("tokens", 0))})

    return response(200, {
        "activeUsers": unique_users,
        "monthlyTokens": total_tokens,
        "orgQuotaPercent": min(int(total_tokens / 2_250_000_000 * 100), 100) if total_tokens else 0,
        "topUsers": top_users,
        "tokenHistory": token_history,
    })


def handle_users(event):
    """GET /api/users - list users with usage."""
    result = metrics_table.query(
        IndexName="UserActivityIndex",
        KeyConditionExpression=Key("gsi1pk").eq("USER"),
        Limit=100,
        ScanIndexForward=False,
    )
    users = []
    for item in result.get("Items", []):
        users.append({
            "email": item.get("user_email", item.get("gsi1sk", "").split("#")[0]),
            "monthlyTokens": int(item.get("monthly_tokens", 0)),
            "lastActive": item.get("last_active", item.get("timestamp", "")),
            "status": "blocked" if item.get("blocked") else "active",
        })
    return response(200, {"users": users})


def handle_user_me(event):
    """GET /api/users/me - current user's data."""
    email = get_caller_email(event)

    # Get user's quota metrics
    result = quota_table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{email}"),
        Limit=1,
        ScanIndexForward=False,
    )
    item = result.get("Items", [{}])[0] if result.get("Items") else {}

    # Get user's policy
    policy_result = policies_table.query(
        IndexName="PolicyTypeIndex",
        KeyConditionExpression=Key("policy_type").eq("user") & Key("identifier").eq(email),
        Limit=1,
    )
    policy = policy_result.get("Items", [{}])[0] if policy_result.get("Items") else {}

    # Fallback to default policy
    if not policy:
        default_result = policies_table.query(
            IndexName="PolicyTypeIndex",
            KeyConditionExpression=Key("policy_type").eq("default"),
            Limit=1,
        )
        policy = default_result.get("Items", [{}])[0] if default_result.get("Items") else {}

    monthly_limit = int(policy.get("monthly_limit", 225_000_000))
    daily_limit = int(policy.get("daily_limit", 0)) or int(monthly_limit / 30)
    monthly_used = int(item.get("monthly_tokens", 0))
    daily_used = int(item.get("daily_tokens", 0))

    return response(200, {
        "monthly": {"used": monthly_used, "limit": monthly_limit},
        "daily": {"used": daily_used, "limit": daily_limit},
        "model": os.environ.get("SELECTED_MODEL", "Claude Sonnet 4"),
        "status": "blocked" if item.get("blocked") else "active",
    })


def handle_quotas(event):
    """GET /api/quotas - list all quota policies."""
    result = policies_table.scan(Limit=100)
    policies = []
    for item in result.get("Items", []):
        policies.append({
            "id": item.get("pk", ""),
            "type": item.get("policy_type", "default"),
            "target": item.get("identifier", "All Users"),
            "monthlyLimit": int(item.get("monthly_limit", 225_000_000)),
            "dailyLimit": int(item.get("daily_limit", 0)) or None,
            "enforcement": item.get("enforcement_mode", "block"),
        })
    return response(200, {"policies": policies})


def handle_models(event):
    """GET /api/config/models - available models."""
    # Read current config from DynamoDB (or env defaults)
    try:
        result = policies_table.get_item(Key={"pk": "CONFIG#models", "sk": "CURRENT"})
        config = result.get("Item", {})
    except Exception:
        config = {}

    return response(200, {
        "selectedModel": config.get("selected_model", os.environ.get("SELECTED_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")),
        "region": config.get("region", os.environ.get("AWS_REGION", "us-east-1")),
        "crossRegionProfile": config.get("cross_region_profile", os.environ.get("CROSS_REGION_PROFILE", "us")),
        "availableModels": [
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "us.anthropic.claude-sonnet-4-6",
            "us.anthropic.claude-opus-4-20250514-v1:0",
            "us.anthropic.claude-opus-4-7",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ],
    })


def handle_update_models(event):
    """PUT /api/config/models - update model configuration."""
    body = json.loads(event.get("body", "{}"))

    item = {
        "pk": "CONFIG#models",
        "sk": "CURRENT",
        "selected_model": body.get("selectedModel", ""),
        "region": body.get("region", "us-east-1"),
        "cross_region_profile": body.get("crossRegionProfile", "us"),
    }
    policies_table.put_item(Item=item)
    return response(200, {"updated": True, **item})


def handle_activity(event):
    """GET /api/users/me/activity - recent activity for current user."""
    email = get_caller_email(event)
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    # Query user's recent metrics
    result = metrics_table.query(
        IndexName="UserActivityIndex",
        KeyConditionExpression=Key("gsi1pk").eq(f"USER#{email}") & Key("gsi1sk").gte(seven_days_ago),
        Limit=50,
        ScanIndexForward=False,
    )
    activities = []
    for item in result.get("Items", []):
        activities.append({
            "timestamp": item.get("timestamp", item.get("gsi1sk", "")),
            "tokens": int(item.get("tokens", 0)),
            "model": item.get("model", ""),
            "type": item.get("metric_type", "session"),
        })

    return response(200, {"activities": activities})


def handle_billing_report(event):
    """GET /api/billing/report - CSV export of usage by user."""
    import csv
    import io

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # Query metrics for the period
    result = metrics_table.query(
        KeyConditionExpression=Key("pk").eq("METRICS") & Key("sk").gte(thirty_days_ago),
        Limit=500,
        ScanIndexForward=False,
    )
    items = result.get("Items", [])

    # Aggregate by user from top_users
    user_totals: dict = {}
    for item in items:
        for u in item.get("top_users", []):
            if isinstance(u, dict):
                email = u.get("user", "unknown")
                tokens = int(u.get("tokens", 0))
                user_totals[email] = user_totals.get(email, 0) + tokens

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User", "Tokens", "Estimated Cost ($)"])
    for email, tokens in sorted(user_totals.items(), key=lambda x: -x[1]):
        cost = (tokens / 1_000_000) * 8  # ~$8/M blended
        writer.writerow([email, tokens, f"{cost:.2f}"])

    csv_content = output.getvalue()

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename=billing-report-{now.strftime('%Y-%m-%d')}.csv",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
        },
        "body": csv_content,
    }


def handle_download(event):
    """GET /api/download - generate presigned URL for latest package."""
    bucket = os.environ.get("DISTRIBUTION_BUCKET", "")
    if not bucket:
        return response(404, {"error": "Distribution bucket not configured"})

    s3 = boto3.client("s3")

    # Find the latest package
    try:
        result = s3.list_objects_v2(Bucket=bucket, Prefix="packages/", Delimiter="/")
        prefixes = sorted([p["Prefix"] for p in result.get("CommonPrefixes", [])], reverse=True)
        if not prefixes:
            return response(404, {"error": "No packages found"})

        # Get the zip file in the latest prefix
        latest = prefixes[0]
        objects = s3.list_objects_v2(Bucket=bucket, Prefix=latest)
        zips = [o["Key"] for o in objects.get("Contents", []) if o["Key"].endswith(".zip")]
        if not zips:
            return response(404, {"error": "No zip file found in latest package"})

        # Generate presigned URL (1 hour expiry)
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": zips[0]},
            ExpiresIn=3600,
        )
        return response(200, {"url": url, "filename": zips[0].split("/")[-1]})
    except Exception as e:
        return response(500, {"error": f"Failed to generate download URL: {str(e)}"})


def handle_create_quota(event):
    """POST /api/quotas - create quota policy."""
    body = json.loads(event.get("body", "{}"))
    policy_type = body.get("type", "default")
    identifier = body.get("target", "")
    pk = f"POLICY#{policy_type}#{identifier}" if identifier else f"POLICY#{policy_type}"

    item = {
        "pk": pk,
        "sk": "CURRENT",
        "policy_type": policy_type,
        "identifier": identifier,
        "monthly_limit": int(body.get("monthlyLimit", 225_000_000)),
        "daily_limit": int(body.get("dailyLimit", 0)),
        "enforcement_mode": body.get("enforcement", "block"),
    }
    policies_table.put_item(Item=item)
    return response(201, {"id": pk, **body})


def handle_update_quota(event):
    """PUT /api/quotas/{id} - update quota policy."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    policy_id = path.split("/api/quotas/", 1)[-1]
    body = json.loads(event.get("body", "{}"))

    updates = {}
    if "monthlyLimit" in body:
        updates["monthly_limit"] = {"Value": int(body["monthlyLimit"]), "Action": "PUT"}
    if "dailyLimit" in body:
        updates["daily_limit"] = {"Value": int(body["dailyLimit"]), "Action": "PUT"}
    if "enforcement" in body:
        updates["enforcement_mode"] = {"Value": body["enforcement"], "Action": "PUT"}

    if updates:
        policies_table.update_item(
            Key={"pk": policy_id, "sk": "CURRENT"},
            AttributeUpdates=updates,
        )
    return response(200, {"id": policy_id, "updated": list(updates.keys())})


def handle_delete_quota(event):
    """DELETE /api/quotas/{id} - delete quota policy."""
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    policy_id = path.split("/api/quotas/", 1)[-1]
    policies_table.delete_item(Key={"pk": policy_id, "sk": "CURRENT"})
    return response(200, {"deleted": policy_id})


ROUTES = {
    "GET /api/metrics/summary": handle_summary,
    "GET /api/users": handle_users,
    "GET /api/users/me": handle_user_me,
    "GET /api/quotas": handle_quotas,
    "POST /api/quotas": handle_create_quota,
    "GET /api/config/models": handle_models,
    "GET /api/download": handle_download,
    "GET /api/billing/report": handle_billing_report,
    "GET /api/users/me/activity": handle_activity,
}


def lambda_handler(event, context):
    """Main Lambda handler - routes requests."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    route_key = f"{method} {path}"

    # Handle OPTIONS for CORS
    if method == "OPTIONS":
        return response(200, {})

    # Exact match first
    handler = ROUTES.get(route_key)

    # Path-parameter routes for quotas
    if not handler and path.startswith("/api/quotas/"):
        if method == "PUT":
            handler = handle_update_quota
        elif method == "DELETE":
            handler = handle_delete_quota

    # Model config update
    if not handler and path == "/api/config/models" and method == "PUT":
        handler = handle_update_models

    if not handler:
        return response(404, {"error": "Not found", "route": route_key})

    try:
        return handler(event)
    except Exception as e:
        return response(500, {"error": str(e)})
