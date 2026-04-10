# ABOUTME: Lambda function that enforces quotas by tagging Bedrock Application Inference Profiles
# ABOUTME: Runs every 5 minutes (same cadence as MetricsAggregator) and sets status=enabled/disabled
# ABOUTME: on each user's inference profile based on their quota usage in UserQuotaMetrics.
# ABOUTME: IAM policies on the federated role deny bedrock:InvokeModel when status != enabled,
# ABOUTME: providing server-side enforcement that cannot be bypassed by client config changes.

import json
import boto3
import os
from datetime import datetime, timezone

# Clients
bedrock_client = boto3.client("bedrock")
dynamodb = boto3.resource("dynamodb")

# Configuration
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
POLICIES_TABLE = os.environ.get("POLICIES_TABLE", "QuotaPolicies")

quota_table = dynamodb.Table(QUOTA_TABLE)
policies_table = dynamodb.Table(POLICIES_TABLE)


def lambda_handler(event, context):
    print("Starting quota enforcement via inference profile tagging")

    # 1. Load the default policy (fallback for users without a specific policy)
    default_policy = _get_default_policy()

    # 2. Build all APPLICATION inference profiles grouped by email
    email_to_arns = _build_email_to_arns_map()
    if not email_to_arns:
        print("No application inference profiles with user.email tags found")
        return {"statusCode": 200, "body": "No inference profiles found"}

    print(f"Found profiles for {len(email_to_arns)} user(s)")

    # 3. For each user check quota and set tag
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    enabled_count = 0
    disabled_count = 0

    for email, arns in email_to_arns.items():
        # Per-user policy takes precedence over default
        policy = _get_user_policy(email) or default_policy
        if policy is None:
            # No policy at all — allow by default
            for arn in arns:
                _set_status_tag(arn, "enabled")
            enabled_count += len(arns)
            print(f"  ALLOWED {email}: no policy configured → {len(arns)} profile(s) tagged status=enabled")
            continue

        monthly_limit = policy.get("monthly_token_limit", 0)
        daily_limit = policy.get("daily_token_limit")
        enforcement_mode = policy.get("enforcement_mode", "alert")

        if enforcement_mode != "block" or monthly_limit <= 0:
            # Policy exists but enforcement is alert-only — ensure profiles are enabled
            for arn in arns:
                _set_status_tag(arn, "enabled")
            enabled_count += len(arns)
            print(f"  ALLOWED {email}: enforcement_mode={enforcement_mode} → {len(arns)} profile(s) tagged status=enabled")
            continue

        usage = _get_user_usage(email, current_month, current_date)
        should_block = _is_over_quota(usage, monthly_limit, daily_limit)

        new_status = "disabled" if should_block else "enabled"
        reason = _block_reason(usage, monthly_limit, daily_limit) if should_block else "within quota"

        for arn in arns:
            _set_status_tag(arn, new_status)

        if should_block:
            disabled_count += len(arns)
            print(f"  BLOCKED {email}: {reason} → {len(arns)} profile(s) tagged status=disabled")
        else:
            enabled_count += len(arns)
            print(f"  ALLOWED {email}: {reason} → {len(arns)} profile(s) tagged status=enabled")

    print(f"Done: {enabled_count} profile(s) enabled, {disabled_count} profile(s) disabled")
    return {
        "statusCode": 200,
        "body": json.dumps({"enabled": enabled_count, "disabled": disabled_count}),
    }


def _get_default_policy() -> dict | None:
    """Fetch the default quota policy from DynamoDB."""
    try:
        response = policies_table.get_item(
            Key={"pk": "POLICY#default#default", "sk": "CURRENT"}
        )
        item = response.get("Item")
        if not item:
            return None
        return {
            "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
            "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
            "enforcement_mode": item.get("enforcement_mode", "alert"),
        }
    except Exception as e:
        print(f"Error loading default policy: {e}")
        return None


def _get_user_policy(email: str) -> dict | None:
    """Fetch a per-user quota policy from DynamoDB. Returns None if not found."""
    try:
        response = policies_table.get_item(
            Key={"pk": f"POLICY#user#{email}", "sk": "CURRENT"}
        )
        item = response.get("Item")
        if not item or not item.get("enabled", True):
            return None
        return {
            "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
            "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
            "enforcement_mode": item.get("enforcement_mode", "alert"),
        }
    except Exception as e:
        print(f"Error loading user policy for {email}: {e}")
        return None


def _get_user_policy(email: str) -> dict | None:
    """Fetch a per-user quota policy. Returns None if no user-specific policy exists."""
    try:
        response = policies_table.get_item(
            Key={"pk": f"POLICY#user#{email}", "sk": "CURRENT"}
        )
        item = response.get("Item")
        if not item or not item.get("enabled", True):
            return None
        return {
            "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
            "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
            "enforcement_mode": item.get("enforcement_mode", "alert"),
        }
    except Exception as e:
        print(f"Error loading user policy for {email}: {e}")
        return None


def _build_email_to_arns_map() -> dict:
    """
    Return { email: [arn, ...] } for all APPLICATION inference profiles
    that carry a user.email tag.
    """
    result = {}
    try:
        paginator = bedrock_client.get_paginator("list_inference_profiles")
        for page in paginator.paginate(typeEquals="APPLICATION"):
            for summary in page.get("inferenceProfileSummaries", []):
                arn = summary.get("inferenceProfileArn")
                if not arn:
                    continue
                try:
                    tags = bedrock_client.list_tags_for_resource(resourceARN=arn).get("tags", [])
                    email = next((t["value"] for t in tags if t.get("key") == "user.email"), None)
                    if email:
                        result.setdefault(email, []).append(arn)
                except Exception as e:
                    print(f"Warning: could not get tags for {arn}: {e}")
    except Exception as e:
        print(f"Error listing inference profiles: {e}")
    return result


def _get_user_usage(email: str, current_month: str, current_date: str) -> dict:
    """Fetch current month's token usage for a user from UserQuotaMetrics."""
    try:
        response = quota_table.get_item(
            Key={"pk": f"USER#{email}", "sk": f"MONTH#{current_month}"}
        )
        item = response.get("Item", {})
        daily_tokens = float(item.get("daily_tokens", 0))
        # Reset daily if date changed
        if item.get("daily_date") != current_date:
            daily_tokens = 0
        return {
            "total_tokens": float(item.get("total_tokens", 0)),
            "daily_tokens": daily_tokens,
        }
    except Exception as e:
        print(f"Error fetching usage for {email}: {e}")
        return {"total_tokens": 0, "daily_tokens": 0}


def _is_over_quota(usage: dict, monthly_limit: int, daily_limit) -> bool:
    if monthly_limit > 0 and usage["total_tokens"] >= monthly_limit:
        return True
    if daily_limit and daily_limit > 0 and usage["daily_tokens"] >= daily_limit:
        return True
    return False


def _block_reason(usage: dict, monthly_limit: int, daily_limit) -> str:
    if monthly_limit > 0 and usage["total_tokens"] >= monthly_limit:
        pct = usage["total_tokens"] / monthly_limit * 100
        return f"monthly {int(usage['total_tokens']):,}/{monthly_limit:,} ({pct:.0f}%)"
    if daily_limit and daily_limit > 0 and usage["daily_tokens"] >= daily_limit:
        pct = usage["daily_tokens"] / daily_limit * 100
        return f"daily {int(usage['daily_tokens']):,}/{daily_limit:,} ({pct:.0f}%)"
    return "unknown"


def _set_status_tag(arn: str, status: str) -> None:
    """Update the status tag on an inference profile."""
    try:
        bedrock_client.tag_resource(
            resourceARN=arn,
            tags=[{"key": "status", "value": status}],
        )
    except Exception as e:
        print(f"Error tagging {arn} with status={status}: {e}")
