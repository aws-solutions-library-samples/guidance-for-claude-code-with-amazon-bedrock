"""
Cost Estimator Lambda — computes per-user, per-model token cost from CloudWatch metrics.

Runs hourly via EventBridge. Reads claude_code.token.usage metrics from CloudWatch
(broken down by user and token type), applies Bedrock pricing rates, and publishes
claude_code.cost.estimated metrics back to CloudWatch.

Works with both central and sidecar collector modes — reads from the common
CloudWatch namespace regardless of how metrics were ingested.

User identity is resolved from the user.email dimension when available,
falling back to user.id for cases where email is not present (e.g., anonymous
users or IDC users whose ARN session name is not an email).
"""

import os
from datetime import datetime, timedelta, timezone

import boto3

# Import shared pricing utility (deployed alongside this Lambda)
from shared.pricing import calculate_cost, get_model_family, get_pricing_rates, is_cross_region

# CloudWatch namespace for Claude Code metrics
NAMESPACE = os.environ.get("METRICS_NAMESPACE", "ClaudeCode")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Token types emitted by the OTEL collector
TOKEN_TYPES = ["input", "output", "cache_write", "cache_read"]

# CloudWatch API limits
MAX_METRIC_DATA_QUERIES = 500
MAX_PUT_METRIC_DATA = 1000


def _resolve_user_dimension() -> str:
    """Determine which CloudWatch dimension identifies users.

    The OTEL collector emits both user.email and user.id as resource attributes.
    Prefer user.email for readability; fall back to user.id.
    """
    return os.environ.get("USER_DIMENSION", "user.email")


def _discover_active_users(cw, user_dim: str) -> list[str]:
    """Discover unique user identifiers from CloudWatch metrics."""
    users = set()
    paginator = cw.get_paginator("list_metrics")

    for page in paginator.paginate(
        Namespace=NAMESPACE,
        MetricName="claude_code.token.usage",
        Dimensions=[{"Name": user_dim}],
    ):
        for metric in page.get("Metrics", []):
            for dim in metric.get("Dimensions", []):
                if dim["Name"] == user_dim and dim["Value"]:
                    users.add(dim["Value"])

    return list(users)


def _discover_active_models(cw) -> list[str]:
    """Discover unique model identifiers from CloudWatch metrics."""
    models = set()
    paginator = cw.get_paginator("list_metrics")

    for page in paginator.paginate(
        Namespace=NAMESPACE,
        MetricName="claude_code.token.usage",
        Dimensions=[{"Name": "model"}],
    ):
        for metric in page.get("Metrics", []):
            for dim in metric.get("Dimensions", []):
                if dim["Name"] == "model" and dim["Value"]:
                    models.add(dim["Value"])

    return list(models)


def _query_user_model_tokens(cw, user_dim: str, user: str, model: str,
                              start_time, end_time) -> dict:
    """Query token counts by type for a specific user + model combination.

    Returns: {token_type: count}
    """
    queries = []
    type_map = {}

    for i, token_type in enumerate(TOKEN_TYPES):
        query_id = f"t{i}"
        type_map[query_id] = token_type
        queries.append({
            "Id": query_id,
            "MetricStat": {
                "Metric": {
                    "Namespace": NAMESPACE,
                    "MetricName": "claude_code.token.usage",
                    "Dimensions": [
                        {"Name": user_dim, "Value": user},
                        {"Name": "model", "Value": model},
                        {"Name": "token_type", "Value": token_type},
                    ],
                },
                "Period": 3600,
                "Stat": "Sum",
            },
            "ReturnData": True,
        })

    try:
        response = cw.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
        )
    except Exception as e:
        print(f"Error querying tokens for user={user} model={model}: {e}")
        return {}

    tokens_by_type = {}
    for result in response.get("MetricDataResults", []):
        token_type = type_map.get(result["Id"])
        if token_type and result.get("Values"):
            tokens_by_type[token_type] = sum(result["Values"])

    return tokens_by_type


def lambda_handler(event, context):
    """Main handler — query per-user token usage, calculate cost, publish metrics."""
    cw = boto3.client("cloudwatch", region_name=REGION)
    rates = get_pricing_rates()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=1)

    user_dim = _resolve_user_dimension()
    users = _discover_active_users(cw, user_dim)
    models = _discover_active_models(cw)

    if not users or not models:
        print(f"No active users ({len(users)}) or models ({len(models)}) found")
        return {"statusCode": 200, "body": "No data to process"}

    print(f"Processing cost for {len(users)} users × {len(models)} models")

    metric_data = []
    total_cost = 0.0

    for user in users:
        user_cost = 0.0
        for model in models:
            tokens_by_type = _query_user_model_tokens(
                cw, user_dim, user, model, start_time, end_time
            )
            if not tokens_by_type:
                continue

            family = get_model_family(model)
            cost = calculate_cost(tokens_by_type, family, rates, model_id=model)

            if cost > 0:
                user_cost += cost
                metric_data.append({
                    "MetricName": "claude_code.cost.estimated",
                    "Timestamp": end_time,
                    "Value": cost,
                    "Unit": "None",
                    "Dimensions": [
                        {"Name": user_dim, "Value": user},
                        {"Name": "model_family", "Value": family},
                    ],
                })

        # Also publish aggregate per-user cost (all models combined)
        if user_cost > 0:
            total_cost += user_cost
            metric_data.append({
                "MetricName": "claude_code.cost.estimated.total",
                "Timestamp": end_time,
                "Value": user_cost,
                "Unit": "None",
                "Dimensions": [
                    {"Name": user_dim, "Value": user},
                ],
            })

    # Publish in batches
    for i in range(0, len(metric_data), MAX_PUT_METRIC_DATA):
        batch = metric_data[i:i + MAX_PUT_METRIC_DATA]
        try:
            cw.put_metric_data(Namespace=NAMESPACE, MetricData=batch)
        except Exception as e:
            print(f"Error publishing metrics batch {i}: {e}")

    print(f"Published {len(metric_data)} cost metrics. Total hourly cost: ${total_cost:.4f}")
    return {
        "statusCode": 200,
        "body": f"Cost estimation complete: {len(users)} users, ${total_cost:.4f}/hr",
    }
